"""Saved setup conditions and one scheduled evaluation.

The scheduler is intentionally a command boundary: cron, launchd, or another
runner can invoke ``surf watch run``.  The calculation remains the same source
and scoring path used by the manual forecast command.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .forecast import Hour, SpotForecast
from .response import Response
from .score import reference_field, score_hour
from .snapshots import SnapshotStore, size_band, snapshot_from_hour
from .sources import Reading, Window
from .spots import Spot, SpotBook


class WatchError(ValueError):
    """A saved setup is malformed or cannot be evaluated safely."""


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


@dataclass(frozen=True)
class Range:
    """Inclusive numeric bounds. A missing bound is an explicit no-limit."""

    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise WatchError("range minimum cannot exceed maximum")

    def contains(self, value: float | None) -> bool:
        return value is not None and (self.minimum is None or value >= self.minimum) and (self.maximum is None or value <= self.maximum)

    def as_dict(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.minimum is not None:
            out["min"] = self.minimum
        if self.maximum is not None:
            out["max"] = self.maximum
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> Range:
        data = data or {}
        if not isinstance(data, Mapping):
            raise WatchError("range must be an object")
        return cls(
            None if data.get("min") is None else float(data["min"]),
            None if data.get("max") is None else float(data["max"]),
        )


@dataclass(frozen=True)
class SwellCondition:
    kind: str = "swell"
    height_m: Range = field(default_factory=Range)
    period_s: Range = field(default_factory=Range)
    direction_deg: Range = field(default_factory=Range)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "height_m": self.height_m.as_dict(),
            "period_s": self.period_s.as_dict(),
            "direction_deg": self.direction_deg.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SwellCondition:
        return cls(
            kind=str(data.get("kind", "swell")),
            height_m=Range.from_dict(data.get("height_m")),
            period_s=Range.from_dict(data.get("period_s")),
            direction_deg=Range.from_dict(data.get("direction_deg")),
        )


@dataclass(frozen=True)
class WindCondition:
    speed_mps: Range = field(default_factory=Range)
    direction_deg: Range = field(default_factory=Range)

    def as_dict(self) -> dict[str, Any]:
        return {"speed_mps": self.speed_mps.as_dict(), "direction_deg": self.direction_deg.as_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WindCondition:
        return cls(
            speed_mps=Range.from_dict((data or {}).get("speed_mps")),
            direction_deg=Range.from_dict((data or {}).get("direction_deg")),
        )


@dataclass(frozen=True)
class TideCondition:
    height_m: Range = field(default_factory=Range)
    stages: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"height_m": self.height_m.as_dict(), "stages": list(self.stages)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> TideCondition:
        return cls(
            height_m=Range.from_dict((data or {}).get("height_m")),
            stages=tuple(str(stage) for stage in (data or {}).get("stages", ())),
        )


@dataclass(frozen=True)
class SetupConditions:
    """All condition axes are represented, even when a setup leaves one open."""

    swell_partitions: tuple[SwellCondition, ...] = ()
    direction_deg: Range = field(default_factory=Range)
    period_s: Range = field(default_factory=Range)
    size_band: str | None = None
    wind: WindCondition = field(default_factory=WindCondition)
    tide: TideCondition = field(default_factory=TideCondition)
    minimum_model_agreement: float | None = None
    lead_hours: Range = field(default_factory=Range)
    regime: str = ""

    def __post_init__(self) -> None:
        if self.minimum_model_agreement is not None and not 0.0 <= self.minimum_model_agreement <= 1.0:
            raise WatchError("minimum_model_agreement must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "swell_partitions": [item.as_dict() for item in self.swell_partitions],
            "direction_deg": self.direction_deg.as_dict(),
            "period_s": self.period_s.as_dict(),
            "size_band": self.size_band,
            "wind": self.wind.as_dict(),
            "tide": self.tide.as_dict(),
            "model_agreement": {"min": self.minimum_model_agreement} if self.minimum_model_agreement is not None else {},
            "lead_hours": self.lead_hours.as_dict(),
            "regime": self.regime,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SetupConditions:
        return cls(
            swell_partitions=tuple(SwellCondition.from_dict(item) for item in data.get("swell_partitions", ())),
            direction_deg=Range.from_dict(data.get("direction_deg")),
            period_s=Range.from_dict(data.get("period_s")),
            size_band=data.get("size_band"),
            wind=WindCondition.from_dict(data.get("wind")),
            tide=TideCondition.from_dict(data.get("tide")),
            minimum_model_agreement=(_model_minimum(data.get("model_agreement"))),
            lead_hours=Range.from_dict(data.get("lead_hours")),
            regime=str(data.get("regime", "")),
        )


def _model_minimum(data: Any) -> float | None:
    if data in (None, {}):
        return None
    if isinstance(data, Mapping):
        return None if data.get("min") is None else float(data["min"])
    return float(data)


@dataclass(frozen=True)
class SavedSetup:
    name: str
    spots: tuple[str, ...]
    conditions: SetupConditions

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.spots:
            raise WatchError("a setup needs a name and at least one spot")

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "spots": list(self.spots), "conditions": self.conditions.as_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SavedSetup:
        return cls(
            name=str(data["name"]),
            spots=tuple(str(spot) for spot in data["spots"]),
            conditions=SetupConditions.from_dict(data["conditions"]),
        )


class SetupStore:
    """One human-named saved setup per JSON file, with no prose state."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def save(self, setup: SavedSetup) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(setup.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def load(self) -> SavedSetup:
        try:
            return SavedSetup.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise WatchError(f"{self.path}: malformed saved setup: {exc}") from exc


