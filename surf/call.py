from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .daylight import Daylight, daylight
from .response import Response
from .score import NOMINAL_SLOPE, PLUNGING_BAND, Components, reference_field, score_hour
from .sources import Reading
from .spots import Derived, Spot
from .waves import Forecast, TidePoint, WaveField


@dataclass(frozen=True)
class Signal:
    """One thing that drove the call."""

    text: str
    weight: float = 1.0


@dataclass(frozen=True)
class Candidate:
    spot_id: str
    spot_name: str
    at: datetime
    components: Components
    signals: tuple[Signal, ...] = ()
    timezone: str = ""         # the spot's IANA zone, so output renders local
    tide_note: str = ""
    access_note: str = ""
    model_only: bool = False


@dataclass(frozen=True)
class Call:
    winner: Candidate
    window: str                      # human time window, e.g. "Thu 06:30-09:00"
    signals: tuple[Signal, ...]
    falsifiers: tuple[str, ...]      # what would make this wrong
    neighbour: str = ""              # "resembles your 2024-03-24 Lido session"
    runners_up: tuple[Candidate, ...] = ()
    caveats: tuple[str, ...] = field(default_factory=tuple)
    horizon_note: str = ""


# Inside this many days the call is sharp: size, timing, a window.
SHARP_DAYS = 5
# Out to here we say only "swell arrives"; past it we say nothing at all.
HEADS_UP_DAYS = 10

# An hour joins the window while it holds this fraction of the peak hour's
# ordering key — high enough to keep genuine shoulder hours and drop merely
# adjacent ones.
WINDOW_FRACTION = 0.8

MAX_SIGNALS = 3
MAX_RUNNERS_UP = 2

# Below this, model disagreement is itself a headline falsifier.
SHAKY_CONFIDENCE = 0.55
# A heads-up is about groundswell arriving, not about wind chop.
ARRIVAL_PERIOD_S = 11.0


def _utc(when: datetime) -> datetime:
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)


def _end_of_day(when: datetime) -> datetime:
    # Horizons land on day boundaries: "five days" read as exactly 120 hours
    # would drop the last afternoon of day five.
    return when.replace(hour=23, minute=59, second=59, microsecond=0)


@dataclass(frozen=True)
class SpotOutlook:
    """Everything fetched for one spot. `forecasts` holds one entry per model
    that answered; `observed` is the nearest buoy's latest field, or None."""

    spot: Spot
    forecasts: tuple[Forecast, ...] = ()
    observed: WaveField | None = None
    tide: tuple[TidePoint, ...] = ()
    slope: Derived | None = None
    matrix: Response | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def model_only(self) -> bool:
        return self.observed is None

    def response(self) -> Response:
        # Without a matrix, SIZE would be scored unrefracted, which pretends
        # every swell direction reaches the break equally.
        return self.matrix if self.matrix is not None else Response.for_spot(self.spot)


@dataclass(frozen=True)
class ScoredHour:
    """One spot at one hour, scored across every model that covered it."""

    spot: Spot
    at: datetime
    components: Components
    fields: tuple[WaveField, ...]
    model_only: bool = False

    @property
    def key(self) -> float:
        """Internal ordering only — never printed as a rating."""
        return self.components.ordering_key()

    @property
    def reference(self) -> WaveField | None:
        return reference_field(self.fields)


def hours_by_time(forecasts: Iterable[Forecast]) -> dict[datetime, tuple[WaveField, ...]]:
    """Transpose per-model forecasts into per-hour bundles of model fields."""
    bundles: dict[datetime, list[WaveField]] = {}
    for forecast in forecasts:
        for hour in forecast.hours:
            bundles.setdefault(_utc(hour.time), []).append(hour)
    return {at: tuple(fields) for at, fields in sorted(bundles.items())}


@lru_cache(maxsize=512)
def _lit_cached(lat: float, lon: float, on: date) -> Daylight:
    return daylight(lat, lon, on)


def _lit(spot: Spot, at: datetime) -> Daylight:
    # Cached: a multi-day scan asks this 24 times per spot per day and the
    # answer depends only on (lat, lon, date).
    return _lit_cached(spot.lat, spot.lon, at.date())


