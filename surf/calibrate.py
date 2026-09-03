from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .call import Signal
from .response import Response
from .score import Components, score_hour
from .sessions import Session, load_sessions, resolution_report, usable
from .sources import Archive, Reading
from .spots import Spot, SpotBook, data_dir
from .waves import SwellPartition, WaveField, Wind, angle_between, normalise_bearing, signed_angle

# Local hour assumed when a row records no time. Flagged on every row that uses
# it, since an invented hour recovers the wrong conditions.
DEFAULT_LOCAL_HOUR = 8

TOP_RATING = 5
BOTTOM_RATING = 1

# One unit of neighbour distance per axis: 0.5 m of height, 3 s of period and
# 30 degrees of direction all count the same.
HEIGHT_SCALE_M = 0.5
PERIOD_SCALE_S = 3.0
DIRECTION_SCALE_DEG = 30.0

LIDO_SPOT_ID = "lido-beach"
LIDO_CURRENT_MONTH_DAY = (3, 3)


@dataclass(frozen=True)
class Longshore:
    """`sets_deg` is the bearing the water flows TOWARD. `strength` is the
    normalised alongshore forcing sin(theta)cos(theta): 1.0 at 45 degrees of
    incidence, 0 for a swell straight in or straight along the beach.
    """

    sets_deg: float
    compass: str
    strength: float
    incidence_deg: float     # signed, + = swell arrives from clockwise of the normal
    basis: str

    @property
    def real(self) -> bool:
        """False when the swell cannot reach the beach, so the set direction is
        arithmetic rather than water."""
        return abs(self.incidence_deg) < 90.0


_COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def _compass(bearing_deg: float) -> str:
    index = int((normalise_bearing(bearing_deg) + 22.5) // 45) % 8
    return _COMPASS[index]


def longshore(spot: Spot, direction_deg: float) -> Longshore:
    """With `theta` the signed angle from the shore normal to where the swell
    comes from, the wave travels toward `theta + 180`, whose alongshore component
    points at `normal + 90` for negative `theta` and `normal - 90` for positive.
    Magnitude is the sin(theta)cos(theta) radiation-stress form, peaking at 45 deg.
    """
    theta = signed_angle(spot.shore_normal.value, direction_deg)
    rad = math.radians(theta)
    strength = abs(math.sin(rad) * math.cos(rad)) * 2.0
    sets = normalise_bearing(spot.shore_normal.value + (-90.0 if theta > 0 else 90.0))
    if abs(theta) < 1e-9:
        strength = 0.0
    word = _compass(sets)

    if abs(theta) >= 90.0:
        basis = (
            f"swell from {normalise_bearing(direction_deg):.0f} deg is {abs(theta):.0f} deg "
            f"off the shore normal ({spot.shore_normal.value:.0f} deg) — offshore of the "
            "beach, so there is no longshore forcing to speak of"
        )
        return Longshore(sets, word, 0.0, theta, basis)

    basis = (
        f"swell from {normalise_bearing(direction_deg):.0f} deg meets the "
        f"{spot.shore_normal.value:.0f} deg shore normal at {theta:+.0f} deg, "
        f"so the current sets {word} (toward {sets:.0f} deg) at {strength:.2f} of peak"
    )
    return Longshore(sets, word, strength, theta, basis)


def _sets_toward(spot: Spot, compass_word: str) -> tuple[float, float]:
    """The swell-direction band that sets the current the named way, as a
    half-open (from, to) pair of bearings."""
    normal = spot.shore_normal.value
    clockwise = (normalise_bearing(normal), normalise_bearing(normal + 90.0))
    anticlockwise = (normalise_bearing(normal - 90.0), normalise_bearing(normal))
    if _compass(normalise_bearing(normal - 90.0)) == compass_word:
        return clockwise
    return anticlockwise


def default_cache_dir() -> Path:
    return Path(os.environ.get("SURF_CACHE_DIR") or data_dir() / "cache") / "calibration"


def _field_to_json(field: WaveField) -> dict:
    return {
        "time": field.time.isoformat(),
        "model": field.model,
        "total_height_m": field.total_height_m,
        "total_period_s": field.total_period_s,
        "wind": None if field.wind is None else {
            "speed_mps": field.wind.speed_mps,
            "direction_deg": field.wind.direction_deg,
        },
        "partitions": [
            {
                "height_m": p.height_m,
                "period_s": p.period_s,
                "direction_deg": p.direction_deg,
                "kind": p.kind,
            }
            for p in field.partitions
        ],
    }


def _field_from_json(raw: dict) -> WaveField:
    wind = raw.get("wind")
    return WaveField(
        time=datetime.fromisoformat(raw["time"]),
        partitions=tuple(
            SwellPartition(
                height_m=float(p["height_m"]),
                period_s=float(p["period_s"]),
                direction_deg=float(p["direction_deg"]),
                kind=p.get("kind", "swell"),
            )
            for p in raw.get("partitions", ())
        ),
        wind=None if wind is None else Wind(
            speed_mps=float(wind["speed_mps"]),
            direction_deg=float(wind["direction_deg"]),
        ),
        total_height_m=raw.get("total_height_m"),
        total_period_s=raw.get("total_period_s"),
        model=raw.get("model", ""),
    )


class ConditionCache:
    """One JSON file per recovered session hour, keyed by spot, UTC date and UTC
    hour. Reanalysis for a past day never changes, so there is no expiry.
    """

    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory is not None else default_cache_dir()

    def _path(self, spot_id: str, on: date, hour: int) -> Path:
        return self.dir / f"{spot_id}@{on.isoformat()}T{hour:02d}.json"

    def get(self, spot_id: str, on: date, hour: int) -> tuple[WaveField, str] | None:
        try:
            raw = json.loads(self._path(spot_id, on, hour).read_text())
        except (OSError, ValueError):
            return None
        try:
            return _field_from_json(raw["field"]), raw.get("note", "")
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, spot_id: str, on: date, hour: int, field: WaveField, note: str = "") -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(spot_id, on, hour)
        body = {
            "spot_id": spot_id,
            "utc_date": on.isoformat(),
            "utc_hour": hour,
            "note": note,
            "field": _field_to_json(field),
        }
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        return path


def _utc_moment(spot: Spot, on: date, local_hour: int) -> tuple[date, int, int]:
    """The UTC (date, hour) of a local clock time, plus the offset that applied.

    The log carries no timezone, so the spot's IANA zone supplies it; the
    nautical fallback (one hour per 15 deg of longitude) ignores both civil time
    and summer time and lands an hour off wherever those differ.
    """
    if spot.timezone:
        try:
            local = datetime(on.year, on.month, on.day, local_hour,
                             tzinfo=ZoneInfo(spot.timezone))
        except ZoneInfoNotFoundError:
            pass
        else:
            moment = local.astimezone(timezone.utc)
            offset = int(round((local.utcoffset() or timedelta()).total_seconds() / 3600.0))
            return moment.date(), moment.hour, offset

    offset = int(round(spot.lon / 15.0))
    moment = datetime(on.year, on.month, on.day, local_hour) - timedelta(hours=offset)
    return moment.date(), moment.hour, offset


@dataclass(frozen=True)
class Recovered:
    session: Session
    spot: Spot
    on_utc: date
    hour_utc: int
    utc_offset_h: int
    field: WaveField | None
    status: str          # "ok" | "cached" | "skipped" | "failed"
    note: str
    hour_assumed: bool

    @property
    def ok(self) -> bool:
        return self.field is not None

    @property
    def rating(self) -> int | None:
        return self.session.rating

    def label(self) -> str:
        when = self.session.on.isoformat() if self.session.on else self.session.raw_date
        mark = "~" if self.hour_assumed else " "
        return (
            f"{when}{mark}{self.hour_utc:02d}Z {self.spot.name} "
            f"{self.session.rating}/5 [{self.status}] {self.note}".rstrip()
        )


