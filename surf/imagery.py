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
    scaled: bool = False
    swell_present: bool | None = None
    wavelength_m: float | None = None
    whitewash_fraction: float | None = None
    wave_shape: str | None = None


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


@dataclass(frozen=True)
class WaveStateReview:
    candidate: str
    decision: str
    lat: float
    lon: float
    source: str
    resolution_m: float | None
    capture_dates: tuple[str, ...]
    frames: tuple[str, ...]
    wavelength_m: float | None = None
    period_s: float | None = None
    whitewash_fraction: float | None = None
    wave_shape: str | None = None
    status: str = ""
    evidence_level: str = "geometry-and-visual-inference"
    note: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            object.__setattr__(self, "status", self.decision)


@dataclass(frozen=True)
class WaveStateScreen:
    zone: str
    source: str
    status: str
    fetched_at: datetime
    reviews: tuple[WaveStateReview, ...]
    dropped: tuple[str, ...] = field(default_factory=tuple)
    note: str = (
        "dynamic wave state only; geometry screen is separate; "
        "visual inference is not confirmation"
    )


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
    wavelength = raw.get("wavelength_m")
    if wavelength is not None:
        wavelength = float(wavelength)
        if not math.isfinite(wavelength) or wavelength <= 0:
            raise ValueError("imagery frame wavelength_m must be positive")
    whitewash = raw.get("whitewash_fraction")
    if whitewash is not None:
        whitewash = float(whitewash)
        if not math.isfinite(whitewash) or not 0 <= whitewash <= 1:
            raise ValueError("whitewash_fraction must be between zero and one")
    swell_present = raw.get("swell_present")
    if swell_present is not None and not isinstance(swell_present, bool):
        raise ValueError("swell_present must be true or false when supplied")
    return ImageryFrame(
        candidate=str(raw["candidate"]),
        source=source,
        resolution_m=resolution,
        captured_at=captured_at,
        cloud_free=bool(raw.get("cloud_free", False)),
        georeferenced=bool(raw.get("georeferenced", False)),
        measurements_m=tuple(numeric),
        usable_line=raw.get("usable_line"),
        scaled=bool(raw.get("scaled", False)),
        swell_present=swell_present,
        wavelength_m=wavelength,
        whitewash_fraction=whitewash,
        wave_shape=str(raw["wave_shape"]) if raw.get("wave_shape") is not None else None,
    )


