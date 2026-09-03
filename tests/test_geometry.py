"""Bathymetry and beach slope. The fixtures are verbatim getSamples responses
captured on 2026-09-03; only the `network`-marked test goes out to the server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from surf.sources import Http
from surf.bathymetry import NceiBathymetry, Sample, destination
from surf.spots import Derived, Spot
from surf.sources import Reading
from surf.geometry import (
    COARSE_GRID_M,
    GeometryCache,
    beach_slope,
    fit_beach_slope,
    seaward_bearing,
)

# Lido Beach faces ~170 (S/SSE). Verified US high-resolution DEM coverage.
LIDO = Spot(
    id="lido",
    name="Lido Beach",
    lat=40.5875,
    lon=-73.5665,
    shore_normal=Derived(170.0, "manual"),
    beach_slope=Derived(0.02, "default"),
    offshore_lat=40.55,
    offshore_lon=-73.5665,
    region="NY",
    break_type="beach",
    buoys=("44025",),
)

# Llandudno is outside US DEM coverage: the mosaic answers there with the
# ~463 m global grid.
LLANDUDNO = Spot(
    id="llandudno",
    name="Llandudno",
    lat=-34.0080,
    lon=18.3410,
    shore_normal=Derived(250.0, "manual"),
    beach_slope=Derived(0.05, "default"),
    offshore_lat=-34.02,
    offshore_lon=18.32,
    region="ZA",
)

FINE_M = 3.43     # 3.086e-5 deg, what Lido returned
COARSE_M = 463.0  # 0.0041667 deg — 15 arc-seconds, what Llandudno returned


def planar(slope: float, *, spacing=25.0, count=40, berm_m=2.0, resolution=FINE_M):
    """A beach that rises `berm_m` above sea level at the spot coordinate and
    falls away at a constant `slope`."""
    out = []
    for i in range(count):
        d = i * spacing
        out.append(Sample(d, 0.0, 0.0, berm_m - slope * d, resolution))
    return tuple(out)


class FakeDepths:
    """A DepthSource that counts calls, so cache hits are provable."""

    name = "fake"

    def __init__(self, reading: Reading):
        self._reading = reading
        self.calls = 0

    def soundings(self, spot, bearing_deg, *, spacing_m=25.0, count=60):
        self.calls += 1
        self.bearing = bearing_deg
        return self._reading


def ok(samples) -> Reading:
    from surf.sources import now
    return Reading(samples, "fake", "ok", now())


def test_planar_beach_recovers_its_slope():
    s = planar(0.02)
    fit = fit_beach_slope([x.distance_m for x in s], [x.elevation_m for x in s],
                          resolution_m=FINE_M)
    assert fit.usable
    assert fit.tan_beta == pytest.approx(0.02, rel=1e-6)
    assert fit.ratio == "1:50"
    assert fit.shoreline_m == pytest.approx(100.0)
    assert "3 m DEM" in fit.basis


def test_fit_stops_at_the_breaking_depth_not_the_shelf():
    """Past the surf zone the floor flattens. Fitting the whole profile would
    report a beach four times gentler than the one waves actually break on."""
    steep, flat = 0.02, 0.001
    samples, z = [], 0.0
    for i in range(60):
        d = i * 25.0
        z = 2.0 - steep * d if z > -6.0 else z - flat * 25.0
        samples.append(Sample(d, 0.0, 0.0, z, FINE_M))
    fit = fit_beach_slope([x.distance_m for x in samples], [x.elevation_m for x in samples],
                          resolution_m=FINE_M)
    assert fit.tan_beta == pytest.approx(steep, rel=0.05)
    assert fit.max_depth_m >= 6.0


def test_coarse_grid_refuses_to_guess_a_slope():
    """The Llandudno case: a 463 m cell cannot describe a beach face, so the
    answer is 'no slope', in words, not a plausible-looking number."""
    s = planar(0.02, resolution=COARSE_M)
    fit = fit_beach_slope([x.distance_m for x in s], [x.elevation_m for x in s],
                          resolution_m=COARSE_M)
    assert not fit.usable
    assert fit.tan_beta is None
    assert fit.resolution_m == COARSE_M
    assert "463" in fit.basis and "steepness proxy" in fit.basis
    assert fit.as_derived() is None
    assert fit.ratio == "unknown"


def test_coarse_threshold_is_the_documented_one():
    fine = fit_beach_slope(*_pairs(planar(0.02, resolution=COARSE_GRID_M - 1)),
                           resolution_m=COARSE_GRID_M - 1)
    coarse = fit_beach_slope(*_pairs(planar(0.02, resolution=COARSE_GRID_M)),
                             resolution_m=COARSE_GRID_M)
    assert fine.usable and not coarse.usable


def test_inland_bearing_is_reported_not_fitted():
    s = planar(-0.01, berm_m=1.0)  # rises forever: the bearing points at a dune
    fit = fit_beach_slope(*_pairs(s), resolution_m=FINE_M)
    assert not fit.usable
    assert "inland" in fit.basis


def test_flat_lagoon_never_deepens():
    s = tuple(Sample(i * 25.0, 0, 0, -1.0, FINE_M) for i in range(20))
    fit = fit_beach_slope(*_pairs(s), resolution_m=FINE_M)
    assert not fit.usable
    assert "does not deepen" in fit.basis


def test_bars_are_counted_and_the_fit_spans_them():
    """A barred profile is the barrelling case, so the bar must not break the
    fit — it is reported alongside a slope, not instead of one."""
    profile = [2.0, 1.0, -0.5, -1.5, -1.0, -2.0, -3.5, -4.0, -5.0, -6.5]
    d = [i * 25.0 for i in range(len(profile))]
    fit = fit_beach_slope(d, profile, resolution_m=FINE_M)
    assert fit.usable
    assert fit.bars == 1
    assert "reversal" in fit.basis


def test_holes_are_skipped_not_interpolated():
    whole = fit_beach_slope(*_pairs(planar(0.02)), resolution_m=FINE_M)
    s = list(planar(0.02))
    s[6] = Sample(s[6].distance_m, 0, 0, None, FINE_M)  # a hole in the surf zone
    fit = fit_beach_slope(*_pairs(s), resolution_m=FINE_M)
    assert fit.tan_beta == pytest.approx(0.02, rel=1e-6)
    assert fit.fit_points == whole.fit_points - 1


def test_no_data_at_all_is_a_stated_reason():
    fit = fit_beach_slope([0.0, 25.0, 50.0], [None, None, None])
    assert not fit.usable
    assert "no profile to fit" in fit.basis


def test_short_profile_says_it_never_reached_depth():
    s = planar(0.02, count=8)  # 200 m at 1:50 is 2 m of water
    fit = fit_beach_slope(*_pairs(s), resolution_m=FINE_M)
    assert fit.usable
    assert "never reached" in fit.basis


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        fit_beach_slope([0.0, 1.0], [0.0])


def _pairs(samples):
    return [x.distance_m for x in samples], [x.elevation_m for x in samples]


def test_beach_slope_shoots_the_profile_down_the_shore_normal():
    src = FakeDepths(ok(planar(0.02)))
    reading = beach_slope(LIDO, src)
    assert reading.ok and reading.status == "ok"
    assert src.bearing == seaward_bearing(LIDO) == 170.0
    assert reading.value.bearing_deg == 170.0
    assert reading.source == "geometry:fake"
    assert reading.value.as_derived().provenance == "derived"


def test_a_dead_source_degrades_the_slope_and_kills_nothing():
    from surf.sources import now
    src = FakeDepths(Reading(None, "fake", "failed", now(), note="ConnectError"))
    reading = beach_slope(LIDO, src)
    assert reading.status == "failed"
    assert reading.value is None
    assert not reading.ok
    assert "ConnectError" in reading.note


def test_degraded_soundings_stay_degraded_even_with_a_good_fit():
    from surf.sources import now
    src = FakeDepths(Reading(planar(0.02), "fake", "degraded", now(),
                             dropped=("2 NoData soundings",)))
    reading = beach_slope(LIDO, src)
    assert reading.value.usable
    assert reading.status == "degraded"
    assert reading.dropped == ("2 NoData soundings",)


def test_geometry_is_cached_not_refetched(tmp_path):
    cache = GeometryCache(tmp_path)
    src = FakeDepths(ok(planar(0.02)))
    first = beach_slope(LIDO, src, cache=cache)
    second = beach_slope(LIDO, src, cache=cache)
    assert src.calls == 1
    assert second.value.tan_beta == pytest.approx(first.value.tan_beta)
    assert "cached" in second.note
    assert beach_slope(LIDO, src, cache=cache, refresh=True).ok
    assert src.calls == 2


def test_cache_is_keyed_by_bearing():
    """A profile shot down a different bearing is a different measurement."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        cache = GeometryCache(d)
        src = FakeDepths(ok(planar(0.02)))
        beach_slope(LIDO, src, cache=cache)
        beach_slope(LIDO, src, cache=cache, bearing_deg=90.0)
        assert src.calls == 2


