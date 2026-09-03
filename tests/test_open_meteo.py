"""Offline tests for the Open-Meteo marine and archive sources. Every quirk asserted
here was observed against the live API on 2026-09-03."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from surf.sources import BadPayload, Http, SourceDown
from surf.open_meteo import (
    MODELS,
    REJECTED_MODELS,
    MarineModelSet,
    OpenMeteoArchive,
    OpenMeteoMarine,
)
from surf.spots import Derived, Spot
from surf.sources import Window

UTC = timezone.utc


class FakeResponse:
    def __init__(self, payload: dict | str):
        self._payload = payload

    @property
    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else ""

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class FakeHttp:
    """Routes on (url, model) the way the real API does, and records every call so
    tests can assert a dead model was never asked."""

    def __init__(self, routes: dict, fail: dict | None = None):
        self.routes = routes
        self.fail = fail or {}
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, source: str, url: str, params: dict | None = None):
        params = params or {}
        self.calls.append((source, url, params))
        for pattern, exc in self.fail.items():
            if pattern in source:
                raise exc
        key = (url, params.get("models"))
        if key not in self.routes:
            key = (url, None)
        if key not in self.routes:
            raise AssertionError(f"unrouted call: {url} models={params.get('models')}")
        return FakeResponse(self.routes[key])

    def get_json(self, source: str, url: str, params: dict | None = None):
        """Mirrors `Http.get_json`: an unparseable body is retried once, then named
        as this source's failure rather than raised as a decoding error."""
        last = ""
        for attempt in (1, 2):
            response = self.get(source, url, params)
            try:
                return response.json()
            except ValueError:
                last = (response.text or "empty body").splitlines()[0][:120]
                if attempt == 2:
                    raise BadPayload(f"HTTP 200 but body was not JSON: {last!r}") from None
        raise BadPayload(last)


MARINE = "https://marine-api.open-meteo.com/v1/marine"
WEATHER = "https://api.open-meteo.com/v1/forecast"
WEATHER_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def hours(start: datetime, n: int) -> list[str]:
    return [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]


def gwam_payload(start: datetime, n: int = 6) -> dict:
    """Shaped like a real `gwam` response: partitions populated."""
    return {
        "hourly": {
            "time": hours(start, n),
            "wave_height": [0.94] * n,
            "wave_period": [5.5] * n,
            "wave_direction": [111] * n,
            "swell_wave_height": [0.82] * n,
            "swell_wave_period": [6.2] * n,
            "swell_wave_direction": [111] * n,
            "wind_wave_height": [0.46] * n,
            "wind_wave_period": [2.75] * n,
            "wind_wave_direction": [115] * n,
        }
    }


def ecmwf_payload(start: datetime, n: int = 6) -> dict:
    """ECMWF answers 200 with every partition column null."""
    return {
        "hourly": {
            "time": hours(start, n),
            "wave_height": [1.16] * n,
            "wave_period": [6.35] * n,
            "wave_direction": [120] * n,
            "swell_wave_height": [None] * n,
            "swell_wave_period": [None] * n,
            "swell_wave_direction": [None] * n,
        }
    }


def wind_payload(start: datetime, n: int = 6) -> dict:
    return {
        "hourly": {
            "time": hours(start, n),
            "wind_speed_10m": [4.2] * n,
            "wind_direction_10m": [280] * n,
        }
    }


SPOT = Spot(
    id="lido",
    name="Lido Beach",
    lat=40.583,
    lon=-73.577,
    shore_normal=Derived(170.0, "manual"),
    beach_slope=Derived(0.03, "default"),
    offshore_lat=40.5,
    offshore_lon=-73.55,
    region="ny",
    break_type="beach",
    buoys=("44025",),
)

START = datetime(2026, 9, 4, 0, 0, tzinfo=UTC)
WINDOW = Window(start=START, hours=6)


def marine(routes, fail=None, model="gwam", **kw) -> OpenMeteoMarine:
    return OpenMeteoMarine(FakeHttp(routes, fail), model=model, **kw)


