"""Offline breaker-intensity tests.

The panel these thresholds came from lives in `docs/CALIBRATION.md`; what is
tested here is the arithmetic, the depth band, and the refusals.
"""

from __future__ import annotations

import math

import pytest

from surf.bathymetry import BathymetryGrid, Sample
from surf.tube import (
    BELOW_SCHEDULE,
    COARSE_GRID_M,
    FEATURE_GRID_M,
    MIN_BAND_CELLS,
    UNRESOLVED_AT_RESOLUTION,
    band_gradients,
    intensity_class,
    measure,
    vortex_ratio,
)


def ramp(tan_beta: float, resolution: float = 3.0, spacing_m: float = 40.0,
         n: int = 9, offset_m: float = 1.0) -> BathymetryGrid:
    """A plane sea floor deepening due north at `tan_beta`."""
    cells = []
    for row in range(n):
        for col in range(n):
            cells.append(Sample(
                distance_m=row * spacing_m,
                lat=41.0 + row * spacing_m / 111320.0,
                lon=-71.0 + col * spacing_m / 111320.0,
                elevation_m=-(offset_m + row * spacing_m * tan_beta),
                resolution_m=resolution,
            ))
    return BathymetryGrid(tuple(cells), n, n, resolution, "fixture datum")


def test_vortex_ratio_reproduces_the_published_fit() -> None:
    # A 1:20 sea floor: Y = 0.065 * 20 + 0.821.
    assert vortex_ratio(1 / 20) == pytest.approx(2.121)
    assert intensity_class(vortex_ratio(1 / 20)) == "very high"
    # A 1:10 ledge is off the bottom of the published schedule.
    assert intensity_class(vortex_ratio(1 / 10)) == "beyond the published range"
    # A 1:40 sand beach is off the top of it.
    assert intensity_class(vortex_ratio(1 / 40)) == BELOW_SCHEDULE
    assert vortex_ratio(0.0) is None
    assert intensity_class(None) == "unknown"


def test_intensity_falls_as_the_sea_floor_flattens() -> None:
    """Ordering is the whole claim: gentler floor, milder barrel."""
    ratios = [vortex_ratio(1 / n) for n in (8, 15, 25, 60)]
    assert ratios == sorted(ratios)


def test_band_gradient_recovers_a_known_plane() -> None:
    gradients = band_gradients(ramp(0.05), spacing_m=40.0)
    assert gradients
    assert all(g == pytest.approx(0.05, rel=1e-6) for g in gradients)


def test_band_excludes_dry_land_and_deep_water() -> None:
    # 1:5 over 40 m steps: the profile passes 12 m within four rows, so the deep
    # end must be dropped rather than averaged in.
    grid = ramp(0.2, offset_m=0.0)
    inside = band_gradients(grid, spacing_m=40.0, depth_band_m=(1.0, 12.0))
    everything = band_gradients(grid, spacing_m=40.0, depth_band_m=(0.0, 1000.0))
    assert 0 < len(inside) < len(everything)


def test_nodata_neighbour_drops_the_cell_rather_than_filling_it() -> None:
    grid = ramp(0.05)
    holed = list(grid.samples)
    holed[grid.cols * 3 + 3] = Sample(
        distance_m=0.0, lat=41.0, lon=-71.0, elevation_m=None, resolution_m=3.0,
    )
    with_hole = BathymetryGrid(tuple(holed), grid.rows, grid.cols, 3.0, "fixture datum")
    assert len(band_gradients(with_hole, spacing_m=40.0)) < len(
        band_gradients(grid, spacing_m=40.0)
    )


def test_measure_reports_a_reef_class_on_a_steep_floor() -> None:
    result = measure(ramp(1 / 18), spacing_m=40.0)
    assert result.usable
    assert result.status == "ok"
    assert result.ratio == "1:18"
    assert result.intensity == "very high"
    assert "Mead and Black" in result.basis


def test_measure_calls_a_sand_beach_below_the_schedule() -> None:
    result = measure(ramp(1 / 70), spacing_m=40.0)
    assert result.usable
    assert result.intensity == BELOW_SCHEDULE


def test_coarse_dem_refuses_rather_than_estimating() -> None:
    result = measure(ramp(1 / 18, resolution=COARSE_GRID_M), spacing_m=40.0)
    assert not result.usable
    assert result.status == "unresolved"
    assert result.vortex_ratio is None
    assert "coarser than the surf zone" in result.basis


def test_a_grid_between_the_two_resolutions_measures_but_does_not_classify() -> None:
    """The gradient is what the grid says; the barrel class is a claim the grid
    cannot support, and the panel measured it at chance."""
    result = measure(ramp(1 / 18, resolution=FEATURE_GRID_M + 1.0), spacing_m=40.0)
    assert result.usable
    assert result.ratio == "1:18"
    assert result.status == "degraded"
    assert result.vortex_ratio is None
    assert result.intensity == UNRESOLVED_AT_RESOLUTION
    assert "AUC 0.50" in result.basis


def test_a_box_that_is_not_on_a_break_refuses() -> None:
    # Entirely in 40 m of water: nothing in the breaking band.
    deep = ramp(1 / 18, offset_m=40.0)
    result = measure(deep, spacing_m=40.0)
    assert not result.usable
    assert result.status == "unresolved"
    assert result.band_cells < MIN_BAND_CELLS
    assert "not centred on a break" in result.basis


def test_bad_arguments_raise_rather_than_returning_a_number() -> None:
    with pytest.raises(ValueError):
        band_gradients(ramp(0.05), spacing_m=0.0)
    with pytest.raises(ValueError):
        band_gradients(ramp(0.05), spacing_m=40.0, depth_band_m=(12.0, 1.0))
    with pytest.raises(ValueError):
        band_gradients(
            BathymetryGrid(ramp(0.05).samples[:-1], 9, 9, 3.0, "fixture"), spacing_m=40.0
        )


def test_the_median_is_used_so_one_cliff_cell_cannot_carry_the_box() -> None:
    """A single violent cell must not turn a beach into a barrel."""
    grid = ramp(1 / 70)
    spiked = list(grid.samples)
    spiked[grid.cols * 4 + 4] = Sample(
        distance_m=0.0, lat=41.0, lon=-71.0, elevation_m=-11.0, resolution_m=3.0,
    )
    result = measure(
        BathymetryGrid(tuple(spiked), grid.rows, grid.cols, 3.0, "fixture datum"),
        spacing_m=40.0,
    )
    assert result.intensity == BELOW_SCHEDULE
    assert max(result.gradients) > 5 * result.tan_beta
    assert not math.isnan(result.tan_beta)
