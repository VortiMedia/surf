from __future__ import annotations

from datetime import datetime

import pytest

from surf.score import (
    NOMINAL_SLOPE,
    PLUNGING_BAND,
    SINGLE_MODEL_CONFIDENCE,
    barrel,
    classify_breaker,
    cleanness,
    confidence,
    iribarren,
    reference_field,
    score_hour,
    size,
)
from surf.spots import Derived, Spot
from surf.waves import SwellPartition, WaveField, Wind

T0 = datetime(2026, 9, 10, 7, 0)

MEASURED = Derived(0.030, "derived", "NCEI profile")
UNKNOWN = Derived(0.020, "default", "placeholder, nobody measured this")


def make_spot(shore_normal: float = 90.0, slope: Derived = MEASURED) -> Spot:
    """An east-facing beach unless told otherwise: offshore wind is from 270."""
    return Spot(
        id="test",
        name="Test Beach",
        lat=40.6,
        lon=-73.6,
        shore_normal=Derived(shore_normal, "manual"),
        beach_slope=slope,
        offshore_lat=40.5,
        offshore_lon=-73.4,
        region="test",
        break_type="beach",
    )


def field(
    height: float = 1.2,
    period: float = 12.0,
    direction: float = 90.0,
    *,
    model: str = "gwam",
    wind: Wind | None = None,
    kind: str = "swell",
) -> WaveField:
    return WaveField(
        time=T0,
        partitions=(SwellPartition(height, period, direction, kind),),
        wind=wind,
        total_height_m=height,
        total_period_s=period,
        model=model,
    )


class FlatMatrix:
    """A response matrix that always passes the same fraction."""

    spot_id = "test"
    method = "analytic"

    def __init__(self, value: float = 1.0) -> None:
        self.value = value

    def transmission(self, direction_deg: float, period_s: float) -> float:
        return self.value


def test_iribarren_matches_the_formula():
    # H=1m, T=10s -> L0 = 9.80665*100/2pi = 156.1 m, steepness 0.006406,
    # xi = 0.03 / 0.08004 = 0.3748
    assert iribarren(1.0, 10.0, 0.03) == pytest.approx(0.3748, abs=1e-3)


def test_iribarren_is_zero_without_energy_or_slope():
    assert iribarren(0.0, 10.0, 0.03) == 0.0
    assert iribarren(1.0, 0.0, 0.03) == 0.0
    assert iribarren(1.0, 10.0, 0.0) == 0.0


def test_classification_pins_the_plunging_band():
    low, high = PLUNGING_BAND
    assert classify_breaker(low - 0.05) == "spilling"
    assert classify_breaker(low + 0.05) == "plunging"
    assert classify_breaker(1.0) == "plunging"
    assert classify_breaker(high + 0.5) == "surging"
    assert classify_breaker(0.0) == "none"


def test_long_period_groundswell_beats_short_period_slop_on_the_same_beach():
    spot_slope = MEASURED
    groundswell = barrel(SwellPartition(1.2, 15.0, 90.0), spot_slope)
    windslop = barrel(SwellPartition(2.0, 6.0, 90.0), spot_slope)
    assert groundswell.value > windslop.value
    assert "plunging" in groundswell.basis
    assert "spilling" in windslop.basis


def test_barrel_peaks_inside_the_band_and_decays_outside():
    # Slopes chosen against the DEEP-WATER band (0.5..3.3), whose log-centre for
    # this swell sits near tan(beta)=0.105.
    steep_reef = Derived(0.60, "derived")
    flat_beach = Derived(0.005, "derived")
    p = SwellPartition(1.5, 12.0, 90.0)
    mid = barrel(p, Derived(0.105, "derived"))
    assert mid.value > barrel(p, flat_beach).value
    assert mid.value > barrel(p, steep_reef).value
    assert classify_breaker(barrel(p, steep_reef).raw) == "surging"


