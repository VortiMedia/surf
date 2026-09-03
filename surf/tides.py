from __future__ import annotations

from datetime import date, datetime, timezone

from .sources import Http, Reading, SourceDown, now
from .spots import Spot
from .waves import TidePoint

COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"

COOPS = "coops"
OPEN_METEO = "open_meteo_tides"

# MLLW is the chart datum tide tables are read in; Open-Meteo can only give
# MSL, hence the datum label on every reading.
_COOPS_DATUM = "MLLW"
_OPEN_METEO_DATUM = "MSL"

_APPLICATION = "surf-intelligence"


class CoopsError(RuntimeError):
    """CO-OPS returns HTTP 200 with `{"error": {...}}` for a bad station, datum
    or date; unraised, that parses as an empty prediction list, i.e. a flat tide.
    """


def _parse_coops_time(stamp: str) -> datetime:
    # Timestamps are tz-naive in whatever zone was requested; we always ask GMT.
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def _coops_payload(response_json: dict) -> dict:
    if "error" in response_json:
        raise CoopsError(str(response_json["error"].get("message", response_json["error"])))
    return response_json


def _stage_from_neighbours(prev_h: float | None, next_h: float | None, h: float) -> str:
    """Rising or falling from the curve either side; CO-OPS labels the extremes
    itself, so this only fills the points in between."""
    if prev_h is not None and next_h is not None:
        # Strict, so an hourly sample sitting at the same height as the hi/lo
        # turn beside it is not reported as a second high.
        if h > prev_h and h > next_h:
            return "high"
        if h < prev_h and h < next_h:
            return "low"
    if next_h is not None and next_h != h:
        return "rising" if next_h > h else "falling"
    if prev_h is not None and prev_h != h:
        return "rising" if h > prev_h else "falling"
    return ""


def _label_stages(points: list[TidePoint]) -> tuple[TidePoint, ...]:
    """Fill empty stages from the curve, leaving explicitly stated ones alone."""
    out: list[TidePoint] = []
    for i, p in enumerate(points):
        if p.stage:
            out.append(p)
            continue
        prev_h = points[i - 1].height_m if i > 0 else None
        next_h = points[i + 1].height_m if i + 1 < len(points) else None
        out.append(TidePoint(time=p.time, height_m=p.height_m,
                             stage=_stage_from_neighbours(prev_h, next_h, p.height_m)))
    return tuple(out)


def _merge(hilo: list[TidePoint], hourly: list[TidePoint]) -> tuple[TidePoint, ...]:
    """Hourly gives a readable curve, hi/lo the exact turn times no hourly sample
    lands on. Keep both; hi/lo wins a collision, being the actual extreme."""
    by_time: dict[datetime, TidePoint] = {p.time: p for p in hourly}
    by_time.update({p.time: p for p in hilo})
    return _label_stages(sorted(by_time.values(), key=lambda p: p.time))