@dataclass(frozen=True)
class Alert:
    setup: str
    spot: str
    valid_at: datetime | None
    fired: bool
    evidence: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class WatchRun:
    alerts: tuple[Alert, ...]
    snapshots_written: int = 0
    dropped: tuple[str, ...] = ()
    readings: tuple[Reading[Any], ...] = ()


def _direction_contains(bounds: Range, value: float | None) -> bool:
    if value is None:
        return False
    if bounds.minimum is None and bounds.maximum is None:
        return True
    minimum = bounds.minimum if bounds.minimum is not None else 0.0
    maximum = bounds.maximum if bounds.maximum is not None else 360.0
    value %= 360.0
    if minimum <= maximum:
        return minimum <= value <= maximum
    return value >= minimum or value <= maximum


def _match_swell(conditions: Sequence[SwellCondition], field: Any) -> bool:
    if not conditions:
        return True
    for wanted in conditions:
        matches = [partition for partition in field.partitions
                   if (not wanted.kind or partition.kind == wanted.kind)
                   and wanted.height_m.contains(partition.height_m)
                   and wanted.period_s.contains(partition.period_s)
                   and _direction_contains(wanted.direction_deg, partition.direction_deg)]
        if not matches:
            return False
    return True


def _matches(conditions: SetupConditions, spot: Spot, hour: Hour, now: datetime) -> tuple[bool, tuple[str, ...]]:
    reference = reference_field(hour.fields)
    primary = reference.primary if reference else None
    lead = (_utc(hour.at) - _utc(now)).total_seconds() / 3600.0
    lead_limited = conditions.lead_hours.minimum is not None or conditions.lead_hours.maximum is not None
    if lead < 0 or (lead_limited and not conditions.lead_hours.contains(lead)):
        return False, (f"lead time {lead:.1f} h outside saved limit",)
    if reference is None:
        return False, ("no model field",)
    if not _match_swell(conditions.swell_partitions, reference):
        return False, ("swell partition condition not met",)
    if not _direction_contains(conditions.direction_deg, primary.direction_deg if primary else None):
        return False, ("direction condition not met",)
    period_limited = conditions.period_s.minimum is not None or conditions.period_s.maximum is not None
    if period_limited and not conditions.period_s.contains(primary.period_s if primary else None):
        return False, ("period condition not met",)
    if conditions.size_band is not None:
        actual = size_band(reference.total_height_m)
        if actual != conditions.size_band:
            return False, (f"size band {actual or 'unknown'} does not match {conditions.size_band}",)
    wind = next((field.wind for field in hour.fields if field.wind is not None), None)
    if conditions.wind.speed_mps.minimum is not None or conditions.wind.speed_mps.maximum is not None:
        if wind is None or not conditions.wind.speed_mps.contains(wind.speed_mps):
            return False, ("wind speed condition not met",)
    if conditions.wind.direction_deg.minimum is not None or conditions.wind.direction_deg.maximum is not None:
        if wind is None or not _direction_contains(conditions.wind.direction_deg, wind.direction_deg):
            return False, ("wind direction condition not met",)
    if conditions.tide.height_m.minimum is not None or conditions.tide.height_m.maximum is not None:
        if hour.tide is None or not conditions.tide.height_m.contains(hour.tide.height_m):
            return False, ("tide height condition not met",)
    if conditions.tide.stages and (hour.tide is None or hour.tide.stage not in conditions.tide.stages):
        return False, ("tide stage condition not met",)
    components = score_hour(spot, hour.fields, Response.for_spot(spot))
    if conditions.minimum_model_agreement is not None and components.confidence.value < conditions.minimum_model_agreement:
        return False, (f"model agreement {components.confidence.value:.2f} below saved minimum",)
    evidence = [f"{len(hour.fields)} model field(s)", f"lead {lead:.1f} h"]
    if primary:
        evidence.append(f"{primary.period_s:.1f} s from {primary.direction_deg:.0f} deg")
    if reference.total_height_m is not None:
        evidence.append(f"offshore Hs {reference.total_height_m:.2f} m ({size_band(reference.total_height_m)})")
    if wind:
        evidence.append(f"wind {wind.speed_mps:.1f} m/s from {wind.direction_deg:.0f} deg")
    if hour.tide:
        evidence.append(f"tide {hour.tide.stage or 'unknown'} {hour.tide.height_m:+.2f} m")
    evidence.append(f"model agreement {components.confidence.value:.2f}")
    return True, tuple(evidence)