def load_frames(path: Path) -> tuple[ImageryFrame, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("frames") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("imagery manifest must be a list or an object with frames")
    return tuple(_manifest_frame(row) for row in rows)


def load_screen(path: Path) -> ImageryScreen:
    raw = json.loads(path.read_text(encoding="utf-8"))
    reviews = []
    for item in raw.get("reviews", []):
        reviews.append(GeometryReview(
            candidate=item["candidate"], decision=item["decision"],
            lat=item["lat"], lon=item["lon"], source=item["source"],
            resolution_m=item.get("resolution_m"),
            capture_dates=tuple(item.get("capture_dates", ())),
            frames=tuple(item.get("frames", ())),
            measurements_m=tuple(tuple(pair) for pair in item.get("measurements_m", ())),
            status=item.get("status", ""), note=item.get("note", ""),
        ))
    return ImageryScreen(
        zone=raw["zone"], source=raw["source"], status=raw["status"],
        fetched_at=datetime.fromisoformat(raw["fetched_at"]), reviews=tuple(reviews),
        note=raw.get("note", ""), dropped=tuple(raw.get("dropped", ())),
    )


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


DEEP_WATER_GRAVITY = 9.81


def deep_water_period(wavelength_m: float) -> float:
    """Derive deep-water period from a georeferenced wavelength."""
    if not math.isfinite(wavelength_m) or wavelength_m <= 0:
        raise ValueError("wavelength must be positive")
    return math.sqrt(2 * math.pi * wavelength_m / DEEP_WATER_GRAVITY)


def _wave_review(key: str, static: GeometryReview, frames: tuple[ImageryFrame, ...]) -> WaveStateReview:
    if not frames:
        return WaveStateReview(
            key, "no_clear_pass_coincident_with_swell", static.lat, static.lon,
            "none", None, (), (),
            note="no imagery frame records swell coincident with a clear pass",
        )
    assessed_frames = tuple(frame for frame in frames if frame.swell_present is not None)
    swell_frames = tuple(frame for frame in assessed_frames if frame.swell_present is True)
    coincident = tuple(frame for frame in swell_frames if frame.cloud_free)
    source = ", ".join(sorted({frame.source for frame in frames}))
    dates = tuple(frame.captured_at for frame in frames)
    names = tuple(frame.source for frame in frames)
    resolution = min((frame.resolution_m for frame in frames if frame.resolution_m is not None), default=None)
    if not assessed_frames:
        return WaveStateReview(
            key, "unresolvable", static.lat, static.lon, source, resolution, dates, names,
            note="frames do not explicitly assess whether swell was present",
        )
    if not swell_frames:
        return WaveStateReview(
            key, "no_swell", static.lat, static.lon, source, resolution, dates, names,
            note="available frames report no swell; this is not a geometry result",
        )
    if not coincident:
        return WaveStateReview(
            key, "no_clear_pass_coincident_with_swell", static.lat, static.lon,
            source, resolution, dates, names,
            note="swell is present in the manifest, but no clear pass is coincident with it",
        )
    usable = tuple(frame for frame in coincident if frame.georeferenced and frame.scaled)
    if not usable:
        return WaveStateReview(
            key, "unresolvable", static.lat, static.lon, source, resolution, dates, names,
            note="clear swell frame is unscaled or not georeferenced; wavelength refused",
        )
    measured = tuple(frame for frame in usable if frame.wavelength_m is not None)
    if not measured:
        return WaveStateReview(
            key, "unresolvable", static.lat, static.lon, source, resolution, dates, names,
            note="scaled georeferenced frame has no measured wavelength",
        )
    selected = measured[0]
    return WaveStateReview(
        key, "observed", static.lat, static.lon, selected.source, selected.resolution_m,
        (selected.captured_at,), (selected.source,), selected.wavelength_m,
        deep_water_period(selected.wavelength_m), selected.whitewash_fraction,
        selected.wave_shape,
        note="visual inference only; not confirmation of surfability",
    )


def screen_wave_state(static: ImageryScreen, frames: tuple[ImageryFrame, ...], zone: str, fetched_at: datetime) -> WaveStateScreen:
    survivors = tuple(review for review in static.reviews if review.decision == "kept")
    reviews = tuple(
        _wave_review(review.candidate, review, tuple(frame for frame in frames if frame.candidate == review.candidate))
        for review in survivors
    )
    dropped = tuple(
        f"{review.candidate}: geometry unresolvable or rejected by static screen"
        for review in static.reviews if review.decision != "kept"
    )
    return WaveStateScreen(
        zone, "; ".join(sorted({frame.source for frame in frames})) or "none",
        "ok", fetched_at, reviews, dropped,
    )


def imagery_cache_path(zone: str, bbox: tuple[float, float, float, float], root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", zone.casefold()).strip("-") or "zone"
    suffix = "-" + "-".join(f"{value:.4f}" for value in bbox)
    return (root or (data_dir() / "imagery")) / f"imagery-{safe}{suffix}.json"


def wave_state_cache_path(zone: str, bbox: tuple[float, float, float, float], root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", zone.casefold()).strip("-") or "zone"
    suffix = "-" + "-".join(f"{value:.4f}" for value in bbox)
    return (root or (data_dir() / "imagery")) / f"wave-state-{safe}{suffix}.json"


def save_screen(path: Path, screen: ImageryScreen) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1, "zone": screen.zone, "source": screen.source,
        "status": screen.status, "fetched_at": screen.fetched_at.isoformat(),
        "note": screen.note, "dropped": list(screen.dropped),
        "reviews": [review.__dict__ for review in screen.reviews],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def save_wave_state(path: Path, screen: WaveStateScreen) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1, "zone": screen.zone, "source": screen.source,
        "status": screen.status, "fetched_at": screen.fetched_at.isoformat(),
        "note": screen.note, "dropped": list(screen.dropped),
        "reviews": [review.__dict__ for review in screen.reviews],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
