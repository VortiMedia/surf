"""Offline static-geometry imagery-screen tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from surf import cli
from surf.imagery import ImageryFrame, review_candidate
from surf.terrain import TerrainObject, TerrainScan, save_terrain_cache, terrain_cache_path
from surf.spots import SpotBook


UTC = timezone.utc
WHEN = datetime(2026, 9, 3, tzinfo=UTC)


def candidate() -> TerrainObject:
    return TerrainObject(
        object_type="bank/reef", lat=41.055, lon=-71.045, cells=5,
        relief_m=2.1, resolution_m=3.0, vertical_datum="unknown datum",
        smoothing_survives=True, resolution_survives=True,
    )


def scan() -> TerrainScan:
    return TerrainScan(
        "test-zone-cell-0", "fixture-bathymetry", "ok", WHEN, 3.0,
        "unknown datum", (candidate(),),
    )


def frame(candidate_key: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "candidate": candidate_key,
        "source": "sentinel-2",
        "resolution_m": 10.0,
        "captured_at": "2026-08-12",
        "cloud_free": True,
        "georeferenced": True,
        "measurements_m": {"reef_width_m": 84.0, "channel_width_m": 31.5},
        "usable_line": True,
    }
    result.update(overrides)
    return result


def test_static_geometry_keep_records_metres_source_resolution_and_date() -> None:
    key = "test-zone-cell-0:0"
    review = review_candidate(key, candidate(), frames_from([frame(key)]))
    assert review.decision == "kept"
    assert review.source == "sentinel-2"
    assert review.resolution_m == 10.0
    assert review.capture_dates == ("2026-08-12",)
    assert dict(review.measurements_m)["reef_width_m"] == 84.0
    assert review.status == "kept"
    assert "wave" not in review.note.lower()


def test_rejected_and_unresolvable_are_distinct() -> None:
    key = "test-zone-cell-0:0"
    rejected = review_candidate(key, candidate(), frames_from([frame(key, usable_line=False)]))
    unresolvable = review_candidate(key, candidate(), frames_from([frame(key, cloud_free=False)]))
    assert rejected.decision == "rejected"
    assert unresolvable.decision == "unresolvable"
    assert rejected.decision != unresolvable.decision
    assert "wave" not in unresolvable.note.lower()


def test_non_georeferenced_frame_is_unresolvable() -> None:
    key = "test-zone-cell-0:0"
    result = review_candidate(key, candidate(), frames_from([frame(key, georeferenced=False)]))
    assert result.decision == "unresolvable"
    assert result.resolution_m is None


def test_cli_screens_only_cached_terrain_candidates_and_writes_gitignored_area(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SURF_DATA", str(tmp_path))
    bbox = (41.0, -71.1, 41.1, -71.0)
    save_terrain_cache(terrain_cache_path("test-zone", bbox), "test-zone", (scan(),), "fixture-bathymetry", "ok", WHEN)
    manifest = tmp_path / "frames.json"
    manifest.write_text(json.dumps({"frames": [frame("test-zone-cell-0:0")]}) + "\n", encoding="utf-8")

    console = cli.Console(book=SpotBook(()), clock=lambda: WHEN)
    code = cli.main([
        "imagery", "--zone", "test-zone", "--bbox", "41.0,-71.1,41.1,-71.0",
        "--frames", str(manifest),
    ], console=console)

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "kept" in out
    assert "sentinel-2" in out
    assert "10.0 m" in out
    assert "2026-08-12" in out
    assert "static geometry only" in out
    assert (tmp_path / "imagery" / "imagery-test-zone-41.0000--71.1000-41.1000--71.0000.json").exists()


def frames_from(rows: list[dict[str, object]]) -> tuple[ImageryFrame, ...]:
    return tuple(
        ImageryFrame(
            candidate=str(row["candidate"]), source=str(row["source"]),
            resolution_m=float(row["resolution_m"]), captured_at=str(row["captured_at"]),
            cloud_free=bool(row["cloud_free"]), georeferenced=bool(row["georeferenced"]),
            measurements_m=tuple((str(key), float(value)) for key, value in row["measurements_m"].items()),  # type: ignore[union-attr]
            usable_line=row.get("usable_line"),
        )
        for row in rows
    )
