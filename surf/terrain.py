"""Feature-respecting bathymetric terrain-object screening."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .bathymetry import BathymetryGrid
from .sources import Reading
from .spots import Spot, SpotBook, data_dir


COARSE_GRID_M = 100.0
MIN_RELIEF_M = 0.5
MIN_CELLS = 4


@dataclass(frozen=True)
class TerrainObject:
    """A bathymetric hypothesis, deliberately not a surf spot."""

    object_type: str
    lat: float
    lon: float
    cells: int
    relief_m: float
    resolution_m: float
    vertical_datum: str
    smoothing_survives: bool
    resolution_survives: bool
    label: str = "terrain object — human review required; not a surf spot"
    promotion: str = "A human must verify mechanism, access and surfability before a spots.tsv row."


@dataclass(frozen=True)
class TerrainLocation:
    """A scan cell, not a promoted spot row."""

    id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class TerrainScan:
    spot_id: str
    source: str
    status: str
    fetched_at: datetime
    resolution_m: float | None
    vertical_datum: str
    candidates: tuple[TerrainObject, ...] = field(default_factory=tuple)
    note: str = ""
    dropped: tuple[str, ...] = field(default_factory=tuple)


class TerrainSource(Protocol):
    name: str

    def grid(self, spot: TerrainLocation, *, radius_m: float, spacing_m: float, rows: int, cols: int) -> Reading[BathymetryGrid]: ...


def _elevations(grid: BathymetryGrid) -> list[list[float | None]]:
    return [
        [sample.elevation_m for sample in grid.samples[row * grid.cols:(row + 1) * grid.cols]]
        for row in range(grid.rows)
    ]


def _relief(values: list[list[float | None]], row: int, col: int, step: int = 1) -> float | None:
    center = values[row][col]
    if center is None or center >= 0.0:
        return None
    neighbors: list[float] = []
    for dr, dc in ((-step, 0), (step, 0), (0, -step), (0, step)):
        r, c = row + dr, col + dc
        if (
            0 <= r < len(values)
            and 0 <= c < len(values[0])
            and values[r][c] is not None
            and values[r][c] < 0.0  # type: ignore[operator]
        ):
            neighbors.append(values[r][c])  # type: ignore[arg-type]
    if len(neighbors) < 3:
        return None
    return center - sum(neighbors) / len(neighbors)


def _smooth(values: list[list[float | None]]) -> list[list[float | None]]:
    out: list[list[float | None]] = [[None for _ in row] for row in values]
    for row in range(len(values)):
        for col in range(len(values[0])):
            if values[row][col] is None or values[row][col] >= 0.0:  # type: ignore[operator]
                continue
            nearby = [
                values[r][c]
                for r in range(max(0, row - 1), min(len(values), row + 2))
                for c in range(max(0, col - 1), min(len(values[0]), col + 2))
                if values[r][c] is not None and values[r][c] < 0.0  # type: ignore[operator]
            ]
            if nearby:
                out[row][col] = sum(nearby) / len(nearby)
    return out


def _components(mask: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    remaining = set(mask)
    result: list[set[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque([start])
        while queue:
            row, col = queue.popleft()
            for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        result.append(component)
    return result


def scan_grid(spot: Spot, grid: BathymetryGrid) -> TerrainScan:
    """Propose only multi-cell terrain objects stable under two perturbations."""
    fetched_at = datetime.now().astimezone()
    resolution = grid.resolution_m
    if resolution is None or resolution >= COARSE_GRID_M:
        return TerrainScan(
            spot.id, "ncei", "degraded", fetched_at, resolution, grid.vertical_datum,
            note="coarse or unreported grid — no gradient; no terrain object proposed",
        )
    values = _elevations(grid)
    reliefs = {
        (row, col): _relief(values, row, col)
        for row in range(grid.rows) for col in range(grid.cols)
    }
    mask = {key for key, value in reliefs.items() if value is not None and abs(value) >= MIN_RELIEF_M}
    smooth_reliefs = {
        (row, col): _relief(_smooth(values), row, col)
        for row in range(grid.rows) for col in range(grid.cols)
    }
    perturbed_reliefs = {
        (row, col): _relief(values, row, col, step=2)
        for row in range(grid.rows) for col in range(grid.cols)
    }
    candidates: list[TerrainObject] = []
    for component in _components(mask):
        if len(component) < MIN_CELLS:
            continue
        # Smoothing can move the strongest signal onto the adjacent cell. Keep
        # the comparison local to the object's one-cell neighbourhood rather
        # than requiring the exact unsmoothed pixels to remain hot.
        rows = [row for row, _ in component]
        cols = [col for _, col in component]
        support = {
            (row, col)
            for row in range(max(0, min(rows) - 1), min(grid.rows, max(rows) + 2))
            for col in range(max(0, min(cols) - 1), min(grid.cols, max(cols) + 2))
        }
        smooth = {key for key in support if smooth_reliefs[key] is not None and abs(smooth_reliefs[key]) >= MIN_RELIEF_M / 2}
        perturbed = {key for key in support if perturbed_reliefs[key] is not None and abs(perturbed_reliefs[key]) >= MIN_RELIEF_M / 2}
        if len(smooth) < 1 or len(perturbed) < 2:
            continue
        points = [grid.samples[row * grid.cols + col] for row, col in component]
        elevations = [values[row][col] for row, col in component if values[row][col] is not None]
        mean_relief = sum(reliefs[row, col] or 0.0 for row, col in component) / len(component)
        candidates.append(TerrainObject(
            object_type="bank/reef" if mean_relief > 0 else "channel/scarp",
            lat=sum(point.lat for point in points) / len(points),
            lon=sum(point.lon for point in points) / len(points),
            cells=len(component),
            relief_m=max(elevations) - min(elevations),
            resolution_m=resolution,
            vertical_datum=grid.vertical_datum,
            smoothing_survives=True,
            resolution_survives=True,
        ))
    return TerrainScan(
        spot.id, "ncei", "ok", fetched_at, resolution, grid.vertical_datum,
        tuple(candidates), note=f"{grid.rows}x{grid.cols} source cells; no interpolation",
    )


def bbox_locations(zone: str, bbox: tuple[float, float, float, float], step_deg: float = 0.05) -> tuple[TerrainLocation, ...]:
    """Tile an explicit bbox; no existing spot is used as a scan seed."""
    min_lat, min_lon, max_lat, max_lon = bbox
    if not (min_lat < max_lat and min_lon < max_lon):
        raise ValueError("bbox must be min_lat,min_lon,max_lat,max_lon")
    if step_deg <= 0:
        raise ValueError("bbox step must be positive")
    locations: list[TerrainLocation] = []
    lat = min_lat + step_deg / 2
    index = 0
    while lat < max_lat:
        lon = min_lon + step_deg / 2
        while lon < max_lon:
            locations.append(TerrainLocation(f"{zone}-cell-{index}", lat, lon))
            index += 1
            lon += step_deg
        lat += step_deg
    return tuple(locations)


def terrain_cache_path(zone: str, bbox: tuple[float, float, float, float] | None = None, root: Path | None = None) -> Path:
    safe = re.sub(r"[^a-z0-9_-]+", "-", zone.casefold()).strip("-") or "zone"
    suffix = ""
    if bbox is not None:
        suffix = "-" + "-".join(f"{value:.4f}" for value in bbox)
    return (root or (data_dir() / "climate")) / f"terrain-{safe}{suffix}.json"


def save_terrain_cache(path: Path, zone: str, scans: tuple[TerrainScan, ...], source: str, status: str, fetched_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1, "zone": zone, "source": source, "status": status,
        "fetched_at": fetched_at.isoformat(),
        "scans": [{
            "spot_id": scan.spot_id, "status": scan.status,
            "fetched_at": scan.fetched_at.isoformat(), "resolution_m": scan.resolution_m,
            "vertical_datum": scan.vertical_datum, "note": scan.note,
            "dropped": list(scan.dropped), "candidates": [obj.__dict__ for obj in scan.candidates],
        } for scan in scans],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_terrain_cache(path: Path, book: SpotBook | None = None) -> tuple[str, str, datetime, tuple[TerrainScan, ...]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scans: list[TerrainScan] = []
    for item in raw.get("scans", []):
        candidates = tuple(TerrainObject(**candidate) for candidate in item.get("candidates", []))
        scans.append(TerrainScan(
            item["spot_id"], raw["source"], item["status"], datetime.fromisoformat(item["fetched_at"]),
            item.get("resolution_m"), item["vertical_datum"], candidates,
            item.get("note", ""), tuple(item.get("dropped", ())),
        ))
    return raw["zone"], raw["status"], datetime.fromisoformat(raw["fetched_at"]), tuple(scans)
