from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Sequence

from .sources import Reading
from .spots import Derived, Spot, data_dir

if TYPE_CHECKING:
    from .bathymetry import Sample

# A DEM cell this wide or wider cannot describe a beach face. The global fallback
# grid measures ~463 m; US coastal DEMs measure 1-10 m, so the threshold sits in a
# two-order-of-magnitude gap and is not delicate.
COARSE_GRID_M = 100.0

# Fit from the shoreline out to here. Waves break in roughly 1.3x their height, so
# 6 m of water covers everything up to a 15 ft face.
FIT_DEPTH_M = 6.0

# Below 1:500 and above 1:3 the fit is describing something other than a beach —
# a lagoon flat, a cliff, or a bad bearing.
PLAUSIBLE_SLOPE = (0.002, 0.35)

# A seaward rise of more than this is a bar, not fitting noise.
BAR_RELIEF_M = 0.25


class DepthSource(Protocol):
    # Soundings carry their grid resolution because the resolution decides whether
    # the slope is real. Structural, so a fake in a test is three lines.

    name: str

    def soundings(
        self, spot: Spot, bearing_deg: float, *, spacing_m: float, count: int
    ) -> Reading[tuple["Sample", ...]]: ...


@dataclass(frozen=True)
class BeachSlope:
    """A slope, or a stated reason there isn't one. `tan_beta` is dimensionless rise
    over run, positive seaward-deepening."""

    tan_beta: float | None
    resolution_m: float | None = None
    basis: str = ""
    fit_points: int = 0
    shoreline_m: float | None = None
    max_depth_m: float | None = None
    bars: int = 0
    bearing_deg: float | None = None

    @property
    def usable(self) -> bool:
        """False means scoring must fall back to the steepness proxy."""
        return self.tan_beta is not None

    @property
    def ratio(self) -> str:
        """"1:52" — how a slope is actually spoken about."""
        if not self.tan_beta:
            return "unknown"
        return f"1:{round(1.0 / self.tan_beta)}"

    def as_derived(self) -> Derived | None:
        # None when there is nothing to store: a spot keeps its default slope
        # rather than a fabricated one.
        if self.tan_beta is None:
            return None
        return Derived(self.tan_beta, "derived", self.basis)