def test_partitions_parses_swell_and_windwave_split():
    src = marine({(MARINE, "gwam"): gwam_payload(START), (WEATHER, None): wind_payload(START)})
    reading = src.partitions(SPOT, WINDOW)

    assert reading.status == "ok"
    assert reading.ok
    forecast = reading.value
    assert forecast.spot_id == "lido"
    assert forecast.model == "gwam"
    assert len(forecast.hours) == 6

    first = forecast.hours[0]
    assert first.time == START
    assert first.total_height_m == pytest.approx(0.94)
    kinds = {p.kind: p for p in first.partitions}
    assert set(kinds) == {"swell", "windwave"}
    assert kinds["swell"].period_s == pytest.approx(6.2)
    assert kinds["windwave"].height_m == pytest.approx(0.46)
    assert first.primary.kind == "swell"
    assert first.wind.speed_mps == pytest.approx(4.2)
    assert first.wind.direction_deg == pytest.approx(280)


def test_reading_is_labelled():
    src = marine({(MARINE, "gwam"): gwam_payload(START), (WEATHER, None): wind_payload(START)})
    reading = src.partitions(SPOT, WINDOW)
    assert reading.source == "open-meteo-marine:gwam"
    assert reading.fetched_at.tzinfo is not None
    assert "gwam" in reading.label()


def test_window_is_clipped_to_what_was_asked_for():
    """The API answers in whole days; the caller asked for six hours."""
    src = marine({(MARINE, "gwam"): gwam_payload(START, 24), (WEATHER, None): wind_payload(START, 24)})
    reading = src.partitions(SPOT, Window(start=START + timedelta(hours=3), hours=4))
    times = [h.time for h in reading.value.hours]
    assert times == [START + timedelta(hours=i) for i in (3, 4, 5, 6)]


def test_ecmwf_is_not_asked_for_partitions_and_says_so():
    http = FakeHttp({(MARINE, "ecmwf_wam025"): ecmwf_payload(START), (WEATHER, None): wind_payload(START)})
    reading = OpenMeteoMarine(http, model="ecmwf_wam025").partitions(SPOT, WINDOW)

    asked = [c for c in http.calls if c[1] == MARINE][0][2]["hourly"]
    assert "swell_wave_height" not in asked

    assert reading.status == "ok"          # this is exactly what we requested
    assert any("partitions" in d for d in reading.dropped)   # but never silently
    field = reading.value.hours[0]
    assert field.total_height_m == pytest.approx(1.16)
    assert [p.kind for p in field.partitions] == ["total"]


def test_ecmwf_null_partitions_never_become_zero():
    """A null height parsed as 0.0 would read as flat ocean. It must not."""
    src = marine(
        {(MARINE, "gwam"): ecmwf_payload(START), (WEATHER, None): wind_payload(START)},
        model="gwam",
    )
    reading = src.partitions(SPOT, WINDOW)
    assert all(p.kind != "swell" for h in reading.value.hours for p in h.partitions)
    assert any("partitions" in d for d in reading.dropped)
    assert reading.status == "degraded"


@pytest.mark.parametrize("name", sorted(REJECTED_MODELS))
def test_dead_model_names_are_refused_before_any_call(name):
    http = FakeHttp({})
    with pytest.raises(ValueError):
        OpenMeteoMarine(http, model=name)
    assert http.calls == []


def test_truncated_response_reports_the_hours_it_lost():
    src = marine({(MARINE, "gwam"): gwam_payload(START, 2), (WEATHER, None): wind_payload(START, 2)})
    reading = src.partitions(SPOT, Window(start=START, hours=48))
    assert reading.status == "degraded"
    assert reading.ok
    assert any("hours: 2 of 48" in d for d in reading.dropped)


def test_window_beyond_the_horizon_is_clamped_out_loud():
    far = datetime.now(UTC) + timedelta(days=30)
    src = marine(
        {(MARINE, "gwam"): gwam_payload(far.replace(minute=0, second=0, microsecond=0), 6),
         (WEATHER, None): wind_payload(far.replace(minute=0, second=0, microsecond=0), 6)}
    )
    reading = src.partitions(SPOT, Window(start=far, hours=6))
    assert any("truncated" in d for d in reading.dropped)


def test_all_zero_model_is_flagged():
    """ncep_gfswave025 returned zeros at the test point. Zeros are not calm."""
    payload = gwam_payload(START)
    payload["hourly"]["wave_height"] = [0.0] * 6
    src = marine({(MARINE, "ncep_gfswave025"): payload, (WEATHER, None): wind_payload(START)},
                 model="ncep_gfswave025")
    reading = src.partitions(SPOT, WINDOW)
    assert any("zeros" in d for d in reading.dropped)
    assert reading.status == "degraded"


