"""Offline static-geometry imagery-screen tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from surf import cli
from surf.imagery import (
    ImageryFrame,
    ImageryScreen,
    deep_water_period,
    imagery_cache_path,
    review_candidate,
    save_screen,
    screen_candidates,
    screen_wave_state,
    wave_state_cache_path,
)
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


def test_wave_state_derives_period_only_from_scaled_coincident_frame() -> None:
    key = "test-zone-cell-0:0"
    static = screen_candidates((scan(),), frames_from([frame(key)]), "test-zone", WHEN)
    wave = frame(
        key, scaled=True, swell_present=True, wavelength_m=122.0,
        whitewash_fraction=0.25, wave_shape="clean A-frame",
    )
    result = screen_wave_state(static, frames_from([wave]), "test-zone", WHEN)
    review = result.reviews[0]
    assert review.decision == "observed"
    assert review.wavelength_m == 122.0
    assert review.period_s == deep_water_period(122.0)
    assert review.whitewash_fraction == 0.25
    assert review.wave_shape == "clean A-frame"
    assert review.evidence_level == "geometry-and-visual-inference"
    assert "not confirmation" in review.note


def test_wave_state_refuses_unscaled_and_separates_no_clear_from_no_swell() -> None:
    key = "test-zone-cell-0:0"
    static = screen_candidates((scan(),), frames_from([frame(key)]), "test-zone", WHEN)
    unscaled = screen_wave_state(
        static, frames_from([frame(key, swell_present=True, wavelength_m=122.0)]), "test-zone", WHEN
    ).reviews[0]
    cloudy = screen_wave_state(
        static, frames_from([frame(key, cloud_free=False, swell_present=True)]), "test-zone", WHEN
    ).reviews[0]
    no_swell = screen_wave_state(
        static, frames_from([frame(key, swell_present=False)]), "test-zone", WHEN
    ).reviews[0]
    assert unscaled.decision == "unresolvable"
    assert "unscaled" in unscaled.note
    assert cloudy.decision == "no_clear_pass_coincident_with_swell"
    assert no_swell.decision == "no_swell"


def test_wave_state_drops_candidates_that_did_not_survive_static_screen() -> None:
    key = "test-zone-cell-0:0"
    static_review = review_candidate(key, candidate(), frames_from([frame(key, usable_line=False)]))
    static = ImageryScreen("test-zone", "sentinel-2", "ok", WHEN, (static_review,))
    result = screen_wave_state(static, frames_from([frame(key, scaled=True, swell_present=True, wavelength_m=122.0)]), "test-zone", WHEN)
    assert result.reviews == ()
    assert result.dropped == (f"{key}: geometry unresolvable or rejected by static screen",)


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


def test_cli_wave_state_reads_static_cache_and_writes_separate_result(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SURF_DATA", str(tmp_path))
    bbox = (41.0, -71.1, 41.1, -71.0)
    key = "test-zone-cell-0:0"
    static = screen_candidates((scan(),), frames_from([frame(key)]), "test-zone", WHEN)
    save_screen(imagery_cache_path("test-zone", bbox), static)
    manifest = tmp_path / "wave-frames.json"
    manifest.write_text(json.dumps({"frames": [frame(
        key, scaled=True, swell_present=True, wavelength_m=122.0,
        whitewash_fraction=0.2, wave_shape="mush",
    )]}) + "\n", encoding="utf-8")
    console = cli.Console(book=SpotBook(()), clock=lambda: WHEN)
    code = cli.main([
        "wave-state", "--zone", "test-zone", "--bbox", "41.0,-71.1,41.1,-71.0",
        "--frames", str(manifest),
    ], console=console)
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "observed" in out
    assert "122 m" in out
    assert "L0 = gT^2/2pi" in out
    assert "geometry-and-visual-inference" in out
    assert (tmp_path / "imagery" / "wave-state-test-zone-41.0000--71.1000-41.1000--71.0000.json").exists()


def frames_from(rows: list[dict[str, object]]) -> tuple[ImageryFrame, ...]:
    return tuple(
        ImageryFrame(
            candidate=str(row["candidate"]), source=str(row["source"]),
            resolution_m=float(row["resolution_m"]), captured_at=str(row["captured_at"]),
            cloud_free=bool(row["cloud_free"]), georeferenced=bool(row["georeferenced"]),
            measurements_m=tuple((str(key), float(value)) for key, value in row["measurements_m"].items()),  # type: ignore[union-attr]
            usable_line=row.get("usable_line"),
            scaled=bool(row.get("scaled", False)),
            swell_present=row.get("swell_present"),
            wavelength_m=float(row["wavelength_m"]) if row.get("wavelength_m") is not None else None,
            whitewash_fraction=float(row["whitewash_fraction"]) if row.get("whitewash_fraction") is not None else None,
            wave_shape=str(row["wave_shape"]) if row.get("wave_shape") is not None else None,
        )
        for row in rows
    )