def test_a_coarse_grid_verdict_is_cached_but_a_failure_is_not(tmp_path):
    from surf.sources import now
    cache = GeometryCache(tmp_path)
    beach_slope(LLANDUDNO, FakeDepths(ok(planar(0.02, resolution=COARSE_M))), cache=cache)
    assert cache.get(LLANDUDNO.id, seaward_bearing(LLANDUDNO)) is not None

    dead = FakeDepths(Reading(None, "fake", "failed", now(), note="down"))
    beach_slope(LIDO, dead, cache=cache)
    assert cache.get(LIDO.id, seaward_bearing(LIDO)) is None


def test_cache_round_trips_every_field(tmp_path):
    cache = GeometryCache(tmp_path)
    src = FakeDepths(ok(planar(0.02)))
    written = beach_slope(LIDO, src, cache=cache).value
    read, _ = cache.get(LIDO.id, 170.0)
    assert read == written


def test_a_corrupt_cache_file_is_a_miss_not_a_crash(tmp_path):
    cache = GeometryCache(tmp_path)
    src = FakeDepths(ok(planar(0.02)))
    beach_slope(LIDO, src, cache=cache)
    next(tmp_path.iterdir()).write_text("{not json")
    assert beach_slope(LIDO, src, cache=cache).ok
    assert src.calls == 2


