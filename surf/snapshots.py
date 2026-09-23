"""Frozen forecast records and later, observation-backed verification.

This module deliberately keeps the forecast and outcome paths separate.  A
snapshot is made from the model fields that were available when it was issued;
an observation attached to a live ``Hour`` is never silently copied into it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from .forecast import Hour, SpotForecast
from .response import Response
from .score import Components, reference_field, score_hour
from .sessions import Session
from .sources import Reading, Status
from .spots import Derived, Spot
from .waves import SwellPartition, WaveField, angle_between

HeightQuantity = Literal["offshore_hs", "nearshore_hs", "face_height"]
HEIGHT_QUANTITIES = frozenset(("offshore_hs", "nearshore_hs", "face_height"))
OBSERVATION_TOLERANCE = timedelta(hours=3)


class SnapshotError(ValueError):
    """A forecast snapshot cannot be safely written or interpreted."""


def _utc(when: datetime) -> datetime:
    """Normalize source timestamps without inventing a local timezone."""
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _iso(when: datetime) -> str:
    return _utc(when).isoformat()


def _finite(value: float | None) -> bool:
    return value is None or math.isfinite(value)


def _component_dict(components: Components) -> dict[str, Any]:
    return {
        name: {"value": getattr(components, name).value,
               "raw": getattr(components, name).raw,
               "basis": getattr(components, name).basis}
        for name in ("barrel", "cleanness", "size", "confidence")
    }


def _components_from_dict(data: Mapping[str, Any]) -> Components:
    from .score import Component

    values = {}
    for name in ("barrel", "cleanness", "size", "confidence"):
        item = data.get(name)
        if not isinstance(item, Mapping):
            raise SnapshotError(f"predicted_components missing {name}")
        values[name] = Component(
            float(item["value"]), str(item.get("basis", "")),
            None if item.get("raw") is None else float(item["raw"]),
        )
    return Components(**values)


@dataclass(frozen=True)
class SourceStatus:
    """The source receipt frozen into a snapshot."""

    source: str
    status: Status
    fetched_at: datetime
    model_run: str | None = None
    note: str = ""
    dropped: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fetched_at", _utc(self.fetched_at))
        object.__setattr__(self, "dropped", tuple(self.dropped))

    @classmethod
    def from_reading(cls, reading: Reading[Any]) -> SourceStatus:
        return cls(
            source=reading.source,
            status=reading.status,
            fetched_at=_utc(reading.fetched_at),
            model_run=reading.model_run,
            note=reading.note,
            dropped=tuple(reading.dropped),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "fetched_at": _iso(self.fetched_at),
            "model_run": self.model_run,
            "note": self.note,
            "dropped": list(self.dropped),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceStatus:
        return cls(
            source=str(data["source"]),
            status=data["status"],
            fetched_at=_parse_time(data["fetched_at"]),
            model_run=data.get("model_run"),
            note=str(data.get("note", "")),
            dropped=tuple(str(item) for item in data.get("dropped", ())),
        )


def geometry_version(spot: Spot, response: Response | None = None,
                     slope: Derived | None = None) -> str:
    """Return a stable version for the stored geometry used in scoring.

    The digest includes values and provenance, so changing either creates a new
    version instead of changing the meaning of old snapshots.
    """
    response = response or Response.for_spot(spot)
    slope = slope or spot.beach_slope
    payload = {
        "spot": spot.id,
        "normal": (spot.shore_normal.value, spot.shore_normal.provenance, spot.shore_normal.note),
        "slope": (slope.value, slope.provenance, slope.note) if slope else None,
        "exposure": (response.exposure.value, response.exposure.provenance, response.exposure.note),
        "method": response.method,
        "reach_deg_per_second": response.reach_deg_per_second,
        "shadow_fraction": response.shadow_fraction,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "geometry-v1:" + hashlib.sha256(encoded).hexdigest()[:16]


def size_band(height_m: float | None) -> str | None:
    """Name an offshore-Hs band only when a height was actually supplied."""
    if height_m is None:
        return None
    feet = height_m * 3.280839895
    if feet < 3.0:
        return "under-3-ft"
    if feet < 6.0:
        return "3-5-ft"
    if feet < 10.0:
        return "6-8-ft"
    return "10-ft-plus"


@dataclass(frozen=True)
class ForecastSnapshot:
    """One forecast as it existed before ``valid_at``.

    ``predicted_height_m`` is accompanied by ``height_quantity``.  In
    particular, no face-height conversion is performed here.
    """

    issued_at: datetime
    valid_at: datetime
    model_run: str
    lead_hours: float
    spot: str
    region: str
    predicted_components: Components
    source_status: tuple[SourceStatus, ...]
    geometry_version: str
    height_quantity: HeightQuantity
    predicted_height_m: float | None
    period_s: float | None = None
    direction_deg: float | None = None
    size_band: str | None = None
    regime: str = ""

    def __post_init__(self) -> None:
        issued = _utc(self.issued_at)
        valid = _utc(self.valid_at)
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "valid_at", valid)
        if issued >= valid:
            raise SnapshotError("issued_at must precede valid_at")
        expected = (valid - issued).total_seconds() / 3600.0
        if not math.isclose(self.lead_hours, expected, abs_tol=1e-6):
            raise SnapshotError(
                f"lead_hours {self.lead_hours} does not match valid_at-issued_at {expected}"
            )
        if not self.model_run.strip():
            raise SnapshotError("model_run is required; do not invent a run identifier")
        if not self.spot.strip() or not self.region.strip():
            raise SnapshotError("spot and region are required")
        if self.height_quantity not in HEIGHT_QUANTITIES:
            raise SnapshotError(f"unknown height quantity {self.height_quantity!r}")
        if not self.geometry_version.strip():
            raise SnapshotError("geometry_version is required")
        if not _finite(self.predicted_height_m) or not _finite(self.period_s) or not _finite(self.direction_deg):
            raise SnapshotError("snapshot measurements must be finite or missing")
        if self.predicted_height_m is not None and self.predicted_height_m < 0:
            raise SnapshotError("predicted height cannot be negative")
        if self.size_band is None:
            object.__setattr__(self, "size_band", size_band(self.predicted_height_m))
        object.__setattr__(self, "source_status", tuple(self.source_status))

    @property
    def snapshot_id(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "issued_at": _iso(self.issued_at),
            "valid_at": _iso(self.valid_at),
            "model_run": self.model_run,
            "lead_hours": self.lead_hours,
            "spot": self.spot,
            "region": self.region,
            "predicted_components": _component_dict(self.predicted_components),
            "source_status": [item.as_dict() for item in self.source_status],
            "geometry_version": self.geometry_version,
            "height_quantity": self.height_quantity,
            "predicted_height_m": self.predicted_height_m,
            "period_s": self.period_s,
            "direction_deg": self.direction_deg,
            "size_band": self.size_band,
            "regime": self.regime,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ForecastSnapshot:
        return cls(
            issued_at=_parse_time(data["issued_at"]),
            valid_at=_parse_time(data["valid_at"]),
            model_run=str(data["model_run"]),
            lead_hours=float(data["lead_hours"]),
            spot=str(data["spot"]),
            region=str(data["region"]),
            predicted_components=_components_from_dict(data["predicted_components"]),
            source_status=tuple(SourceStatus.from_dict(item) for item in data["source_status"]),
            geometry_version=str(data["geometry_version"]),
            height_quantity=data["height_quantity"],
            predicted_height_m=(None if data.get("predicted_height_m") is None
                                else float(data["predicted_height_m"])),
            period_s=None if data.get("period_s") is None else float(data["period_s"]),
            direction_deg=None if data.get("direction_deg") is None else float(data["direction_deg"]),
            size_band=data.get("size_band"),
            regime=str(data.get("regime", "")),
        )


def snapshot_from_hour(
    forecast: SpotForecast,
    hour: Hour,
    *,
    issued_at: datetime,
    model_run: str,
    height_quantity: HeightQuantity = "offshore_hs",
    predicted_height_m: float | None = None,
    regime: str = "",
    response: Response | None = None,
) -> ForecastSnapshot:
    """Freeze model output for an hour; the live observation is ignored."""
    response = response or Response.for_spot(forecast.spot)
    components = score_hour(forecast.spot, hour.fields, response, slope=forecast.slope)
    reference = reference_field(hour.fields)
    primary = reference.primary if reference is not None else None

    if predicted_height_m is None:
        if height_quantity == "offshore_hs":
            # A partition height is not total Hs. Keep it missing when the source
            # did not supply the requested quantity.
            predicted_height_m = reference.total_height_m if reference is not None else None
        elif height_quantity == "nearshore_hs":
            predicted_height_m = components.size.raw
        elif height_quantity == "face_height":
            # Face height is intentionally not calculated from nearshore Hs.
            predicted_height_m = None

    return ForecastSnapshot(
        issued_at=issued_at,
        valid_at=hour.at,
        model_run=model_run,
        lead_hours=(_utc(hour.at) - _utc(issued_at)).total_seconds() / 3600.0,
        spot=forecast.spot.id,
        region=forecast.spot.region,
        predicted_components=components,
        source_status=tuple(SourceStatus.from_reading(r) for r in forecast.readings),
        geometry_version=geometry_version(forecast.spot, response, forecast.slope),
        height_quantity=height_quantity,
        predicted_height_m=predicted_height_m,
        period_s=primary.period_s if primary is not None else None,
        direction_deg=primary.direction_deg if primary is not None else None,
        regime=regime,
    )


freeze_forecast = snapshot_from_hour


class SnapshotStore:
    """Append-only JSONL store. Existing snapshot ids can never be replaced."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self) -> tuple[ForecastSnapshot, ...]:
        if not self.path.exists():
            return ()
        snapshots: list[ForecastSnapshot] = []
        for line, raw in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                snapshots.append(ForecastSnapshot.from_dict(json.loads(raw)))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise SnapshotError(f"{self.path}: malformed snapshot at line {line}: {exc}") from exc
        return tuple(snapshots)

    def write(self, snapshot: ForecastSnapshot, *, now: datetime | None = None) -> str:
        current = _utc(now or datetime.now(timezone.utc))
        if not snapshot.issued_at <= current < snapshot.valid_at:
            raise SnapshotError("snapshot must be written at or after issued_at and before valid_at")
        existing = self.read()
        if any(item.snapshot_id == snapshot.snapshot_id for item in existing):
            raise SnapshotError("snapshot is immutable and already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot.as_dict(), sort_keys=True, separators=(",", ":")) + "\n")
        return snapshot.snapshot_id


@dataclass(frozen=True)
class BuoyObservation:
    """A later buoy value with an explicit height quantity."""

    spot: str
    field: WaveField
    height_quantity: HeightQuantity = "offshore_hs"


@dataclass(frozen=True)
class VerifiedSnapshot:
    snapshot: ForecastSnapshot
    observation: BuoyObservation | None
    sessions: tuple[Session, ...]
    scored: bool
    height_error_m: float | None = None
    period_error_s: float | None = None
    direction_error_deg: float | None = None
    reason: str = ""

    @property
    def regime(self) -> str:
        """Use an issued regime first; otherwise retain one explicit session regime."""
        if self.snapshot.regime:
            return self.snapshot.regime
        regimes = {session.regime for session in self.sessions if session.regime}
        return next(iter(regimes)) if len(regimes) == 1 else ""


@dataclass(frozen=True)
class ErrorGroup:
    lead_hours: float
    region: str
    period_s: float | None
    direction_deg: float | None
    size_band: str | None
    regime: str
    count: int
    mae_height_m: float | None
    mae_period_s: float | None
    mae_direction_deg: float | None


@dataclass(frozen=True)
class VerificationReport:
    rows: tuple[VerifiedSnapshot, ...]
    groups: tuple[ErrorGroup, ...]

    @property
    def scored(self) -> tuple[VerifiedSnapshot, ...]:
        return tuple(row for row in self.rows if row.scored)

    @property
    def unscored(self) -> tuple[VerifiedSnapshot, ...]:
        return tuple(row for row in self.rows if not row.scored)

    @property
    def missing_observations(self) -> tuple[VerifiedSnapshot, ...]:
        return tuple(row for row in self.rows if row.observation is None)


def _observation_values(observation: BuoyObservation) -> tuple[float | None, float | None, float | None]:
    primary = observation.field.primary
    height = observation.field.total_height_m if observation.height_quantity == "offshore_hs" else None
    period = primary.period_s if primary is not None else None
    direction = primary.direction_deg if primary is not None else None
    return height, period, direction


def verify_snapshot(
    snapshot: ForecastSnapshot,
    observation: BuoyObservation | WaveField | None,
    sessions: Iterable[Session] = (),
    *,
    tolerance: timedelta = OBSERVATION_TOLERANCE,
) -> VerifiedSnapshot:
    """Score available quantities, preserving a missing or incompatible outcome."""
    if isinstance(observation, WaveField):
        observation = BuoyObservation(snapshot.spot, observation)
    joined_sessions = tuple(
        session for session in sessions
        if session.spot_id == snapshot.spot and session.on == snapshot.valid_at.date()
    )
    if observation is None:
        return VerifiedSnapshot(snapshot, None, joined_sessions, False, reason="missing observation")
    if observation.spot != snapshot.spot:
        return VerifiedSnapshot(snapshot, observation, joined_sessions, False, reason="observation spot mismatch")
    if abs(_utc(observation.field.time) - snapshot.valid_at) > tolerance:
        return VerifiedSnapshot(snapshot, observation, joined_sessions, False, reason="observation outside tolerance")
    if observation.height_quantity != snapshot.height_quantity:
        return VerifiedSnapshot(snapshot, observation, joined_sessions, False, reason="height quantity mismatch")

    observed_height, observed_period, observed_direction = _observation_values(observation)
    height_error = (
        abs(snapshot.predicted_height_m - observed_height)
        if snapshot.predicted_height_m is not None and observed_height is not None else None
    )
    period_error = (
        abs(snapshot.period_s - observed_period)
        if snapshot.period_s is not None and observed_period is not None else None
    )
    direction_error = (
        angle_between(snapshot.direction_deg, observed_direction)
        if snapshot.direction_deg is not None and observed_direction is not None else None
    )
    scored = any(value is not None for value in (height_error, period_error, direction_error))
    return VerifiedSnapshot(
        snapshot, observation, joined_sessions, scored,
        height_error, period_error, direction_error,
        "" if scored else "observation has no comparable fields",
    )


def _group(rows: Sequence[VerifiedSnapshot]) -> tuple[ErrorGroup, ...]:
    buckets: dict[tuple[Any, ...], list[VerifiedSnapshot]] = defaultdict(list)
    for row in rows:
        if row.scored:
            s = row.snapshot
            key = (s.lead_hours, s.region, s.period_s, s.direction_deg, s.size_band, row.regime)
            buckets[key].append(row)
    result: list[ErrorGroup] = []
    for key, items in sorted(buckets.items(), key=lambda item: str(item[0])):
        lead, region, period, direction, band, regime = key
        def mean(attr: str) -> float | None:
            values = [getattr(item, attr) for item in items if getattr(item, attr) is not None]
            return sum(values) / len(values) if values else None
        result.append(ErrorGroup(
            lead, region, period, direction, band, regime, len(items),
            mean("height_error_m"), mean("period_error_s"), mean("direction_error_deg"),
        ))
    return tuple(result)


def verify_snapshots(
    snapshots: Iterable[ForecastSnapshot],
    observations: Iterable[BuoyObservation] = (),
    sessions: Iterable[Session] = (),
    *,
    tolerance: timedelta = OBSERVATION_TOLERANCE,
) -> VerificationReport:
    """Join immutable snapshots to later buoy values and session rows."""
    observation_rows = tuple(observations)
    session_rows = tuple(sessions)
    rows: list[VerifiedSnapshot] = []
    for snapshot in snapshots:
        candidates = [
            obs for obs in observation_rows
            if obs.spot == snapshot.spot
            and abs(_utc(obs.field.time) - snapshot.valid_at) <= tolerance
        ]
        observation = min(candidates, key=lambda item: abs(_utc(item.field.time) - snapshot.valid_at), default=None)
        rows.append(verify_snapshot(snapshot, observation, session_rows, tolerance=tolerance))
    rows_tuple = tuple(rows)
    return VerificationReport(rows_tuple, _group(rows_tuple))


verify = verify_snapshots


def _parse_time(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise SnapshotError(f"timestamp must be ISO text, got {raw!r}")
    try:
        return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError as exc:
        raise SnapshotError(f"invalid timestamp {raw!r}") from exc


def parse_snapshot_time(raw: str) -> datetime:
    """A caller-supplied ISO time (`--valid-at`, an observation's `time`), in UTC."""
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"invalid ISO timestamp {raw!r}") from exc
    return _utc(value)


def load_observations(path: str | None) -> tuple[BuoyObservation, ...]:
    """Read explicit, later buoy observations without filling omitted fields."""
    if not path:
        return ()
    observations: list[BuoyObservation] = []
    for line, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
            time = parse_snapshot_time(item["time"])
            height_m = item.get("height_m")
            period_s = item.get("period_s")
            direction_deg = item.get("direction_deg")
            partitions = ()
            if height_m is not None and period_s is not None and direction_deg is not None:
                partitions = (SwellPartition(float(height_m), float(period_s), float(direction_deg)),)
            field = WaveField(
                time=time,
                partitions=partitions,
                total_height_m=None if height_m is None else float(height_m),
                total_period_s=None if period_s is None else float(period_s),
                model=str(item.get("source", "buoy")),
            )
            observations.append(BuoyObservation(
                spot=str(item["spot"]), field=field,
                height_quantity=item.get("height_quantity", "offshore_hs"),
            ))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"{path}: malformed observation at line {line}: {exc}") from exc
    return tuple(observations)
