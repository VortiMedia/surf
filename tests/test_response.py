"""Behaviour any response matrix must keep, not the closed form used here."""

from __future__ import annotations

import math

import pytest

from surf.response import Response
from surf.response import (
    MIN_TRANSMISSION,
    Response,
)
from surf.spots import Derived, Spot

NORMAL = 160.0  # Lido faces roughly SSE
ALL_DIRECTIONS = tuple(float(d) for d in range(0, 360, 5))
OFF_AXIS = tuple(float(a) for a in range(1, 181))


def make(normal: float = NORMAL, slope: float = 0.03, exposure: float | None = None):
    kwargs = {}
    if exposure is not None:
        kwargs["exposure"] = Derived(exposure, "manual", "surveyed headland")
    return Response(
        spot_id="lido",
        shore_normal=Derived(normal, "manual"),
        beach_slope=Derived(slope, "derived"),
        **kwargs,
    )


def test_satisfies_the_response_interface() -> None:
    m: Response = make()
    assert m.spot_id == "lido"
    assert m.method == "analytic"
    assert callable(m.transmission)


def test_for_spot_carries_geometry_provenance() -> None:
    spot = Spot(
        id="lido",
        name="Lido Beach",
        lat=40.58,
        lon=-73.62,
        shore_normal=Derived(160.0, "derived", "from coastline"),
        beach_slope=Derived(0.021, "default"),
        offshore_lat=40.5,
        offshore_lon=-73.6,
        region="NY",
    )
    m = Response.for_spot(spot)
    assert m.spot_id == "lido"
    assert m.shore_normal.provenance == "derived"
    # a defaulted slope must not read like a measured one
    assert "default" in m.basis
    assert "derived" in m.basis


def test_dead_on_transmits_fully_at_every_period() -> None:
    m = make()
    for period in (6.0, 10.0, 16.0, 20.0):
        assert m.transmission(NORMAL, period) == pytest.approx(1.0)


def test_transmission_is_monotone_in_angle() -> None:
    m = make()
    for period in (8.0, 12.0, 16.0):
        values = [m.transmission(NORMAL + a, period) for a in range(0, 181)]
        assert all(b <= a for a, b in zip(values, values[1:])), period
        coarse = values[::10]
        assert all(b < a for a, b in zip(coarse, coarse[1:])), period


def test_response_is_symmetric_about_the_shore_normal() -> None:
    m = make()
    for a in (15.0, 55.0, 95.0, 150.0):
        assert m.transmission(NORMAL + a, 12.0) == pytest.approx(
            m.transmission(NORMAL - a, 12.0)
        )


def test_only_the_off_axis_angle_matters_not_the_compass() -> None:
    """Rotating the whole spot must not change the physics."""
    a, b = make(normal=10.0), make(normal=250.0)
    for off in (0.0, 40.0, 100.0):
        assert a.transmission(10.0 + off, 14.0) == pytest.approx(
            b.transmission(250.0 + off, 14.0)
        )


def test_off_axis_angle_wraps_the_compass() -> None:
    m = make(normal=10.0)
    assert m.off_axis_deg(350.0) == pytest.approx(20.0)
    assert m.off_axis_deg(370.0) == pytest.approx(0.0)


def test_sixteen_seconds_beats_eight_at_every_off_axis_angle() -> None:
    m = make()
    for a in OFF_AXIS:
        long_p = m.transmission(NORMAL + a, 16.0)
        short_p = m.transmission(NORMAL + a, 8.0)
        assert long_p > short_p, a


def test_transmission_increases_with_period_off_axis() -> None:
    m = make()
    for a in (20.0, 60.0, 100.0):
        values = [m.transmission(NORMAL + a, p) for p in (6.0, 9.0, 12.0, 15.0, 18.0)]
        assert all(b > x for x, b in zip(values, values[1:])), a


def test_long_period_wraps_much_further_than_short() -> None:
    """Not merely higher — the gap has to be big enough to change a call."""
    m = make()
    assert m.transmission(NORMAL + 110.0, 16.0) > 10.0 * m.transmission(
        NORMAL + 110.0, 8.0
    )