class CoopsTides:
    """NOAA CO-OPS predictions and water level. Days are UTC, so curves line up
    against forecast hours."""

    name = COOPS

    def __init__(self, http: Http | None = None):
        self.http = http or Http()

    def _get(self, params: dict) -> dict:
        base = {
            "station": params.pop("station"),
            "units": "metric",
            "time_zone": "gmt",
            "format": "json",
            "application": _APPLICATION,
        }
        base.update(params)
        r = self.http.get(self.name, COOPS_URL, params=base)
        try:
            return _coops_payload(r.json())
        except CoopsError:
            # A 200 carrying an error is a failure of this source; the breaker
            # must count it or a dead station is retried forever.
            self.http.breaker(self.name).record_failure()
            raise

    def _predictions(self, station: str, day: date, interval: str | None) -> list[TidePoint]:
        stamp = day.strftime("%Y%m%d")
        params = {
            "station": station,
            "product": "predictions",
            "datum": _COOPS_DATUM,
            "begin_date": stamp,
            "end_date": stamp,
        }
        if interval:
            params["interval"] = interval
        rows = self._get(params).get("predictions", [])
        stages = {"H": "high", "L": "low"}
        return [
            TidePoint(
                time=_parse_coops_time(row["t"]),
                height_m=float(row["v"]),
                stage=stages.get(row.get("type", ""), ""),
            )
            for row in rows
        ]

    def preflight(self) -> Reading[bool]:
        try:
            points = self._predictions("8531680", now().date(), "hilo")
        except SourceDown as e:
            return Reading(None, self.name, "skipped", now(), note=str(e))
        except Exception as e:
            return Reading(False, self.name, "failed", now(), note=f"{type(e).__name__}: {e}")
        return Reading(bool(points), self.name, "ok", now(), note=f"{len(points)} hi/lo points")

    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        station = spot.tide_station
        if not station:
            return Reading(None, self.name, "skipped", now(),
                           note=f"{spot.id} has no CO-OPS station")
        try:
            hilo = self._predictions(station, day, "hilo")
        except SourceDown as e:
            return Reading(None, self.name, "skipped", now(), note=str(e))
        except Exception as e:
            return Reading(None, self.name, "failed", now(),
                           note=f"predictions hilo: {type(e).__name__}: {e}")

        # The hourly curve is a convenience on top of the hi/lo extremes, so
        # losing it degrades the reading instead of failing it.
        dropped: list[str] = []
        try:
            hourly = self._predictions(station, day, "h")
        except Exception:
            hourly = []
            dropped.append("hourly-curve")

        points = _merge(hilo, hourly)
        if not points:
            return Reading(None, self.name, "failed", now(),
                           note=f"station {station} returned no predictions for {day}")
        status = "degraded" if dropped else "ok"
        note = f"station {station} datum={_COOPS_DATUM} predicted ({len(hilo)} hi/lo)"
        return Reading(points, self.name, status, now(), note=note, dropped=tuple(dropped))

    def surge(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        """Observed water level minus predicted tide: the storm surge. Past days
        only, and the returned heights are the surge, not a water level.
        """
        station = spot.tide_station
        if not station:
            return Reading(None, self.name, "skipped", now(),
                           note=f"{spot.id} has no CO-OPS station")
        stamp = day.strftime("%Y%m%d")
        try:
            observed_rows = self._get({
                "station": station,
                "product": "water_level",
                "datum": _COOPS_DATUM,
                "begin_date": stamp,
                "end_date": stamp,
            }).get("data", [])
            predicted = self._predictions(station, day, None)
        except SourceDown as e:
            return Reading(None, self.name, "skipped", now(), note=str(e))
        except Exception as e:
            return Reading(None, self.name, "failed", now(),
                           note=f"surge: {type(e).__name__}: {e}")

        # Both products are 6-minute series on the same clock, so matching on the
        # timestamp is exact — no interpolation, and any gap simply drops out.
        pred_by_time = {p.time: p.height_m for p in predicted}
        points: list[TidePoint] = []
        unmatched = 0
        for row in observed_rows:
            t = _parse_coops_time(row["t"])
            if t not in pred_by_time or row.get("v") in ("", None):
                unmatched += 1
                continue
            points.append(TidePoint(time=t, height_m=float(row["v"]) - pred_by_time[t]))
        if not points:
            return Reading(None, self.name, "failed", now(),
                           note=f"station {station} has no observed water level for {day}")
        peak = max(points, key=lambda p: abs(p.height_m))
        note = (f"station {station} surge = observed - predicted, "
                f"peak {peak.height_m:+.2f} m at {peak.time:%H:%M}Z")
        dropped = (f"{unmatched}-unmatched-samples",) if unmatched else ()
        status = "degraded" if unmatched else "ok"
        return Reading(tuple(points), self.name, status, now(), note=note, dropped=dropped)


class OpenMeteoTides:
    """`sea_level_height_msl` — global, keyless, hourly, MSL not MLLW. Being a
    model field it already carries the surge; there is nothing to subtract.
    """

    name = OPEN_METEO

    def __init__(self, http: Http | None = None):
        self.http = http or Http()

    def _hourly(self, lat: float, lon: float, day: date) -> tuple[list[TidePoint], int]:
        stamp = day.isoformat()
        r = self.http.get(self.name, OPEN_METEO_MARINE, params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "sea_level_height_msl",
            "start_date": stamp,
            "end_date": stamp,
            "timezone": "GMT",
        })
        block = r.json().get("hourly") or {}
        times = block.get("time") or []
        heights = block.get("sea_level_height_msl") or []
        points: list[TidePoint] = []
        nulls = 0
        for t, h in zip(times, heights):
            if h is None:
                nulls += 1
                continue
            points.append(TidePoint(time=datetime.fromisoformat(t).replace(tzinfo=timezone.utc),
                                    height_m=float(h)))
        return points, nulls

    def preflight(self) -> Reading[bool]:
        try:
            points, _ = self._hourly(40.47, -74.01, now().date())
        except SourceDown as e:
            return Reading(None, self.name, "skipped", now(), note=str(e))
        except Exception as e:
            return Reading(False, self.name, "failed", now(), note=f"{type(e).__name__}: {e}")
        return Reading(bool(points), self.name, "ok", now(), note=f"{len(points)} hourly points")

    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        """Sampled at the spot itself: tide is a shoreline quantity, and an
        offshore point differs by minutes near a bay mouth."""
        try:
            points, nulls = self._hourly(spot.lat, spot.lon, day)
        except SourceDown as e:
            return Reading(None, self.name, "skipped", now(), note=str(e))
        except Exception as e:
            return Reading(None, self.name, "failed", now(),
                           note=f"{type(e).__name__}: {e}")
        if not points:
            return Reading(None, self.name, "failed", now(),
                           note=f"no sea_level_height_msl at {spot.lat},{spot.lon} on {day}")
        dropped: list[str] = []
        if nulls:
            dropped.append(f"{nulls}-null-hours")
        if len(points) + nulls < 24:
            dropped.append(f"{24 - len(points) - nulls}-hours-missing")
        note = (f"model sea_level_height_msl at {spot.lat:.4f},{spot.lon:.4f} "
                f"datum={_OPEN_METEO_DATUM} (not MLLW)")
        status = "degraded" if dropped else "ok"
        return Reading(_label_stages(points), self.name, status, now(),
                       note=note, dropped=tuple(dropped))


