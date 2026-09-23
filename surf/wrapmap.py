"""Where a coast bends swell — a shelter field, its contours, and wrap zones.

`exposure.py` answers "can this piece of coast see the open ocean". On a long
straight coast facing into an open ocean the answer is almost always yes, so
the map comes out green and says nothing. The useful signal is not the level,
it is the *gradient*: a stretch where exposure falls from open to sheltered
over a few hundred metres is a stretch where the swell is being bent, and bent
swell arrives with a peeling angle instead of as a wall.

So this module produces three things over a box of coast:

  * a **shelter field** — for every patch of water, the fraction of the swell
    fan that reaches it unblocked by land. Drawn as a ground overlay.
  * **shelter contours** — iso-lines of that field. Around a headland they bow
    inward the way a refracting wave front does. They are a *geometric* shadow
    boundary, not a refraction solution: there is no bathymetry in here and
    none is implied.
  * **wrap score** per 200 m of coast — how fast exposure changes along the
    shoreline. Point breaks light up; straight beach goes dark.

What this cannot do, stated once so it is never assumed: it knows land and
water and nothing else. It cannot see the sea floor, so it cannot tell reef
from sand, and it cannot tell a wrapping point with a good bank from the same
point with none. It narrows a coastline to a shortlist worth looking at.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .exposure import (
    ExposureError,
    LandMask,
    Plane,
    _linestrings,
    compute,
    load_land,
)

METRES_PER_DEGREE = 111_320.0

FAN_DEG = 15.0          # half width of the coastline fan, matching exposure.py
FIELD_RAYS = 25         # rays across the spread for the water field
FIELD_REACH_M = 30_000  # how far upswell a blocker still counts
MAX_GRID = 520          # hard cap on the raster's long side
MARCH_STEPS = 220       # samples along each ray

# Real swell is not a single ray. Energy arrives spread about the mean
# direction, and a narrow fan therefore casts a hard-edged geometric shadow
# that no real coast has. The standard description is a cos^2s spreading
# function; s ~ 10 is a reasonable long-period swell, and the resulting soft
# penumbra behind a headland is what makes the lee of a point rideable rather
# than dead. This is still NOT a refraction solution — there is no bathymetry
# here, so energy is not bent, only blocked. It is a directionally-spread
# shadow, and it is labelled as one.
SPREAD_DEG = 45.0
SPREAD_S = 10.0

CONTOUR_LEVELS = (0.15, 0.30, 0.50, 0.70, 0.85)

# A wrap zone is partly sheltered by definition. Outside this band a steep
# gradient means dead water (a harbour, an estuary) or open beach, not a setup.
LIVE_EXPOSURE = (0.15, 0.85)

# KML colours are aabbggrr, not rrggbb.
CONTOUR_COLOUR = "b0ffffff"
WRAP_RAMP: tuple[tuple[float, str, str], ...] = (
    (0.60, "hot", "ff2020ff"),      # red - the sharpest bends
    (0.35, "strong", "ff20a0ff"),   # orange
    (0.18, "some", "ff20ffff"),     # yellow
    (0.00, "flat", "6060c0a0"),     # dim grey-green, deliberately quiet
)


def wrap_band(score: float) -> tuple[str, str]:
    for floor, name, colour in WRAP_RAMP:
        if score >= floor:
            return name, colour
    return WRAP_RAMP[-1][1], WRAP_RAMP[-1][2]


@dataclass(frozen=True)
class ShelterField:
    """The water field and where it sits on the globe."""

    values: Any                     # numpy (ny, nx), row 0 = north, NaN on land
    west: float
    east: float
    south: float
    north: float
    cell_m: float
    swell_deg: float
    reach_m: float
    land: LandMask
    computed_at: datetime

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(self.values.shape)  # type: ignore[return-value]


@dataclass(frozen=True)
class WrapSegment:
    """One piece of coast and how hard the swell bends across it."""

    start: tuple[float, float]
    end: tuple[float, float]
    mid: tuple[float, float]
    exposure: float
    wrap: float                     # 0..1, normalised gradient of exposure

    @property
    def band(self) -> str:
        return wrap_band(self.wrap)[0]


@dataclass(frozen=True)
class WrapMap:
    field: ShelterField
    segments: tuple[WrapSegment, ...]
    contours: tuple[tuple[float, list[tuple[float, float]]], ...]
    coastline: str
    swell_deg: float
    dropped_ambiguous: int
    computed_at: datetime

    def top(
        self,
        n: int = 12,
        *,
        live: tuple[float, float] = LIVE_EXPOSURE,
        apart_m: float = 1500.0,
    ) -> list[WrapSegment]:
        """The sharpest bends that are still in live water.

        A steep gradient on its own is not a setup. The inside of a harbour or
        the back of an estuary has the steepest gradient on the coast and zero
        exposure — the swell is not bending in, it is simply absent. Equally, a
        near-1.0 segment is open beach with nothing shaping it. A wrap zone
        lives in between, so candidates are held to `live`; segments outside it
        are still drawn and still scored, just not offered as setups.
        """
        low, high = live
        ranked = sorted(
            (s for s in self.segments if low <= s.exposure <= high),
            key=lambda s: s.wrap,
            reverse=True,
        )
        picked: list[WrapSegment] = []
        for segment in ranked:
            if any(_metres_between(segment.mid, p.mid) < apart_m for p in picked):
                continue
            picked.append(segment)
            if len(picked) >= n:
                break
        return picked


def _metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2.0)
    return math.hypot(
        (b[0] - a[0]) * METRES_PER_DEGREE * math.cos(lat),
        (b[1] - a[1]) * METRES_PER_DEGREE,
    )


# --- the water field ------------------------------------------------------


def _bbox_of(coastline: Any) -> tuple[float, float, float, float]:
    lines = _linestrings(coastline)
    if not lines:
        raise ExposureError("no line geometry to take a bounding box from")
    lons = [lon for line in lines for lon, _ in line]
    lats = [lat for line in lines for _, lat in line]
    return (min(lons), min(lats), max(lons), max(lats))


def _land_raster(land: LandMask, lons: Any, lats: Any, plane: Plane) -> Any:
    """Boolean (ny, nx) — True where the cell centre is inside a land polygon."""
    import numpy as np
    from matplotlib.path import Path as MplPath
    from shapely.geometry import box as shapely_box

    nx, ny = len(lons), len(lats)
    grid_lon, grid_lat = np.meshgrid(lons, lats)
    points = np.column_stack([grid_lon.ravel(), grid_lat.ravel()])
    mask = np.zeros(points.shape[0], dtype=bool)

    reach_deg = (FIELD_REACH_M / METRES_PER_DEGREE) * 1.2
    window = shapely_box(
        float(lons[0]) - reach_deg, float(lats[0]) - reach_deg,
        float(lons[-1]) + reach_deg, float(lats[-1]) + reach_deg,
    )

    for polygon in land.polygons:
        if not polygon.intersects(window):
            continue
        exterior = np.asarray(polygon.exterior.coords)
        inside = MplPath(exterior).contains_points(points)
        for ring in polygon.interiors:
            hole = MplPath(np.asarray(ring.coords)).contains_points(points)
            inside &= ~hole
        mask |= inside

    return mask.reshape(ny, nx)


def _shadowed(land: Any, dx_cells: float, dy_cells: float, steps: int) -> Any:
    """True where marching `steps` upswell from a cell runs into land.

    dy_cells is in *row* space, where row 0 is north — so a northward march is
    a negative row step. Offsets are deduplicated so a shallow ray does not pay
    for the same cell twice.
    """
    import numpy as np

    blocked = np.zeros_like(land, dtype=bool)
    seen: set[tuple[int, int]] = set()
    for k in range(1, steps + 1):
        ox, oy = int(round(dx_cells * k)), int(round(dy_cells * k))
        if (ox, oy) == (0, 0) or (ox, oy) in seen:
            continue
        seen.add((ox, oy))
        shifted = np.zeros_like(land, dtype=bool)
        ny, nx = land.shape
        # Source window in `land` maps to destination window in `shifted`.
        sy0, sy1 = max(0, oy), min(ny, ny + oy)
        sx0, sx1 = max(0, ox), min(nx, nx + ox)
        dy0, dy1 = max(0, -oy), min(ny, ny - oy)
        dx0, dx1 = max(0, -ox), min(nx, nx - ox)
        if sy0 >= sy1 or sx0 >= sx1:
            continue
        shifted[dy0:dy1, dx0:dx1] = land[sy0:sy1, sx0:sx1]
        blocked |= shifted
    return blocked


def shelter_field(
    land: LandMask,
    swell_deg: float,
    bbox: tuple[float, float, float, float],
    *,
    reach_m: float = FIELD_REACH_M,
    max_grid: int = MAX_GRID,
) -> ShelterField:
    """Fraction of the swell fan reaching each patch of water, unblocked."""
    import numpy as np

    west, south, east, north = bbox
    if east <= west or north <= south:
        raise ExposureError(f"degenerate bounding box: {bbox}")

    lat0 = (south + north) / 2.0
    plane = Plane(lat0=lat0, lon0=(west + east) / 2.0)
    width_m = (east - west) * METRES_PER_DEGREE * math.cos(math.radians(lat0))
    height_m = (north - south) * METRES_PER_DEGREE

    long_side = max(width_m, height_m)
    cell_m = max(long_side / max_grid, 25.0)
    nx = max(2, int(round(width_m / cell_m)))
    ny = max(2, int(round(height_m / cell_m)))

    lons = np.linspace(west, east, nx)
    lats = np.linspace(north, south, ny)          # row 0 = north
    land_grid = _land_raster(land, lons, lats, plane)

    if not land_grid.any():
        raise ExposureError(
            "no land inside the box (or within reach of it), so nothing can "
            "cast a shadow and a shelter field would be a flat 1.0. Widen the "
            "box or pass a finer --land mask."
        )

    steps = MARCH_STEPS
    step_m = reach_m / steps
    open_energy = np.zeros(land_grid.shape, dtype=np.float32)
    total_weight = 0.0
    for i in range(FIELD_RAYS):
        offset = -SPREAD_DEG + (2 * SPREAD_DEG) * i / (FIELD_RAYS - 1)
        # cos^2s directional spreading about the mean direction.
        weight = math.cos(math.radians(offset) / 2.0) ** (2.0 * SPREAD_S)
        total_weight += weight
        theta = math.radians(swell_deg + offset)
        # Marching TOWARD the swell source: north is -row.
        dx_cells = math.sin(theta) * step_m / cell_m
        dy_cells = -math.cos(theta) * step_m / cell_m
        open_energy += weight * (~_shadowed(land_grid, dx_cells, dy_cells, steps))

    values = (open_energy / total_weight).astype(np.float32)
    values[land_grid] = np.nan
    return ShelterField(
        values=values,
        west=float(west), east=float(east), south=float(south), north=float(north),
        cell_m=cell_m,
        swell_deg=swell_deg,
        reach_m=reach_m,
        land=land,
        computed_at=datetime.now(timezone.utc),
    )


def contours(field: ShelterField, levels: Sequence[float] = CONTOUR_LEVELS) -> list[
    tuple[float, list[tuple[float, float]]]
]:
    """Iso-lines of the shelter field, in lon/lat."""
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    values = np.nan_to_num(field.values, nan=1.0)
    ny, nx = values.shape
    lons = np.linspace(field.west, field.east, nx)
    lats = np.linspace(field.north, field.south, ny)

    figure = plt.figure()
    try:
        axes = figure.add_subplot(111)
        cs = axes.contour(lons, lats, values, levels=list(levels))
        out: list[tuple[float, list[tuple[float, float]]]] = []
        for level, path_group in zip(cs.levels, cs.allsegs):
            for seg in path_group:
                if len(seg) < 4:
                    continue
                out.append((float(level), [(float(x), float(y)) for x, y in seg]))
        return out
    finally:
        plt.close(figure)


def overlay_png(field: ShelterField, path: Path | str, *, alpha: float = 0.62) -> Path:
    """Colour the shelter field into an RGBA PNG. Land is fully transparent."""
    import numpy as np
    import matplotlib
    from PIL import Image

    values = field.values
    finite = np.isfinite(values)
    shaded = np.clip(np.nan_to_num(values, nan=0.0), 0.0, 1.0)
    rgba = (matplotlib.colormaps["turbo"](shaded) * 255).astype(np.uint8)
    rgba[..., 3] = (finite * alpha * 255).astype(np.uint8)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


# --- wrap along the coast -------------------------------------------------


def wrap_segments(
    coastline: Any,
    swell_deg: float,
    land: LandMask,
    *,
    coastline_name: str = "coastline",
    smooth: int = 3,
) -> tuple[list[WrapSegment], int]:
    """Exposure per 200 m, plus how fast it changes along the shore."""
    import numpy as np

    base = compute(coastline, swell_deg, land, coastline_name=coastline_name)
    segments = list(base.segments)
    if len(segments) < 3:
        return ([], base.dropped_ambiguous)

    exposure = np.array([s.exposure for s in segments], dtype=float)

    # Gradient is only meaningful between segments that are actually adjacent.
    gaps = np.array([
        _metres_between(segments[i].mid, segments[i + 1].mid) > 600.0
        for i in range(len(segments) - 1)
    ] + [True])

    gradient = np.zeros_like(exposure)
    diff = np.abs(np.diff(exposure))
    diff[gaps[:-1]] = 0.0
    gradient[:-1] += diff
    gradient[1:] += diff
    gradient /= 2.0

    if smooth > 1:
        kernel = np.ones(smooth) / smooth
        gradient = np.convolve(gradient, kernel, mode="same")

    # Normalise against a high percentile, not the max: one freak segment
    # should not flatten every real point break on the coast.
    scale = float(np.percentile(gradient, 99.0)) or 1.0
    wrap = np.clip(gradient / scale, 0.0, 1.0)

    return ([
        WrapSegment(
            start=s.start, end=s.end, mid=s.mid,
            exposure=float(s.exposure), wrap=float(w),
        )
        for s, w in zip(segments, wrap)
    ], base.dropped_ambiguous)


def build(
    coastline: Any,
    swell_deg: float,
    land: LandMask,
    *,
    coastline_name: str = "coastline",
    bbox: tuple[float, float, float, float] | None = None,
    reach_m: float = FIELD_REACH_M,
) -> WrapMap:
    box = bbox or _bbox_of(coastline)
    field = shelter_field(land, swell_deg, box, reach_m=reach_m)
    segments, dropped = wrap_segments(
        coastline, swell_deg, land, coastline_name=coastline_name
    )
    if bbox is not None:
        west, south, east, north = bbox
        segments = [
            s for s in segments
            if west <= s.mid[0] <= east and south <= s.mid[1] <= north
        ]
    return WrapMap(
        field=field,
        segments=tuple(segments),
        contours=tuple(contours(field)),
        coastline=coastline_name,
        swell_deg=swell_deg,
        dropped_ambiguous=dropped,
        computed_at=datetime.now(timezone.utc),
    )


# --- KMZ ------------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def to_kml(result: WrapMap, image_name: str) -> str:
    field = result.field
    provenance = (
        f"swell from {result.swell_deg:.0f}° true, fan ±{FAN_DEG:.0f}°, "
        f"{FIELD_RAYS} rays to {field.reach_m/1000:.0f} km<br/>"
        f"field {field.shape[1]}×{field.shape[0]} cells at {field.cell_m:.0f} m<br/>"
        f"land {_escape(field.land.label())}<br/>"
        f"coastline {_escape(result.coastline)}<br/>"
        f"dropped {result.dropped_ambiguous} segments with no resolvable seaward side<br/>"
        f"computed {result.computed_at.isoformat()}<br/><br/>"
        "<b>Geometry only.</b> Land and water, nothing else. No bathymetry, no "
        "refraction solution, no wind, no tide. Contours are a geometric shadow "
        "boundary, not a wave front."
    )

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f"<name>Wrap map — swell from {result.swell_deg:.0f}°</name>",
        f"<description><![CDATA[{provenance}]]></description>",
    ]

    for _, name, colour in WRAP_RAMP:
        out.append(
            f'<Style id="wrap-{name}"><LineStyle>'
            f"<color>{colour}</color><width>4</width>"
            "</LineStyle></Style>"
        )
    out.append(
        f'<Style id="contour"><LineStyle><color>{CONTOUR_COLOUR}</color>'
        "<width>1</width></LineStyle></Style>"
    )

    out.append(
        "<GroundOverlay><name>Shelter field</name>"
        "<description>Fraction of the swell fan reaching each patch of water "
        "unblocked by land. Blue sheltered, red open.</description>"
        "<drawOrder>0</drawOrder>"
        f"<Icon><href>{_escape(image_name)}</href></Icon>"
        "<LatLonBox>"
        f"<north>{field.north:.8f}</north><south>{field.south:.8f}</south>"
        f"<east>{field.east:.8f}</east><west>{field.west:.8f}</west>"
        "</LatLonBox></GroundOverlay>"
    )

    out.append("<Folder><name>Shelter contours</name>")
    for level, points in result.contours:
        coords = " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in points)
        out.append(
            f"<Placemark><name>{level:.2f}</name><styleUrl>#contour</styleUrl>"
            f"<LineString><tessellate>1</tessellate>"
            f"<coordinates>{coords}</coordinates></LineString></Placemark>"
        )
    out.append("</Folder>")

    out.append("<Folder><name>Wrap zones</name>")
    for segment in result.segments:
        name, _ = wrap_band(segment.wrap)
        coords = (
            f"{segment.start[0]:.7f},{segment.start[1]:.7f},0 "
            f"{segment.end[0]:.7f},{segment.end[1]:.7f},0"
        )
        detail = (
            f"wrap {segment.wrap:.2f} ({name})<br/>"
            f"exposure {segment.exposure:.2f}<br/>"
            f"{segment.mid[1]:.5f}, {segment.mid[0]:.5f}"
        )
        out.append(
            f"<Placemark><name>wrap {segment.wrap:.2f}</name>"
            f"<description><![CDATA[{detail}]]></description>"
            f"<styleUrl>#wrap-{name}</styleUrl>"
            f"<LineString><tessellate>1</tessellate>"
            f"<coordinates>{coords}</coordinates></LineString></Placemark>"
        )
    out.append("</Folder>")

    out.append("<Folder><name>Top setups</name>")
    for rank, segment in enumerate(result.top(), start=1):
        detail = (
            f"rank {rank} of the sharpest exposure gradients on this coast<br/>"
            f"wrap {segment.wrap:.2f}, exposure {segment.exposure:.2f}<br/>"
            f"{segment.mid[1]:.5f}, {segment.mid[0]:.5f}<br/><br/>"
            "A candidate, not a spot. The sea floor is unresolved here."
        )
        out.append(
            f"<Placemark><name>#{rank} wrap {segment.wrap:.2f}</name>"
            f"<description><![CDATA[{detail}]]></description>"
            f"<Point><coordinates>{segment.mid[0]:.7f},{segment.mid[1]:.7f},0"
            "</coordinates></Point></Placemark>"
        )
    out.append("</Folder>")

    out.append("</Document></kml>")
    return "\n".join(out)


def write_kmz(result: WrapMap, path: Path | str) -> Path:
    import tempfile

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image_name = "shelter.png"
    with tempfile.TemporaryDirectory() as tmp:
        png = overlay_png(result.field, Path(tmp) / image_name)
        kml = to_kml(result, image_name)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", kml)
            archive.write(png, image_name)
    return path


# --- CLI ------------------------------------------------------------------


def default_output(swell_deg: float) -> Path:
    from .spots import data_dir  # local import keeps module import cheap

    return data_dir() / "exposure" / f"wrap-{int(round(swell_deg)) % 360:03d}.kmz"


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("coastline", help="coastline GeoJSON to score")
    parser.add_argument(
        "--swell", type=float, required=True,
        help="direction the swell comes FROM, degrees true (180 = south swell)",
    )
    parser.add_argument("--output", help="KMZ to write (default: data/exposure/)")
    parser.add_argument(
        "--land",
        help="land polygon GeoJSON. Default is the cached Natural Earth 50m mask, "
             "which is far too coarse for headlands — pass a finer local mask.",
    )
    parser.add_argument(
        "--bbox",
        help="clip the field to west,south,east,north. Without it the whole "
             "coastline bbox is used, which on a long coast makes a coarse grid.",
    )
    parser.add_argument(
        "--reach", type=float, default=FIELD_REACH_M / 1000.0,
        help="how far upswell a blocker still counts, km (default 30)",
    )
    return parser


def run(args: argparse.Namespace, say: Callable[[str], None]) -> int:
    try:
        document = json.loads(Path(args.coastline).read_text(encoding="utf-8"))
    except FileNotFoundError:
        say(f"coastline not found: {args.coastline}")
        return 1
    except json.JSONDecodeError as exc:
        say(f"coastline is not valid GeoJSON: {exc}")
        return 1

    bbox = None
    if args.bbox:
        try:
            parts = [float(p) for p in args.bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            say("--bbox must be west,south,east,north")
            return 2

    try:
        land = load_land(args.land)
        result = build(
            document, args.swell, land,
            coastline_name=str(args.coastline),
            bbox=bbox,
            reach_m=args.reach * 1000.0,
        )
    except ExposureError as exc:
        say(str(exc))
        return 1

    field = result.field
    say(f"coastline {args.coastline} — {len(result.segments)} segments in view")
    say(f"land {field.land.label()}")
    say(
        f"field {field.shape[1]}x{field.shape[0]} cells at {field.cell_m:.0f} m, "
        f"reach {field.reach_m/1000:.0f} km"
    )
    counts: dict[str, int] = {}
    for segment in result.segments:
        counts[segment.band] = counts.get(segment.band, 0) + 1
    say(" ".join(f"{name}={counts.get(name, 0)}" for _, name, _ in WRAP_RAMP))
    if result.dropped_ambiguous:
        say(
            f"dropped {result.dropped_ambiguous} segments the land mask could not "
            "place a seaward side for — not guessed"
        )

    top = result.top()
    if top:
        say("top wrap zones:")
        for rank, segment in enumerate(top[:8], start=1):
            say(
                f"  {rank:2d}. wrap {segment.wrap:.2f}  exposure {segment.exposure:.2f}"
                f"  {segment.mid[1]:.4f}, {segment.mid[0]:.4f}"
            )

    out = Path(args.output) if args.output else default_output(args.swell)
    write_kmz(result, out)
    say(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surf-wrap",
        description="Map where a coast bends swell: shelter field, contours, wrap zones.",
    )
    return add_arguments(parser)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args, lambda line: print(line))


if __name__ == "__main__":
    raise SystemExit(main())
