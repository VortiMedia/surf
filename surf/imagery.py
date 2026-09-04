"""Static-geometry imagery evidence for unpromoted terrain objects."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .terrain import TerrainObject, TerrainScan
from .spots import data_dir


@dataclass(frozen=True)
class ImageryFrame:
    candidate: str
    source: str
    resolution_m: float | None
    captured_at: str
    cloud_free: bool
    georeferenced: bool
    measurements_m: tuple[tuple[str, float], ...] = ()
    usable_line: bool | None = None


@dataclass(frozen=True)
class GeometryReview:
    candidate: str
    decision: str
    lat: float
    lon: float
    source: str
    resolution_m: float | None
    capture_dates: tuple[str, ...]
    frames: tuple[str, ...]
    measurements_m: tuple[tuple[str, float], ...] = ()
    status: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        # `status` is the candidate disposition; the screen's status remains
        # the provenance status for the manifest processing as a whole.
        if not self.status:
            object.__setattr__(self, "status", self.decision)


@dataclass(frozen=True)
class ImageryScreen:
    zone: str
    source: str
    status: str
    fetched_at: datetime
    reviews: tuple[GeometryReview, ...]
    note: str = "static geometry only; no wave-state analysis"
    dropped: tuple[str, ...] = field(default_factory=tuple)


def candidate_key(scan: TerrainScan, index: int) -> str:
    return f"{scan.spot_id}:{index}"


def _manifest_frame(raw: dict[str, Any]) -> ImageryFrame:
    if not isinstance(raw, dict):
        raise ValueError("each imagery frame must be an object")
    measurements = raw.get("measurements_m", raw.get("measurements", {}))
    if not isinstance(measurements, dict):
        raise ValueError("imagery frame measurements must be an object")
    numeric = []
    for key, value in measurements.items():
        if not str(key).endswith("_m") or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if math.isfinite(value) and value >= 0:
            numeric.append((str(key), value))
    resolution = raw.get("resolution_m")
    source = str(raw.get("source", "")).strip()
    captured_at = str(raw.get("captured_at", "")).strip()
    if not source or not captured_at:
        raise ValueError("imagery frame requires source and captured_at")
    if resolution is not None:
        resolution = float(resolution)
        if not math.isfinite(resolution) or resolution <= 0:
            raise ValueError("imagery frame resolution_m must be positive")
    return ImageryFrame(
        candidate=str(raw["candidate"]),
        source=source,
        resolution_m=resolution,
        captured_at=captured_at,
        cloud_free=bool(raw.get("cloud_free", False)),
        georeferenced=bool(raw.get("georeferenced", False)),
        measurements_m=tuple(numeric),
        usable_line=raw.get("usable_line"),
    )


def load_frames(path: Path) -> tuple[ImageryFrame, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("frames") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("imagery manifest must be a list or an object with frames")
    return tuple(_manifest_frame(row) for row in rows)


def review_candidate(key: str, candidate: TerrainObject, frames: tuple[ImageryFrame, ...]) -> GeometryReview:
    usable = tuple(frame for frame in frames if frame.cloud_free and frame.georeferenced)
    dates = tuple(frame.captured_at for frame in usable)
    frame_names = tuple(frame.source for frame in usable)
    resolution = min((frame.resolution_m for frame in usable if frame.resolution_m is not None), default=None)
    measurements: dict[str, float] = {}
    for frame in usable:
        measurements.update(dict(frame.measurements_m))
    if not usable:
        return GeometryReview(key, "unresolvable", candidate.lat, candidate.lon, "none", None, dates, frame_names, note="no cloud-free georeferenced frame")
    if resolution is None or not measurements:
        return GeometryReview(key, "unresolvable", candidate.lat, candidate.lon, ", ".join(frame_names), resolution, dates, frame_names, tuple(sorted(measurements.items())), note="static geometry is not measurable at the supplied resolution")
    line_flags = [frame.usable_line for frame in usable if frame.usable_line is not None]
    if line_flags and not any(line_flags):
        return GeometryReview(key, "rejected", candidate.lat, candidate.lon, ", ".join(frame_names), resolution, dates, frame_names, tuple(sorted(measurements.items())), note="static geometry has no usable line or channel")
    if not line_flags:
        return GeometryReview(key, "unresolvable", candidate.lat, candidate.lon, ", ".join(frame_names), resolution, dates, frame_names, tuple(sorted(measurements.items())), note="frame has no explicit usable-line assessment")
    return GeometryReview(key, "kept", candidate.lat, candidate.lon, ", ".join(frame_names), resolution, dates, frame_names, tuple(sorted(measurements.items())), note="static geometry supports human review")


def screen_candidates(scans: tuple[TerrainScan, ...], frames: tuple[ImageryFrame, ...], zone: str, fetched_at: datetime) -> ImageryScreen:
    reviews: list[GeometryReview] = []
    for scan in scans:
        for index, candidate in enumerate(scan.candidates):
            key = candidate_key(scan, index)
            reviews.append(review_candidate(key, candidate, tuple(frame for frame in frames if frame.candidate == key)))
    return ImageryScreen(zone, "; ".join(sorted({frame.source for frame in frames})) or "none", "ok", fetched_at, tuple(reviews))


def imagery_cache_path(zone: str, bbox: tuple[float, float, float, float], root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", zone.casefold()).strip("-") or "zone"
    suffix = "-" + "-".join(f"{value:.4f}" for value in bbox)
    return (root or (data_dir() / "imagery")) / f"imagery-{safe}{suffix}.json"


def save_screen(path: Path, screen: ImageryScreen) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1, "zone": screen.zone, "source": screen.source,
        "status": screen.status, "fetched_at": screen.fetched_at.isoformat(),
        "note": screen.note, "dropped": list(screen.dropped),
        "reviews": [review.__dict__ for review in screen.reviews],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
