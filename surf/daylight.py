from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

# Civil twilight, not sunrise: it is rideable before the sun clears the horizon
# and after it drops below, and -6 deg is roughly where you stop reading the water.
TWILIGHT_DEG = -6.0


@dataclass(frozen=True)
class Daylight:
    """Usable-light window for one spot on one day, in UTC."""

    first_light: datetime | None
    last_light: datetime | None
    note: str = ""

    def contains(self, moment: datetime) -> bool:
        # Polar days have no sunrise or sunset at all; admit everything rather
        # than silently excluding a whole latitude.
        if self.first_light is None or self.last_light is None:
            return True
        return self.first_light <= moment <= self.last_light


def _solar_declination(day_fraction: float) -> tuple[float, float]:
    """(declination in radians, equation of time in minutes) for a fractional year angle."""
    g = 2.0 * math.pi * day_fraction
    decl = (
        0.006918
        - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g) + 0.001480 * math.sin(3 * g)
    )
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g)
    )
    return decl, eqtime


def daylight(lat: float, lon: float, on: date, *, horizon_deg: float = TWILIGHT_DEG) -> Daylight:
    """First and last usable light at a coordinate, in UTC."""
    n = on.timetuple().tm_yday
    decl, eqtime = _solar_declination((n - 1) / 365.0)
    phi = math.radians(lat)
    zenith = math.radians(90.0 - horizon_deg)

    cos_ha = (math.cos(zenith) - math.sin(phi) * math.sin(decl)) / (
        math.cos(phi) * math.cos(decl)
    )
    if cos_ha > 1.0:
        return Daylight(None, None, "sun never rises here on this date")
    if cos_ha < -1.0:
        return Daylight(None, None, "sun never sets here on this date")

    # 4 minutes of rotation per degree of longitude or hour angle.
    ha = math.degrees(math.acos(cos_ha))
    noon_min = 720.0 - 4.0 * lon - eqtime
    midnight = datetime(on.year, on.month, on.day, tzinfo=timezone.utc)
    return Daylight(
        midnight + timedelta(minutes=noon_min - 4.0 * ha),
        midnight + timedelta(minutes=noon_min + 4.0 * ha),
    )
