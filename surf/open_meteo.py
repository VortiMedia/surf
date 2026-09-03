from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from .sources import Http, Reading, SourceDown, Window, explain, now
from .spots import Spot
from .waves import Forecast, SwellPartition, WaveField, Wind

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Models whose swell/windwave partitions are actually populated.
PARTITION_MODELS: tuple[str, ...] = ("gwam", "best_match", "ncep_gfswave025")

# Models that answer 200 but publish only total height/period; asking these for
# partitions returns a column of nulls.
TOTAL_ONLY_MODELS: tuple[str, ...] = ("ecmwf_wam025", "era5_ocean")

# Default fanout, partition-capable models first.
MODELS: tuple[str, ...] = ("gwam", "best_match", "ncep_gfswave025", "ecmwf_wam025")

# Plausible-looking names that Open-Meteo answers with 400.
REJECTED_MODELS: frozenset[str] = frozenset(
    {"gfswave025", "gfswave016", "meteofrance_wam", "ecmwf_wam", "gfs_wave"}
)

# ERA5 (and the wave reanalysis behind `era5_ocean`) reaches 1940; the
# partition-capable marine reanalysis only covers the recent years.
ARCHIVE_EARLIEST = date(1940, 1, 1)

# Open-Meteo serves today plus 15 further days; asking beyond it is a 400.
MAX_FORECAST_DAYS = 15

TOTAL_VARS = ("wave_height", "wave_period", "wave_direction")
PARTITION_VARS = (
    "swell_wave_height",
    "swell_wave_period",
    "swell_wave_direction",
    "wind_wave_height",
    "wind_wave_period",
    "wind_wave_direction",
)
WIND_VARS = ("wind_speed_10m", "wind_direction_10m")

# Deep-water point off Long Island, used only for liveness probes.
PROBE_LAT, PROBE_LON = 40.5, -73.5