def test_no_measured_slope_still_scores_and_says_so():
    """A spot with no measured slope still scores, and the basis says so."""
    c = barrel(SwellPartition(1.2, 14.0, 90.0), UNKNOWN)
    assert 0.0 < c.value <= 1.0
    assert "steepness proxy" in c.basis
    assert "no measured beach slope" in c.basis
    assert f"{NOMINAL_SLOPE:.3f}" in c.basis
    assert c.raw == pytest.approx(iribarren(1.2, 14.0, NOMINAL_SLOPE))


def test_fallback_still_separates_groundswell_from_chop():
    assert (
        barrel(SwellPartition(1.0, 16.0, 90.0), UNKNOWN).value
        > barrel(SwellPartition(1.0, 6.0, 90.0), UNKNOWN).value
    )


def test_barrel_uses_the_measured_slope_when_it_exists():
    c = barrel(SwellPartition(1.2, 14.0, 90.0), MEASURED)
    assert "Iribarren" in c.basis
    assert "[derived]" in c.basis
    assert "steepness proxy" not in c.basis


def test_no_swell_is_no_barrel():
    assert barrel(None, MEASURED).value == 0.0
    assert barrel(SwellPartition(0.0, 12.0, 90.0), MEASURED).value == 0.0


def test_offshore_beats_cross_beats_onshore():
    spot = make_spot(shore_normal=90.0)  # faces east; offshore wind is from 270
    off = cleanness(Wind(9.0, 270.0), spot)
    cross = cleanness(Wind(9.0, 0.0), spot)
    on = cleanness(Wind(9.0, 90.0), spot)
    assert off.value > cross.value > on.value
    assert "offshore" in off.basis and "onshore" in on.basis
    assert on.value == pytest.approx(0.0, abs=0.01)


def test_calm_is_glassy_from_any_direction():
    spot = make_spot()
    assert cleanness(Wind(0.5, 90.0), spot).value == pytest.approx(1.0)
    assert cleanness(Wind(0.5, 270.0), spot).value == pytest.approx(1.0)


def test_offshore_gale_is_penalised_not_rewarded():
    spot = make_spot()
    breeze = cleanness(Wind(6.0, 270.0), spot)
    gale = cleanness(Wind(18.0, 270.0), spot)
    assert gale.value < breeze.value
    assert "gale" in gale.basis


def test_missing_wind_is_neutral_and_labelled_rather_than_assumed_clean():
    c = cleanness(None, make_spot())
    assert c.value == 0.5
    assert "unknown" in c.basis


def test_cleanness_raw_is_the_angle_off_offshore():
    spot = make_spot(shore_normal=180.0)  # faces south; offshore is from 0
    assert cleanness(Wind(5.0, 45.0), spot).raw == pytest.approx(45.0)


def test_size_rises_with_height_and_never_falls_off_at_the_top():
    """There is no ceiling, so bigger must never score worse."""
    values = [size(field(height=h)).value for h in (0.3, 0.8, 1.5, 3.0, 6.0)]
    assert values == sorted(values)
    assert values[-1] < 1.0  # saturating, but never a hard cap


def test_matrix_cut_reduces_size_and_the_basis_names_the_method():
    full = size(field(), FlatMatrix(1.0))
    half = size(field(), FlatMatrix(0.25))
    assert half.value < full.value
    # energy fraction 0.25 -> half the height
    assert half.raw == pytest.approx(full.raw / 2.0)
    assert "matrix:analytic" in half.basis


def test_size_without_a_matrix_says_it_is_unrefracted():
    assert "unrefracted" in size(field()).basis


def test_partitions_combine_in_energy():
    two = WaveField(
        time=T0,
        partitions=(
            SwellPartition(1.0, 14.0, 90.0, "swell"),
            SwellPartition(1.0, 6.0, 45.0, "windwave"),
        ),
        model="gwam",
    )
    assert size(two).raw == pytest.approx(2.0 ** 0.5)
    swell_only = size(two, include_windwave=False)
    assert swell_only.raw == pytest.approx(1.0)


def test_size_falls_back_to_total_height_when_partitions_are_null():
    """ECMWF answers with every partition column null but a usable total."""
    ecmwf = WaveField(time=T0, partitions=(), total_height_m=1.5,
                      total_period_s=11.0, model="ecmwf_wam025")
    c = size(ecmwf)
    assert c.raw == pytest.approx(1.5)
    assert c.value > 0.0