class TideAdapter:
    """A CO-OPS station if the spot has one, else the global model. A station
    that is down falls back to the model as a `degraded` reading.
    """

    name = "tides"

    def __init__(self, http: Http | None = None,
                 coops: CoopsTides | None = None,
                 open_meteo: OpenMeteoTides | None = None):
        shared = http or Http()
        self.coops = coops or CoopsTides(shared)
        self.open_meteo = open_meteo or OpenMeteoTides(shared)

    def preflight(self) -> Reading[bool]:
        """Up if either mechanism is up: CO-OPS being down only means every spot
        falls back to the global model."""
        c = self.coops.preflight()
        o = self.open_meteo.preflight()
        alive = [r.source for r in (c, o) if r.value]
        down = tuple(f"{r.source}:{r.status}" for r in (c, o) if not r.value)
        if not alive:
            return Reading(False, self.name, "failed", now(),
                           note=f"{c.label()} | {o.label()}")
        status = "degraded" if down else "ok"
        return Reading(True, self.name, status, now(),
                       note="up: " + ",".join(alive), dropped=down)

    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        if not spot.tide_station:
            return self.open_meteo.curve(spot, day)

        station_reading = self.coops.curve(spot, day)
        if station_reading.ok:
            return station_reading

        fallback = self.open_meteo.curve(spot, day)
        why = f"coops {station_reading.status}: {station_reading.note or 'no detail'}"
        if not fallback.ok:
            return Reading(None, self.name, "failed", now(),
                           note=f"{why} | open_meteo {fallback.status}: {fallback.note}")
        return Reading(
            fallback.value, fallback.source, "degraded", fallback.fetched_at,
            note=f"{fallback.note}; fell back — {why}",
            dropped=fallback.dropped + (f"{COOPS}-station-{spot.tide_station}",),
        )

    def surge(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        """Observed minus predicted, US stations only; there is no global
        equivalent, so elsewhere this is `skipped` rather than approximated."""
        if not spot.tide_station:
            return Reading(None, self.name, "skipped", now(),
                           note="storm surge needs an observing station; none for "
                                f"{spot.id} (model tide already includes it)")
        return self.coops.surge(spot, day)