LIDO_SAMPLES = {
    "samples": [
        {"location": {"x": -73.5665, "y": 40.5875}, "locationId": 0,
         "value": "1.310637593", "rasterId": 1619, "resolution": 3.0864197485206961e-05},
        {"location": {"x": -73.5665, "y": 40.5850}, "locationId": 1,
         "value": "-2.533051491", "rasterId": 1619, "resolution": 3.0864197485206961e-05},
        {"location": {"x": -73.5665, "y": 40.5825}, "locationId": 2,
         "value": "NoData", "rasterId": 1619, "resolution": 3.0864197485206961e-05},
    ]
}


def stub(body, status=200) -> NceiBathymetry:
    def handler(request: httpx.Request) -> httpx.Response:
        stub.last = request
        return httpx.Response(status, json=body)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return NceiBathymetry(Http(client=client), base_url="https://example.invalid/ImageServer")


def test_soundings_parse_values_resolution_and_nodata():
    ncei = stub(LIDO_SAMPLES)
    r = ncei.soundings(LIDO, 170.0, spacing_m=25.0, count=3)
    assert r.status == "degraded"          # one hole, said out loud
    assert r.dropped == ("1 NoData soundings",)
    assert [s.elevation_m for s in r.value] == [pytest.approx(1.310637593),
                                               pytest.approx(-2.533051491), None]
    assert [s.distance_m for s in r.value] == [0.0, 25.0, 50.0]
    assert r.value[0].resolution_m == pytest.approx(3.43, abs=0.05)
    assert "DEM cell ~3 m" in r.note


