"""Surfline benchmark tests. The fixtures are trimmed from real 2026-09-03 responses,
keeping FT-by-default units, the all-zero padding partitions, and the separate wind
endpoint."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import httpx
import pytest

from surf.sources import Http
from surf.surfline import (
    ENV_FLAG,
    Surfline,
    benchmark,
    disagreement,
)
from surf.spots import Derived, Spot
from surf.waves import Forecast, SwellPartition, WaveField
from surf.sources import Window

T0 = 1788343200  # 2026-09-01T18:00:00Z


def _spot(surfline_id: str | None = "5842041f4e65fad6a7708890") -> Spot:
    return Spot(
        id="lido",
        name="Lido Beach",
        lat=40.583,
        lon=-73.598,
        shore_normal=Derived(180.0, "manual"),
        beach_slope=Derived(0.03, "default"),
        offshore_lat=40.5,
        offshore_lon=-73.6,
        region="ny",
        surfline_id=surfline_id,
    )


def _window(hours: int = 3) -> Window:
    return Window(start=datetime.fromtimestamp(T0, timezone.utc), hours=hours)


SWELLS = {
    "associated": {
        "units": {"swellHeight": "FT"},
        "runInitializationTimestamp": 1788372000,
    },
    "data": {
        "swells": [
            {
                "timestamp": T0 + 3600 * i,
                "swells": [
                    {"height": 3.28084, "period": 8, "direction": 59.0},
                    {"height": 6.56168, "period": 14, "direction": 130.0},
                    {"height": 0.0, "period": 0, "direction": 0.0},
                    {"height": 0.0, "period": 0, "direction": 0.0},
                ],
            }
            for i in range(3)
        ]
    },
}

WIND = {
    "associated": {"units": {"windSpeed": "KTS"}, "runInitializationTimestamp": 1788372000},
    "data": {
        "wind": [
            {"timestamp": T0 + 3600 * i, "speed": 19.43844, "direction": 315.0}
            for i in range(3)
        ]
    },
}

SURF = {
    "associated": {"units": {"waveHeight": "FT"}, "runInitializationTimestamp": 1788372000},
    "data": {
        "surf": [
            {
                "timestamp": T0 + 3600 * i,
                "surf": {
                    "min": 3,
                    "max": 4,
                    "humanRelation": "Waist to chest",
                    "raw": {"min": 3.28084, "max": 4.92126},
                },
            }
            for i in range(3)
        ]
    },
}


def _client(routes: dict[str, object]) -> Http:
    """`routes` maps the last URL segment to a payload, an int status, or an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        outcome = routes.get(endpoint)
        if outcome is None:
            return httpx.Response(404, text="not found")
        if isinstance(outcome, int):
            return httpx.Response(outcome, text="upstream said no")
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(200, json=outcome)

    return Http(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _adapter(routes: dict[str, object]) -> Surfline:
    return Surfline(_client(routes), enabled=True)


def test_nothing_else_imports_surfline():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "surf"
    offenders = []
    for path in src.rglob("*.py"):
        if path.name == "surfline.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if "surfline" in stripped:
                offenders.append(f"{path}:{lineno}: {stripped}")
    assert offenders == [], "Surfline must never be imported by the core: " + "; ".join(offenders)


def test_benchmark_is_off_by_default(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert benchmark() is None


def test_benchmark_opt_in_by_env(monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    bench = benchmark()
    assert isinstance(bench, Surfline) and bench.enabled


def test_disabled_adapter_never_touches_the_network():
    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a disabled benchmark must not make a call")

    off = Surfline(Http(client=httpx.Client(transport=httpx.MockTransport(explode))), enabled=False)
    for reading in (off.preflight(), off.partitions(_spot(), _window()), off.surf_heights(_spot(), _window())):
        assert reading.status == "skipped"
        assert not reading.ok


def test_partitions_converts_units_drops_padding_and_merges_wind():
    r = _adapter({"swells": SWELLS, "wind": WIND}).partitions(_spot(), _window())
    assert r.status == "ok" and r.ok
    forecast = r.value
    assert isinstance(forecast, Forecast)
    assert forecast.model == "surfline" and forecast.spot_id == "lido"
    assert len(forecast.hours) == 3

    hour = forecast.hours[0]
    assert hour.time == datetime.fromtimestamp(T0, timezone.utc)
    # four entries in, two real trains out: the zero rows are array shape.
    assert len(hour.partitions) == 2
    # FT in, metres out, most energetic first.
    assert hour.partitions[0].height_m == pytest.approx(2.0, abs=1e-3)
    assert hour.partitions[0].period_s == 14
    assert hour.partitions[1].height_m == pytest.approx(1.0, abs=1e-3)
    # KTS in, m/s out.
    assert hour.wind is not None
    assert hour.wind.speed_mps == pytest.approx(10.0, abs=1e-3)
    assert hour.wind.direction_deg == 315.0

    assert r.model_run == "2026-09-02T18:00:00+00:00"
    assert r.confidence is None  # one opaque model, so any confidence would be invented


def test_metric_response_is_not_double_converted():
    metric = json.loads(json.dumps(SWELLS))
    metric["associated"]["units"]["swellHeight"] = "M"
    r = _adapter({"swells": metric, "wind": WIND}).partitions(_spot(), _window())
    assert r.value.hours[0].partitions[0].height_m == pytest.approx(6.56168)


def test_dead_wind_endpoint_degrades_instead_of_killing():
    r = _adapter({"swells": SWELLS, "wind": 404}).partitions(_spot(), _window())
    assert r.status == "degraded" and r.ok
    assert any("wind" in d for d in r.dropped)
    assert len(r.value.hours) == 3
    assert r.value.hours[0].wind is None
    assert r.value.hours[0].partitions  # swell survived intact


def test_dead_swells_endpoint_fails_without_raising():
    r = _adapter({"swells": 500, "wind": WIND}).partitions(_spot(), _window())
    assert r.status == "failed" and r.value is None and not r.ok
    assert r.source == "surfline" and r.fetched_at is not None


def test_short_response_names_what_was_dropped():
    r = _adapter({"swells": SWELLS, "wind": WIND}).partitions(_spot(), _window(hours=12))
    assert r.status == "degraded"
    assert any("12h" in d for d in r.dropped)


def test_hours_outside_the_window_are_not_smuggled_in():
    r = _adapter({"swells": SWELLS, "wind": WIND}).partitions(_spot(), _window(hours=1))
    assert len(r.value.hours) == 1
    assert r.value.hours[0].time == datetime.fromtimestamp(T0, timezone.utc)


def test_spot_without_a_surfline_id_is_skipped_not_guessed():
    r = _adapter({"swells": SWELLS, "wind": WIND}).partitions(_spot(None), _window())
    assert r.status == "skipped" and "no surfline_id" in r.note


def test_open_breaker_yields_skipped():
    adapter = _adapter({"swells": 500, "wind": 500})
    breaker = adapter._http.breaker("surfline")
    for _ in range(breaker.threshold):
        breaker.record_failure()
    r = adapter.partitions(_spot(), _window())
    assert r.status == "skipped" and "breaker" in r.note


def test_surf_heights_use_raw_values_and_keep_the_human_words():
    r = _adapter({"surf": SURF}).surf_heights(_spot(), _window())
    assert r.status == "ok"
    first = r.value[0]
    assert first.min_m == pytest.approx(1.0, abs=1e-3)
    assert first.max_m == pytest.approx(1.5, abs=1e-3)
    assert first.human_relation == "Waist to chest"
    assert "not Hs" in r.note  # never comparable to a model's significant height


def test_surf_heights_failure_is_labelled():
    r = _adapter({"surf": 503}).surf_heights(_spot(), _window())
    assert r.status == "failed" and r.value is None


def test_preflight_ok_and_failed():
    assert _adapter({"surf": SURF}).preflight().value is True
    bad = _adapter({"surf": 502}).preflight()
    assert bad.status == "failed" and bad.value is False


def test_preflight_of_an_empty_body_is_a_failure_not_a_pass():
    r = _adapter({"surf": {"associated": {}, "data": {"surf": []}}}).preflight()
    assert r.status == "failed" and r.value is False


def _field(hour: int, height: float, period: float) -> WaveField:
    return WaveField(
        time=datetime.fromtimestamp(T0 + 3600 * hour, timezone.utc),
        partitions=(SwellPartition(height, period, 130.0),),
        model="gwam",
    )


def test_disagreement_matches_hours_and_signs_the_delta():
    ours = Forecast("lido", "gwam", (_field(0, 1.0, 10.0), _field(1, 1.0, 10.0), _field(9, 5.0, 5.0)))
    theirs = Forecast("lido", "surfline", (_field(0, 1.5, 12.0), _field(1, 1.1, 11.0)))
    d = disagreement(ours, theirs)
    assert d.hours_compared == 2  # the unmatched hour is not counted as agreement
    assert d.mean_height_delta_m == pytest.approx(0.3)
    assert d.max_height_delta_m == pytest.approx(0.5)
    assert d.mean_period_delta_s == pytest.approx(1.5)


def test_disagreement_with_no_overlap_says_so():
    d = disagreement(Forecast("lido", "gwam", (_field(0, 1.0, 10.0),)),
                     Forecast("lido", "surfline", (_field(50, 1.0, 10.0),)))
    assert d.hours_compared == 0 and "no overlapping hours" in d.note


@pytest.mark.network
def test_live_surfline_still_answers():
    """curl gets a 403 from the WAF here; httpx with a real User-Agent does not."""
    adapter = Surfline(enabled=True)
    assert adapter.preflight().value is True
    r = adapter.partitions(_spot(), _window(hours=24))
    assert r.ok and r.value.hours
    assert r.value.hours[0].partitions
