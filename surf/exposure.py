"""Colour a coastline by exposure to one swell direction.

Geometry and nothing else: no bathymetry, no refraction, no wind, no forecast.
A segment's exposure is how squarely it faces the swell multiplied by the
fraction of a +/-15 degree arriving fan that reaches it without crossing land.

Projection is a local equirectangular plane (longitude scaled by cos(latitude)
about a local origin). Over a coastal scan that costs nothing and buys no
dependency; `pyproj` is deliberately absent.

Natural Earth carries no winding-order guarantee (see `docs/DATA-SOURCES.md`),
so the seaward side of every segment is *probed* against the land mask, never
inferred from ring orientation. A segment whose seaward side the mask cannot
settle is dropped and counted, never guessed.
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
from typing import Any, Callable, Iterable, Sequence

from .spots import data_dir

# Metres per degree of latitude. Longitude is this times cos(latitude).
METRES_PER_DEGREE = 111_320.0

SEGMENT_M = 200.0          # coastline is cut into segments this long
FAN_DEG = 15.0             # rays span swell_direction +/- this
RAY_COUNT = 9              # rays per segment across the fan
RAY_KM = 60.0              # how far offshore a ray is followed
# Distances tried, in order, when moving off the coastline into open water.
PROBE_M = (200.0, 500.0, 1000.0, 2000.0)

NE_LAND_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_land.geojson"
)

# Bands are (floor, name, KML ABGR). KML colours are aabbggrr, not rrggbb.
BANDS: tuple[tuple[float, str, str], ...] = (
    (0.70, "green", "ff00ff00"),
    (0.40, "yellow", "ff00ffff"),
    (0.20, "orange", "ff00a5ff"),
    (0.00, "red", "ff0000ff"),
)


class ExposureError(Exception):
    """A hole that must not be filled with an estimate."""


def band_of(exposure: float) -> tuple[str, str]:
    for floor, name, colour in BANDS:
        if exposure >= floor:
            return name, colour
    return BANDS[-1][1], BANDS[-1][2]


@dataclass(frozen=True)
class Plane:
    """Local equirectangular plane in metres about (lat0, lon0)."""

    lat0: float
    lon0: float

    @property
    def x_scale(self) -> float:
        return METRES_PER_DEGREE * math.cos(math.radians(self.lat0))

    def xy(self, lon: float, lat: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.x_scale, (lat - self.lat0) * METRES_PER_DEGREE)

    def lonlat(self, x: float, y: float) -> tuple[float, float]:
        return (self.lon0 + x / self.x_scale, self.lat0 + y / METRES_PER_DEGREE)


@dataclass(frozen=True)
class LandMask:
    """Land polygons plus where they came from."""

    polygons: tuple[Any, ...]
    source: str
    status: str
    fetched_at: datetime

    def label(self) -> str:
        return f"{self.source}:{self.status} fetched_at={self.fetched_at.isoformat()}"


@dataclass(frozen=True)
class Segment:
    """One 200 m piece of coast and its exposure to the chosen swell."""

    start: tuple[float, float]      # (lon, lat)
    end: tuple[float, float]
    mid: tuple[float, float]
    normal_deg: float               # offshore-facing normal, degrees true
    facing: float                   # cos of the off-axis angle, clamped at 0
    unblocked: float                # fraction of the fan reaching open water
    exposure: float

    @property
    def band(self) -> str:
        return band_of(self.exposure)[0]


@dataclass(frozen=True)
class ExposureMap:
    segments: tuple[Segment, ...]
    swell_deg: float
    coastline: str
    land: LandMask
    dropped_ambiguous: int
    computed_at: datetime

    def counts(self) -> dict[str, int]:
        counts = {name: 0 for _, name, _ in BANDS}
        for segment in self.segments:
            counts[segment.band] += 1
        return counts


# --- GeoJSON --------------------------------------------------------------


def _geometries(node: Any) -> Iterable[dict]:
    """Every geometry in a GeoJSON document, whatever it is wrapped in."""
    if not isinstance(node, dict):
        return
    kind = node.get("type")
    if kind == "FeatureCollection":
        for feature in node.get("features") or ():
            yield from _geometries(feature)
    elif kind == "Feature":
        yield from _geometries(node.get("geometry"))
    elif kind == "GeometryCollection":
        for geometry in node.get("geometries") or ():
            yield from _geometries(geometry)
    elif kind:
        yield node


def _linestrings(document: Any) -> list[list[tuple[float, float]]]:
    lines: list[list[tuple[float, float]]] = []
    for geometry in _geometries(document):
        kind = geometry.get("type")
        coords = geometry.get("coordinates") or []
        if kind == "LineString":
            lines.append([(float(c[0]), float(c[1])) for c in coords])
        elif kind == "MultiLineString":
            lines.extend([(float(c[0]), float(c[1])) for c in line] for line in coords)
        elif kind == "Polygon":
            lines.extend([(float(c[0]), float(c[1])) for c in ring] for ring in coords)
        elif kind == "MultiPolygon":
            for polygon in coords:
                lines.extend([(float(c[0]), float(c[1])) for c in ring] for ring in polygon)
    return [line for line in lines if len(line) >= 2]


def _polygons(document: Any) -> list[Any]:
    from shapely.geometry import Polygon

    polygons: list[Any] = []
    for geometry in _geometries(document):
        kind = geometry.get("type")
        coords = geometry.get("coordinates") or []
        rings = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
        for ring_set in rings:
            if not ring_set or len(ring_set[0]) < 4:
                continue
            polygon = Polygon(ring_set[0], [r for r in ring_set[1:] if len(r) >= 4])
            if polygon.is_valid and not polygon.is_empty:
                polygons.append(polygon)
            elif not polygon.is_empty:
                repaired = polygon.buffer(0)
                if not repaired.is_empty:
                    polygons.append(repaired)
    return polygons


# --- land mask ------------------------------------------------------------


def default_land_cache() -> Path:
    root = Path(os.environ.get("SURF_CACHE_DIR") or data_dir() / "cache")
    return root / "coastline" / "ne_50m_land.geojson"


def load_land(path: Path | str | None = None, *, download: bool = True) -> LandMask:
    """The land mask, from an explicit file or the cached Natural Earth one.

    Natural Earth 50m is coarse. If a finer local mask exists — an OSM
    `natural=coastline` derived polygon set, for instance — pass it with
    `--land`; this function will not silently substitute a coarser one for a
    finer one, and it will not invent a mask when it has none.
    """
    if path is not None:
        source = Path(path)
        if not source.exists():
            raise ExposureError(f"land mask not found: {source}")
        document = json.loads(source.read_text(encoding="utf-8"))
        fetched_at = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc)
        return LandMask(tuple(_polygons(document)), str(source), "ok", fetched_at)

    cache = default_land_cache()
    if cache.exists():
        document = json.loads(cache.read_text(encoding="utf-8"))
        fetched_at = datetime.fromtimestamp(cache.stat().st_mtime, tz=timezone.utc)
        return LandMask(
            tuple(_polygons(document)), "natural-earth:ne_50m_land (cached)", "ok", fetched_at
        )
    if not download:
        raise ExposureError(
            f"no land mask cached at {cache} and downloading is off; pass --land PATH"
        )

    import httpx

    try:
        response = httpx.get(NE_LAND_URL, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:  # network, HTTP, whatever the transport raised
        raise ExposureError(
            "land mask unavailable "
            f"({type(exc).__name__}: {exc}); ray shadowing cannot be computed. "
            "Pass --land PATH with a local land polygon file."
        ) from None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(response.text, encoding="utf-8")
    document = json.loads(response.text)
    return LandMask(
        tuple(_polygons(document)),
        "natural-earth:ne_50m_land",
        "ok",
        datetime.now(timezone.utc),
    )


# --- geometry -------------------------------------------------------------


def _bearing(dx: float, dy: float) -> float:
    """Degrees true from a plane vector (x east, y north)."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def facing_score(normal_deg: float, swell_deg: float) -> float:
    """How squarely a segment faces swell arriving FROM `swell_deg`.

    The offshore normal and the direction the swell comes from are the same
    convention, so a perfect match is cos(0) = 1. Energy falls off with angle;
    there is no cutoff — a long-period swell wraps further than a short one,
    and a fixed off-axis limit is wrong physics.
    """
    return max(0.0, math.cos(math.radians(normal_deg - swell_deg)))


