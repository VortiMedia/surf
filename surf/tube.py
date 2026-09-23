"""Breaker intensity from the sea floor, after Mead and Black (2001).

The BARREL axis in `score.py` is an Iribarren band. Mead and Black reject that
instrument for surfing waves explicitly — the surf-similarity parameter
describes every breaker from spilling to collapsing and is too general to rank
rides — and the personal backtest agrees, returning ``rho(rating, barrel) =
-0.07``. Their replacement is a field measurement over 28 world-class breaks:
the *orthogonal seabed gradient* predicts the vortex ratio of the plunging
wave, which is the shape of the barrel.

    Y = 0.065 X + 0.821        R^2 = 0.71

`Y` is the vortex ratio, `X` the orthogonal seabed gradient. The paper's own
classification schedule runs extreme 1.6-1.9, very high 1.9-2.2, high 2.2-2.5,
medium/high 2.5-2.8, medium 2.8-3.1, and a low ratio is the violent barrel
while a high one is a mild one. Inverting the fit against that schedule puts
the classes at X = 12-17, 17-21, 21-26, 26-30 and 30-35, which is only
self-consistent if `X` is the gradient *denominator*, a 1:X slope. That reading
is what this module implements, and `docs/CALIBRATION.md` records the panel it
was checked against.

This module answers one question — *can the sea floor here hold a barrel* — and
answers it from the sea floor alone. It says nothing about whether swell or
wind ever arrive, nothing about access, and nothing about whether the wave has
a rideable line. It is a nominator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .bathymetry import BathymetryGrid

# Mead and Black (2001), Predicting the breaking intensity of surfing waves,
# Journal of Coastal Research SI 29: 103-130.
VORTEX_FIT_SLOPE = 0.065
VORTEX_FIT_INTERCEPT = 0.821
VORTEX_FIT_R2 = 0.71

# Their classification schedule, as (upper bound of vortex ratio, name). A lower
# ratio is a rounder, more violent barrel.
INTENSITY_CLASSES: tuple[tuple[float, str], ...] = (
    (1.6, "beyond the published range"),
    (1.9, "extreme"),
    (2.2, "very high"),
    (2.5, "high"),
    (2.8, "medium/high"),
    (3.1, "medium"),
)
BELOW_SCHEDULE = "below the published range"

# Depths in which a 1-4 m face breaks or is about to. Waves break in roughly
# 1.3x their height, so 1-12 m spans everything from a knee-high shorebreak to
# the shoaling ramp outside a double-overhead reef.
BREAKING_BAND_M: tuple[float, float] = (1.0, 12.0)

# Fewer cells than this in the band and the box is describing a coastline, not a
# break. The panel entries that fell under it were bad coordinates every time.
MIN_BAND_CELLS = 12

# `geometry.py` already draws the line here: a DEM cell this wide cannot describe
# a surf zone. Kept identical on purpose, so one number governs both.
COARSE_GRID_M = 100.0

# The panel in docs/CALIBRATION.md separated known tube breaks from known soft
# breaks perfectly on a ~3 m DEM (AUC 1.00, n=9) and at exactly chance on a 61 m
# grid (AUC 0.50, n=17). So the gradient stays a measurement at any resolution
# the grid supports, but the inference from gradient to barrel class is only
# emitted below this cell size. Between here and COARSE_GRID_M the number is
# real and the classification is withheld.
FEATURE_GRID_M = 10.0

UNRESOLVED_AT_RESOLUTION = "unresolved at this DEM resolution"


@dataclass(frozen=True)
class Intensity:
    """A breaker-intensity reading, or a stated reason there isn't one."""

    tan_beta: float | None
    vortex_ratio: float | None
    intensity: str
    band_cells: int
    resolution_m: float | None
    status: str                     # ok | degraded | unresolved. Never "failed":
                                    # a sea floor too coarse to read is an answer,
                                    # not a source that fell over.
    basis: str
    depth_band_m: tuple[float, float] = BREAKING_BAND_M
    gradients: tuple[float, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.tan_beta is not None

    @property
    def ratio(self) -> str:
        if not self.tan_beta:
            return "unknown"
        return f"1:{round(1.0 / self.tan_beta)}"


def vortex_ratio(tan_beta: float) -> float | None:
    """Mead and Black's fit, fed the gradient denominator it was written in."""
    if tan_beta <= 0.0:
        return None
    return VORTEX_FIT_SLOPE * (1.0 / tan_beta) + VORTEX_FIT_INTERCEPT


def intensity_class(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    for upper, name in INTENSITY_CLASSES:
        if ratio < upper:
            return name
    return BELOW_SCHEDULE


def band_gradients(
    grid: BathymetryGrid,
    spacing_m: float,
    *,
    depth_band_m: tuple[float, float] = BREAKING_BAND_M,
) -> tuple[float, ...]:
    """Seabed gradient magnitude at every interior cell inside the breaking band.

    Central differences, so a cell needs all four neighbours; a NoData neighbour
    drops the cell rather than being filled in.
    """
    if spacing_m <= 0.0:
        raise ValueError("spacing must be positive")
    shallow, deep = depth_band_m
    if not 0.0 <= shallow < deep:
        raise ValueError("depth band must be 0 <= shallow < deep")
    rows, cols = grid.rows, grid.cols
    z = [s.elevation_m for s in grid.samples]
    if len(z) != rows * cols:
        raise ValueError("grid samples do not fill rows x cols")
    out: list[float] = []
    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            here = z[r * cols + c]
            if here is None or not (-deep <= here <= -shallow):
                continue
            north = z[(r + 1) * cols + c]
            south = z[(r - 1) * cols + c]
            east = z[r * cols + (c + 1)]
            west = z[r * cols + (c - 1)]
            if north is None or south is None or east is None or west is None:
                continue
            dy = (north - south) / (2.0 * spacing_m)
            dx = (east - west) / (2.0 * spacing_m)
            out.append(math.hypot(dx, dy))
    return tuple(out)


def _median(values: tuple[float, ...]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def measure(
    grid: BathymetryGrid,
    spacing_m: float,
    *,
    depth_band_m: tuple[float, float] = BREAKING_BAND_M,
) -> Intensity:
    """Median breaking-band gradient, converted to a vortex ratio and a class.

    The median rather than a high percentile: the tail of the gradient
    distribution in a coastal box is cliff and rock platform, and it reads
    'extreme' on beginner beaches. The panel in docs/CALIBRATION.md separates on
    the median and does not separate on the 90th percentile.
    """
    resolution = grid.resolution_m
    if resolution is not None and resolution >= COARSE_GRID_M:
        return Intensity(
            None, None, "unresolved", 0, resolution, "unresolved",
            f"DEM cell ~{resolution:.0f} m — coarser than the surf zone; the sea "
            "floor cannot be read here at all",
            depth_band_m,
        )
    gradients = band_gradients(grid, spacing_m, depth_band_m=depth_band_m)
    if len(gradients) < MIN_BAND_CELLS:
        return Intensity(
            None, None, "unresolved", len(gradients), resolution, "unresolved",
            f"only {len(gradients)} cells between {depth_band_m[0]:.0f} and "
            f"{depth_band_m[1]:.0f} m of water — the box is not centred on a break",
            depth_band_m, gradients,
        )
    tan_beta = _median(gradients)
    measured = (
        f"median gradient of {len(gradients)} cells between {depth_band_m[0]:.0f} "
        f"and {depth_band_m[1]:.0f} m of water, {_grid_words(resolution)}"
    )
    if resolution is None or resolution > FEATURE_GRID_M:
        # The gradient is what the grid says. The barrel class is not: on the
        # calibration panel this statistic ranked known tubes against known soft
        # breaks at AUC 0.50 on a 61 m grid, which is a coin toss, and it called
        # Muizenberg steeper than Thurso. Report the number, withhold the claim.
        return Intensity(
            tan_beta, None, UNRESOLVED_AT_RESOLUTION, len(gradients), resolution,
            "degraded",
            measured
            + f"; a {_grid_words(resolution)} smooths a reef into sand and this "
            "statistic scored AUC 0.50 there on the calibration panel, so no "
            "breaker-intensity class is claimed",
            depth_band_m, gradients,
        )
    ratio = vortex_ratio(tan_beta)
    return Intensity(
        tan_beta, ratio, intensity_class(ratio), len(gradients), resolution, "ok",
        measured
        + f"; vortex ratio {ratio:.2f} from Mead and Black (2001), R2={VORTEX_FIT_R2}",
        depth_band_m, gradients,
    )


def _grid_words(resolution_m: float | None) -> str:
    return f"~{resolution_m:.0f} m DEM" if resolution_m else "DEM resolution unreported"


@dataclass(frozen=True)
class TubeReading:
    """One coordinate's breaker-intensity screen with its provenance."""

    label: str
    lat: float
    lon: float
    intensity: Intensity
    source: str
    fetched_at: datetime
    note: str = ""
    dropped: tuple[str, ...] = field(default_factory=tuple)
