from __future__ import annotations

import io
from datetime import date, datetime, timezone

from surf import cli
from surf.calibrate import ConditionCache, recover
from surf.call import SpotOutlook, make_call
from surf.reach import Reach, reach_from_log
from surf.sessions import Session
from surf.spots import SpotBook
from surf.waves import Forecast, SwellPartition, WaveField, Wind


BOOK = SpotBook.load()


def field(height: float) -> WaveField:
    return WaveField(
        time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        partitions=(SwellPartition(height, 11.0, 100.0, "swell"),),
        wind=Wind(3.0, 280.0),
        total_height_m=height,
        total_period_s=11.0,
        model="fixture",
    )


class Archive:
    name = "reach-fixture"

    def __init__(self, by_spot: dict[str, WaveField]):
        self.by_spot = by_spot

    def conditions(self, spot, on, hour):
        value = self.by_spot.get(spot.id)
        if value is None:
            from surf.sources import Reading

            return Reading(None, self.name, "failed", datetime.now(timezone.utc), note="missing")
        from surf.sources import Reading

        return Reading(value, self.name, "ok", datetime.now(timezone.utc), note="fixture")


def session(day: int, spot: str, rating: int) -> Session:
    return Session(
        raw_date=f"2024-04-{day:02d}",
        raw_spot=spot,
        raw_time="08:00",
        rating=rating,
        notes="",
        on=date(2024, 4, day),
        hour=8,
        spot_id=spot,
    )


def test_reach_uses_largest_4_or_5_and_ignores_a_3_outlier(tmp_path):
    rows = (session(1, "lido-beach", 4), session(2, "belmar", 3))
    cache = ConditionCache(tmp_path / "calibration")
    recover(rows, Archive({"lido-beach": field(1.4), "belmar": field(3.5)}), book=BOOK, cache=cache)

    reach = reach_from_log(BOOK, sessions=rows, cache=cache)

    assert reach.status == "ok"
    assert reach.sample_count == 1
    assert reach.mark_m is not None and reach.mark_m < 2.0
    assert reach.ceiling_m == reach.mark_m + 0.5


def test_reach_degrades_when_a_qualifying_session_is_not_cached(tmp_path):
    rows = (session(1, "lido-beach", 4),)
    reach = reach_from_log(BOOK, sessions=rows, cache=ConditionCache(tmp_path / "empty"))

    assert reach.status == "degraded"
    assert reach.mark_m is None
    assert reach.ceiling_m is None
    assert "missing conditions" in reach.render()


def test_partial_reach_still_enforces_the_known_ceiling() -> None:
    reach = Reach(mark_m=1.5, status="degraded", dropped=("one session missing",))
    assert reach.ceiling_m == 2.0
    assert reach.accepts(1.9)
    assert not reach.accepts(2.1)
    assert not reach.accepts(None)
    assert "known evidence" in reach.render()


def test_session_add_fetches_a_qualifying_row_and_ratchets_without_a_size_field(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SURF_CACHE_DIR", str(tmp_path / "cache"))
    log = tmp_path / "sessions.tsv"
    out, err = io.StringIO(), io.StringIO()
    console = cli.Console(
        out=out,
        err=err,
        book=BOOK,
        archive=Archive({"lido-beach": field(1.4)}),
    )
    code = cli.main([
        "session", "add", "--date", "2024-04-01", "--spot", "lido-beach",
        "--time", "08:00", "--rating", "4", "--path", str(log),
    ], console=console)
    assert code == cli.EXIT_OK
    assert "REACH mark" in out.getvalue()
    assert "did not ratchet" not in err.getvalue()
    assert console.readings and console.readings[0].source == "reach-fixture"


def test_call_drops_hours_above_known_reach_ceiling_without_ordering_reach():
    from tests.test_call_service import NOW, field as forecast_field, make_spot, outlook

    low = make_spot("low")
    high = make_spot("high")
    low_outlook = outlook(low, forecasts=(Forecast(low.id, "fixture", (forecast_field(NOW, height=1.0),)),))
    high_outlook = outlook(high, forecasts=(Forecast(high.id, "fixture", (forecast_field(NOW, height=2.5),)),))

    reading = make_call(
        [low_outlook, high_outlook], now=NOW, daylight_only=False,
        reach=Reach(mark_m=1.0, status="ok", basis="fixture"),
    )

    assert reading.ok and reading.value is not None
    assert reading.value.winner.spot_id == "low"
    assert any("above REACH ceiling" in dropped for dropped in reading.dropped)
    components = reading.value.winner.components
    assert "reach" not in components.as_dict()
    assert components.ordering_key() == components.barrel.value * components.size.value * components.cleanness.value
