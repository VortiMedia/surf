"""Seasonal swell/wind overlap over the derived climate cache."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .open_meteo import WEATHER_ARCHIVE_URL, MARINE_URL, _column, _parse_time, _hourly_of
from .sources import Http, Reading, SourceDown, now
from .spots import Spot, SpotBook, data_dir


MIN_SWELL_HEIGHT_M = 1.0
MIN_SWELL_PERIOD_S = 10.0
CALM_WIND_MPS = 12.0 / 3.6
MAX_OFFSHORE_ANGLE_DEG = 60.0
EVENT_GAP_HOURS = 6.0


@dataclass(frozen=True)
class ClimateSample:
    """One cell's wave and wind values at one shared UTC timestamp."""

    time: datetime
    swell_height_m: float | None
    swell_period_s: float | None
    swell_direction_deg: float | None
    wind_speed_mps: float | None
    wind_direction_deg: float | None


@dataclass(frozen=True)
class CellOverlap:
    spot_id: str
    shared_hours: int
    overlap_hours: int
    days: int
    independent_events: int
    event_durations_hours: tuple[float, ...]
    season: str
    local_hours: tuple[tuple[int, int], ...]
    years_with_event: tuple[int, ...]
    years_total: int

    @property
    def total_duration_hours(self) -> float:
        return sum(self.event_durations_hours)

    @property
    def mean_duration_hours(self) -> float:
        return self.total_duration_hours / self.independent_events if self.independent_events else 0.0

    @property
    def fraction_years(self) -> float:
        return len(self.years_with_event) / self.years_total if self.years_total else 0.0

    @property
    def rejected(self) -> bool:
        return self.overlap_hours == 0


@dataclass(frozen=True)
class ClimateResult:
    zone: str
    start: date
    end: date
    cells: tuple[CellOverlap, ...]
    source: str
    status: str
    fetched_at: datetime
    note: str = ""
    dropped: tuple[str, ...] = field(default_factory=tuple)
    terrain_shelter: str = "unverified: coarse wind grid cannot resolve local relief"

    @property
    def rejected(self) -> bool:
        return bool(self.cells) and all(cell.rejected for cell in self.cells)


class ClimateSource(Protocol):
    name: str

    def cell(self, spot: Spot, start: date, end: date) -> Reading[tuple[ClimateSample, ...]]: ...


