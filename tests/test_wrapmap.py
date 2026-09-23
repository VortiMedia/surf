"""The wrap map: does a headland actually cast a shadow, and does the
gradient light up where the coast bends rather than where it is straight."""

from __future__ import annotations

import json
import math
import zipfile
from datetime import datetime, timezone

import pytest

pytest.importorskip("shapely")
pytest.importorskip("matplotlib")
pytest.importorskip("PIL")

import numpy as np
from shapely.geometry import Polygon

from surf.exposure import ExposureError, LandMask
from surf import wrapmap


def _mask(*polygons: Polygon) -> LandMask:
    return LandMask(
        polygons=tuple(polygons),
        source="test",
        status="ok",
        fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _headland() -> LandMask:
    """Land south of y=0 with a finger poking north — a crude point break."""
    coast = Polygon([(-0.20, -0.20), (0.20, -0.20), (0.20, 0.0), (-0.20, 0.0)])
    finger = Polygon([(-0.004, 0.0), (0.004, 0.0), (0.004, 0.03), (-0.004, 0.03)])
    return _mask(coast, finger)


def test_a_headland_shadows_the_water_behind_it():
    """Swell from the WNW, so the finger's lee falls in open water east of it
    rather than on the dry land south of the shore."""
    field = wrapmap.shelter_field(
        _headland(), 300.0, (-0.05, -0.02, 0.05, 0.02), reach_m=8_000
    )
    values = field.values
    assert np.nanmax(values) > 0.9, "open water should be nearly fully exposed"
    assert np.nanmin(values) < 0.5, "the lee of the finger should be sheltered"


def test_the_shadow_moves_when_the_swell_swings():
    box = (-0.05, -0.02, 0.05, 0.02)
    from_north = wrapmap.shelter_field(_headland(), 0.0, box, reach_m=8_000)
    from_east = wrapmap.shelter_field(_headland(), 60.0, box, reach_m=8_000)
    a = np.nan_to_num(from_north.values, nan=1.0)
    b = np.nan_to_num(from_east.values, nan=1.0)
    assert not np.allclose(a, b), "a different swell direction must move the shadow"


def test_spreading_softens_the_shadow_edge():
    """A spread swell must produce a penumbra, not a hard geometric edge."""
    field = wrapmap.shelter_field(
        _headland(), 0.0, (-0.05, -0.02, 0.05, 0.02), reach_m=8_000
    )
    values = field.values[np.isfinite(field.values)]
    partial = ((values > 0.05) & (values < 0.95)).sum()
    assert partial > 0, "no partially-sheltered water: the fan is not spreading"


def test_no_land_in_reach_is_an_error_not_a_flat_field():
    empty = _mask(Polygon([(50.0, 50.0), (50.1, 50.0), (50.1, 50.1), (50.0, 50.1)]))
    with pytest.raises(ExposureError):
        wrapmap.shelter_field(empty, 0.0, (-0.05, -0.02, 0.05, 0.02), reach_m=8_000)


def test_a_degenerate_box_is_refused():
    with pytest.raises(ExposureError):
        wrapmap.shelter_field(_headland(), 0.0, (0.0, 0.0, 0.0, 0.0))


def test_wrap_is_higher_at_the_bend_than_along_straight_coast():
    """The gradient must pick the corner, not the wall."""
    coast = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "LineString",
                # straight east-west shore, then a hard turn south
                "coordinates": (
                    [[-0.05 + 0.002 * i, 0.0] for i in range(30)]
                    + [[0.01, -0.002 * i] for i in range(1, 25)]
                ),
            },
        }],
    }
    segments, _ = wrapmap.wrap_segments(coast, 0.0, _headland(), smooth=1)
    assert segments, "expected segments"
    corner = [s for s in segments if abs(s.mid[0] - 0.01) < 0.004 and s.mid[1] > -0.02]
    straight = [s for s in segments if s.mid[0] < -0.02]
    assert corner and straight
    assert max(s.wrap for s in corner) > max(s.wrap for s in straight)


def test_bands_follow_the_stated_thresholds():
    assert wrapmap.wrap_band(0.9)[0] == "hot"
    assert wrapmap.wrap_band(0.45)[0] == "strong"
    assert wrapmap.wrap_band(0.20)[0] == "some"
    assert wrapmap.wrap_band(0.0)[0] == "flat"


def test_kmz_holds_the_overlay_and_its_provenance(tmp_path):
    coast = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "LineString",
                "coordinates": [[-0.04 + 0.002 * i, 0.0] for i in range(40)],
            },
        }],
    }
    result = wrapmap.build(
        coast, 0.0, _headland(), bbox=(-0.05, -0.02, 0.05, 0.02), reach_m=8_000
    )
    out = wrapmap.write_kmz(result, tmp_path / "wrap.kmz")
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        assert names == {"doc.kml", "shelter.png"}
        kml = archive.read("doc.kml").decode()
    assert "<GroundOverlay>" in kml
    assert "shelter.png" in kml
    assert "Geometry only" in kml, "the KMZ must carry its own limits"
    assert "no bathymetry" in kml.lower() or "No bathymetry" in kml
    assert "<LatLonBox>" in kml


def test_top_setups_are_spread_out_not_clustered():
    coast = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "LineString",
                "coordinates": [[-0.04 + 0.001 * i, 0.0] for i in range(80)],
            },
        }],
    }
    result = wrapmap.build(
        coast, 0.0, _headland(), bbox=(-0.05, -0.02, 0.05, 0.02), reach_m=8_000
    )
    picked = result.top(6)
    for i, a in enumerate(picked):
        for b in picked[i + 1:]:
            assert wrapmap._metres_between(a.mid, b.mid) >= 1500.0