def _f(v: Any) -> float | None:
    # A missing hour is JSON null; it must never become 0.0.
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_time(stamp: str) -> datetime:
    # Responses are requested with timezone=UTC and come back naive.
    parsed = datetime.fromisoformat(stamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_utc(when: datetime) -> datetime:
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when.astimezone(timezone.utc)


def _column(hourly: dict, key: str, length: int) -> list[float | None]:
    raw = hourly.get(key) or []
    vals = [_f(v) for v in raw]
    vals.extend([None] * (length - len(vals)))
    return vals[:length]


def _partition(
    height: float | None, period: float | None, direction: float | None, kind: str
) -> SwellPartition | None:
    # All three numbers are required: a height with no period is a data hole,
    # not a swell train.
    if height is None or period is None or direction is None:
        return None
    if height <= 0.0 or period <= 0.0:
        return None
    return SwellPartition(
        height_m=height, period_s=period, direction_deg=direction % 360.0, kind=kind
    )


def _wave_fields(
    hourly: dict, model: str, winds: dict[datetime, Wind] | None = None
) -> tuple[WaveField, ...]:
    times = [_parse_time(t) for t in (hourly.get("time") or [])]
    n = len(times)
    heights = _column(hourly, "wave_height", n)
    periods = _column(hourly, "wave_period", n)
    swell_h = _column(hourly, "swell_wave_height", n)
    swell_p = _column(hourly, "swell_wave_period", n)
    swell_d = _column(hourly, "swell_wave_direction", n)
    ww_h = _column(hourly, "wind_wave_height", n)
    ww_p = _column(hourly, "wind_wave_period", n)
    ww_d = _column(hourly, "wind_wave_direction", n)
    total_d = _column(hourly, "wave_direction", n)

    fields: list[WaveField] = []
    for i, t in enumerate(times):
        if heights[i] is None:
            continue
        parts: list[SwellPartition] = []
        swell = _partition(swell_h[i], swell_p[i], swell_d[i], "swell")
        if swell:
            parts.append(swell)
        windwave = _partition(ww_h[i], ww_p[i], ww_d[i], "windwave")
        if windwave:
            parts.append(windwave)
        if not parts:
            # No split published: the total is a usable wave train, but labelled
            # "total" so nothing mistakes it for a resolved partition.
            total = _partition(heights[i], periods[i], total_d[i], "total")
            if total:
                parts.append(total)
        fields.append(
            WaveField(
                time=t,
                partitions=tuple(parts),
                wind=(winds or {}).get(t),
                total_height_m=heights[i],
                total_period_s=periods[i],
                model=model,
            )
        )
    return tuple(fields)


def _hourly_of(payload: dict) -> dict:
    hourly = payload.get("hourly")
    return hourly if isinstance(hourly, dict) else {}


class OpenMeteoMarine:
    """One named wave model. `MarineModelSet` fans these out; the breaker key is
    per model so a dead model cannot open the breaker for a live one."""

    def __init__(self, http: Http, model: str = "gwam", include_wind: bool = True):
        if model in REJECTED_MODELS:
            raise ValueError(
                f"{model!r} is not an Open-Meteo model id (verified 400). "
                f"Use one of {MODELS}."
            )
        self.model = model
        self.name = f"open-meteo-marine:{model}"
        self.http = http
        self.include_wind = include_wind

    @property
    def has_partitions(self) -> bool:
        return self.model not in TOTAL_ONLY_MODELS

    def preflight(self) -> Reading[bool]:
        started = now()
        params = {
            "latitude": PROBE_LAT,
            "longitude": PROBE_LON,
            "hourly": "wave_height",
            "forecast_days": 1,
            "timezone": "UTC",
            "models": self.model,
        }
        try:
            payload = self.http.get_json(self.name, MARINE_URL, params)
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", started, note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", started, note=_why(exc))
        alive = any(v is not None for v in _hourly_of(payload).get("wave_height", []))
        if not alive:
            return Reading(
                False, self.name, "degraded", started,
                note="answered but published no wave height at the probe point",
            )
        return Reading(True, self.name, "ok", started)

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        """Hourly wave state at the spot's fixed offshore point. Never raises;
        a failure comes back as a labelled Reading with value None."""
        started = now()
        start, end = _window_bounds(window)
        dropped: list[str] = []
        expected: list[str] = []   # gaps we asked for; labelled, but not degradation

        last_day = (end - timedelta(hours=1)).date()
        horizon = _today() + timedelta(days=MAX_FORECAST_DAYS)
        if last_day > horizon:
            dropped.append(
                f"window truncated at {horizon.isoformat()}: "
                f"Open-Meteo serves {MAX_FORECAST_DAYS} days beyond today"
            )
            last_day = horizon

        variables: tuple[str, ...] = TOTAL_VARS
        if self.has_partitions:
            variables += PARTITION_VARS
        else:
            expected.append(f"partitions: {self.model} publishes none (all null)")
            dropped.append(expected[-1])

        params = {
            "latitude": spot.offshore_lat,
            "longitude": spot.offshore_lon,
            "hourly": ",".join(variables),
            "start_date": start.date().isoformat(),
            "end_date": last_day.isoformat(),
            "timezone": "UTC",
            "models": self.model,
        }
        try:
            payload = self.http.get_json(self.name, MARINE_URL, params)
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", started, note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", started, note=_why(exc))

        winds: dict[datetime, Wind] = {}
        if self.include_wind:
            winds, wind_note = self._wind(spot, start, last_day)
            if wind_note:
                dropped.append(wind_note)

        hours = tuple(
            f for f in _wave_fields(_hourly_of(payload), self.model, winds)
            if start <= f.time < end
        )
        if not hours:
            return Reading(
                None, self.name, "failed", started,
                note="no hour in the requested window carried a wave height",
                dropped=tuple(dropped),
            )

        requested = max(1, int((end - start).total_seconds() // 3600))
        if len(hours) < requested:
            dropped.append(f"hours: {len(hours)} of {requested} requested")
        if self.has_partitions and not any(
            p.kind in ("swell", "windwave") for f in hours for p in f.partitions
        ):
            dropped.append("partitions: none populated at this point")
        if all((f.total_height_m or 0.0) == 0.0 for f in hours):
            dropped.append(f"{self.model} returned all zeros at this point")

        status = "degraded" if _degrading(dropped, expected) else "ok"
        forecast = Forecast(spot_id=spot.id, model=self.model, hours=hours)
        return Reading(
            forecast, self.name, status, started,
            note=f"{len(hours)}h from {self.model} at {spot.offshore_lat},{spot.offshore_lon}",
            dropped=tuple(dropped),
        )

    def _wind(
        self, spot: Spot, start: datetime, last_day: date
    ) -> tuple[dict[datetime, Wind], str]:
        # Wind lives on a different endpoint; losing it must not cost the waves,
        # so this returns ({}, reason) instead of raising.
        params = {
            "latitude": spot.lat,
            "longitude": spot.lon,
            "hourly": ",".join(WIND_VARS),
            "start_date": start.date().isoformat(),
            "end_date": last_day.isoformat(),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        try:
            payload = self.http.get_json("open-meteo-weather", WEATHER_URL, params)
        except SourceDown as exc:
            return {}, f"wind: {exc}"
        except Exception as exc:
            return {}, f"wind: {_why(exc)}"
        return _winds_of(_hourly_of(payload)), ""


def _winds_of(hourly: dict) -> dict[datetime, Wind]:
    times = [_parse_time(t) for t in (hourly.get("time") or [])]
    speed = _column(hourly, "wind_speed_10m", len(times))
    direction = _column(hourly, "wind_direction_10m", len(times))
    out: dict[datetime, Wind] = {}
    for i, t in enumerate(times):
        if speed[i] is None or direction[i] is None:
            continue
        out[t] = Wind(speed_mps=speed[i], direction_deg=direction[i] % 360.0)
    return out


class MarineModelSet:
    """One Reading per model. Each model is called on its own URL with its own
    breaker, and failures come back labelled rather than dropped."""

    name = "open-meteo-marine"

    def __init__(
        self, http: Http, models: Sequence[str] = MODELS, include_wind: bool = True
    ):
        self.sources: tuple[OpenMeteoMarine, ...] = tuple(
            OpenMeteoMarine(http, m, include_wind=include_wind) for m in models
        )

    def preflight(self) -> dict[str, Reading[bool]]:
        return {s.model: s.preflight() for s in self.sources}

    def partitions_by_model(self, spot: Spot, window: Window) -> dict[str, Reading[Forecast]]:
        return {s.model: s.partitions(spot, window) for s in self.sources}

    @staticmethod
    def live(readings: Iterable[Reading[Forecast]]) -> tuple[Forecast, ...]:
        return tuple(r.value for r in readings if r.ok and r.value is not None)


class OpenMeteoArchive:
    """Past conditions for any date. Two reanalyses are in play: the marine
    default has the swell/windwave split but only recent years, `era5_ocean` has
    total height/period back to 1940, so `conditions()` tries the split first."""

    name = "open-meteo-archive"

    def __init__(self, http: Http):
        self.http = http

    def preflight(self) -> Reading[bool]:
        started = now()
        params = {
            "latitude": PROBE_LAT,
            "longitude": PROBE_LON,
            "hourly": "wave_height",
            "start_date": "2024-03-24",
            "end_date": "2024-03-24",
            "timezone": "UTC",
        }
        try:
            payload = self.http.get_json(self.name, MARINE_URL, params)
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", started, note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", started, note=_why(exc))
        alive = any(v is not None for v in _hourly_of(payload).get("wave_height", []))
        if not alive:
            return Reading(
                False, self.name, "degraded", started,
                note="archive answered with no wave height at the probe point",
            )
        return Reading(True, self.name, "ok", started)

    def conditions(self, spot: Spot, on: date, hour: int) -> Reading[WaveField]:
        started = now()
        if on < ARCHIVE_EARLIEST:
            return Reading(
                None, self.name, "skipped", started,
                note=f"{on.isoformat()} predates the reanalysis ({ARCHIVE_EARLIEST.isoformat()})",
            )
        if on > _today():
            return Reading(
                None, self.name, "skipped", started,
                note=f"{on.isoformat()} is not in the past; use the forecast source",
            )

        dropped: list[str] = []
        field, note = self._marine_hour(spot, on, hour, model=None)
        if field is None or field.total_height_m is None:
            dropped.append("partition reanalysis has no data for this date")
            field, note = self._marine_hour(spot, on, hour, model="era5_ocean")
        if field is None:
            return Reading(
                None, self.name, "failed", started,
                note=note or f"no archived wave data for {on.isoformat()} {hour:02d}:00",
                dropped=tuple(dropped),
            )
        if not any(p.kind in ("swell", "windwave") for p in field.partitions):
            dropped.append("partitions: total height/period only")

        winds, wind_note = self._wind(spot, on)
        if wind_note:
            dropped.append(wind_note)
        wind = winds.get(field.time)
        if wind is None and not wind_note:
            dropped.append("wind: no archived value at this hour")
        field = WaveField(
            time=field.time,
            partitions=field.partitions,
            wind=wind,
            total_height_m=field.total_height_m,
            total_period_s=field.total_period_s,
            model=field.model,
        )
        status = "degraded" if _degrading(dropped, ()) else "ok"
        return Reading(
            field, self.name, status, started,
            note=f"{field.model} reanalysis, {on.isoformat()} {hour:02d}:00Z",
            dropped=tuple(dropped),
        )

    def _marine_hour(
        self, spot: Spot, on: date, hour: int, model: str | None
    ) -> tuple[WaveField | None, str]:
        variables = TOTAL_VARS + (PARTITION_VARS if model != "era5_ocean" else ())
        params: dict[str, Any] = {
            "latitude": spot.offshore_lat,
            "longitude": spot.offshore_lon,
            "hourly": ",".join(variables),
            "start_date": on.isoformat(),
            "end_date": on.isoformat(),
            "timezone": "UTC",
        }
        if model:
            params["models"] = model
        key = f"{self.name}:{model or 'default'}"
        try:
            payload = self.http.get_json(key, MARINE_URL, params)
        except SourceDown as exc:
            return None, str(exc)
        except Exception as exc:
            return None, _why(exc)
        wanted = datetime(on.year, on.month, on.day, hour % 24, tzinfo=timezone.utc)
        for f in _wave_fields(_hourly_of(payload), model or "open-meteo-marine"):
            if f.time == wanted:
                return f, ""
        return None, f"no archived hour at {wanted.isoformat()}"

    def _wind(self, spot: Spot, on: date) -> tuple[dict[datetime, Wind], str]:
        params = {
            "latitude": spot.lat,
            "longitude": spot.lon,
            "hourly": ",".join(WIND_VARS),
            "start_date": on.isoformat(),
            "end_date": on.isoformat(),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }
        try:
            payload = self.http.get_json(
                "open-meteo-archive-weather", WEATHER_ARCHIVE_URL, params
            )
        except SourceDown as exc:
            return {}, f"wind: {exc}"
        except Exception as exc:
            return {}, f"wind: {_why(exc)}"
        return _winds_of(_hourly_of(payload)), ""


def _today() -> date:
    return now().date()


def _window_bounds(window: Window) -> tuple[datetime, datetime]:
    start = _as_utc(window.start).replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=max(1, window.hours))


def _degrading(dropped: Sequence[str], expected: Sequence[str]) -> bool:
    # A column we knew was empty and never requested is labelled, not degraded.
    return any(d not in set(expected) for d in dropped)


def _why(exc: Exception) -> str:
    # Surfaces Open-Meteo's own "reason" string, which names the bad parameter.
    response = getattr(exc, "response", None)
    if response is not None:
        reason = ""
        try:
            body = response.json()
            reason = str(body.get("reason", ""))
        except Exception:
            reason = (response.text or "")[:120]
        return f"HTTP {response.status_code}: {reason}".strip()
    return explain(exc)
