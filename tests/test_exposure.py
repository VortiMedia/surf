"""Exposure geometry on synthetic coasts — offline, no land mask download."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone

import pytest

pytest.importorskip("shapely")

from surf import exposure as ex


def land_mask(*polygons: list[list[float]]) -> ex.LandMask:
    document = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Polygon", "coordinates": [ring]}}
            for ring in polygons
        ],
    }
    return ex.LandMask(
        tuple(ex._polygons(document)), "synthetic", "ok", datetime.now(timezone.utc)
    )


def ring(lon0: float, lat0: float, lon1: float, lat1: float) -> list[list[float]]:
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


COAST = {
    "type": "Feature",
    "properties": {},
    "geometry": {"type": "LineString", "coordinates": [[-0.4, 0.0], [0.4, 0.0]]},
}
# Land fills everything north of the coastline: the sea is to the south.
MAINLAND = ring(-2.0, 0.0, 2.0, 2.0)


def test_south_facing_coast_is_fully_exposed_to_a_south_swell():
    result = ex.compute(COAST, 180.0, land_mask(MAINLAND))
    assert result.segments
    assert result.dropped_ambiguous == 0
    for segment in result.segments:
        assert segment.normal_deg == pytest.approx(180.0, abs=1.0)
        assert segment.exposure > 0.99
        assert segment.band == "green"


def test_the_same_coast_sees_nothing_of_a_north_swell():
    result = ex.compute(COAST, 0.0, land_mask(MAINLAND))
    assert result.segments
    for segment in result.segments:
        assert segment.facing == pytest.approx(0.0, abs=1e-9)
        assert segment.exposure == pytest.approx(0.0, abs=1e-9)
        assert segment.band == "red"


def test_a_landmass_offshore_shadows_the_segments_behind_it():
    # An island 28 km offshore, wide enough to cover the whole +/-15 fan of the
    # coast directly behind it and none of the coast well to the east.
    island = ring(-0.15, -0.30, 0.15, -0.25)
    result = ex.compute(COAST, 180.0, land_mask(MAINLAND, island))
    behind = [s for s in result.segments if -0.05 <= s.mid[0] <= 0.05]
    clear = [s for s in result.segments if s.mid[0] > 0.25]
    assert behind and clear
    assert max(s.exposure for s in behind) == pytest.approx(0.0, abs=1e-9)
    assert max(s.facing for s in behind) > 0.99   # it faces the swell; land hides it
    assert min(s.exposure for s in clear) > 0.99


def test_bands_and_colours_follow_the_stated_thresholds():
    assert ex.band_of(1.00)[0] == "green"
    assert ex.band_of(0.70)[0] == "green"
    assert ex.band_of(0.69)[0] == "yellow"
    assert ex.band_of(0.40)[0] == "yellow"
    assert ex.band_of(0.39)[0] == "orange"
    assert ex.band_of(0.20)[0] == "orange"
    assert ex.band_of(0.19)[0] == "red"
    assert ex.band_of(0.00)[0] == "red"


def test_kmz_is_a_zip_holding_styled_kml_with_its_provenance(tmp_path):
    result = ex.compute(COAST, 180.0, land_mask(MAINLAND))
    path = ex.write_kmz(result, tmp_path / "south.kmz")
    with zipfile.ZipFile(path) as archive:
        kml = archive.read("doc.kml").decode("utf-8")
    assert kml.startswith("<?xml")
    assert '<Style id="exposure-green">' in kml
    assert "ff00ff00" in kml
    assert "land=synthetic:ok" in kml and "computed_at=" in kml
    assert kml.count("<Placemark>") == len(result.segments)


def test_a_missing_land_mask_is_an_error_not_a_guess(tmp_path):
    with pytest.raises(ex.ExposureError):
        ex.load_land(tmp_path / "nope.geojson")
    with pytest.raises(ex.ExposureError):
        ex.compute(COAST, 180.0, land_mask(ring(50.0, 50.0, 51.0, 51.0)))


def test_cli_writes_a_kmz_through_the_subcommand(tmp_path, capsys):
    from surf import cli

    coast = tmp_path / "coast.geojson"
    coast.write_text(json.dumps(COAST))
    land = tmp_path / "land.geojson"
    land.write_text(json.dumps({
        "type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [MAINLAND]},
    }))
    out = tmp_path / "south.kmz"

    code = cli.main([
        "exposure", str(coast), "--swell", "180",
        "--output", str(out), "--land", str(land),
    ])
    assert code == 0
    assert zipfile.is_zipfile(out)
    printed = capsys.readouterr().out
    assert "green=" in printed and "land=" not in printed.split("\n")[0]
