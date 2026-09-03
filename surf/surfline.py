from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .sources import Http, Reading, SourceDown, Window, now
from .spots import Spot
from .waves import FEET_PER_METRE, KNOTS_PER_MPS, Forecast, SwellPartition, WaveField, Wind

BASE = "https://services.surfline.com/kbyg/spots/forecasts"
SOURCE = "surfline"

# Above this the API returns 400 "Parameters out of bounds".
MAX_DAYS = 16

# Health-check target. Any valid spot ObjectId works; an invalid one returns
# 400, which would read as an outage.
PROBE_SPOT_ID = "5842041f4e65fad6a7708890"

ENV_FLAG = "SURF_SURFLINE"


def _to_metres(value: float, unit: str) -> float:
    u = (unit or "").upper()
    if u == "FT":
        return value / FEET_PER_METRE
    if u in ("M", "METERS", "METRES", ""):
        return value
    raise ValueError(f"unknown height unit {unit!r}")


def _to_mps(value: float, unit: str) -> float:
    u = (unit or "").upper()
    if u in ("KTS", "KT", "KNOTS"):
        return value / KNOTS_PER_MPS
    if u == "MPH":
        return value * 0.44704
    if u == "KPH":
        return value / 3.6
    if u in ("MS", "M/S", ""):
        return value
    raise ValueError(f"unknown speed unit {unit!r}")


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), timezone.utc)


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SurfHeight:
    """Surfline's face-height call for one hour, in metres. Not Hs and not
    comparable to a model's significant height, hence the separate type.
    """

    time: datetime
    min_m: float
    max_m: float
    human_relation: str = ""


@dataclass(frozen=True)
class Disagreement:
    hours_compared: int
    mean_height_delta_m: float
    max_height_delta_m: float
    mean_period_delta_s: float
    note: str = ""


def disagreement(ours: Forecast, theirs: Forecast) -> Disagreement:
    """Compare two forecasts on their primary swell train, hour by hour.

    Only hours present in both count, and `hours_compared` is returned so a
    two-hour overlap is not read as agreement. Positive delta = theirs bigger.
    """
    mine = {_aware(h.time): h for h in ours.hours}
    dh: list[float] = []
    dp: list[float] = []
    for hour in theirs.hours:
        mate = mine.get(_aware(hour.time))
        if mate is None:
            continue
        a, b = mate.primary, hour.primary
        if a is None or b is None:
            continue
        dh.append(b.height_m - a.height_m)
        dp.append(b.period_s - a.period_s)
    if not dh:
        return Disagreement(0, 0.0, 0.0, 0.0, "no overlapping hours with a primary swell")
    return Disagreement(
        hours_compared=len(dh),
        mean_height_delta_m=sum(dh) / len(dh),
        max_height_delta_m=max(dh, key=abs),
        mean_period_delta_s=sum(dp) / len(dp),
        note=f"{ours.model} vs {theirs.model}; positive = surfline bigger",
    )