def recover(
    sessions: Sequence[Session],
    archive: Archive | None = None,
    *,
    book: SpotBook | None = None,
    cache: ConditionCache | None = None,
    refresh: bool = False,
) -> tuple[Recovered, ...]:
    """The cache answers first; `archive=None` is offline mode, where anything
    uncached comes back `skipped` with a reason rather than being dropped. Rows
    with no date, spot or rating are omitted — `resolution_report()` covers them.
    """
    book = book if book is not None else SpotBook.load()
    cache = cache if cache is not None else ConditionCache()

    out: list[Recovered] = []
    for session in usable(sessions):
        spot = book.get(session.spot_id or "")
        if spot is None or session.on is None:
            continue
        hour_assumed = session.hour is None
        local_hour = session.hour if session.hour is not None else DEFAULT_LOCAL_HOUR
        on_utc, hour_utc, offset = _utc_moment(spot, session.on, local_hour)

        hit = None if refresh else cache.get(spot.id, on_utc, hour_utc)
        if hit is not None:
            field, note = hit
            out.append(Recovered(
                session, spot, on_utc, hour_utc, offset, field, "cached", note, hour_assumed,
            ))
            continue

        if archive is None:
            out.append(Recovered(
                session, spot, on_utc, hour_utc, offset, None, "skipped",
                "not cached, and no archive was given (offline run)", hour_assumed,
            ))
            continue

        reading: Reading[WaveField] = archive.conditions(spot, on_utc, hour_utc)
        if not reading.ok or reading.value is None:
            out.append(Recovered(
                session, spot, on_utc, hour_utc, offset, None,
                reading.status, reading.label(), hour_assumed,
            ))
            continue

        cache.put(spot.id, on_utc, hour_utc, reading.value, reading.label())
        out.append(Recovered(
            session, spot, on_utc, hour_utc, offset, reading.value,
            reading.status, reading.label(), hour_assumed,
        ))
    return tuple(out)


@dataclass(frozen=True)
class Scored:
    recovered: Recovered
    components: Components

    @property
    def rating(self) -> int:
        assert self.recovered.session.rating is not None  # `usable()` guaranteed it
        return self.recovered.session.rating

    @property
    def key(self) -> float:
        """A crude internal ordering, never a rating."""
        return self.components.ordering_key()

    def label(self) -> str:
        c = self.components
        return (
            f"{self.recovered.label()} -> key={self.key:.3f} "
            f"(barrel {c.barrel.value:.2f} size {c.size.value:.2f} "
            f"clean {c.cleanness.value:.2f} conf {c.confidence.value:.2f})"
        )


def score_sessions(
    recovered: Sequence[Recovered],
    *,
    matrix: bool = True,
) -> tuple[Scored, ...]:
    """Scores past sessions through the same path as a live forecast hour;
    scoring the log with a special-case model would prove nothing about the model
    that gives the call. `matrix=False` isolates the scoring from the response
    matrix.
    """
    out: list[Scored] = []
    for rec in recovered:
        if rec.field is None:
            continue
        response: Response | None = (
            Response.for_spot(rec.spot) if matrix else None
        )
        out.append(Scored(rec, score_hour(rec.spot, [rec.field], response)))
    return tuple(out)