def evaluate_forecast(setup: SavedSetup, forecast: SpotForecast, *, now: datetime) -> Alert:
    """Evaluate the existing forecast result without fetching or fallback data."""
    failed = tuple(reading.label() for reading in forecast.readings if reading.status != "ok")
    if forecast.status != "ok" or failed:
        dropped = failed or (f"forecast:{forecast.status}",)
        return Alert(setup.name, forecast.spot.id, None, False, dropped=dropped,
                     reason="source evidence degraded; confident alert suppressed")
    for hour in forecast.hours:
        matched, evidence = _matches(setup.conditions, forecast.spot, hour, now)
        if matched:
            return Alert(setup.name, forecast.spot.id, hour.at, True, evidence=evidence)
    return Alert(setup.name, forecast.spot.id, None, False, reason="no forecast hour clears saved conditions")


def run_watch(
    setup: SavedSetup,
    *,
    service: Any,
    book: SpotBook,
    now: datetime,
    snapshot_store: SnapshotStore | None = None,
    model_run: str | None = None,
) -> WatchRun:
    """Run one scheduled check using ``ForecastService.outlook`` per spot."""
    now = _utc(now)
    max_lead = setup.conditions.lead_hours.maximum or 120.0
    hours = max(1, int(max_lead) + 2)
    alerts: list[Alert] = []
    dropped: list[str] = []
    snapshots_written = 0
    readings: list[Reading[Any]] = []
    for spot_name in setup.spots:
        spot = book.resolve(spot_name)
        if spot is None:
            alerts.append(Alert(setup.name, spot_name, None, False, reason="spot does not resolve"))
            continue
        forecast = service.outlook(spot, Window.from_hour(now, hours))
        readings.extend(forecast.readings)
        alerts.append(evaluate_forecast(setup, forecast, now=now))
        if snapshot_store is None or not model_run:
            if snapshot_store is not None and not model_run:
                dropped.append(f"{spot.id}: snapshot not written; explicit model_run is required")
            continue
        for hour in forecast.hours:
            if _utc(hour.at) <= now:
                continue
            try:
                snapshot = snapshot_from_hour(
                    forecast, hour, issued_at=now, model_run=model_run,
                    height_quantity="offshore_hs", regime=setup.conditions.regime,
                )
                snapshot_store.write(snapshot, now=now)
            except ValueError as exc:
                if "immutable" in str(exc):
                    continue
                dropped.append(f"{spot.id} {hour.at.isoformat()}: snapshot not written: {exc}")
            else:
                snapshots_written += 1
    return WatchRun(tuple(alerts), snapshots_written, tuple(dropped), tuple(readings))