def fit_beach_slope(
    distances_m: Sequence[float],
    elevations_m: Sequence[float | None],
    *,
    resolution_m: float | None = None,
    bearing_deg: float | None = None,
    fit_depth_m: float = FIT_DEPTH_M,
    coarse_grid_m: float = COARSE_GRID_M,
) -> BeachSlope:
    """Least-squares slope of the shoreface, shoreline out to `fit_depth_m`.

    Least squares rather than a two-point secant because a real profile has bars and
    troughs: a secant measures whichever bar it landed on, and moving one point 25 m
    can double the answer.
    """
    if len(distances_m) != len(elevations_m):
        raise ValueError("distances and elevations must be the same length")

    spacing = _spacing(distances_m)
    if resolution_m is not None and resolution_m >= coarse_grid_m:
        return BeachSlope(
            None,
            resolution_m,
            f"DEM cell ~{resolution_m:.0f} m — coarser than the whole surf zone; "
            f"no beach slope, use the steepness proxy",
            bearing_deg=bearing_deg,
        )
    # Not fatal, but worth saying: neighbouring soundings share a DEM cell, so the
    # profile has fewer independent points than it has samples.
    oversampled = bool(resolution_m and spacing and resolution_m > spacing)

    pairs = [(d, z) for d, z in zip(distances_m, elevations_m) if z is not None]
    if len(pairs) < 3:
        return BeachSlope(
            None, resolution_m,
            f"only {len(pairs)} soundings with data — no profile to fit",
            bearing_deg=bearing_deg,
        )

    crossing = _shoreline(pairs)
    anchored = crossing is not None
    if crossing is None:
        deepest = min(z for _, z in pairs)
        if deepest >= 0.0:
            return BeachSlope(
                None, resolution_m,
                f"profile stays above sea level out to {pairs[-1][0]:.0f} m "
                f"(min {deepest:+.1f} m) — bearing is pointing inland",
                bearing_deg=bearing_deg,
            )
        # Entirely underwater: the spot coordinate already sits offshore. There is no
        # measured shoreline to anchor to, and pretending the first sounding is at sea
        # level would invent the relief the fit then reports.
        crossing = pairs[0][0]

    wet = [(d, z) for d, z in pairs if d >= crossing and z <= 0.0]
    # Cut at the first sounding past the fit depth, keeping it so the fit spans the
    # whole breaking range. Cutting by index rather than filtering keeps a barred
    # profile in order — a bar past the cut must not pull the fit back.
    cut = next((i for i, (_, z) in enumerate(wet) if z < -fit_depth_m), None)
    truncated = cut is None
    within = wet if truncated else wet[: cut + 1]
    if len(within) < 2:
        within = wet[:2]
    if len(within) + (1 if anchored else 0) < 2:
        return BeachSlope(
            None, resolution_m,
            "fewer than two wet soundings inside the surf zone",
            shoreline_m=crossing, bearing_deg=bearing_deg,
        )

    # Anchor the fit at the shoreline: depth is 0 there by definition, and it is the
    # one point on the profile that is not a DEM sample's opinion. Only when the
    # crossing was actually observed.
    points = [p for p in within if p[0] > crossing]
    if anchored:
        points = [(crossing, 0.0)] + points
    slope = _least_squares_slope(points)
    max_depth = -min(z for _, z in within)
    bars = _bars(within)

    if slope >= 0.0:
        return BeachSlope(
            None, resolution_m,
            "profile does not deepen seaward along this bearing — check the shore normal",
            fit_points=len(points), shoreline_m=crossing, max_depth_m=max_depth,
            bars=bars, bearing_deg=bearing_deg,
        )

    tan_beta = -slope
    basis = (
        f"least-squares fit of {len(points)} soundings from the shoreline at "
        f"{crossing:.0f} m to {max_depth:.1f} m depth, {_grid_words(resolution_m)}"
    )
    if bars:
        basis += f"; {bars} bar/trough reversal{'s' if bars > 1 else ''}"
    lo, hi = PLAUSIBLE_SLOPE
    if not (lo <= tan_beta <= hi):
        basis += f"; 1:{round(1.0 / tan_beta)} is outside the plausible beach range"
    if truncated:
        basis += f"; profile never reached {fit_depth_m:.0f} m — extend it"
    if oversampled:
        basis += "; sampled finer than the DEM cell"
    return BeachSlope(
        tan_beta, resolution_m, basis,
        fit_points=len(points), shoreline_m=crossing, max_depth_m=max_depth,
        bars=bars, bearing_deg=bearing_deg,
    )


def _spacing(distances_m: Sequence[float]) -> float | None:
    if len(distances_m) < 2:
        return None
    return abs(distances_m[1] - distances_m[0])


def _grid_words(resolution_m: float | None) -> str:
    return f"{resolution_m:.0f} m DEM" if resolution_m else "resolution unreported"