def test_request_is_a_getsamples_multipoint_in_lon_lat_order():
    ncei = stub(LIDO_SAMPLES)
    ncei.soundings(LIDO, 170.0, spacing_m=25.0, count=3)
    q = stub.last.url.params
    assert stub.last.url.path.endswith("/getSamples")
    assert q["geometryType"] == "esriGeometryMultipoint" and q["f"] == "json"
    pts = json.loads(q["geometry"])["points"]
    assert pts[0] == [pytest.approx(LIDO.lon), pytest.approx(LIDO.lat)]
    assert pts[1][1] < pts[0][1]           # bearing 170 heads south


def test_profile_truncates_at_a_hole_and_says_so():
    """A tuple[float, ...] has no room for a hole, and inventing a depth to fill
    one would degrade the profile silently."""
    r = stub(LIDO_SAMPLES).profile(LIDO, 170.0)
    assert r.status == "degraded"
    assert len(r.value) == 2
    assert any("after first NoData" in d for d in r.dropped)


def test_an_arcgis_error_body_fails_the_reading_without_raising():
    r = stub({"error": {"code": 400, "message": "Invalid geometry"}}).soundings(
        LIDO, 170.0, spacing_m=25.0, count=3)
    assert r.status == "failed" and r.value is None
    assert "Invalid geometry" in r.note


def test_total_nodata_is_a_failure_not_an_empty_profile():
    body = {"samples": [dict(s, value=None) for s in LIDO_SAMPLES["samples"]]}
    r = stub(body).soundings(LIDO, 170.0, spacing_m=25.0, count=3)
    assert r.status == "failed" and r.value is None
    assert "no DEM coverage" in r.note


def test_missing_locations_come_back_as_holes():
    """getSamples may simply omit a point. Position in the list is not the
    contract; locationId is."""
    body = {"samples": [LIDO_SAMPLES["samples"][0], LIDO_SAMPLES["samples"][2]]}
    r = stub(body).soundings(LIDO, 170.0, spacing_m=25.0, count=3)
    assert [s.elevation_m is None for s in r.value] == [False, True, True]


def test_preflight_reports_down_without_raising():
    def handler(request):
        raise httpx.ConnectError("no route to host")
    ncei = NceiBathymetry(Http(client=httpx.Client(transport=httpx.MockTransport(handler))))
    assert ncei.preflight().status == "failed"


def test_breaker_open_is_skipped_not_failed():
    ncei = stub(LIDO_SAMPLES)
    for _ in range(3):
        ncei._http.breaker("ncei").record_failure()
    assert ncei.soundings(LIDO, 170.0, spacing_m=25.0, count=3).status == "skipped"
    assert ncei.preflight().status == "skipped"


def test_destination_walks_the_right_way():
    north = destination(40.0, -73.0, 0.0, 1000.0)
    east = destination(40.0, -73.0, 90.0, 1000.0)
    assert north[0] > 40.0 and north[1] == pytest.approx(-73.0)
    assert east[1] > -73.0 and east[0] == pytest.approx(40.0)


@pytest.mark.network
def test_live_ncei_resolution_splits_us_from_global():
    """The quirk the whole module turns on: US coverage is metres per cell,
    everywhere else is the ~460 m global grid."""
    ncei = NceiBathymetry()
    fine = ncei.soundings(LIDO, seaward_bearing(LIDO), spacing_m=25.0, count=20)
    coarse = ncei.soundings(LLANDUDNO, seaward_bearing(LLANDUDNO), spacing_m=25.0, count=20)
    assert fine.value[0].resolution_m < 20.0
    assert coarse.value[0].resolution_m > 100.0
    assert beach_slope(LIDO, ncei).value.usable
    assert not beach_slope(LLANDUDNO, ncei).value.usable
