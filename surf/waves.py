from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

FEET_PER_METRE = 3.280839895
KNOTS_PER_MPS = 1.943844492
GRAVITY = 9.80665


def m_to_ft(metres: float) -> float:
    return metres * FEET_PER_METRE


def mps_to_kt(mps: float) -> float:
    return mps * KNOTS_PER_MPS


def normalise_bearing(deg: float) -> float:
    return deg % 360.0


def angle_between(a: float, b: float) -> float:
    """Smallest absolute separation between two bearings, in [0, 180]."""
    d = abs(normalise_bearing(a) - normalise_bearing(b)) % 360.0
    return 360.0 - d if d > 180.0 else d


def signed_angle(frm: float, to: float) -> float:
    """Signed turn from `frm` to `to`, in (-180, 180]. Positive is clockwise."""
    d = (normalise_bearing(to) - normalise_bearing(frm) + 180.0) % 360.0 - 180.0
    return d + 360.0 if d <= -180.0 else d


def deep_water_wavelength(period_s: float) -> float:
    """L0 = g T^2 / 2pi, metres. The 1.56*T^2 rule, exactly."""
    return GRAVITY * period_s * period_s / (2.0 * math.pi)


def deep_water_celerity(period_s: float) -> float:
    """Phase speed in deep water, m/s."""
    return GRAVITY * period_s / (2.0 * math.pi)


@dataclass(frozen=True)
class SwellPartition:
    height_m: float          # significant height
    period_s: float
    direction_deg: float     # where the swell comes FROM, degrees true
    kind: str = "swell"      # "swell" | "windwave" | "total"

    @property
    def energy(self) -> float:
        """H^2 T, the deep-water power proxy. Not a rating."""
        return self.height_m * self.height_m * self.period_s


@dataclass(frozen=True)
class Wind:
    speed_mps: float
    direction_deg: float  # blowing FROM, degrees true


@dataclass(frozen=True)
class TidePoint:
    time: datetime
    height_m: float
    stage: str = ""  # "rising" | "falling" | "high" | "low"


@dataclass(frozen=True)
class WaveField:
    time: datetime
    partitions: tuple[SwellPartition, ...] = ()
    wind: Wind | None = None
    total_height_m: float | None = None
    total_period_s: float | None = None
    model: str = ""

    @property
    def primary(self) -> SwellPartition | None:
        """The most energetic swell train, ignoring wind waves unless that is all there is."""
        swells = [p for p in self.partitions if p.kind != "windwave"] or list(self.partitions)
        return max(swells, key=lambda p: p.energy, default=None)


@dataclass(frozen=True)
class Forecast:
    spot_id: str
    model: str
    hours: tuple[WaveField, ...] = field(default_factory=tuple)