@dataclass(frozen=True)
class CheckResult:
    """`passed=None` means the check could not run — missing data, not
    agreement.
    """

    name: str
    passed: bool | None
    detail: str
    evidence: tuple[str, ...] = ()

    @property
    def mark(self) -> str:
        return "PASS" if self.passed else "FAIL" if self.passed is False else "SKIP"

    def render(self) -> str:
        lines = [f"[{self.mark}] {self.name}: {self.detail}"]
        lines.extend(f"    {line}" for line in self.evidence)
        return "\n".join(lines)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation, no scipy. None when a rank is degenerate."""
    n = len(xs)
    if n < 3:
        return None

    def rank(vs: Sequence[float]) -> list[float]:
        order = sorted(range(len(vs)), key=lambda i: vs[i])
        out = [0.0] * len(vs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0.0 or dy == 0.0:
        return None
    return num / (dx * dy)


def component_trends(scored: Sequence[Scored]) -> tuple[str, ...]:
    """Rank correlation of each component against the logged rating. Diagnostic
    only: it says which component disagrees when the dominance check fails.
    """
    if len(scored) < 3:
        return ()
    ratings = [float(s.rating) for s in scored]
    out = []
    for name in ("barrel", "size", "cleanness", "confidence"):
        vals = [getattr(s.components, name).value for s in scored]
        rho = _spearman(ratings, vals)
        out.append(f"rho(rating, {name}) = {rho:+.2f}" if rho is not None else
                   f"rho(rating, {name}) = n/a")
    return tuple(out)


def ranking_check(
    scored: Sequence[Scored],
    *,
    top: int = TOP_RATING,
    bottom: int = BOTTOM_RATING,
) -> CheckResult:
    """Require that no {bottom}/5 dominates a {top}/5 on every component at once.

    Dominance rather than a fused score: barrel and size move in opposite
    directions with wave height (xi ~ H^-0.5, so barrel falls as size rises), so
    their product ranks by whichever normalisation is steeper, not by the ocean.
    With few low-rated anchors the pairs are not independent, so a pass here is a
    tripwire, not a validation.
    """
    highs = [s for s in scored if s.rating == top]
    lows = [s for s in scored if s.rating == bottom]
    trends = component_trends(scored)
    if not highs or not lows:
        return CheckResult(
            f"no {bottom}/5 dominates a {top}/5", None,
            f"need at least one {top}/5 and one {bottom}/5 with recovered conditions; "
            f"have {len(highs)} and {len(lows)}",
            trends,
        )

    def dominates(low: Scored, high: Scored) -> bool:
        a, b = low.components, high.components
        return (a.barrel.value >= b.barrel.value
                and a.size.value >= b.size.value
                and a.cleanness.value >= b.cleanness.value)

    inversions = [(h, l) for h in highs for l in lows if dominates(l, h)]
    pairs = len(highs) * len(lows)
    detail = (
        f"{pairs - len(inversions)}/{pairs} pairs clear "
        f"({len(highs)} sessions at {top}/5 vs {len(lows)} at {bottom}/5"
        + (f"; only {len(lows)} low anchor, so the pairs are not independent"
           if len(lows) < 2 else "") + ")"
    )
    evidence = [
        f"dominated: {l.recovered.label()} beats {h.recovered.label()} on every component "
        f"(barrel {l.components.barrel.value:.2f}>={h.components.barrel.value:.2f}, "
        f"size {l.components.size.value:.2f}>={h.components.size.value:.2f}, "
        f"clean {l.components.cleanness.value:.2f}>={h.components.cleanness.value:.2f})"
        for h, l in inversions
    ]
    return CheckResult(f"no {bottom}/5 dominates a {top}/5", not inversions,
                       detail, tuple(evidence) + trends)


def current_check(
    spot: Spot,
    expected: str,
    *,
    direction_deg: float | None = None,
    when: str = "",
) -> CheckResult:
    """Does the stored shore normal imply the current that was actually felt?"""
    label = f"{spot.name} current sets {expected}" + (f" on {when}" if when else "")
    if direction_deg is None:
        band = _sets_toward(spot, expected)
        return CheckResult(
            label, None,
            f"no swell direction recovered for this session; with the stored "
            f"{spot.shore_normal.value:.0f} deg shore normal the current sets {expected} "
            f"for swell from {band[0]:.0f}-{band[1]:.0f} deg, which is what would confirm it",
        )
    current = longshore(spot, direction_deg)
    passed = current.compass == expected and current.real
    detail = f"model says {current.compass}, log says {expected} — {current.basis}"
    return CheckResult(label, passed, detail)


def lido_current_check(
    recovered: Sequence[Recovered],
    book: SpotBook | None = None,
    sessions: Sequence[Session] = (),
) -> tuple[CheckResult, ...]:
    """Two halves of one logged claim: the current at Lido normally pulls west,
    and on 03-03 it pulled east. Both are tested against the same stored shore
    normal, and the typical direction is the vector mean of the recovered Lido
    sessions rather than an assumption. The 03-03 row carries no year, so that
    half usually reports SKIP with the swell band that would confirm it.
    """
    book = book if book is not None else SpotBook.load()
    spot = book.get(LIDO_SPOT_ID)
    if spot is None:
        return (CheckResult("Lido longshore current", None, f"no spot {LIDO_SPOT_ID!r} in the book"),)

    at_lido = [r for r in recovered if r.spot.id == LIDO_SPOT_ID and r.field is not None]

    # Searched across the whole log, not just the recovered set: with no year the
    # anomaly row has no conditions to recover, so it never reaches `recovered`.
    pool: Sequence[Session] = sessions or [r.session for r in recovered]
    anomaly = next(
        (
            s for s in pool
            if s.spot_id == LIDO_SPOT_ID
            and "current" in s.notes.lower()
            and (s.on is None or (s.on.month, s.on.day) == LIDO_CURRENT_MONTH_DAY)
        ),
        None,
    )
    typical = [r for r in at_lido if r.session is not anomaly]

    direction = _mean_direction(
        [p.direction_deg for r in typical if (p := r.field.primary) is not None]  # type: ignore[union-attr]
    )
    if direction is None:
        normal_check = CheckResult(
            "Lido current sets west on typical swell", None,
            "no Lido session with a recovered swell direction; nothing to take a typical "
            "direction from",
        )
    else:
        normal_check = current_check(
            spot, "west", direction_deg=direction,
            when=f"typical swell ({len(typical)} recovered sessions, mean {direction:.0f} deg)",
        )

    anomaly_rec = next((r for r in at_lido if r.session is anomaly), None)
    anomaly_dir = None
    if anomaly_rec is not None and anomaly_rec.field is not None:
        primary = anomaly_rec.field.primary
        anomaly_dir = primary.direction_deg if primary is not None else None
    anomaly_check = current_check(
        spot, "east", direction_deg=anomaly_dir,
        when=(anomaly.raw_date if anomaly is not None else "03-03"),
    )
    return (normal_check, anomaly_check)


def _mean_direction(directions: Sequence[float]) -> float | None:
    """Vector mean of bearings: averaging 350 and 10 arithmetically gives 180,
    the opposite of the answer."""
    if not directions:
        return None
    x = sum(math.cos(math.radians(d)) for d in directions)
    y = sum(math.sin(math.radians(d)) for d in directions)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None
    return normalise_bearing(math.degrees(math.atan2(y, x)))


@dataclass(frozen=True)
class Neighbour:
    recovered: Recovered
    distance: float

    @property
    def similarity(self) -> float:
        """0..1, monotone in distance. A comparison aid, never a probability."""
        return 1.0 / (1.0 + self.distance)

    def sentence(self, when: str = "") -> str:
        session = self.recovered.session
        stamp = session.on.isoformat() if session.on else session.raw_date
        lead = f"{when} at {self.recovered.spot.name}" if when else self.recovered.spot.name
        note = session.notes.split("(")[0].strip().rstrip(";,")
        tail = f" — \"{note}\"" if note else ""
        return (
            f"{lead} resembles your {stamp} session there, which you rated "
            f"{session.rating}/5{tail}"
        )


def _distance(a: WaveField, b: WaveField) -> float | None:
    """Normalised distance between two hours: height, period, direction.

    Wind is left out on purpose — it decides whether a day was clean, but the
    swell decides whether one day resembles another.
    """
    pa, pb = a.primary, b.primary
    if pa is None or pb is None:
        return None
    dh = (pa.height_m - pb.height_m) / HEIGHT_SCALE_M
    dt = (pa.period_s - pb.period_s) / PERIOD_SCALE_S
    dd = angle_between(pa.direction_deg, pb.direction_deg) / DIRECTION_SCALE_DEG
    return math.sqrt(dh * dh + dt * dt + dd * dd)


def nearest(
    field: WaveField,
    spot_id: str,
    recovered: Sequence[Recovered],
    *,
    limit: int = 1,
    same_spot_only: bool = True,
) -> tuple[Neighbour, ...]:
    """The sessions most like this hour, nearest first."""
    scored: list[Neighbour] = []
    for rec in recovered:
        if rec.field is None:
            continue
        if same_spot_only and rec.spot.id != spot_id:
            continue
        d = _distance(field, rec.field)
        if d is None:
            continue
        scored.append(Neighbour(rec, d))
    scored.sort(key=lambda n: (n.distance, n.recovered.on_utc))
    return tuple(scored[:limit])


def signals_from(neighbours: Sequence[Neighbour], when: str = "") -> tuple[Signal, ...]:
    """Neighbour lines in the shape `call.py` consumes."""
    return tuple(Signal(n.sentence(when), n.similarity) for n in neighbours)


@dataclass(frozen=True)
class CalibrationReport:
    checks: tuple[CheckResult, ...]
    recovered: tuple[Recovered, ...]
    scored: tuple[Scored, ...]
    coverage: str
    public_anchors: int = 0

    @property
    def failed(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.passed is False)

    @property
    def passed(self) -> bool:
        """A skipped check is not a failure, but it prints as SKIP rather than
        as agreement."""
        return not self.failed

    def render(self) -> str:
        lines = [c.render() for c in self.checks]
        lines.append("")
        lines.append(self.coverage)
        recovered_ok = sum(1 for r in self.recovered if r.ok)
        assumed = sum(1 for r in self.recovered if r.ok and r.hour_assumed)
        lines.append(
            f"conditions recovered: {recovered_ok}/{len(self.recovered)} usable sessions"
            f"  ({assumed} at an assumed {DEFAULT_LOCAL_HOUR:02d}:00 local)"
        )
        for rec in self.recovered:
            if not rec.ok:
                lines.append(f"  no conditions: {rec.label()}")
        if self.public_anchors:
            lines.append(
                f"public anchors held separately: {self.public_anchors} "
                "(never merged into David's scale)"
            )
        return "\n".join(lines)


def calibrate(
    archive: Archive | None = None,
    *,
    sessions: Sequence[Session] | None = None,
    anchors: Sequence[Session] = (),
    book: SpotBook | None = None,
    cache: ConditionCache | None = None,
    refresh: bool = False,
    matrix: bool = True,
) -> CalibrationReport:
    """`archive=None` runs entirely from the cache. Public anchors are counted
    but held out of the ranking check.
    """
    book = book if book is not None else SpotBook.load()
    sessions = tuple(sessions) if sessions is not None else load_sessions(book=book)

    david = [s for s in sessions if s.source == "david"]
    public = [s for s in sessions if s.source != "david"] + list(anchors)

    recovered = recover(david, archive, book=book, cache=cache, refresh=refresh)
    scored = score_sessions(recovered, matrix=matrix)

    checks = [ranking_check(scored), *lido_current_check(recovered, book, david)]
    return CalibrationReport(
        checks=tuple(checks),
        recovered=recovered,
        scored=scored,
        coverage=resolution_report(david),
        public_anchors=len(public),
    )
