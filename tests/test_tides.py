"""Tide adapter tests, offline against fixtures captured from the live services on
2026-09-03. The one live probe is marked `network`."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import httpx
import pytest

from surf.sources import Http
from surf.tides import (
    COOPS,
    OPEN_METEO,
    CoopsError,
    CoopsTides,
    OpenMeteoTides,
    TideAdapter,
    _label_stages,
    _parse_coops_time,
)
from surf.spots import Derived, Spot
from surf.waves import TidePoint

DAY = date(2026, 9, 4)

# Captured verbatim from api.tidesandcurrents.noaa.gov, station 8531680.
HILO = {"predictions": [
    {"t": "2026-09-04 05:36", "v": "1.335", "type": "H"},
    {"t": "2026-09-04 11:32", "v": "0.234", "type": "L"},
    {"t": "2026-09-04 18:03", "v": "1.639", "type": "H"},
]}
HOURLY = {"predictions": [
    {"t": f"2026-09-04 {h:02d}:00", "v": f"{v:.3f}"}
    for h, v in zip(range(24), [
        0.303, 0.423, 0.668, 0.947, 1.190, 1.320, 1.300, 1.140, 0.880, 0.590,
        0.340, 0.240, 0.300, 0.510, 0.820, 1.150, 1.430, 1.610, 1.639, 1.520,
        1.260, 0.930, 0.620, 0.400,
    ])
]}
# 6-minute pairs used for surge: observed sits 0.20 m above the prediction.
SIX_MIN = [f"2026-09-04 00:{m:02d}" for m in (0, 6, 12, 18)]
WATER_LEVEL = {"metadata": {"id": "8531680"},
               "data": [{"t": t, "v": f"{0.30 + 0.20:.3f}", "s": "0.03", "q": "p"} for t in SIX_MIN]}
PREDICTED_6MIN = {"predictions": [{"t": t, "v": "0.300"} for t in SIX_MIN]}

OM_TIMES = [f"2026-09-04T{h:02d}:00" for h in range(24)]
OM_HEIGHTS = [round(0.7 * math.sin(h / 24 * 4 * math.pi), 3) for h in range(24)]


def spot(station: str | None) -> Spot:
    return Spot(
        id="sandy-hook" if station else "llandudno",
        name="Sandy Hook" if station else "Llandudno",
        lat=40.4669 if station else -34.0058,
        lon=-74.0094 if station else 18.3389,
        shore_normal=Derived(90.0, "manual"),
        beach_slope=Derived(0.03, "default"),
        offshore_lat=40.5,
        offshore_lon=-73.9,
        region="NJ" if station else "Western Cape",
        tide_station=station,
    )


def _client(handler) -> Http:
    return Http(client=httpx.Client(transport=httpx.MockTransport(handler)))


def coops_handler(hilo=HILO, hourly=HOURLY, water_level=WATER_LEVEL,
                  predicted=PREDICTED_6MIN, status=200):
    """Route a datagetter request by product/interval, the way CO-OPS does."""
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params
        if q.get("product") == "water_level":
            body = water_level
        elif q.get("interval") == "hilo":
            body = hilo
        elif q.get("interval") == "h":
            body = hourly
        else:
            body = predicted
        if body is None:
            return httpx.Response(500, text="boom")
        return httpx.Response(status, json=body)
    return handler


def om_handler(times=OM_TIMES, heights=OM_HEIGHTS, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, json={
            "hourly_units": {"sea_level_height_msl": "m"},
            "hourly": {"time": times, "sea_level_height_msl": heights},
        })
    return handler


def both_handler(coops=None, om=None):
    """One transport for both services, dispatching on host."""
    coops = coops or coops_handler()
    om = om or om_handler()
    def handler(request: httpx.Request) -> httpx.Response:
        if "tidesandcurrents" in request.url.host:
            return coops(request)
        return om(request)
    return handler


def test_coops_times_are_utc_because_we_ask_for_gmt():
    t = _parse_coops_time("2026-09-04 05:36")
    assert t == datetime(2026, 9, 4, 5, 36, tzinfo=timezone.utc)


def test_stages_are_only_filled_where_a_source_did_not_state_one():
    pts = [
        TidePoint(datetime(2026, 9, 4, 5, tzinfo=timezone.utc), 1.0),
        TidePoint(datetime(2026, 9, 4, 6, tzinfo=timezone.utc), 2.0, stage="high"),
        TidePoint(datetime(2026, 9, 4, 7, tzinfo=timezone.utc), 1.5),
    ]
    stages = [p.stage for p in _label_stages(pts)]
    assert stages == ["rising", "high", "falling"]


def test_us_spot_merges_hilo_turn_times_into_the_hourly_curve():
    r = CoopsTides(_client(coops_handler())).curve(spot("8531680"), DAY)
    assert r.status == "ok" and r.source == COOPS
    assert "MLLW" in r.note
    times = [p.time for p in r.value]
    assert times == sorted(times)
    assert len(r.value) == 27  # 24 hourly samples plus 3 exact turns
    highs = [p for p in r.value if p.stage == "high"]
    assert [p.time.strftime("%H:%M") for p in highs] == ["05:36", "18:03"]
    assert any(p.stage == "low" and p.time.strftime("%H:%M") == "11:32" for p in r.value)


def test_a_200_carrying_an_error_document_is_a_failure_not_a_flat_tide():
    err = {"error": {"message": "No Predictions data was found."}}
    adapter = CoopsTides(_client(coops_handler(hilo=err)))
    r = adapter.curve(spot("8531680"), DAY)
    assert r.status == "failed" and r.value is None
    assert "No Predictions data" in r.note
    # and the breaker counted it, or a dead station would be retried forever
    assert adapter.http.breaker(COOPS).failures == 1


def test_error_document_raises_rather_than_returning_an_empty_list():
    adapter = CoopsTides(_client(coops_handler(hilo={"error": {"message": "bad datum"}})))
    with pytest.raises(CoopsError):
        adapter._predictions("8531680", DAY, "hilo")


def test_losing_the_hourly_curve_degrades_the_reading_and_says_so():
    r = CoopsTides(_client(coops_handler(hourly=None))).curve(spot("8531680"), DAY)
    assert r.status == "degraded"
    assert r.dropped == ("hourly-curve",)
    assert len(r.value) == 3  # the hi/lo extremes survive
    assert "hourly-curve" in r.label()


def test_a_spot_with_no_station_is_skipped_by_coops_not_failed():
    r = CoopsTides(_client(coops_handler())).curve(spot(None), DAY)
    assert r.status == "skipped" and r.value is None


def test_open_breaker_skips_instead_of_calling():
    adapter = CoopsTides(_client(coops_handler()))
    b = adapter.http.breaker(COOPS)
    for _ in range(b.threshold):
        b.record_failure()
    r = adapter.curve(spot("8531680"), DAY)
    assert r.status == "skipped" and "breaker open" in r.note


def test_surge_is_observed_minus_predicted():
    r = CoopsTides(_client(coops_handler())).surge(spot("8531680"), DAY)
    assert r.status == "ok"
    assert all(abs(p.height_m - 0.20) < 1e-9 for p in r.value)
    assert "+0.20" in r.note and "observed - predicted" in r.note


def test_surge_reports_samples_it_could_not_match():
    observed = {"data": [{"t": "2026-09-04 00:00", "v": "0.500"},
                         {"t": "2026-09-04 00:03", "v": "0.500"}]}
    r = CoopsTides(_client(coops_handler(water_level=observed))).surge(spot("8531680"), DAY)
    assert r.status == "degraded"
    assert r.dropped == ("1-unmatched-samples",)


def test_non_us_spot_uses_the_global_model_and_labels_the_datum():
    r = OpenMeteoTides(_client(om_handler())).curve(spot(None), DAY)
    assert r.status == "ok" and r.source == OPEN_METEO
    assert "MSL" in r.note and "not MLLW" in r.note
    assert len(r.value) == 24
    assert {p.stage for p in r.value} >= {"rising", "falling"}
    assert any(p.stage in ("high", "low") for p in r.value)


def test_null_hours_are_reported_never_dropped_silently():
    heights = list(OM_HEIGHTS)
    heights[3] = None
    r = OpenMeteoTides(_client(om_handler(heights=heights))).curve(spot(None), DAY)
    assert r.status == "degraded"
    assert r.dropped == ("1-null-hours",)
    assert len(r.value) == 23


def test_a_short_day_reports_the_missing_hours():
    r = OpenMeteoTides(_client(om_handler(times=OM_TIMES[:10], heights=OM_HEIGHTS[:10]))).curve(
        spot(None), DAY)
    assert r.status == "degraded"
    assert "14-hours-missing" in r.dropped


def test_http_failure_is_a_failed_reading_not_an_exception():
    r = OpenMeteoTides(_client(om_handler(status=503))).curve(spot(None), DAY)
    assert r.status == "failed" and r.value is None and r.note


def test_the_port_picks_coops_for_a_us_spot_and_the_model_elsewhere():
    tides = TideAdapter(_client(both_handler()))
    assert tides.curve(spot("8531680"), DAY).source == COOPS
    assert tides.curve(spot(None), DAY).source == OPEN_METEO


def test_a_dead_station_falls_back_to_the_global_model_and_admits_it():
    tides = TideAdapter(_client(both_handler(coops=coops_handler(hilo=None))))
    r = tides.curve(spot("8531680"), DAY)
    assert r.ok and r.source == OPEN_METEO
    assert r.status == "degraded"
    assert "fell back" in r.note and "MSL" in r.note
    assert f"{COOPS}-station-8531680" in r.dropped


def test_both_mechanisms_down_fails_loudly_with_both_reasons():
    tides = TideAdapter(_client(both_handler(coops=coops_handler(hilo=None),
                                             om=om_handler(status=503))))
    r = tides.curve(spot("8531680"), DAY)
    assert r.status == "failed" and r.value is None
    assert "coops" in r.note and "open_meteo" in r.note


def test_preflight_is_degraded_not_down_when_only_coops_is_missing():
    tides = TideAdapter(_client(both_handler(coops=coops_handler(hilo=None))))
    r = tides.preflight()
    assert r.value is True and r.status == "degraded"
    assert any(d.startswith(COOPS) for d in r.dropped)


def test_preflight_fails_only_when_no_tide_source_answers():
    tides = TideAdapter(_client(both_handler(coops=coops_handler(hilo=None),
                                             om=om_handler(status=503))))
    assert tides.preflight().status == "failed"


def test_surge_outside_the_us_is_skipped_never_approximated():
    r = TideAdapter(_client(both_handler())).surge(spot(None), DAY)
    assert r.status == "skipped" and r.value is None
    assert "model tide already includes it" in r.note


@pytest.mark.network
def test_live_both_mechanisms_answer():
    tides = TideAdapter()
    us = tides.curve(spot("8531680"), date.today())
    za = tides.curve(spot(None), date.today())
    assert us.ok and us.source == COOPS
    assert za.ok and za.source == OPEN_METEO
