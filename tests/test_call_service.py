"""The call: what it commits to and what it refuses to. Offline; the component
arithmetic is in tests/test_scoring.py.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from surf.call import Call
from surf.spots import Derived, Spot
from surf.waves import Forecast, SwellPartition, TidePoint, WaveField, Wind
from surf.sources import Reading
from surf.call import (
    _lit,
    HEADS_UP_DAYS,
    MAX_RUNNERS_UP,
    MAX_SIGNALS,
    SHARP_DAYS,
    SpotOutlook,
    hours_by_time,
    horizon_note,
    make_call,
    score_outlook,
    tide_note,
    window_hours,
    window_text,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)   # 08:00 EDT — the fixtures
                                                          # must sit in daylight now that
                                                          # the call refuses dark hours
MEASURED = Derived(0.035, "derived", "NCEI profile")
UNMEASURED = Derived(0.020, "default", "placeholder; nobody measured this")


def make_spot(
    spot_id: str = "lido",
    *,
    shore_normal: float = 90.0,
    buoys: tuple[str, ...] = ("44025",),
    access: str = "",
    slope: Derived = MEASURED,
) -> Spot:
    """An east-facing beach: offshore wind blows from 270."""
    return Spot(
        id=spot_id,
        name=spot_id.title(),
        lat=40.6,
        lon=-73.6,
        shore_normal=Derived(shore_normal, "manual"),
        beach_slope=slope,
        offshore_lat=40.5,
        offshore_lon=-73.4,
        region="US-NY",
        break_type="beach",
        buoys=buoys,
        access=access,
    )


def field(
    at: datetime,
    *,
    height: float = 1.4,
    period: float = 12.0,
    direction: float = 90.0,
    wind_from: float = 270.0,
    wind_mps: float = 3.0,
    model: str = "gwam",
) -> WaveField:
    return WaveField(
        time=at,
        partitions=(SwellPartition(height, period, direction, "swell"),),
        wind=Wind(wind_mps, wind_from),
        total_height_m=height,
        total_period_s=period,
        model=model,
    )


def forecast(
    spot_id: str,
    *,
    model: str = "gwam",
    start_hour: int = 6,
    hours: int = 4,
    day: int = 0,
    **kwargs,
) -> Forecast:
    base = NOW + timedelta(days=day)
    return Forecast(
        spot_id=spot_id,
        model=model,
        hours=tuple(
            field(base + timedelta(hours=start_hour + i), model=model, **kwargs)
            for i in range(hours)
        ),
    )


def outlook(spot: Spot | None = None, **kwargs) -> SpotOutlook:
    spot = spot or make_spot()
    kwargs.setdefault("forecasts", (forecast(spot.id, day=1),))
    kwargs.setdefault("slope", MEASURED)
    return SpotOutlook(spot=spot, **kwargs)


def unwrap(reading: Reading[Call]) -> Call:
    assert reading.ok and reading.value is not None, reading.label()
    return reading.value


def test_hours_by_time_transposes_models_into_hours():
    spot = make_spot()
    bundles = hours_by_time(
        (forecast(spot.id, model="gwam", day=1), forecast(spot.id, model="ecmwf", day=1))
    )

    assert len(bundles) == 4
    for fields in bundles.values():
        assert {f.model for f in fields} == {"gwam", "ecmwf"}


def test_score_outlook_reports_what_it_dropped():
    spot = make_spot()
    far = forecast(spot.id, day=SHARP_DAYS + 2)
    hours, dropped = score_outlook(
        outlook(spot, forecasts=(forecast(spot.id, day=1), far)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )

    assert len(hours) == 4
    assert any("outside the horizon" in line for line in dropped)


def test_daylight_filter_is_stated_not_silent():
    """Dark hours are dropped and the drop is announced. The lit window is solar
    geometry per spot and date, not fixed UTC hours: Lido in September is lit from
    about 10:00Z to 23:45Z, and those same hours are dark in December."""
    spot = make_spot()
    hours, dropped = score_outlook(
        outlook(spot, forecasts=(forecast(spot.id, day=1, start_hour=2, hours=12),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )

    assert hours, "the lit hours must survive"
    assert all(_lit(spot, hour.at).contains(hour.at) for hour in hours)
    assert any("in the dark" in line for line in dropped)


def test_daylight_can_be_turned_off_for_a_dawn_patrol_question():
    spot = make_spot()
    hours, _ = score_outlook(
        outlook(spot, forecasts=(forecast(spot.id, day=1, start_hour=2, hours=12),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
        daylight_only=False,
    )
    assert len(hours) == 12


def test_window_stops_at_a_gap_in_the_hours():
    spot = make_spot()
    # start_hour is an offset from NOW (12:00Z), so these land at 18:00Z and
    # 03:00Z — the first run in daylight at Lido, the second in the dark.
    good = forecast(spot.id, day=1, start_hour=6, hours=3)
    later = forecast(spot.id, day=1, start_hour=15, hours=2)
    hours, _ = score_outlook(
        outlook(spot, forecasts=(Forecast(spot.id, "gwam", good.hours + later.hours),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )
    peak = max(hours, key=lambda h: h.key)
    run = window_hours(hours, peak)

    assert len(run) == 3
    assert run[0].at.hour == 18 and run[-1].at.hour == 20
    assert window_text(run) == f"{run[0].at:%a %d %b} 18:00-21:00 UTC"


def test_window_drops_hours_that_fall_well_off_the_peak():
    spot = make_spot()
    strong = field(NOW + timedelta(days=1, hours=6))
    weak = field(NOW + timedelta(days=1, hours=7), height=0.2, wind_from=90.0, wind_mps=12.0)
    hours, _ = score_outlook(
        outlook(spot, forecasts=(Forecast(spot.id, "gwam", (strong, weak)),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )
    peak = max(hours, key=lambda h: h.key)

    assert window_hours(hours, peak) == (peak,)


def test_call_commits_to_a_spot_a_day_and_a_time():
    call = unwrap(make_call([outlook()], now=NOW))

    assert call.winner.spot_id == "lido"
    assert NOW < call.winner.at <= NOW + timedelta(days=SHARP_DAYS)
    assert "UTC" in call.window
    assert 2 <= len(call.signals) <= MAX_SIGNALS


def test_call_always_names_a_falsifier():
    call = unwrap(make_call([outlook()], now=NOW))

    assert call.falsifiers
    # Which branch fires depends on where xi lands, so assert the falsifier is
    # about the plunging band rather than pinning one branch's wording.
    assert any("plunging band" in f for f in call.falsifiers)
    assert any("wind is" in f for f in call.falsifiers)


def test_model_only_spot_is_flagged_in_the_call_and_in_the_falsifiers():
    spot = make_spot("llandudno", buoys=())
    call = unwrap(make_call([outlook(spot)], now=NOW))

    assert call.winner.model_only is True
    assert any("no buoy in range" in f for f in call.falsifiers)
    assert any("model-only" in c for c in call.caveats)


def test_a_buoy_that_answered_with_nothing_reads_differently_from_no_buoy():
    spot = make_spot("lido", buoys=("44025",))
    call = unwrap(make_call([outlook(spot)], now=NOW))

    assert any("buoy 44025 returned nothing" in f for f in call.falsifiers)


def test_an_observed_spot_is_not_flagged_model_only():
    spot = make_spot()
    observed = field(NOW + timedelta(days=1, hours=6), model="ndbc/44025")
    call = unwrap(make_call([outlook(spot, observed=observed)], now=NOW))

    assert call.winner.model_only is False
    assert not any("model-only" in f for f in call.falsifiers)


def test_unmeasured_slope_falsifier_says_the_slope_is_assumed():
    spot = make_spot(slope=UNMEASURED)
    call = unwrap(make_call([SpotOutlook(spot=spot, forecasts=(forecast(spot.id, day=1),))], now=NOW))

    assert any("assumed" in f and "not measured" in f for f in call.falsifiers)


def test_access_is_a_cost_not_a_filter():
    """an expensive spot still wins if it is the best spot."""
    far = make_spot("aquinnah", access="rental car + ferry, ~$150")
    near = make_spot("lido", access="subway")
    call = unwrap(
        make_call(
            [
                outlook(far, forecasts=(forecast(far.id, day=1),)),
                outlook(near, forecasts=(forecast(near.id, day=1, height=0.3, period=5.0),)),
            ],
            now=NOW,
        )
    )

    assert call.winner.spot_id == "aquinnah"
    assert call.winner.access_note == "rental car + ferry, ~$150"
    assert any("a cost, not a filter" in c for c in call.caveats)


def test_runners_up_stay_a_short_list_and_exclude_the_winner():
    spots = [make_spot(f"spot{i}") for i in range(5)]
    call = unwrap(
        make_call(
            [
                outlook(spot, forecasts=(forecast(spot.id, day=1, height=1.4 - 0.1 * i),))
                for i, spot in enumerate(spots)
            ],
            now=NOW,
        )
    )

    assert len(call.runners_up) == MAX_RUNNERS_UP
    assert call.winner.spot_id not in {c.spot_id for c in call.runners_up}


def test_tide_note_rides_along_and_becomes_a_signal():
    spot = make_spot()
    at = NOW + timedelta(days=1, hours=6)
    tide = (TidePoint(at, 0.4, "rising"), TidePoint(at + timedelta(hours=6), 1.5, "high"))
    call = unwrap(make_call([outlook(spot, tide=tide)], now=NOW))

    assert "rising" in call.winner.tide_note
    assert not any("no tide curve" in f for f in call.falsifiers)


def test_missing_tide_is_a_falsifier():
    call = unwrap(make_call([outlook()], now=NOW))

    assert any("no tide curve" in f for f in call.falsifiers)


def test_tide_note_admits_when_the_nearest_point_is_far_away():
    at = NOW + timedelta(days=1, hours=6)
    note = tide_note((TidePoint(at + timedelta(hours=9), 1.2, "high"),), at)

    assert "unknown" in note


def test_a_day_seven_swell_never_wins_the_call():
    """Beyond five days size and timing are not trustworthy, so day 7 cannot win."""
    sharp = make_spot("lido")
    distant = make_spot("hero")
    call = unwrap(
        make_call(
            [
                outlook(sharp, forecasts=(forecast(sharp.id, day=1, height=1.0),)),
                outlook(
                    distant,
                    forecasts=(forecast(distant.id, day=SHARP_DAYS + 2, height=3.0, period=16.0),),
                ),
            ],
            now=NOW,
        )
    )

    assert call.winner.spot_id == "lido"
    assert "day 7" in call.horizon_note
    assert "arrival signal only" in call.horizon_note


def test_horizon_note_reports_arrival_without_pricing_it():
    spot = make_spot()
    note = horizon_note(
        [outlook(spot, forecasts=(forecast(spot.id, day=SHARP_DAYS + 2, height=2.5, period=15.0),))],
        now=NOW,
    )

    assert "15 s from" in note
    assert "2.5" not in note  # a heads-up carries period and direction, not size


def test_windswell_alone_is_not_an_arrival_signal():
    spot = make_spot()
    note = horizon_note(
        [outlook(spot, forecasts=(forecast(spot.id, day=SHARP_DAYS + 2, period=6.0),))],
        now=NOW,
    )

    assert note.startswith("nothing on the charts")


def test_hours_past_the_headsup_horizon_are_dropped_out_loud():
    spot = make_spot()
    reading = make_call(
        [
            outlook(
                spot,
                forecasts=(
                    forecast(spot.id, day=1),
                    forecast(spot.id, day=HEADS_UP_DAYS + 3),
                ),
            )
        ],
        now=NOW,
    )

    assert any("outside the horizon" in line for line in reading.dropped)


def test_no_scoreable_hour_fails_cleanly_rather_than_inventing_a_call():
    spot = make_spot()
    reading = make_call([SpotOutlook(spot=spot)], now=NOW)

    assert reading.value is None
    assert reading.status == "failed"
    assert reading.ok is False
    assert "no model answered" in " ".join(reading.dropped)


def test_dead_sources_become_caveats_on_the_call():
    dead = Reading(
        value=None,
        source="open-meteo-marine:ecmwf_wam025",
        status="failed",
        fetched_at=NOW,
        note="connect timeout",
    )
    reading = make_call([outlook()], now=NOW, readings=[dead])
    call = unwrap(reading)

    assert any("ecmwf_wam025:failed" in c for c in call.caveats)
    assert reading.status == "degraded"


def test_the_reading_is_labelled_like_every_other_reading():
    reading = make_call([outlook()], now=NOW)

    assert reading.source == "call"
    assert reading.fetched_at == NOW
    assert reading.confidence is not None
    assert "spots scored" in reading.note


def test_neighbour_is_passed_through_for_calibration_to_fill():
    call = unwrap(make_call([outlook()], now=NOW, neighbour="resembles your 2024-03-24 Lido session"))

    assert call.neighbour.startswith("resembles")


def test_naive_forecast_times_are_treated_as_utc():
    spot = make_spot()
    naive = WaveField(
        time=datetime(2026, 9, 11, 18, 0),
        partitions=(SwellPartition(1.4, 12.0, 90.0, "swell"),),
        wind=Wind(3.0, 270.0),
        model="gwam",
    )
    call = unwrap(make_call([outlook(spot, forecasts=(Forecast(spot.id, "gwam", (naive,)),))], now=NOW))

    assert call.winner.at == datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("days", [1, 3, 5])
def test_every_day_inside_the_sharp_horizon_can_win(days: int):
    spot = make_spot()
    call = unwrap(make_call([outlook(spot, forecasts=(forecast(spot.id, day=days),))], now=NOW))

    assert call.winner.at.date() == (NOW + timedelta(days=days)).date()
    assert call.winner.at.date() <= (NOW + timedelta(days=SHARP_DAYS)).date()


def test_window_is_rendered_in_the_spots_own_local_time():
    """Nobody drives to a beach on UTC, and a window ending at 00:00 reads as
    broken rather than as midnight."""
    spot = replace(make_spot(), timezone="America/New_York")
    hours, _ = score_outlook(
        outlook(spot, forecasts=(forecast(spot.id, day=1, start_hour=6, hours=3),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )
    text = window_text(hours)

    assert "EDT" in text and "UTC" not in text
    assert "14:00-17:00" in text            # 18:00-21:00Z is 14:00-17:00 EDT


def test_a_spot_with_no_timezone_prints_utc_and_says_utc():
    hours, _ = score_outlook(
        outlook(make_spot(), forecasts=(forecast("lido", day=1, start_hour=6, hours=3),)),
        start=NOW,
        end=NOW + timedelta(days=SHARP_DAYS),
    )
    assert window_text(hours).endswith("UTC")