def score_outlook(
    outlook: SpotOutlook,
    *,
    start: datetime,
    end: datetime,
    daylight_only: bool = True,
) -> tuple[tuple[ScoredHour, ...], tuple[str, ...]]:
    """Score every hour of one spot inside the sharp horizon, returning the
    hours and what was dropped getting there."""
    matrix = outlook.response()
    slope = outlook.slope
    scored: list[ScoredHour] = []
    outside = 0
    nightly = 0

    for at, fields in hours_by_time(outlook.forecasts).items():
        if at < start or at > end:
            outside += 1
            continue
        if daylight_only and not _lit(outlook.spot, at).contains(at):
            nightly += 1
            continue
        scored.append(
            ScoredHour(
                spot=outlook.spot,
                at=at,
                components=score_hour(outlook.spot, fields, matrix, slope=slope),
                fields=fields,
                model_only=outlook.model_only,
            )
        )

    dropped: list[str] = []
    if outside:
        dropped.append(f"{outlook.spot.id}: {outside} h outside the horizon")
    if nightly:
        dropped.append(f"{outlook.spot.id}: {nightly} h in the dark")
    if not outlook.forecasts:
        dropped.append(f"{outlook.spot.id}: no model answered")
    return tuple(scored), tuple(dropped)


def window_hours(hours: Sequence[ScoredHour], peak: ScoredHour) -> tuple[ScoredHour, ...]:
    """The contiguous run of hours around the peak that holds up.

    Contiguity matters: two good hours either side of a blown-out midday are two
    windows, not one six-hour window.
    """
    ordered = sorted(hours, key=lambda h: h.at)
    index = ordered.index(peak)
    floor = peak.key * WINDOW_FRACTION

    first = index
    while first > 0:
        previous = ordered[first - 1]
        if previous.key < floor or ordered[first].at - previous.at != timedelta(hours=1):
            break
        first -= 1

    last = index
    while last < len(ordered) - 1:
        following = ordered[last + 1]
        if following.key < floor or following.at - ordered[last].at != timedelta(hours=1):
            break
        last += 1

    return tuple(ordered[first : last + 1])


def window_text(run: Sequence[ScoredHour]) -> str:
    """Local where the spot carries an IANA zone, UTC otherwise.

    The end is the hour after the last scored one, so a run ending at 23:00
    prints 24:00 rather than a 00:00 that reads as broken.
    """
    if not run:
        return ""
    zone = run[0].spot.timezone
    start, end = run[0].at, run[-1].at + timedelta(hours=1)
    if zone:
        try:
            local_start = start.astimezone(ZoneInfo(zone))
            local_end = end.astimezone(ZoneInfo(zone))
        except ZoneInfoNotFoundError:
            pass
        else:
            hours = (local_end - local_start).total_seconds() / 3600.0
            end_h = local_start.hour + hours
            tail = (f"{int(end_h):02d}:{local_end:%M}" if end_h > local_start.hour and end_h <= 24
                    else f"{local_end:%H:%M}")
            return f"{local_start:%a %d %b %H:%M}-{tail} {local_start:%Z}"
    return f"{start:%a %d %b %H:%M}-{end:%H:%M} UTC"


def _first_clause(basis: str) -> str:
    return basis.split(";")[0].split(" — ")[0].strip()


def _clock(at: datetime, zone: str) -> str:
    # One block of output must not mix zones: a window in EDT beside a tide in
    # UTC is a four-hour trap.
    if zone:
        try:
            local = at.astimezone(ZoneInfo(zone))
        except ZoneInfoNotFoundError:
            pass
        else:
            return f"{local:%H:%M %Z}"
    return f"{_utc(at):%H:%M} UTC"


def tide_note(points: Sequence[TidePoint], at: datetime, zone: str = "") -> str:
    """The tide nearest the peak hour, in words. Empty when no tide was fetched."""
    if not points:
        return ""
    nearest = min(points, key=lambda p: abs(_utc(p.time) - at))
    gap = abs(_utc(nearest.time) - at)
    stage = nearest.stage or "tide"
    if gap > timedelta(hours=3):
        return f"nearest tide point {gap.total_seconds() / 3600:.0f} h away — tide stage unknown at this hour"
    return f"{stage} {nearest.height_m:+.2f} m at {_clock(_utc(nearest.time), zone)}"