def _shoreline(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Distance where the profile first crosses sea level, linearly interpolated.
    None when it never does: the bearing points inland, or the whole profile is
    already underwater."""
    if pairs[0][1] <= 0.0:
        return None if all(z <= 0.0 for _, z in pairs) else pairs[0][0]
    for (d0, z0), (d1, z1) in zip(pairs, pairs[1:]):
        if z0 > 0.0 >= z1:
            span = z0 - z1
            return d0 + (d1 - d0) * (z0 / span if span else 0.0)
    return None


def _least_squares_slope(points: Sequence[tuple[float, float]]) -> float:
    """dz/dx. Negative for a normal shoreface."""
    n = len(points)
    mx = sum(d for d, _ in points) / n
    mz = sum(z for _, z in points) / n
    num = sum((d - mx) * (z - mz) for d, z in points)
    den = sum((d - mx) ** 2 for d, _ in points)
    return num / den if den else 0.0


def _bars(points: Sequence[tuple[float, float]]) -> int:
    """Count seaward shallowings — sandbars. Reported, not corrected for: the fit
    already spans them."""
    return sum(1 for (_, z0), (_, z1) in zip(points, points[1:]) if z1 - z0 > BAR_RELIEF_M)


def seaward_bearing(spot: Spot) -> float:
    return spot.shore_normal.value % 360.0


@dataclass(frozen=True)
class ShoreNormal:
    """A bearing derived from the sea floor rather than estimated off a chart."""

    bearing_deg: float | None
    depth_gain_m: float
    monotonicity: float
    basis: str
    candidates_tried: int = 0

    @property
    def usable(self) -> bool:
        return self.bearing_deg is not None

    def as_derived(self) -> Derived | None:
        if self.bearing_deg is None:
            return None
        return Derived(self.bearing_deg, "derived", self.basis)


def _profile_quality(samples: Sequence["Sample"]) -> tuple[float, float]:
    """(depth gain, monotonicity) — how much a profile deepens and how steadily.
    Monotonicity is the fraction of steps that go downhill: a bearing running along
    the beach can gain depth at the far end while wandering."""
    zs = [s.elevation_m for s in samples if s.elevation_m is not None]
    if len(zs) < 3:
        return (-999.0, 0.0)
    gain = zs[0] - min(zs)
    steps = [b - a for a, b in zip(zs, zs[1:])]
    down = sum(1 for d in steps if d < 0.0)
    return (gain, down / len(steps) if steps else 0.0)


def derive_shore_normal(
    spot: Spot,
    source: DepthSource,
    *,
    step_deg: float = 15.0,
    spacing_m: float = 25.0,
    count: int = 40,
    search_halfwidth_deg: float = 90.0,
) -> ShoreNormal:
    """Find the bearing that actually walks into deep water.

    The search is bounded to `search_halfwidth_deg` either side of the stored
    bearing because a chart estimate is wrong by tens of degrees, not by 180: an
    unbounded search at a spot on a narrow spit will happily find the bay behind it.
    """
    stored = seaward_bearing(spot)
    tried: list[tuple[float, float, float]] = []
    offset = -search_halfwidth_deg
    while offset <= search_halfwidth_deg:
        bearing = (stored + offset) % 360.0
        reading = source.soundings(spot, bearing, spacing_m=spacing_m, count=count)
        if reading.value:
            gain, mono = _profile_quality(reading.value)
            tried.append((bearing, gain, mono))
        offset += step_deg

    usable = [t for t in tried if t[1] > 1.0 and t[2] >= 0.6]
    if not usable:
        return ShoreNormal(
            None, 0.0, 0.0,
            f"no bearing within {search_halfwidth_deg:.0f} deg of the stored "
            f"{stored:.0f} deg deepens steadily — the spot coordinate itself may be wrong",
            len(tried),
        )

    # Depth gain decides, monotonicity breaks ties.
    best = max(usable, key=lambda t: (round(t[1], 1), t[2]))
    bearing, gain, mono = best
    drift = ((bearing - stored + 180.0) % 360.0) - 180.0
    return ShoreNormal(
        bearing, gain, mono,
        f"deepest of {len(tried)} bearings sampled every {step_deg:.0f} deg: "
        f"{gain:.1f} m gain, {mono * 100:.0f}% of steps downhill, "
        f"{drift:+.0f} deg from the stored estimate",
        len(tried),
    )


def beach_slope(
    spot: Spot,
    source: DepthSource,
    *,
    cache: "GeometryCache | None" = None,
    bearing_deg: float | None = None,
    spacing_m: float = 25.0,
    count: int = 60,
    landward_count: int = 24,
    refresh: bool = False,
) -> Reading[BeachSlope]:
    """Slope at `spot`, from cache when it is there and from the sea floor once.

    A failed fetch is never cached — an outage must not freeze into a permanent "no
    slope here". A coarse grid is cached: that is a fact about the location.
    """
    bearing = seaward_bearing(spot) if bearing_deg is None else bearing_deg % 360.0
    if cache and not refresh:
        hit = cache.get(spot.id, bearing)
        if hit is not None:
            slope, stored_at = hit
            return Reading(
                slope,
                f"geometry:{source.name}",
                "ok" if slope.usable else "degraded",
                stored_at,
                note=f"cached {stored_at.date().isoformat()}",
            )

    reading = source.soundings(spot, bearing, spacing_m=spacing_m, count=count)
    if reading.value is None:
        return Reading(
            None, f"geometry:{source.name}", reading.status, reading.fetched_at,
            note=reading.note or "no soundings", dropped=reading.dropped,
        )

    samples = reading.value
    #: Walk landward too when the stored coordinate is already in the water: the fit
    #: is anchored at the shoreline, and many stored spot coordinates sit in the surf
    #: or beyond it. The landward leg is stitched on with negative distances so the
    #: crossing is observed rather than assumed.
    first = next((x.elevation_m for x in samples if x.elevation_m is not None), None)
    if first is not None and first <= 0.0 and landward_count > 0:
        back = source.soundings(
            spot, (bearing + 180.0) % 360.0, spacing_m=spacing_m, count=landward_count
        )
        if back.value:
            inland = [
                replace(x, distance_m=-x.distance_m)
                for x in back.value if x.distance_m > 0.0
            ]
            samples = tuple(sorted(inland, key=lambda x: x.distance_m)) + tuple(samples)

    resolution = next((s.resolution_m for s in samples if s.resolution_m), None)
    slope = fit_beach_slope(
        [s.distance_m for s in samples],
        [s.elevation_m for s in samples],
        resolution_m=resolution,
        bearing_deg=bearing,
    )

    if cache:
        cache.put(spot.id, slope, reading.fetched_at)
    return Reading(
        slope,
        f"geometry:{source.name}",
        "ok" if slope.usable and reading.status == "ok" else "degraded",
        reading.fetched_at,
        note=slope.basis,
        dropped=reading.dropped,
    )


def default_cache_dir() -> Path:
    return Path(os.environ.get("SURF_CACHE_DIR") or data_dir() / "cache") / "geometry"


class GeometryCache:
    """One small JSON file per spot, keyed by bearing as well as spot: a profile shot
    down a different bearing is a different measurement."""

    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory is not None else default_cache_dir()

    def _path(self, spot_id: str, bearing_deg: float) -> Path:
        return self.dir / f"{spot_id}@{bearing_deg:03.0f}.json"

    def get(self, spot_id: str, bearing_deg: float) -> tuple[BeachSlope, datetime] | None:
        path = self._path(spot_id, bearing_deg)
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        try:
            stored_at = datetime.fromisoformat(raw["stored_at"])
        except (KeyError, ValueError):
            stored_at = datetime.now(timezone.utc)
        fields = {k: raw.get(k) for k in (
            "tan_beta", "resolution_m", "basis", "fit_points",
            "shoreline_m", "max_depth_m", "bars", "bearing_deg",
        )}
        fields["basis"] = fields["basis"] or ""
        fields["fit_points"] = int(fields["fit_points"] or 0)
        fields["bars"] = int(fields["bars"] or 0)
        return BeachSlope(**fields), stored_at

    def put(self, spot_id: str, slope: BeachSlope, stored_at: datetime) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        bearing = slope.bearing_deg if slope.bearing_deg is not None else 0.0
        path = self._path(spot_id, bearing)
        body = {
            "spot_id": spot_id,
            "stored_at": stored_at.isoformat(),
            "tan_beta": slope.tan_beta,
            "ratio": slope.ratio,
            "resolution_m": slope.resolution_m,
            "basis": slope.basis,
            "fit_points": slope.fit_points,
            "shoreline_m": slope.shoreline_m,
            "max_depth_m": slope.max_depth_m,
            "bars": slope.bars,
            "bearing_deg": slope.bearing_deg,
        }
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        return path
