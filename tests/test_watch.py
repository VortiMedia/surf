from __future__ import annotations

from datetime import datetime, timedelta, timezone

from surf.forecast import Hour, SpotForecast
from surf.snapshots import SnapshotStore, size_band
from surf.spots import SpotBook
from surf.sources import Reading, Window
from surf.waves import SwellPartition, TidePoint, WaveField, Wind
from surf.watch import (
    Range,
    SavedSetup,
    SetupConditions,
    SetupStore,
    SwellCondition,
    TideCondition,
    WindCondition,
    evaluate_forecast,
    run_watch,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
SPOT = SpotBook.load().resolve("point-judith")
assert SPOT is not None


def forecast(status: str = "ok") -> SpotForecast:
    valid = NOW + timedelta(hours=6)
    field = WaveField(
        time=valid,
        partitions=(SwellPartition(1.4, 12.0, 165.0, "swell"),),
        wind=Wind(3.0, 340.0),
        total_height_m=1.4,
        total_period_s=12.0,
        model="gwam",
    )
    return SpotForecast(
        spot=SPOT,
        window=Window(NOW, 1),
        hours=(Hour(valid, fields=(field,), tide=TidePoint(valid, 0.5, "rising")),),
        readings=(Reading(True, "gwam", status, NOW, model_run="run-1", dropped=("wind",) if status != "ok" else ()),),
    )


SETUP = SavedSetup(
    name="Point Judith prime",
    spots=(SPOT.id,),
    conditions=SetupConditions(
        swell_partitions=(SwellCondition(
            height_m=Range(1.0, 2.0), period_s=Range(10.0, 14.0), direction_deg=Range(150.0, 180.0),
        ),),
        direction_deg=Range(150.0, 180.0), period_s=Range(10.0, 14.0),
        size_band=size_band(1.4),
        wind=WindCondition(speed_mps=Range(0.0, 5.0), direction_deg=Range(300.0, 360.0)),
        tide=TideCondition(height_m=Range(0.0, 1.0), stages=("rising",)),
        minimum_model_agreement=0.3,
        lead_hours=Range(3.0, 12.0),
        regime="groundswell",
    ),
)


class Service:
    def __init__(self, result: SpotForecast):
        self.result = result
        self.calls = []

    def outlook(self, spot, window):
        self.calls.append((spot.id, window))
        return self.result


def test_setup_is_structured_and_round_trips(tmp_path):
    path = tmp_path / "setup.json"
    SetupStore(path).save(SETUP)
    loaded = SetupStore(path).load()
    assert loaded == SETUP
    data = loaded.as_dict()
    assert data["conditions"]["swell_partitions"][0]["period_s"] == {"min": 10.0, "max": 14.0}
    assert data["conditions"]["wind"]["speed_mps"] == {"min": 0.0, "max": 5.0}
    assert data["conditions"]["model_agreement"] == {"min": 0.3}


def test_run_watch_uses_forecast_path_fires_with_evidence_and_freezes_snapshots(tmp_path):
    service = Service(forecast())
    snapshots = SnapshotStore(tmp_path / "snapshots.jsonl")
    result = run_watch(
        SETUP, service=service, book=SpotBook.load(), now=NOW,
        snapshot_store=snapshots, model_run="run-1",
    )
    assert service.calls and service.calls[0][0] == SPOT.id
    assert result.alerts[0].fired is True
    assert "offshore Hs" in " ".join(result.alerts[0].evidence)
    assert result.snapshots_written == len(snapshots.read())
    assert result.snapshots_written > 0


def test_degraded_source_suppresses_alert_and_names_dropped_evidence():
    alert = evaluate_forecast(SETUP, forecast("degraded"), now=NOW)
    assert alert.fired is False
    assert "degraded" in alert.reason
    assert any("dropped=wind" in item for item in alert.dropped)


def test_no_model_run_does_not_invent_snapshot_provenance(tmp_path):
    result = run_watch(
        SETUP, service=Service(forecast()), book=SpotBook.load(), now=NOW,
        snapshot_store=SnapshotStore(tmp_path / "snapshots.jsonl"),
    )
    assert result.snapshots_written == 0
    assert "model_run is required" in result.dropped[0]