def test_size_of_nothing_is_zero_and_labelled():
    assert size(None).value == 0.0
    assert "no partitions" in size(WaveField(time=T0, model="x")).basis


def test_agreeing_models_beat_disagreeing_models():
    agree = [field(1.2, 12.0, 90.0, model="gwam"), field(1.25, 12.4, 94.0, model="best_match")]
    disagree = [field(0.6, 8.0, 90.0, model="gwam"), field(2.0, 15.0, 200.0, model="best_match")]
    assert confidence(agree).value > 0.8
    assert confidence(disagree).value < 0.1


def test_one_model_is_not_confidence():
    c = confidence([field(model="gwam")])
    assert c.value == SINGLE_MODEL_CONFIDENCE
    assert "single model" in c.basis
    assert "gwam" in c.basis


def test_confidence_names_the_models_that_answered():
    c = confidence([field(model="gwam"), field(model="ncep_gfswave025")])
    assert "gwam" in c.basis and "ncep_gfswave025" in c.basis
    assert "2 models" in c.basis


def test_direction_disagreement_alone_costs_confidence():
    same_size = [field(1.2, 12.0, 60.0, model="a"), field(1.2, 12.0, 150.0, model="b")]
    assert confidence(same_size).value < confidence(
        [field(1.2, 12.0, 60.0, model="a"), field(1.2, 12.0, 62.0, model="b")]
    ).value


def test_no_partitions_anywhere_is_zero_confidence():
    empty = WaveField(time=T0, model="ecmwf_wam025")
    assert confidence([empty]).value == 0.0


def test_reference_field_is_the_median_not_the_first():
    fields = [field(3.0, model="a"), field(1.0, model="b"), field(1.5, model="c")]
    assert reference_field(fields).model == "c"


def test_score_hour_returns_four_separate_components_never_fused():
    spot = make_spot()
    fields = [
        field(1.4, 13.0, 90.0, model="gwam", wind=Wind(4.0, 270.0)),
        field(1.5, 12.5, 95.0, model="best_match"),
    ]
    c = score_hour(spot, fields, FlatMatrix(0.9))
    assert set(c.as_dict()) == {"barrel", "cleanness", "size", "confidence"}
    for name, value in c.as_dict().items():
        assert 0.0 <= value <= 1.0, name
    assert all(part.basis for part in (c.barrel, c.cleanness, c.size, c.confidence))
    assert c.cleanness.value > 0.9  # light offshore
    assert c.confidence.value > 0.8


def test_score_hour_takes_wind_from_whichever_model_carried_it():
    spot = make_spot()
    fields = [field(model="ecmwf_wam025"), field(model="gwam", wind=Wind(6.0, 90.0))]
    assert score_hour(spot, fields).cleanness.raw == pytest.approx(180.0)


def test_score_hour_survives_an_empty_model_set():
    """Every source failing is a scored zero with a reason, not an exception."""
    c = score_hour(make_spot(), [])
    assert c.as_dict() == {"barrel": 0.0, "cleanness": 0.0, "size": 0.0, "confidence": 0.0}
    assert "no model" in c.barrel.basis


def test_score_hour_uses_the_spot_slope_and_honours_an_override():
    fields = [field(1.2, 14.0, 90.0, model="gwam")]
    unmeasured = score_hour(make_spot(slope=UNKNOWN), fields)
    assert "steepness proxy" in unmeasured.barrel.basis
    overridden = score_hour(make_spot(slope=UNKNOWN), fields, slope=Derived(0.04, "manual"))
    assert "Iribarren" in overridden.barrel.basis


def test_ordering_key_prefers_the_hollow_clean_day_over_the_big_mushy_one():
    spot = make_spot()
    hollow = score_hour(
        spot, [field(1.3, 15.0, 90.0, model="gwam", wind=Wind(4.0, 270.0))]
    )
    mushy = score_hour(
        spot, [field(2.2, 6.0, 90.0, model="gwam", wind=Wind(9.0, 90.0))]
    )
    assert hollow.ordering_key() > mushy.ordering_key()