def _utc_stamp(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _season(start: date, end: date) -> str:
    return f"{start:%Y-%m-%d} to {end:%Y-%m-%d} ({start:%b}–{end:%b})"


def _years(start: date, end: date) -> int:
    return max(0, end.year - start.year + 1)


def _is_overlap(sample: ClimateSample, spot: Spot) -> bool:
    if (
        sample.swell_height_m is None
        or sample.swell_period_s is None
        or sample.swell_direction_deg is None
        or sample.wind_speed_mps is None
        or sample.wind_direction_deg is None
    ):
        return False
    if sample.swell_height_m < MIN_SWELL_HEIGHT_M or sample.swell_period_s < MIN_SWELL_PERIOD_S:
        return False
    # Wind direction is where it comes FROM; the offshore bearing is also a
    # from-direction, so compare those directly.
    # The clean rule is deliberately an OR: calm wind is usable regardless of
    # direction, while stronger wind must be within 60 degrees of offshore.
    return (
        sample.wind_speed_mps <= CALM_WIND_MPS
        or _angle(sample.wind_direction_deg, spot.offshore_wind_bearing) <= MAX_OFFSHORE_ANGLE_DEG
    )


def overlap(spot: Spot, samples: tuple[ClimateSample, ...], start: date, end: date) -> CellOverlap:
    """Measure complete swell/wind hours, never either marginal series."""
    start_at = datetime.combine(start, datetime.min.time(), timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc)
    ordered = tuple(sorted((s for s in samples if start_at <= _utc_stamp(s.time) < end_at), key=lambda s: s.time))
    shared = tuple(
        s for s in ordered
        if s.swell_height_m is not None
        and s.swell_period_s is not None
        and s.swell_direction_deg is not None
        and s.wind_speed_mps is not None
        and s.wind_direction_deg is not None
    )
    good = tuple(s for s in shared if _is_overlap(s, spot))
    events: list[list[ClimateSample]] = []
    for sample in good:
        if not events or (_utc_stamp(sample.time) - _utc_stamp(events[-1][-1].time)).total_seconds() / 3600.0 > EVENT_GAP_HOURS:
            events.append([])
        events[-1].append(sample)
    durations = tuple(
        (_utc_stamp(event[-1].time) - _utc_stamp(event[0].time)).total_seconds() / 3600.0 + 1.0
        for event in events
    )
    local = ZoneInfo(spot.timezone) if spot.timezone else timezone.utc
    hours = Counter(_utc_stamp(s.time).astimezone(local).hour for s in good)
    days = len({_utc_stamp(s.time).astimezone(local).date() for s in good})
    years = tuple(sorted({_utc_stamp(s.time).year for s in good}))
    return CellOverlap(
        spot_id=spot.id,
        shared_hours=len(shared),
        overlap_hours=len(good),
        days=days,
        independent_events=len(events),
        event_durations_hours=durations,
        season=_season(start, end),
        local_hours=tuple(sorted(hours.items())),
        years_with_event=years,
        years_total=_years(start, end),
    )


def cache_path(zone: str, start: date, end: date, root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", zone.casefold()).strip("-") or "zone"
    return (root or (data_dir() / "climate")) / f"{safe}-{start.isoformat()}-{end.isoformat()}.json"


def _sample_json(sample: ClimateSample) -> dict[str, Any]:
    return {
        "time": _utc_stamp(sample.time).isoformat(),
        "swell_height_m": sample.swell_height_m,
        "swell_period_s": sample.swell_period_s,
        "swell_direction_deg": sample.swell_direction_deg,
        "wind_speed_mps": sample.wind_speed_mps,
        "wind_direction_deg": sample.wind_direction_deg,
    }


def _sample_from_json(raw: dict[str, Any]) -> ClimateSample:
    return ClimateSample(
        time=_utc_stamp(datetime.fromisoformat(raw["time"])),
        swell_height_m=raw.get("swell_height_m"),
        swell_period_s=raw.get("swell_period_s"),
        swell_direction_deg=raw.get("swell_direction_deg"),
        wind_speed_mps=raw.get("wind_speed_mps"),
        wind_direction_deg=raw.get("wind_direction_deg"),
    )


def save_cache(path: Path, result: ClimateResult, samples: dict[str, tuple[ClimateSample, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "zone": result.zone,
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "source": result.source,
        "status": result.status,
        "fetched_at": result.fetched_at.isoformat(),
        "note": result.note,
        "dropped": list(result.dropped),
        "cells": {spot_id: [_sample_json(s) for s in values] for spot_id, values in samples.items()},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_cache(path: Path, book: SpotBook) -> ClimateResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    zone, start, end = raw["zone"], date.fromisoformat(raw["start"]), date.fromisoformat(raw["end"])
    cells: list[CellOverlap] = []
    for spot_id, rows in raw.get("cells", {}).items():
        spot = book.get(spot_id)
        if spot is not None:
            cells.append(overlap(spot, tuple(_sample_from_json(r) for r in rows), start, end))
    return ClimateResult(
        zone=zone,
        start=start,
        end=end,
        cells=tuple(cells),
        source=raw["source"],
        status=raw["status"],
        fetched_at=datetime.fromisoformat(raw["fetched_at"]),
        note=raw.get("note", ""),
        dropped=tuple(raw.get("dropped", ())),
    )


def _archive_params(spot: Spot, start: date, end: date, variables: tuple[str, ...]) -> dict[str, str]:
    return {
        "latitude": str(spot.offshore_lat),
        "longitude": str(spot.offshore_lon),
        "hourly": ",".join(variables),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "UTC",
    }


class OpenMeteoClimate:
    """Bulk archive adapter. Wave and wind responses are joined by timestamp."""

    name = "open-meteo-climate"

    def __init__(self, http: Http):
        self.http = http

    def cell(self, spot: Spot, start: date, end: date) -> Reading[tuple[ClimateSample, ...]]:
        fetched = now()
        try:
            wave_params = _archive_params(
                spot,
                start,
                end,
                ("wave_height", "wave_period", "wave_direction"),
            )
            wave_params["models"] = "era5_ocean"
            waves = self.http.get_json(
                self.name,
                MARINE_URL,
                wave_params,
            )
            winds = self.http.get_json(
                self.name,
                WEATHER_ARCHIVE_URL,
                {
                    "latitude": str(spot.lat),
                    "longitude": str(spot.lon),
                    "hourly": "wind_speed_10m,wind_direction_10m",
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "timezone": "UTC",
                    "wind_speed_unit": "ms",
                },
            )
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", fetched, note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", fetched, note=f"{type(exc).__name__}: {exc}")

        wh = _hourly_of(waves)
        vh = _hourly_of(winds)
        wave_times = [_parse_time(t) for t in (wh.get("time") or [])]
        wind_times = [_parse_time(t) for t in (vh.get("time") or [])]
        wave_cols = {key: _column(wh, key, len(wave_times)) for key in (
            "wave_height", "wave_period", "wave_direction"
        )}
        wind_cols = {key: _column(vh, key, len(wind_times)) for key in (
            "wind_speed_10m", "wind_direction_10m"
        )}
        wi = {time: i for i, time in enumerate(wind_times)}
        samples: list[ClimateSample] = []
        for i, time in enumerate(wave_times):
            j = wi.get(time)
            if j is None:
                continue
            samples.append(ClimateSample(
                time=time,
                swell_height_m=wave_cols["wave_height"][i],
                swell_period_s=wave_cols["wave_period"][i],
                swell_direction_deg=wave_cols["wave_direction"][i],
                wind_speed_mps=wind_cols["wind_speed_10m"][j],
                wind_direction_deg=wind_cols["wind_direction_10m"][j],
            ))
        dropped = ["ERA5 Ocean total wave fields used as a swell proxy"]
        if not samples:
            dropped.append("no shared wave/wind timestamps")
        return Reading(
            tuple(samples), self.name, "degraded", fetched,
            note=f"{len(samples)} shared UTC hours; model=era5_ocean",
            dropped=tuple(dropped),
        )


def climate_cell_key(spot: Spot) -> tuple[float, float, float, float]:
    """Coordinates rounded to the coarse archive grid used for de-duplication."""
    return tuple(round(value, 2) for value in (
        spot.offshore_lat, spot.offshore_lon, spot.lat, spot.lon
    ))  # type: ignore[return-value]


def build_result(
    zone: str,
    spots: tuple[Spot, ...],
    samples: dict[str, tuple[ClimateSample, ...]],
    start: date,
    end: date,
    *,
    source: str,
    status: str,
    fetched_at: datetime,
    note: str = "",
    dropped: tuple[str, ...] = (),
) -> ClimateResult:
    return ClimateResult(
        zone=zone,
        start=start,
        end=end,
        cells=tuple(overlap(s, samples.get(s.id, ()), start, end) for s in spots),
        source=source,
        status=status,
        fetched_at=fetched_at,
        note=note,
        dropped=dropped,
    )
