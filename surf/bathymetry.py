from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .sources import Http, Reading, SourceDown, explain, now
from .spots import Spot

NCEI_IMAGE_SERVER = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/ImageServer"
)

EARTH_RADIUS_M = 6_371_008.8

# getSamples puts the point list in the query string, so URL length binds well
# before the server's sample cap. 120 points at 25 m is 3 km of shoreface.
MAX_POINTS = 120


@dataclass(frozen=True)
class Sample:
    """One sounding. `elevation_m` is None where the mosaic has no data — kept
    as a hole rather than interpolated. `resolution_m` is the DEM grid spacing.
    """

    distance_m: float
    lat: float
    lon: float
    elevation_m: float | None
    resolution_m: float | None


def destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Point `distance_m` from (lat, lon) along `bearing_deg` true."""
    # Flat-earth on a sphere: over the ~3 km profiles here the error against a
    # full geodesic is centimetres, far below the 3 m DEM cell being sampled.
    theta = math.radians(bearing_deg)
    dlat = (distance_m * math.cos(theta)) / EARTH_RADIUS_M
    dlon = (distance_m * math.sin(theta)) / (EARTH_RADIUS_M * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def _resolution_to_m(resolution_deg: float | None, lat: float) -> float | None:
    """getSamples reports resolution in the request's units, i.e. degrees."""
    # Converted along the meridian, the conservative direction: a parallel is
    # shorter, so the cell is never coarser than this says.
    if resolution_deg is None:
        return None
    return abs(resolution_deg) * math.pi / 180.0 * EARTH_RADIUS_M


def _value(raw: object) -> float | None:
    """getSamples returns the pixel value as a string, and NoData variously as
    null, an empty string, or the literal "NoData"."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nodata":
        return None
    try:
        return float(text)
    except ValueError:
        return None


class NceiBathymetry:
    name = "ncei"

    def __init__(self, http: Http | None = None, base_url: str = NCEI_IMAGE_SERVER):
        self._http = http or Http()
        self._base = base_url.rstrip("/")

    def preflight(self) -> Reading[bool]:
        """One sample in the deep Atlantic: the mosaic is global, so a point far
        from any coast still has to answer, and a failure means the service is
        down rather than uncovered."""
        try:
            samples = self._get_samples([(0.0, -30.0)])
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", now(), note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", now(), note=explain(exc))
        alive = bool(samples) and samples[0][0] is not None
        return Reading(
            alive,
            self.name,
            "ok" if alive else "degraded",
            now(),
            note="" if alive else "getSamples answered with no value",
        )

    def profile(self, spot: Spot, bearing_deg: float) -> Reading[tuple[float, ...]]:
        """Depths in metres, negative below sea level, near-to-far seaward.

        A bare tuple has no room for a hole, so a NoData sounding truncates the
        profile and is reported in `dropped`. Use `soundings` for the full
        picture: spacing, per-point resolution, holes.
        """
        reading = self.soundings(spot, bearing_deg)
        if reading.value is None:
            return Reading(
                None, reading.source, reading.status, reading.fetched_at,
                note=reading.note, dropped=reading.dropped,
            )
        depths: list[float] = []
        for s in reading.value:
            if s.elevation_m is None:
                break
            depths.append(s.elevation_m)
        dropped = reading.dropped
        status = reading.status
        if len(depths) < len(reading.value):
            dropped = dropped + (f"{len(reading.value) - len(depths)} soundings after first NoData",)
            status = "degraded"
        return Reading(
            tuple(depths), reading.source, status, reading.fetched_at,
            note=reading.note, dropped=dropped,
        )

    def soundings(
        self,
        spot: Spot,
        bearing_deg: float,
        *,
        spacing_m: float = 25.0,
        count: int = 60,
        start_m: float = 0.0,
    ) -> Reading[tuple[Sample, ...]]:
        """The profile with its metadata: distance, position, elevation and the
        DEM resolution each point came from.

        Starts at the spot coordinate, normally on the beach, so the shoreline
        crossing lands inside the profile instead of being assumed.
        """
        count = min(count, MAX_POINTS)
        points = [
            destination(spot.lat, spot.lon, bearing_deg, start_m + i * spacing_m)
            for i in range(count)
        ]
        try:
            values = self._get_samples(points)
        except SourceDown as exc:
            return Reading(None, self.name, "skipped", now(), note=str(exc))
        except Exception as exc:
            return Reading(None, self.name, "failed", now(), note=explain(exc))

        samples = tuple(
            Sample(
                distance_m=start_m + i * spacing_m,
                lat=points[i][0],
                lon=points[i][1],
                elevation_m=values[i][0] if i < len(values) else None,
                resolution_m=values[i][1] if i < len(values) else None,
            )
            for i in range(count)
        )
        holes = sum(1 for s in samples if s.elevation_m is None)
        dropped: tuple[str, ...] = ()
        status = "ok"
        if holes:
            dropped += (f"{holes} NoData soundings",)
            status = "degraded"
        if holes == count:
            return Reading(
                None, self.name, "failed", now(),
                note=f"no DEM coverage along {bearing_deg:.0f} deg from {spot.id}",
                dropped=dropped,
            )
        res = next((s.resolution_m for s in samples if s.resolution_m), None)
        note = f"{spacing_m:.0f} m spacing"
        if res:
            note += f", DEM cell ~{res:.0f} m"
        return Reading(samples, self.name, status, now(), note=note, dropped=dropped)

    def _get_samples(self, points: list[tuple[float, float]]) -> list[tuple[float | None, float | None]]:
        """(elevation_m, resolution_m) per point, in request order."""
        geometry = {
            "points": [[lon, lat] for lat, lon in points],
            "spatialReference": {"wkid": 4326},
        }
        r = self._http.get(
            self.name,
            f"{self._base}/getSamples",
            params={
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": "esriGeometryMultipoint",
                "returnFirstValueOnly": "true",
                "f": "json",
            },
        )
        body = r.json()
        if "error" in body:
            raise RuntimeError(f"NCEI: {body['error'].get('message', body['error'])}")
        out: list[tuple[float | None, float | None]] = [(None, None)] * len(points)
        for s in body.get("samples", []):
            # locationId indexes the request; the server may reorder or omit.
            idx = s.get("locationId")
            if not isinstance(idx, int) or not 0 <= idx < len(points):
                continue
            out[idx] = (
                _value(s.get("value")),
                _resolution_to_m(s.get("resolution"), points[idx][0]),
            )
        return out