def _cut(line: Sequence[tuple[float, float]], plane: Plane, spacing: float) -> list[
    tuple[tuple[float, float], tuple[float, float]]
]:
    """Walk a projected line, emitting a vertex every `spacing` metres."""
    points = [plane.xy(lon, lat) for lon, lat in line]
    cuts: list[tuple[float, float]] = [points[0]]
    carry = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        if length == 0.0:
            continue
        travelled = spacing - carry
        while travelled <= length:
            t = travelled / length
            cuts.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            travelled += spacing
        carry = (carry + length) % spacing
    return list(zip(cuts, cuts[1:]))


def _seaward(
    mid: tuple[float, float], normal: tuple[float, float], inside: Callable[[float, float], bool]
) -> tuple[float, float] | None:
    """Pick the seaward normal by probing both sides, and say so when it cannot.

    Returns the outward unit normal, or None when the mask puts both sides (or
    neither) in the same class — a fjord, an inlet, or a coastline finer than
    the mask. Those segments are dropped and counted, not guessed.
    """
    nx, ny = normal
    hits_a = sum(inside(mid[0] + nx * d, mid[1] + ny * d) for d in PROBE_M)
    hits_b = sum(inside(mid[0] - nx * d, mid[1] - ny * d) for d in PROBE_M)
    if hits_a < hits_b:
        return (nx, ny)
    if hits_b < hits_a:
        return (-nx, -ny)
    return None