def signals_for(hour: ScoredHour, outlook: SpotOutlook) -> tuple[Signal, ...]:
    # BARREL leads whenever there is any barrel at all, because barrel potential
    # is the ranking target; the rest fill in by weight.
    components = hour.components
    candidates = [
        Signal(_first_clause(components.barrel.basis), components.barrel.value),
        Signal(_first_clause(components.size.basis), components.size.value),
        Signal(_first_clause(components.cleanness.basis), components.cleanness.value),
    ]
    note = tide_note(outlook.tide, hour.at, outlook.spot.timezone)
    if note:
        candidates.append(Signal(note, 0.5))

    lead = candidates[0] if components.barrel.value > 0.0 else None
    rest = sorted(
        (s for s in candidates if s is not lead), key=lambda s: s.weight, reverse=True
    )
    chosen = ([lead] if lead else []) + rest
    return tuple(chosen[:MAX_SIGNALS])


def _why_model_only(outlook: SpotOutlook) -> str:
    # No buoy at all is geography; a listed buoy that returned nothing is a
    # source that fell over.
    if not outlook.spot.buoys:
        return f"no buoy in range of {outlook.spot.name}"
    return f"buoy {'/'.join(outlook.spot.buoys)} returned nothing"


def falsifiers_for(hour: ScoredHour, outlook: SpotOutlook) -> tuple[str, ...]:
    """What would make this call wrong. Never empty."""
    out: list[str] = []
    components = hour.components
    reference = hour.reference
    primary = reference.primary if reference else None

    xi = components.barrel.raw
    low, high = PLUNGING_BAND
    if primary and xi and xi > 0.0:
        if low <= xi <= high:
            # xi scales linearly with period at fixed height and slope, so the
            # period that drops it out of the band is exact arithmetic.
            edge_s = primary.period_s * low / xi
            out.append(
                f"period under {edge_s:.0f} s (forecast {primary.period_s:.0f} s) and it "
                f"leaves the plunging band — spilling, not barrelling"
            )
        elif xi < low:
            out.append(
                f"already below the plunging band (xi={xi:.2f}) — this is the best hour "
                "available, not a barrel forecast"
            )
        else:
            out.append(
                f"xi={xi:.2f} is above the plunging band — steep and surging, a shorter "
                "period would improve it"
            )

    if components.cleanness.raw is not None:
        off_angle = components.cleanness.raw
        out.append(
            f"wind is {off_angle:.0f} deg off the offshore bearing "
            f"({outlook.spot.offshore_wind_bearing:.0f} deg); a swing past 90 deg before "
            "the window opens blows it out"
        )
    else:
        out.append("no wind forecast for this hour — cleanness is a guess")

    if components.confidence.value < SHAKY_CONFIDENCE:
        out.append(f"models disagree — {components.confidence.basis}")

    if hour.model_only:
        out.append(
            f"model-only ({_why_model_only(outlook)}), so nothing observed will "
            "contradict the models before you drive"
        )

    if components.barrel.basis.startswith("steepness proxy"):
        out.append(
            f"beach slope here is assumed ({NOMINAL_SLOPE:.3f}), not measured — a flatter "
            "bottom turns this from plunging to spilling"
        )

    if not outlook.tide:
        out.append("no tide curve for this day — a wrong stage undoes everything above")

    if not out:  # pragma: no cover — the wind clause always fires
        out.append("nothing here is measured; treat the whole call as provisional")
    return tuple(out)


