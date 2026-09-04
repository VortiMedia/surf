"""Offline tests for the joint seasonal climate screen."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from dataclasses import replace

from surf import cli
from surf.climate import (
    ClimateSample,
    OpenMeteoClimate,
    build_result,
    load_cache,
    overlap,
    save_cache,
)
from surf.spots import Derived, Spot, SpotBook
from surf.sources import Reading

UTC = timezone.utc


def spot(zone: str | None = "test-zone") -> Spot:
    return Spot(
        id="test",
        name="Test",
        lat=41.0,
        lon=-71.0,
        shore_normal=Derived(180.0, "manual", "fixture"),
        beach_slope=Derived(0.02, "derived", "fixture"),
        offshore_lat=40.9,
        offshore_lon=-71.0,
        region="US-RI",
        timezone="America/New_York",
        zone=zone,
    )


def sample(at: datetime, *, wind_direction: float = 0.0, swell_height: float = 1.5) -> ClimateSample:
    return ClimateSample(at, swell_height, 12.0, 180.0, 6.0, wind_direction)


def test_overlap_joins_complete_hours_and_reports_events_local_hours_and_years() -> None:
    samples = (
        sample(datetime(2023, 1, 1, 0, tzinfo=UTC)),
        sample(datetime(2023, 1, 1, 1, tzinfo=UTC)),
        sample(datetime(2023, 1, 1, 10, tzinfo=UTC), wind_direction=180.0),
        sample(datetime(2024, 1, 2, 0, tzinfo=UTC)),
    )
    result = overlap(spot(), samples, date(2023, 1, 1), date(2024, 1, 2))
    assert result.shared_hours == 4
    assert result.overlap_hours == 3
    assert result.days == 2
    assert result.independent_events == 2
    assert result.event_durations_hours == (2.0, 1.0)
    assert result.local_hours == ((19, 2), (20, 1))
    assert result.years_with_event == (2023, 2024)
    assert result.years_total == 2
    assert result.fraction_years == 1.0


def test_overlap_rejects_a_swell_only_season() -> None:
    samples = (
        sample(datetime(2024, 7, 1, 0, tzinfo=UTC), wind_direction=180.0),
        sample(datetime(2024, 7, 1, 1, tzinfo=UTC), wind_direction=180.0),
    )
    result = overlap(spot(), samples, date(2024, 7, 1), date(2024, 7, 31))
    assert result.shared_hours == 2
    assert result.overlap_hours == 0
    assert result.rejected
    assert result.independent_events == 0
    assert result.fraction_years == 0.0


def test_calm_wind_passes_and_stronger_wind_uses_the_sixty_degree_rule() -> None:
    calm = ClimateSample(datetime(2024, 7, 1, tzinfo=UTC), 1.5, 12.0, 180.0, 0.5, 180.0)
    crossshore = ClimateSample(datetime(2024, 7, 1, tzinfo=UTC), 1.5, 12.0, 180.0, 8.0, 50.0)
    onshore = ClimateSample(datetime(2024, 7, 1, tzinfo=UTC), 1.5, 12.0, 180.0, 8.0, 100.0)
    result = overlap(spot(), (calm, crossshore, onshore), date(2024, 7, 1), date(2024, 7, 1))
    assert result.overlap_hours == 2


def test_cache_round_trip_preserves_source_status_and_fetch_time(tmp_path) -> None:
    s = spot()
    samples = (sample(datetime(2024, 1, 1, tzinfo=UTC)),)
    fetched = datetime(2026, 9, 3, 12, tzinfo=UTC)
    result = build_result(
        "test-zone", (s,), {s.id: samples}, date(2024, 1, 1), date(2024, 1, 1),
        source="fixture", status="degraded", fetched_at=fetched,
    )
    path = tmp_path / "climate.json"
    save_cache(path, result, {s.id: samples})
    loaded = load_cache(path, SpotBook((s,)))
    assert loaded.source == "fixture"
    assert loaded.status == "degraded"
    assert loaded.fetched_at == fetched
    assert loaded.cells[0].overlap_hours == 1


class FakeClimate:
    name = "fixture-climate"

    def __init__(self, rows: dict[str, tuple[ClimateSample, ...]]):
        self.rows = rows
        self.calls: list[str] = []

    def cell(self, spot: Spot, start: date, end: date) -> Reading[tuple[ClimateSample, ...]]:
        self.calls.append(spot.id)
        return Reading(self.rows.get(spot.id, ()), self.name, "ok", datetime(2026, 9, 3, tzinfo=UTC))


def test_cli_climate_runs_each_zone_cell_and_reports_rejection(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SURF_DATA", str(tmp_path))
    s = spot()
    same_cell = replace(
        s,
        id="test-2",
        name="Test 2",
        lat=s.lat + 0.02,
        lon=s.lon + 0.02,
        offshore_lat=s.offshore_lat + 0.1,
        offshore_lon=s.offshore_lon + 0.1,
    )
    source = FakeClimate({s.id: (
        sample(datetime(2024, 7, 1, 0, tzinfo=UTC), wind_direction=180.0),
    )})
    console = cli.Console(book=SpotBook((s, same_cell)), climate_source=source)
    code = cli.main(
        ["climate", "--zone", "test-zone", "--start", "2024-07-01", "--end", "2024-07-31", "--refresh"],
        console=console,
    )
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert source.calls == ["test"]
    assert "shared timestamps  1 hours" in out
    assert "REJECTED for season" in out
    assert "terrain shelter unverified" in out
    assert (tmp_path / "climate" / "test-zone-2024-07-01-2024-07-31.json").exists()


def test_open_meteo_climate_only_joins_exact_matching_timestamps() -> None:
    calls = []
    class Http:
        def get_json(self, source, url, params):
            calls.append((url, params))
            if "marine-api" in url:
                return {"hourly": {
                    "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
                    "wave_height": [1.5, 1.5],
                    "wave_period": [12, 12],
                    "wave_direction": [180, 180],
                }}
            return {"hourly": {
                "time": ["2024-01-01T01:00", "2024-01-01T02:00"],
                "wind_speed_10m": [6, 6],
                "wind_direction_10m": [0, 0],
            }}

    reading = OpenMeteoClimate(Http()).cell(spot(), date(2024, 1, 1), date(2024, 1, 1))
    assert reading.status == "degraded"
    assert calls[0][1]["models"] == "era5_ocean"
    assert "total wave" in reading.dropped[0]
    assert [row.time for row in reading.value] == [datetime(2024, 1, 1, 1, tzinfo=UTC)]