def compute(
    coastline: Any,
    swell_deg: float,
    land: LandMask,
    *,
    coastline_name: str = "coastline",
) -> ExposureMap:
    """Exposure per 200 m of coast to swell arriving from `swell_deg`."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    lines = _linestrings(coastline)
    if not lines:
        raise ExposureError(f"{coastline_name}: no line geometry in the GeoJSON")

    lons = [lon for line in lines for lon, _ in line]
    lats = [lat for line in lines for _, lat in line]
    plane = Plane((min(lats) + max(lats)) / 2.0, (min(lons) + max(lons)) / 2.0)

    # Only land that a ray from this coast could ever reach is worth projecting.
    reach = RAY_KM * 1000.0 + 5_000.0
    pad_lat = reach / METRES_PER_DEGREE
    pad_lon = reach / plane.x_scale
    box = (min(lons) - pad_lon, min(lats) - pad_lat, max(lons) + pad_lon, max(lats) + pad_lat)

    projected: list[Any] = []
    for polygon in land.polygons:
        x0, y0, x1, y1 = polygon.bounds
        if x1 < box[0] or x0 > box[2] or y1 < box[1] or y0 > box[3]:
            continue
        shell = [plane.xy(lon, lat) for lon, lat in polygon.exterior.coords]
        holes = [[plane.xy(lon, lat) for lon, lat in ring.coords] for ring in polygon.interiors]
        candidate = Polygon(shell, holes)
        if not candidate.is_valid:
            candidate = candidate.buffer(0)
        if not candidate.is_empty:
            projected.append(candidate)
    if not projected:
        raise ExposureError(
            f"land mask {land.source} has no polygon within {RAY_KM:.0f} km of "
            f"{coastline_name}; shadowing cannot be computed"
        )

    tree = STRtree(projected)
    prepared = [prep(polygon) for polygon in projected]

    def inside(x: float, y: float) -> bool:
        point = Point(x, y)
        return any(prepared[i].contains(point) for i in tree.query(point))

    def blocked(line: Any) -> bool:
        return any(prepared[i].intersects(line) for i in tree.query(line))

    fan = [
        swell_deg - FAN_DEG + (2 * FAN_DEG) * i / (RAY_COUNT - 1) for i in range(RAY_COUNT)
    ]
    ray_m = RAY_KM * 1000.0

    segments: list[Segment] = []
    dropped = 0
    for line in lines:
        for (x0, y0), (x1, y1) in _cut(line, plane, SEGMENT_M):
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length == 0.0:
                continue
            mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            outward = _seaward(mid, (dy / length, -dx / length), inside)
            if outward is None:
                dropped += 1
                continue
            nx, ny = outward
            normal_deg = _bearing(nx, ny)

            # Start the fan in open water, so a segment is never shadowed by the
            # coastline it sits on. If no probe distance clears land, the mask
            # cannot answer here and the segment is dropped.
            origin = None
            for distance in PROBE_M:
                candidate = (mid[0] + nx * distance, mid[1] + ny * distance)
                if not inside(*candidate):
                    origin = candidate
                    break
            if origin is None:
                dropped += 1
                continue

            clear = 0
            for bearing in fan:
                theta = math.radians(bearing)
                end = (origin[0] + math.sin(theta) * ray_m, origin[1] + math.cos(theta) * ray_m)
                if not blocked(LineString([origin, end])):
                    clear += 1
            unblocked = clear / RAY_COUNT
            facing = facing_score(normal_deg, swell_deg)
            segments.append(
                Segment(
                    start=plane.lonlat(x0, y0),
                    end=plane.lonlat(x1, y1),
                    mid=plane.lonlat(*mid),
                    normal_deg=normal_deg,
                    facing=facing,
                    unblocked=unblocked,
                    exposure=facing * unblocked,
                )
            )

    return ExposureMap(
        segments=tuple(segments),
        swell_deg=swell_deg,
        coastline=coastline_name,
        land=land,
        dropped_ambiguous=dropped,
        computed_at=datetime.now(timezone.utc),
    )


# --- KMZ ------------------------------------------------------------------


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def to_kml(result: ExposureMap) -> str:
    styles = "".join(
        f'<Style id="exposure-{name}"><LineStyle><color>{colour}</color>'
        f"<width>4</width></LineStyle></Style>"
        for _, name, colour in BANDS
    )
    provenance = (
        f"swell from {result.swell_deg:.0f} deg | fan +/-{FAN_DEG:.0f} deg, "
        f"{RAY_COUNT} rays, {RAY_KM:.0f} km | segment {SEGMENT_M:.0f} m | "
        f"coastline={result.coastline} | land={result.land.label()} | "
        f"dropped_ambiguous={result.dropped_ambiguous} | "
        f"computed_at={result.computed_at.isoformat()}"
    )
    places = []
    for i, segment in enumerate(result.segments):
        name, _ = band_of(segment.exposure)
        description = (
            f"exposure {segment.exposure:.2f} = facing {segment.facing:.2f} "
            f"x unblocked {segment.unblocked:.2f}; offshore normal "
            f"{segment.normal_deg:.0f} deg"
        )
        coords = (
            f"{segment.start[0]:.6f},{segment.start[1]:.6f},0 "
            f"{segment.end[0]:.6f},{segment.end[1]:.6f},0"
        )
        places.append(
            f"<Placemark><name>{i:05d} {segment.exposure:.2f}</name>"
            f"<description>{_escape(description)}</description>"
            f'<styleUrl>#exposure-{name}</styleUrl>'
            f"<LineString><tessellate>1</tessellate>"
            f"<coordinates>{coords}</coordinates></LineString></Placemark>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>Swell exposure {result.swell_deg:.0f} deg</name>"
        f"<description>{_escape(provenance)}</description>"
        f"{styles}{''.join(places)}"
        "</Document></kml>"
    )


def write_kmz(result: ExposureMap, path: Path | str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", to_kml(result))
    return target


# --- CLI ------------------------------------------------------------------


def default_output(swell_deg: float) -> Path:
    return data_dir() / "exposure" / f"exposure-{swell_deg:03.0f}.kmz"


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("coastline", help="coastline GeoJSON to colour")
    parser.add_argument(
        "--swell", type=float, required=True,
        help="direction the swell comes FROM, degrees true (180 = south swell)",
    )
    parser.add_argument("--output", default=None, help="KMZ to write (default: data/exposure/)")
    parser.add_argument(
        "--land", default=None,
        help="land polygon GeoJSON. Default is the cached Natural Earth 50m mask, "
             "which is coarse; pass a finer local mask when you have one",
    )
    return parser


def run(args: argparse.Namespace, say: Callable[[str], None]) -> int:
    """Shared by `surf exposure` and the `surf-exposure` console script."""
    coastline_path = Path(args.coastline)
    if not coastline_path.exists():
        raise ExposureError(f"coastline not found: {coastline_path}")
    document = json.loads(coastline_path.read_text(encoding="utf-8"))
    land = load_land(args.land)
    result = compute(document, args.swell, land, coastline_name=str(coastline_path))
    output = Path(args.output) if args.output else default_output(args.swell)
    write_kmz(result, output)

    counts = result.counts()
    say(f"coastline {coastline_path} — {len(result.segments)} segments of {SEGMENT_M:.0f} m")
    say(f"land {land.label()}")
    say(
        f"swell from {args.swell:.0f} deg, fan +/-{FAN_DEG:.0f} deg, "
        f"{RAY_COUNT} rays to {RAY_KM:.0f} km"
    )
    say(" ".join(f"{name}={counts[name]}" for _, name, _ in BANDS))
    if result.dropped_ambiguous:
        say(
            f"dropped {result.dropped_ambiguous} segments the land mask could not "
            "place a seaward side for — not guessed"
        )
    say(f"wrote {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surf-exposure",
        description="Colour a coastline GeoJSON by exposure to one swell direction.",
    )
    return add_arguments(parser)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args, print)
    except ExposureError as exc:
        print(f"surf-exposure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
