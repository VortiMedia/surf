from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from surf.forecast import Hour, SpotForecast
from surf.sessions import Session
from surf.snapshots import (
    BuoyObservation,
    SnapshotError,
    SnapshotStore,
    snapshot_from_hour,
    verify_snapshots,
)
from surf.spots import SpotBook
from surf.sources import Reading, Window
from surf.waves import SwellPartition, WaveField


UTC = timezone.utc
ISSUED = datetime(2026, 9, 10, 12, tzinfo=UTC)
VALID = ISSUED + timedelta(hours=6)
BOOK = SpotBook.load()
SPOT = BOOK.resolve("point-judith")
assert SPOT is not None


def wave(at: datetime, height: float, model: str = "gwam") -> WaveField:
    return WaveField(
        time=at,
        partitions=(SwellPartition(height, 12.0, 165.0),),
        total_height_m=height,
        total_period_s=12.0,
        model=model,
    )


def make_snapshot(*, quantity: str = "offshore_hs"):
    forecast = SpotForecast(
        spot=SPOT,
        window=Window(ISSUED, 7),
        hours=(Hour(VALID, fields=(wave(VALID, 1.4),)),),
        readings=(Reading(True, "gwam", "ok", ISSUED, model_run="20260910T00Z"),),
    )
    return snapshot_from_hour(
        forecast, forecast.hours[0], issued_at=ISSUED,
        model_run="20260910T00Z", height_quantity=quantity,
    )


def test_snapshot_has_required_provenance_and_is_append_only(tmp_path):
    snapshot = make_snapshot()
    assert snapshot.issued_at < snapshot.valid_at
    assert snapshot.model_run == "20260910T00Z"
    assert snapshot.spot == "point-judith"
    assert snapshot.predicted_components.size.raw is not None
    assert snapshot.source_status[0].status == "ok"
    assert snapshot.geometry_version.startswith("geometry-v1:")
    assert snapshot.height_quantity == "offshore_hs"

    store = SnapshotStore(tmp_path / "snapshots.jsonl")
    snapshot_id = store.write(snapshot, now=ISSUED + timedelta(hours=1))
    assert snapshot_id == snapshot.snapshot_id
    assert store.read() == (snapshot,)
    with pytest.raises(SnapshotError, match="immutable"):
        store.write(snapshot, now=ISSUED + timedelta(hours=2))
    with pytest.raises(SnapshotError, match="before valid_at"):
        SnapshotStore(tmp_path / "late.jsonl").write(snapshot, now=VALID)


def test_snapshot_round_trip_keeps_explicit_height_quantity():
    snapshot = make_snapshot(quantity="face_height")
    assert snapshot.predicted_height_m is None
    assert snapshot.as_dict()["height_quantity"] == "face_height"
    assert type(snapshot.from_dict(snapshot.as_dict()).predicted_components).__name__ == "Components"


def test_verification_joins_buoy_and_session_and_groups_all_dimensions():
    snapshot = make_snapshot()
    session = Session(
        raw_date=str(VALID.date()), raw_spot=SPOT.id, raw_time="08:00", rating=4,
        notes="ground swell", on=VALID.date(), hour=8, spot_id=SPOT.id,
        regime="groundswell",
    )
    observation = BuoyObservation(SPOT.id, wave(VALID, 1.0, "ndbc/44097"))
    report = verify_snapshots((snapshot,), (observation,), (session,))
    assert len(report.scored) == 1
    row = report.scored[0]
    assert row.height_error_m == pytest.approx(0.4)
    assert row.sessions == (session,)
    group = report.groups[0]
    assert (group.lead_hours, group.region, group.period_s, group.direction_deg) == (
        6.0, SPOT.region, 12.0, 165.0
    )
    assert group.size_band == snapshot.size_band
    assert group.regime == "groundswell"
    assert group.count == 1


def test_missing_observation_and_wrong_quantity_are_unscored():
    snapshot = make_snapshot()
    missing = verify_snapshots((snapshot,), (), ())
    assert len(missing.unscored) == 1
    assert missing.missing_observations[0].reason == "missing observation"

    wrong = verify_snapshots(
        (snapshot,),
        (BuoyObservation(SPOT.id, wave(VALID, 1.0), "nearshore_hs"),),
    )
    assert wrong.scored == ()
    assert wrong.unscored[0].reason == "height quantity mismatch"


def test_snapshot_requires_issue_before_valid_and_no_unproven_run():
    with pytest.raises(SnapshotError, match="issued_at"):
        replace(make_snapshot(), issued_at=VALID)
    with pytest.raises(SnapshotError, match="model_run"):
        replace(make_snapshot(), model_run="")