class Surfline:
    """A benchmark forecast source that is allowed to be absent. Disabled,
    unknown spot and open breaker all return a `skipped` Reading rather than
    raising, so it can never fail the forecast path.
    """

    name = SOURCE

    def __init__(self, http: Http | None = None, enabled: bool = True):
        self._http = http or Http()
        self.enabled = enabled

    def preflight(self) -> Reading[bool]:
        if not self.enabled:
            return self._skipped(None, "disabled")
        try:
            r = self._http.get(SOURCE, f"{BASE}/surf", {"spotId": PROBE_SPOT_ID, "days": 1})
            alive = bool(r.json().get("data", {}).get("surf"))
        except SourceDown as e:
            return self._skipped(False, str(e))
        except Exception as e:
            return Reading(False, SOURCE, "failed", now(), note=f"{type(e).__name__}: {e}")
        if not alive:
            return Reading(False, SOURCE, "failed", now(), note="probe returned no surf data")
        return Reading(True, SOURCE, "ok", now())

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        """Swell partitions, with wind merged in when available. Wind is a
        separate endpoint, so losing it degrades rather than fails the reading.
        """
        gate = self._gate(spot)
        if gate is not None:
            return gate

        days = self._days(window)
        try:
            swell_rows, assoc = self._fetch("swells", spot, days)
        except SourceDown as e:
            return self._skipped(None, str(e))
        except Exception as e:
            return Reading(None, SOURCE, "failed", now(), note=f"swells: {type(e).__name__}: {e}")

        dropped: list[str] = []
        winds: dict[datetime, Wind] = {}
        try:
            wind_rows, wind_assoc = self._fetch("wind", spot, days)
            unit = wind_assoc.get("units", {}).get("windSpeed", "KTS")
            for row in wind_rows:
                winds[_utc(row["timestamp"])] = Wind(
                    speed_mps=_to_mps(float(row.get("speed") or 0.0), unit),
                    direction_deg=float(row.get("direction") or 0.0),
                )
        except Exception as e:
            dropped.append(f"wind ({type(e).__name__})")

        height_unit = assoc.get("units", {}).get("swellHeight", "FT")
        start, end = self._span(window)
        hours: list[WaveField] = []
        outside = 0
        for row in swell_rows:
            t = _utc(row["timestamp"])
            if not (start <= t <= end):
                outside += 1
                continue
            hours.append(
                WaveField(
                    time=t,
                    partitions=self._trains(row.get("swells") or (), height_unit),
                    wind=winds.get(t),
                    model=SOURCE,
                )
            )

        if not hours:
            return Reading(
                None, SOURCE, "failed", now(),
                model_run=self._run(assoc),
                note=f"no hours inside the window ({outside} returned outside it)",
            )

        requested = window.hours
        if len(hours) < requested:
            dropped.append(f"{requested - len(hours)}h of {requested}h requested")

        status = "degraded" if dropped else "ok"
        return Reading(
            Forecast(spot_id=spot.id, model=SOURCE, hours=tuple(hours)),
            SOURCE,
            status,
            now(),
            model_run=self._run(assoc),
            note="benchmark only, never an input",
            dropped=tuple(dropped),
        )

    def surf_heights(self, spot: Spot, window: Window) -> Reading[tuple[SurfHeight, ...]]:
        """Surfline's own face-height call.

        `raw` min/max are unrounded; the integer `min`/`max` beside them are
        already rounded for display, so they are not used.
        """
        gate = self._gate(spot)
        if gate is not None:
            return gate

        try:
            rows, assoc = self._fetch("surf", spot, self._days(window))
        except SourceDown as e:
            return self._skipped(None, str(e))
        except Exception as e:
            return Reading(None, SOURCE, "failed", now(), note=f"surf: {type(e).__name__}: {e}")

        unit = assoc.get("units", {}).get("waveHeight", "FT")
        start, end = self._span(window)
        out: list[SurfHeight] = []
        for row in rows:
            t = _utc(row["timestamp"])
            if not (start <= t <= end):
                continue
            surf = row.get("surf") or {}
            raw = surf.get("raw") or {}
            out.append(
                SurfHeight(
                    time=t,
                    min_m=_to_metres(float(raw.get("min", surf.get("min", 0.0))), unit),
                    max_m=_to_metres(float(raw.get("max", surf.get("max", 0.0))), unit),
                    human_relation=surf.get("humanRelation") or "",
                )
            )
        if not out:
            return Reading(None, SOURCE, "failed", now(), note="no surf hours inside the window")

        dropped = ()
        status = "ok"
        if len(out) < window.hours:
            dropped = (f"{window.hours - len(out)}h of {window.hours}h requested",)
            status = "degraded"
        return Reading(
            tuple(out), SOURCE, status, now(),
            model_run=self._run(assoc),
            note="face height at the break, not Hs",
            dropped=dropped,
        )

    def _fetch(self, endpoint: str, spot: Spot, days: int) -> tuple[list[dict], dict]:
        r = self._http.get(
            SOURCE,
            f"{BASE}/{endpoint}",
            {
                "spotId": spot.surfline_id,
                "days": days,
                "intervalHours": 1,
                "units[swellHeight]": "M",
                "units[waveHeight]": "M",
            },
        )
        body = r.json()
        data = body.get("data", {})
        return list(data.get(endpoint) or ()), dict(body.get("associated") or {})

    def _trains(self, rows, unit: str) -> tuple[SwellPartition, ...]:
        # All-zero entries are array padding, not swell trains.
        out = []
        for s in rows:
            h = float(s.get("height") or 0.0)
            p = float(s.get("period") or 0.0)
            if h <= 0.0 or p <= 0.0:
                continue
            out.append(
                SwellPartition(
                    height_m=_to_metres(h, unit),
                    period_s=p,
                    direction_deg=float(s.get("direction") or 0.0),
                )
            )
        return tuple(sorted(out, key=lambda t: t.energy, reverse=True))

    def _gate(self, spot: Spot) -> Reading | None:
        if not self.enabled:
            return self._skipped(None, "disabled")
        if not spot.surfline_id:
            return self._skipped(None, f"no surfline_id for {spot.id}")
        return None

    def _days(self, window: Window) -> int:
        return max(1, min(MAX_DAYS, math.ceil(window.hours / 24)))

    def _span(self, window: Window) -> tuple[datetime, datetime]:
        start = _aware(window.start)
        return start, start + timedelta(hours=window.hours - 1)

    def _run(self, assoc: dict) -> str | None:
        ts = assoc.get("runInitializationTimestamp")
        return _utc(ts).isoformat() if ts else None

    def _skipped(self, value, note: str) -> Reading:
        return Reading(value, SOURCE, "skipped", now(), note=note)


def benchmark(http: Http | None = None, enabled: bool | None = None) -> Surfline | None:
    """A benchmark only if one was asked for: `enabled=None` reads
    `SURF_SURFLINE`, unset by default, so normally no Surfline call is made."""
    if enabled is None:
        enabled = os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None
    return Surfline(http, enabled=True)