def horizon_note(
    outlooks: Sequence[SpotOutlook],
    *,
    now: datetime,
    sharp_days: int = SHARP_DAYS,
    heads_up_days: int = HEADS_UP_DAYS,
) -> str:
    """One arrival line for the days past the sharp horizon: period, direction
    and day only, since size and timing are not trustworthy that far out."""
    now = _utc(now)
    start = _end_of_day(now + timedelta(days=sharp_days))
    end = _end_of_day(now + timedelta(days=heads_up_days))

    best: tuple[float, str] = (0.0, "")
    for outlook in outlooks:
        for at, fields in hours_by_time(outlook.forecasts).items():
            if not (start < at <= end):
                continue
            for wave in fields:
                swell = wave.primary
                if swell is None or swell.period_s < ARRIVAL_PERIOD_S:
                    continue
                if swell.energy > best[0]:
                    best = (
                        swell.energy,
                        f"day {(at - now).days} ({at:%a %d %b}): {swell.period_s:.0f} s from "
                        f"{swell.direction_deg:.0f} deg reaching {outlook.spot.name} "
                        f"[{wave.model or 'model'}] — arrival signal only, size and timing "
                        "are not trustworthy this far out",
                    )
    if best[1]:
        return best[1]
    return f"nothing on the charts for days {sharp_days + 1}-{heads_up_days}"


def _candidate(hour: ScoredHour, outlook: SpotOutlook) -> Candidate:
    return Candidate(
        spot_id=outlook.spot.id,
        spot_name=outlook.spot.name,
        at=hour.at,
        components=hour.components,
        signals=signals_for(hour, outlook),
        timezone=outlook.spot.timezone,
        tide_note=tide_note(outlook.tide, hour.at, outlook.spot.timezone),
        access_note=outlook.spot.access,
        model_only=hour.model_only,
    )


def make_call(
    outlooks: Sequence[SpotOutlook],
    *,
    now: datetime | None = None,
    sharp_days: int = SHARP_DAYS,
    heads_up_days: int = HEADS_UP_DAYS,
    daylight_only: bool = True,
    neighbour: str = "",
    readings: Sequence[Reading] = (),
) -> Reading[Call]:
    """Commit to a spot, a day and a time — or say plainly that there is none.

    `readings` are the source labels from the fetch that produced these outlooks;
    every one that is not `ok` becomes a caveat.
    """
    fetched_at = _utc(now) if now is not None else datetime.now(timezone.utc)
    start = fetched_at
    sharp_end = _end_of_day(fetched_at + timedelta(days=sharp_days))

    by_spot: dict[str, tuple[SpotOutlook, tuple[ScoredHour, ...]]] = {}
    dropped: list[str] = []
    for outlook in outlooks:
        hours, lost = score_outlook(
            outlook, start=start, end=sharp_end, daylight_only=daylight_only
        )
        dropped.extend(lost)
        if hours:
            by_spot[outlook.spot.id] = (outlook, hours)

    caveats = [reading.label() for reading in readings if reading.status != "ok"]
    horizon = horizon_note(
        outlooks, now=fetched_at, sharp_days=sharp_days, heads_up_days=heads_up_days
    )

    if not by_spot:
        return Reading(
            value=None,
            source="call",
            status="failed",
            fetched_at=fetched_at,
            note="no spot produced a scoreable hour inside the sharp horizon",
            dropped=tuple(dropped),
        )

    ranked = sorted(
        (
            max(hours, key=lambda h: (h.key, -h.at.timestamp()))
            for _, hours in by_spot.values()
        ),
        key=lambda h: (-h.key, h.at, h.spot.id),
    )
    peak = ranked[0]
    outlook, hours = by_spot[peak.spot.id]
    run = window_hours(hours, peak)

    if outlook.spot.access:
        caveats.append(f"access: {outlook.spot.access} — a cost, not a filter")
    if peak.model_only:
        caveats.append(f"{outlook.spot.name} is model-only — {_why_model_only(outlook)}")
    caveats.extend(outlook.notes)

    runners = tuple(
        _candidate(hour, by_spot[hour.spot.id][0]) for hour in ranked[1 : 1 + MAX_RUNNERS_UP]
    )

    call = Call(
        winner=_candidate(peak, outlook),
        window=window_text(run),
        signals=signals_for(peak, outlook),
        falsifiers=falsifiers_for(peak, outlook),
        neighbour=neighbour,
        runners_up=runners,
        caveats=tuple(caveats),
        horizon_note=horizon,
    )

    status = "degraded" if (dropped or caveats) else "ok"
    return Reading(
        value=call,
        source="call",
        status=status,
        fetched_at=fetched_at,
        confidence=peak.components.confidence.value,
        note=f"{len(by_spot)} spots scored, {len(hours)} hours at {outlook.spot.id}",
        dropped=tuple(dropped),
    )