def test_angular_reach_grows_with_period() -> None:
    m = make()
    assert m.angular_reach_deg(16.0) > m.angular_reach_deg(8.0)
    assert m.angular_reach_deg(16.0) == pytest.approx(2.0 * m.angular_reach_deg(8.0))


def test_no_hard_zero_anywhere_in_the_water() -> None:
    m = make()
    for direction in ALL_DIRECTIONS:
        for period in (6.0, 12.0, 18.0):
            t = m.transmission(direction, period)
            assert MIN_TRANSMISSION <= t <= 1.0
            assert t > 0.0


def test_energy_past_eighty_degrees_is_not_clipped_away() -> None:
    m = make()
    assert m.transmission(NORMAL + 80.0, 14.0) > 0.4
    assert m.transmission(NORMAL + 85.0, 14.0) > 0.3
    assert m.transmission(NORMAL + 95.0, 14.0) > 0.2
    # and no cliff across 80 degrees
    inside = m.transmission(NORMAL + 79.0, 14.0)
    outside = m.transmission(NORMAL + 81.0, 14.0)
    assert outside / inside > 0.9


def test_a_narrower_open_water_window_costs_transmission() -> None:
    open_beach = make(exposure=90.0)
    tucked = make(exposure=45.0)
    assert tucked.transmission(NORMAL + 70.0, 14.0) < open_beach.transmission(
        NORMAL + 70.0, 14.0
    )
    # inside the narrow window nothing is shadowed, so they agree
    assert tucked.transmission(NORMAL + 30.0, 14.0) == pytest.approx(
        open_beach.transmission(NORMAL + 30.0, 14.0)
    )


def test_a_gentler_shelf_bends_energy_further() -> None:
    steep = make(slope=0.06)
    gentle = make(slope=0.01)
    assert gentle.angular_reach_deg(12.0) > steep.angular_reach_deg(12.0)
    assert gentle.transmission(NORMAL + 90.0, 12.0) > steep.transmission(
        NORMAL + 90.0, 12.0
    )


def test_calibration_can_move_the_constants_without_a_new_class() -> None:
    m = make()
    wider = m.with_constants(reach_deg_per_second=12.0)
    assert wider.transmission(NORMAL + 90.0, 10.0) > m.transmission(NORMAL + 90.0, 10.0)
    assert m.reach_deg_per_second == 8.0  # frozen; the original is untouched


def test_table_shape_matches_its_axes() -> None:
    m = make()
    t = m.table(directions=(0.0, 90.0, 180.0, 270.0), periods=(8.0, 16.0))
    assert t.spot_id == "lido"
    assert t.method == "analytic"
    assert len(t.rows) == 4
    assert all(len(row) == 2 for row in t.rows)
    assert t.at(90.0, 16.0) == pytest.approx(m.transmission(90.0, 16.0))


def test_wrapping_is_visible_in_the_table() -> None:
    """Period-dependent wrapping must be readable off the table, not just true
    in the formula."""
    m = make()
    t = m.table(periods=(8.0, 16.0))
    shadowed = [
        (row[0], row[1])
        for d, row in zip(t.directions, t.rows)
        if m.off_axis_deg(d) > 100.0
    ]
    assert shadowed
    assert all(long_p > short_p for short_p, long_p in shadowed)
    assert all(short_p > 0.0 for short_p, _ in shadowed)


def test_a_nonpositive_period_is_an_error_not_a_nan() -> None:
    m = make()
    with pytest.raises(ValueError):
        m.transmission(NORMAL, 0.0)
    with pytest.raises(ValueError):
        m.transmission(NORMAL, -12.0)


def test_impossible_geometry_is_refused_at_construction() -> None:
    with pytest.raises(ValueError):
        make(exposure=0.0)
    with pytest.raises(ValueError):
        Response("x", Derived(0.0), Derived(0.0))


def test_extreme_periods_stay_finite_and_bounded() -> None:
    m = make()
    for period in (0.5, 1.0, 40.0, 600.0):
        t = m.transmission(NORMAL + 120.0, period)
        assert math.isfinite(t)
        assert MIN_TRANSMISSION <= t <= 1.0
