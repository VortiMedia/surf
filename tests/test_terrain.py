"""Offline terrain-object scan tests."""

from __future__ import annotations

from datetime import datetime, timezone

from surf import cli
from surf.bathymetry import BathymetryGrid, Sample
from surf.terrain import COARSE_GRID_M, scan_grid
from surf.spots import Derived, Spot, SpotBook
from surf.sources import Reading

UTC = timezone.utc


def spot() -> Spot:
    return Spot(
        id="candidate", name="Candidate", lat=41.0, lon=-71.0,
        shore_normal=Derived(180.0, "manual", "fixture"),
        beach_slope=Derived(0.02, "derived", "fixture"),
        offshore_lat=40.9, offshore_lon=-71.0, region="US-RI",
    )


def grid(resolution: float = 3.0) -> BathymetryGrid:
    cells = []
    for row in range(7):
        for col in range(7):
            bump = 2.0 if 2 <= row <= 4 and 2 <= col <= 4 else 0.0
            cells.append(Sample(
                distance_m=row * 50.0, lat=41.0 + row / 10000, lon=-71.0 + col / 10000,
                elevation_m=-10.0 - row * 0.1 - col * 0.1 + bump,
                resolution_m=resolution,
            ))
    return BathymetryGrid(tuple(cells), 7, 7, resolution, "unknown datum (fixture)")


def test_scan_requires_multiple_cells_and_perturbation_stability() -> None:
    result = scan_grid(spot(), grid())
    assert result.status == "ok"
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate.cells >= 4
    assert candidate.resolution_m == 3.0
    assert candidate.vertical_datum == "unknown datum (fixture)"
    assert candidate.smoothing_survives and candidate.resolution_survives
    assert "terrain object" in candidate.label
    assert "spots.tsv" in candidate.promotion


def test_coarse_grid_reports_no_gradient_without_interpolation() -> None:
    result = scan_grid(spot(), grid(COARSE_GRID_M))
    assert result.status == "degraded"
    assert result.candidates == ()
    assert "no gradient" in result.note


def test_land_cliff_is_not_reported_as_underwater_terrain() -> None:
    cells = []
    for row in range(7):
        for col in range(7):
            cells.append(Sample(
                distance_m=row * 50.0,
                lat=41.0 + row / 10000,
                lon=-71.0 + col / 10000,
                elevation_m=10.0 if col < 3 else -10.0,
                resolution_m=3.0,
            ))
    land_edge = BathymetryGrid(
        tuple(cells), 7, 7, 3.0, "unknown datum (fixture)"
    )

    result = scan_grid(spot(), land_edge)

    assert result.candidates == ()


def test_cli_reports_candidates_as_terrain_objects_and_caches_them(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SURF_DATA", str(tmp_path))

    class Source:
        name = "fixture-bathymetry"

        calls = []

        def grid(self, spot, *, radius_m, spacing_m, rows, cols):
            self.calls.append(spot)
            return Reading(grid(), self.name, "ok", datetime(2026, 9, 3, tzinfo=UTC))

    source = Source()
    console = cli.Console(book=SpotBook(()), terrain_source=source)
    code = cli.main(["terrain", "--zone", "test-zone", "--bbox", "41.0,-71.1,41.1,-71.0", "--step", "0.1", "--refresh"], console=console)
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "terrain object" in out
    assert "3.0 m" in out
    assert "unknown datum (fixture)" in out
    assert "not a surf spot" in out
    assert "41." in out and "-70." in out
    assert source.calls and source.calls[0].id == "test-zone-cell-0"
    assert source.calls[0].lat == 41.05 and source.calls[0].lon == -71.05
    assert (tmp_path / "climate" / "terrain-test-zone-41.0000--71.1000-41.1000--71.0000.json").exists()
