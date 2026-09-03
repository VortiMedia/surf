from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .spots import Derived, Spot
from .waves import angle_between, normalise_bearing

# Degrees of Gaussian angular half-width gained per second of period: ~64 deg wide
# at 8 s, ~128 deg at 16 s.
REACH_DEG_PER_SECOND = 8.0

# The diffracted path beyond the open-water window decays this much faster than the
# direct one, so swell from behind the land arrives at fractions of a percent
# rather than at exactly zero.
SHADOW_FRACTION = 0.25

# Blended in rather than clipped on, so no direction is ever reported as impossible
# when it is merely unlikely.
MIN_TRANSMISSION = 1e-5

# Slope the reach constant was written against. A gentler shelf refracts over a
# longer path and therefore bends further; a steep one bends less.
SLOPE_REF = 0.03
_SLOPE_FACTOR_RANGE = (0.7, 1.4)

# Periods outside this are model noise, not swell. Clamped for the reach term only;
# the requested period is still what the caller asked about.
_PERIOD_RANGE = (2.0, 30.0)
_REACH_RANGE = (15.0, 220.0)

_DEFAULT_EXPOSURE = Derived(90.0, "default", "open beach; no headland surveyed")


@dataclass(frozen=True)
class TransmissionTable:
    """`rows[i][j]` is the transmission for `directions[i]` at `periods[j]`."""

    spot_id: str
    method: str
    directions: tuple[float, ...]
    periods: tuple[float, ...]
    rows: tuple[tuple[float, ...], ...]

    def at(self, direction_deg: float, period_s: float) -> float:
        return self.rows[self.directions.index(direction_deg)][self.periods.index(period_s)]


@dataclass(frozen=True)
class Response:
    """Closed-form directional response for one spot.

    Geometry arrives as `Derived` so provenance travels with the answer. `exposure`
    is the half-width in degrees either side of the shore normal of open water in
    front of the break: 90 is an unobstructed beach.
    """

    spot_id: str
    shore_normal: Derived
    beach_slope: Derived
    exposure: Derived = _DEFAULT_EXPOSURE
    reach_deg_per_second: float = REACH_DEG_PER_SECOND
    shadow_fraction: float = SHADOW_FRACTION
    method: str = "analytic"

    def __post_init__(self) -> None:
        if not 0.0 < self.exposure.value <= 90.0:
            raise ValueError(f"exposure half-width must be in (0, 90], got {self.exposure.value}")
        if self.beach_slope.value <= 0.0:
            raise ValueError(f"beach slope must be positive, got {self.beach_slope.value}")
        if self.reach_deg_per_second <= 0.0:
            raise ValueError("reach_deg_per_second must be positive")

    @classmethod
    def for_spot(cls, spot: Spot, exposure: Derived | None = None) -> Response:
        # exposure is passed in rather than read off the spot: no surveyed field for
        # it exists, and None takes the labelled default rather than guessing.
        return cls(
            spot_id=spot.id,
            shore_normal=spot.shore_normal,
            beach_slope=spot.beach_slope,
            exposure=exposure or _DEFAULT_EXPOSURE,
        )

    def with_constants(
        self, reach_deg_per_second: float | None = None, shadow_fraction: float | None = None
    ) -> Response:
        return replace(
            self,
            reach_deg_per_second=(
                self.reach_deg_per_second if reach_deg_per_second is None else reach_deg_per_second
            ),
            shadow_fraction=self.shadow_fraction if shadow_fraction is None else shadow_fraction,
        )

    def angular_reach_deg(self, period_s: float) -> float:
        """Gaussian half-width of the angular response. Linear in period because
        bending distance scales with wavelength, scaled by the shelf slope."""
        period = _clamp(period_s, *_PERIOD_RANGE)
        slope_factor = _clamp(
            (SLOPE_REF / self.beach_slope.value) ** 0.25, *_SLOPE_FACTOR_RANGE
        )
        return _clamp(self.reach_deg_per_second * period * slope_factor, *_REACH_RANGE)

    def off_axis_deg(self, direction_deg: float) -> float:
        """Separation between where the swell comes FROM and the direction the beach
        faces, in [0, 180]. 0 is dead on the nose."""
        return angle_between(normalise_bearing(direction_deg), self.shore_normal.value)

    def transmission(self, direction_deg: float, period_s: float) -> float:
        """Fraction of offshore energy reaching the break, 0..1.

        Dead-on swell transmits 1.0 at any period: period buys angular reach, not
        free energy, which keeps this from double-counting period against H^2 T.
        """
        if period_s <= 0.0:
            raise ValueError(f"period must be positive, got {period_s}")

        alpha = self.off_axis_deg(direction_deg)
        reach = self.angular_reach_deg(period_s)

        refraction = math.exp(-((alpha / reach) ** 2))

        beyond = max(0.0, alpha - self.exposure.value)
        diffraction = math.exp(-beyond / (self.shadow_fraction * reach))

        return MIN_TRANSMISSION + (1.0 - MIN_TRANSMISSION) * refraction * diffraction

    def table(
        self,
        directions: tuple[float, ...] | None = None,
        periods: tuple[float, ...] = (6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0),
    ) -> TransmissionTable:
        dirs = directions if directions is not None else tuple(float(d) for d in range(0, 360, 10))
        rows = tuple(
            tuple(self.transmission(d, p) for p in periods) for d in dirs
        )
        return TransmissionTable(self.spot_id, self.method, dirs, periods, rows)

    @property
    def basis(self) -> str:
        """One line saying what this matrix was built on, provenance included."""
        return (
            f"analytic: reach {self.reach_deg_per_second:.1f}deg/s of period"
            f", normal {self.shore_normal.value:.0f}deg ({self.shore_normal.provenance})"
            f", slope {self.beach_slope.value:.3f} ({self.beach_slope.provenance})"
            f", open-water half-width {self.exposure.value:.0f}deg ({self.exposure.provenance})"
        )


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x
