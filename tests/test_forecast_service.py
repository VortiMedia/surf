"""The forecast fanout, run offline against fakes that misbehave on cue: `Exploding`
raises on every call, `Silent` fails its health check, and `Breakered` raises the
shape an open circuit breaker raises.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from surf.bathymetry import Sample
from surf.spots import Derived, Spot
from surf.waves import Forecast, SwellPartition, TidePoint, WaveField, Wind
from surf.sources import Reading, Window
from surf.forecast import (
    MODEL_ONLY_NOTE,
    ForecastService,
    Sources,
    SpotForecast,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
WINDOW = Window(start=T0, hours=6)

LIDO = Spot(
    id="lido",
    name="Lido Beach",
    lat=40.5875,
    lon=-73.5665,
    shore_normal=Derived(170.0, "manual"),
    beach_slope=Derived(0.02, "default"),
    offshore_lat=40.55,
    offshore_lon=-73.5665,
    region="US-NY",
    break_type="beach",
    buoys=("44025", "44065"),
    tide_station="8516402",
)

# David's 5/5 spots are exactly where no free buoy exists.
LLANDUDNO = Spot(
    id="llandudno",
    name="Llandudno",
    lat=-34.008,
    lon=18.341,
    shore_normal=Derived(250.0, "manual"),
    beach_slope=Derived(0.05, "default"),
    offshore_lat=-34.02,
    offshore_lon=18.32,
    region="ZA",
)


def clock() -> datetime:
    return datetime(2026, 9, 10, 6, 30, tzinfo=UTC)


def wave(at: datetime, model: str, height: float = 1.2, period: float = 11.0) -> WaveField:
    return WaveField(
        time=at,
        partitions=(SwellPartition(height, period, 160.0, "swell"),),
        wind=Wind(4.0, 350.0),
        total_height_m=height,
        total_period_s=period,
        model=model,
    )


class FakeModel:
    """A ForecastSource that answers. `hours` is how many it is willing to give."""

    def __init__(self, name: str, *, height: float = 1.2, hours: int = 6, start: datetime = T0):
        self.name = name
        self._height = height
        self._hours = hours
        self._start = start
        self.preflights = 0
        self.calls = 0

    def preflight(self) -> Reading[bool]:
        self.preflights += 1
        return Reading(True, self.name, "ok", clock())

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        self.calls += 1
        hours = tuple(
            wave(self._start + timedelta(hours=i), self.name, self._height)
            for i in range(self._hours)
        )
        return Reading(
            Forecast(spot.id, self.name, hours), self.name, "ok", clock(), model_run=None
        )


class Exploding:
    """Raises on every call it has, health check included."""

    name = "exploding"

    def __init__(self) -> None:
        self.calls = 0

    def preflight(self) -> Reading[bool]:
        self.calls += 1
        raise RuntimeError("everything is on fire")

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        self.calls += 1
        raise RuntimeError("everything is on fire")

    def latest(self, buoy_id: str) -> Reading[WaveField]:
        self.calls += 1
        raise RuntimeError("everything is on fire")

    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        self.calls += 1
        raise RuntimeError("everything is on fire")


class Silent:
    """Passes nothing: preflight says the source is down, so it must not be called."""

    name = "silent"

    def __init__(self) -> None:
        self.calls = 0

    def preflight(self) -> Reading[bool]:
        return Reading(False, self.name, "failed", clock(), note="503 from the model host")

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        self.calls += 1
        raise AssertionError("a source that failed preflight must never be called")


class SourceDown(Exception):
    """Same name and message shape as surf.sources.SourceDown."""


class Breakered:
    name = "breakered"

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", clock())

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        raise SourceDown("breakered: breaker open after 3 failures")


class FakeBuoy:
    """Observations over one canned report."""

    name = "ndbc"

    def __init__(self, at: datetime = T0, *, dead_buoys: tuple[str, ...] = ()):
        self._at = at
        self._dead = dead_buoys
        self.asked: list[str] = []

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", clock())

    def latest(self, buoy_id: str) -> Reading[WaveField]:
        self.asked.append(buoy_id)
        src = f"{self.name}/{buoy_id}"
        if buoy_id in self._dead:
            return Reading(None, src, "failed", clock(), note="404")
        return Reading(wave(self._at, src, height=1.5), src, "ok", clock())


class FakeTides:
    name = "tides"

    def __init__(self) -> None:
        self.days: list[date] = []

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", clock())

    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]:
        self.days.append(day)
        points = tuple(
            TidePoint(datetime(day.year, day.month, day.day, h, 0, tzinfo=UTC), 0.5 + 0.1 * h)
            for h in range(24)
        )
        return Reading(points, self.name, "ok", clock(), note="datum=MLLW predicted")


class FakeDepth:
    """A beach that really does slope: +1 m of dry sand out to -9 m of water."""

    name = "ncei"

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", clock())

    def soundings(self, spot, bearing_deg, *, spacing_m=25.0, count=60):
        samples = tuple(
            Sample(
                distance_m=i * spacing_m,
                lat=spot.lat,
                lon=spot.lon,
                elevation_m=1.0 - i * (10.0 / count),
                resolution_m=3.43,
            )
            for i in range(count)
        )
        return Reading(samples, self.name, "ok", clock())


def service(**kwargs) -> ForecastService:
    return ForecastService(Sources(**kwargs), clock=clock)


def test_preflight_runs_once_across_many_outlooks():
    """27 calls to a dead endpoint is the failure this exists to prevent."""
    gwam = FakeModel("gwam")
    svc = service(forecast=(gwam,))

    svc.outlook(LIDO, WINDOW)
    svc.outlook(LLANDUDNO, WINDOW)

    assert gwam.preflights == 1
    assert gwam.calls == 2


def test_a_source_that_fails_preflight_is_never_called():
    gwam = FakeModel("gwam")
    silent = Silent()
    out = service(forecast=(gwam, silent)).outlook(LIDO, WINDOW)

    assert silent.calls == 0
    reading = next(r for r in out.readings if r.source == "silent")
    assert reading.status == "failed"
    assert "preflight" in reading.note
    assert out.models == ("gwam",)


def test_health_reports_every_source_and_live_sources_filters():
    svc = service(forecast=(FakeModel("gwam"), Silent(), Exploding()))
    health = svc.health()

    assert set(health) == {"gwam", "silent", "exploding"}
    assert health["exploding"].status == "failed"
    assert svc.live_sources() == ("gwam",)


def test_exploding_source_is_labelled_failed_and_nothing_else_is_touched():
    gwam = FakeModel("gwam", height=1.2)
    ecmwf = FakeModel("ecmwf_wam025", height=1.4)
    boom = Exploding()
    buoy = FakeBuoy()
    tides = FakeTides()

    out = service(
        forecast=(gwam, boom, ecmwf), observations=buoy, tides=tides, depth=FakeDepth()
    ).outlook(LIDO, WINDOW)

    assert len(out.hours) == WINDOW.hours
    assert out.models == ("ecmwf_wam025", "gwam")
    assert out.complete

    failed = out.failures
    assert [r.source for r in failed] == ["exploding"]
    assert failed[0].status == "failed"
    assert "RuntimeError" in failed[0].note

    # everything else arrived
    assert out.hours[0].tide is not None
    assert out.slope is not None
    assert out.hours[0].observation_led
    assert out.status == "degraded"          # one source down is degraded, not dead
    assert any("exploding:failed" in line for line in out.label_lines())


def test_an_open_breaker_is_skipped_not_failed():
    out = service(forecast=(FakeModel("gwam"), Breakered())).outlook(LIDO, WINDOW)
    reading = next(r for r in out.readings if r.source == "breakered")
    assert reading.status == "skipped"


def test_every_source_dead_is_a_failed_forecast_not_an_exception():
    out = service(forecast=(Exploding(),), tides=Exploding()).outlook(LIDO, WINDOW)
    assert out.hours == ()
    assert out.status == "failed"
    assert any("no model answered" in n for n in out.notes)


def test_observation_leads_its_own_hours_and_models_lead_the_rest():
    buoy = FakeBuoy(at=T0)
    out = service(forecast=(FakeModel("gwam"), FakeModel("best_match")), observations=buoy).outlook(
        LIDO, WINDOW
    )

    first = out.hours[0]
    assert first.observation_led
    assert first.reference is first.observed
    assert first.reference.model == "ndbc/44025"
    # the buoy is never counted among the models: it would fake model agreement
    assert first.models == ("best_match", "gwam")

    far = out.hours[-1]        # 5 h out, past the relevance window
    assert not far.observation_led
    assert far.reference is not None and far.reference.model in ("best_match", "gwam")
    assert not out.model_only


def test_the_next_buoy_is_tried_when_the_first_one_is_down():
    buoy = FakeBuoy(dead_buoys=("44025",))
    out = service(forecast=(FakeModel("gwam"),), observations=buoy).outlook(LIDO, WINDOW)

    assert buoy.asked == ["44025", "44065"]
    assert out.hours[0].observed is not None
    assert not out.model_only
    assert any(r.source == "ndbc/44025" and r.status == "failed" for r in out.readings)


def test_a_spot_with_no_buoy_is_flagged_model_only():
    """model-only is a property of the place, not a degradation."""
    out = service(forecast=(FakeModel("gwam"),), observations=FakeBuoy()).outlook(
        LLANDUDNO, WINDOW
    )

    assert out.model_only
    assert MODEL_ONLY_NOTE in out.notes
    assert out.status == "ok"
    assert all(h.observed is None for h in out.hours)


def test_a_stale_report_does_not_lead_any_hour():
    buoy = FakeBuoy(at=T0 - timedelta(hours=9))
    out = service(forecast=(FakeModel("gwam"),), observations=buoy).outlook(LIDO, WINDOW)

    assert all(not h.observation_led for h in out.hours)
    assert out.model_only
    assert any("outside every hour asked for" in n for n in out.notes)


def test_a_short_window_is_reported_never_silently_capped():
    out = service(forecast=(FakeModel("gwam", hours=3),)).outlook(LIDO, Window(T0, 12))

    assert len(out.hours) == 3
    assert not out.complete
    assert out.status == "degraded"
    assert any("window short" in n for n in out.notes)


def test_hours_outside_the_window_are_dropped():
    early = FakeModel("gwam", hours=12, start=T0 - timedelta(hours=4))
    out = service(forecast=(early,)).outlook(LIDO, WINDOW)

    assert out.hours[0].at == T0
    assert out.hours[-1].at == T0 + timedelta(hours=5)


def test_tides_are_fetched_per_day_and_matched_to_the_hour():
    tides = FakeTides()
    out = service(forecast=(FakeModel("gwam", hours=30),), tides=tides).outlook(
        LIDO, Window(T0, 30)
    )

    assert tides.days == [date(2026, 9, 10), date(2026, 9, 11)]
    assert out.hours[0].tide is not None
    assert out.hours[0].tide.time == T0
    assert out.hours[-1].tide is not None


def test_no_tide_source_says_so_rather_than_pretending_one_failed():
    out = service(forecast=(FakeModel("gwam"),)).outlook(LIDO, WINDOW)
    assert "no tide source configured" in out.notes
    assert all(h.tide is None for h in out.hours)
    assert not out.failures


def test_slope_comes_from_bathymetry_and_is_flagged_derived():
    out = service(forecast=(FakeModel("gwam"),), depth=FakeDepth()).outlook(LIDO, WINDOW)

    assert out.slope is not None
    assert out.slope.provenance == "derived"
    assert out.slope.value > 0
    assert out.slope_basis


def test_no_bathymetry_hands_scoring_the_stated_fallback():
    out = service(forecast=(FakeModel("gwam"),)).outlook(LIDO, WINDOW)
    assert out.slope is None
    assert "steepness" in out.slope_basis


def test_naive_model_timestamps_are_read_as_utc():
    naive = FakeModel("gwam", start=datetime(2026, 9, 10, 6, 0))
    out = service(forecast=(naive,)).outlook(LIDO, WINDOW)

    assert len(out.hours) == 6
    assert out.hours[0].at == T0
    assert out.at(datetime(2026, 9, 10, 7, 0)) is out.hours[1]


def test_surfline_is_carried_as_a_benchmark_and_never_scored():
    bench = FakeModel("surfline", height=2.4)
    out = service(forecast=(FakeModel("gwam"),), benchmark=bench).outlook(LIDO, WINDOW)

    assert out.benchmark is not None and out.benchmark.model == "surfline"
    assert out.models == ("gwam",)
    assert all("surfline" not in h.models for h in out.hours)


def test_the_system_is_complete_with_surfline_absent():
    out = service(forecast=(FakeModel("gwam"),)).outlook(LIDO, WINDOW)
    assert out.benchmark is None
    assert out.status == "ok"


def test_every_reading_carries_its_label():
    out = service(
        forecast=(FakeModel("gwam"), Exploding()),
        observations=FakeBuoy(),
        tides=FakeTides(),
        depth=FakeDepth(),
    ).outlook(LIDO, WINDOW)

    assert out.readings
    for reading in out.readings:
        assert reading.source and reading.status and reading.fetched_at
    assert isinstance(out, SpotForecast)
    assert out.hours[0].basis().startswith("2026-09-10 06:00Z observed by ndbc/44025")