def test_dead_source_is_a_failed_reading_not_an_exception():
    src = marine({}, fail={"marine": RuntimeError("boom")})
    reading = src.partitions(SPOT, WINDOW)
    assert reading.status == "failed"
    assert reading.value is None
    assert not reading.ok
    assert "boom" in reading.note


def test_open_breaker_yields_skipped_not_failed():
    src = marine({}, fail={"marine": SourceDown("open-meteo-marine:gwam: breaker open")})
    reading = src.partitions(SPOT, WINDOW)
    assert reading.status == "skipped"


def test_wind_failure_does_not_cost_the_waves():
    src = marine(
        {(MARINE, "gwam"): gwam_payload(START)},
        fail={"weather": RuntimeError("wind endpoint down")},
    )
    reading = src.partitions(SPOT, WINDOW)
    assert reading.ok
    assert len(reading.value.hours) == 6
    assert reading.value.hours[0].wind is None
    assert any(d.startswith("wind:") for d in reading.dropped)
    assert reading.status == "degraded"


def test_one_dead_model_degrades_the_set_instead_of_killing_it():
    class PartlyDeadHttp(FakeHttp):
        def get(self, source, url, params=None):
            if "ncep" in source:
                raise RuntimeError("model down")
            return super().get(source, url, params)

    http = PartlyDeadHttp(
        {
            (MARINE, "gwam"): gwam_payload(START),
            (MARINE, "best_match"): gwam_payload(START),
            (MARINE, "ecmwf_wam025"): ecmwf_payload(START),
            (WEATHER, None): wind_payload(START),
        }
    )
    readings = MarineModelSet(http, MODELS).partitions_by_model(SPOT, WINDOW)

    assert set(readings) == set(MODELS)
    assert readings["ncep_gfswave025"].status == "failed"
    assert [m for m, r in readings.items() if r.ok] == ["gwam", "best_match", "ecmwf_wam025"]
    assert len(MarineModelSet.live(readings.values())) == 3


def test_each_model_gets_its_own_breaker_key():
    http = FakeHttp(
        {
            (MARINE, "gwam"): gwam_payload(START),
            (MARINE, "best_match"): gwam_payload(START),
            (WEATHER, None): wind_payload(START),
        }
    )
    MarineModelSet(http, ("gwam", "best_match")).partitions_by_model(SPOT, WINDOW)
    marine_sources = {c[0] for c in http.calls if c[1] == MARINE}
    assert marine_sources == {"open-meteo-marine:gwam", "open-meteo-marine:best_match"}


def test_preflight_happens_once_per_model():
    http = FakeHttp(
        {(MARINE, "gwam"): gwam_payload(START, 1), (MARINE, "best_match"): gwam_payload(START, 1)}
    )
    results = MarineModelSet(http, ("gwam", "best_match")).preflight()
    assert [r.status for r in results.values()] == ["ok", "ok"]
    assert len(http.calls) == 2


def test_preflight_reports_an_empty_answer_as_degraded():
    payload = {"hourly": {"time": hours(START, 2), "wave_height": [None, None]}}
    reading = marine({(MARINE, "gwam"): payload}).preflight()
    assert reading.status == "degraded"
    assert reading.value is False


PAST = date(2024, 3, 24)
PAST_START = datetime(2024, 3, 24, 0, 0, tzinfo=UTC)


def archive_payload(n: int = 24, partitions: bool = True) -> dict:
    hourly = {
        "time": hours(PAST_START, n),
        "wave_height": [2.3] * n,
        "wave_period": [9.65] * n,
        "wave_direction": [154] * n,
    }
    if partitions:
        hourly |= {
            "swell_wave_height": [2.14] * n,
            "swell_wave_period": [8.95] * n,
            "swell_wave_direction": [156] * n,
            "wind_wave_height": [0.6] * n,
            "wind_wave_period": [3.4] * n,
            "wind_wave_direction": [200] * n,
        }
    return {"hourly": hourly}


def archive_wind_payload(n: int = 24) -> dict:
    return {
        "hourly": {
            "time": hours(PAST_START, n),
            "wind_speed_10m": [3.1] * n,
            "wind_direction_10m": [350] * n,
        }
    }


def test_archive_recovers_a_session_hour():
    http = FakeHttp({(MARINE, None): archive_payload(), (WEATHER_ARCHIVE, None): archive_wind_payload()})
    reading = OpenMeteoArchive(http).conditions(SPOT, PAST, 12)

    assert reading.status == "ok"
    field = reading.value
    assert field.time == datetime(2024, 3, 24, 12, tzinfo=UTC)
    assert field.total_height_m == pytest.approx(2.3)
    assert field.primary.period_s == pytest.approx(8.95)
    assert field.wind.direction_deg == pytest.approx(350)
    assert reading.source == "open-meteo-archive"


def test_archive_falls_back_to_era5_when_partitions_do_not_reach_back():
    """Before the partition reanalysis begins the marine default returns nulls;
    era5_ocean still answers with total height, and is labelled as thinner."""
    nulls = {"hourly": {"time": hours(PAST_START, 24), "wave_height": [None] * 24}}
    http = FakeHttp(
        {
            (MARINE, None): nulls,
            (MARINE, "era5_ocean"): archive_payload(partitions=False),
            (WEATHER_ARCHIVE, None): archive_wind_payload(),
        }
    )
    reading = OpenMeteoArchive(http).conditions(SPOT, PAST, 6)

    assert reading.status == "degraded"
    assert reading.value.model == "era5_ocean"
    assert [p.kind for p in reading.value.partitions] == ["total"]
    assert any("total height/period only" in d for d in reading.dropped)
    assert any("era5_ocean" in c[2].get("models", "") for c in http.calls)


def test_archive_refuses_dates_before_the_reanalysis():
    http = FakeHttp({})
    reading = OpenMeteoArchive(http).conditions(SPOT, date(1901, 5, 1), 9)
    assert reading.status == "skipped"
    assert http.calls == []


def test_archive_refuses_the_future():
    http = FakeHttp({})
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    reading = OpenMeteoArchive(http).conditions(SPOT, tomorrow, 9)
    assert reading.status == "skipped"
    assert "forecast" in reading.note
    assert http.calls == []


def test_archive_survives_a_missing_wind_record():
    http = FakeHttp(
        {(MARINE, None): archive_payload()},
        fail={"archive-weather": RuntimeError("ERA5 down")},
    )
    reading = OpenMeteoArchive(http).conditions(SPOT, PAST, 12)
    assert reading.ok
    assert reading.value.wind is None
    assert any(d.startswith("wind:") for d in reading.dropped)


def test_archive_missing_hour_is_a_failed_reading():
    http = FakeHttp(
        {(MARINE, None): archive_payload(3), (MARINE, "era5_ocean"): archive_payload(3, False),
         (WEATHER_ARCHIVE, None): archive_wind_payload(3)}
    )
    reading = OpenMeteoArchive(http).conditions(SPOT, PAST, 18)
    assert reading.status == "failed"
    assert reading.value is None


@pytest.mark.network
def test_live_models_answer_and_ecmwf_partitions_are_still_null():
    http = Http()
    try:
        readings = MarineModelSet(http, MODELS).partitions_by_model(
            SPOT, Window(start=datetime.now(UTC), hours=24)
        )
        assert all(r.status != "failed" for r in readings.values())
        ecmwf = readings["ecmwf_wam025"].value
        assert all(p.kind == "total" for h in ecmwf.hours for p in h.partitions)
        gwam = readings["gwam"].value
        assert any(p.kind == "swell" for h in gwam.hours for p in h.partitions)
    finally:
        http.close()


@pytest.mark.network
def test_live_archive_recovers_a_1940s_date_as_total_only():
    http = Http()
    try:
        reading = OpenMeteoArchive(http).conditions(SPOT, date(1990, 1, 5), 12)
        assert reading.ok
        assert reading.value.total_height_m is not None
        assert any("total height/period only" in d for d in reading.dropped)
    finally:
        http.close()


def test_a_200_that_is_not_json_is_named_not_leaked_as_a_parser_error():
    """Open-Meteo sheds load with HTTP 200 and a plain-text body: raise_for_status
    passes and .json() then dies with 'Expecting value: line 1 column 1 (char 0)'.
    The note must name the overloaded wind service, and the waves must survive it."""
    src = marine({
        (MARINE, "gwam"): gwam_payload(START),
        (WEATHER, None): "Unexpected error while streaming data: timeoutReached",
    })
    reading = src.partitions(SPOT, WINDOW)

    assert reading.ok                                   # the waves survived
    assert reading.status == "degraded"
    dropped = " ".join(reading.dropped)
    assert "wind" in dropped
    assert "not JSON" in dropped
    assert "timeoutReached" in dropped
    assert "Expecting value" not in dropped
