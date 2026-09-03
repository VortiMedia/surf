from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .spots import Derived, Spot
from .waves import SwellPartition, WaveField, Wind, angle_between, deep_water_wavelength


@dataclass(frozen=True)
class Component:
    value: float          # 0..1
    basis: str
    raw: float | None = None   # the underlying physical quantity, unnormalised


@dataclass(frozen=True)
class Components:
    barrel: Component
    cleanness: Component
    size: Component
    confidence: Component

    def as_dict(self) -> dict[str, float]:
        return {
            "barrel": self.barrel.value,
            "cleanness": self.cleanness.value,
            "size": self.size.value,
            "confidence": self.confidence.value,
        }

    def ordering_key(self) -> float:
        """Crude internal sort key only; never printed as a rating."""
        return self.barrel.value * self.size.value * self.cleanness.value


# Surf-similarity band in which breakers plunge rather than spill or surge.
# Battjes (1974) publishes two bands for the same parameter: deep-water
# xi_0 = tan(beta)/sqrt(H0/L0) plunges over 0.5..3.3, breaking-height xi_b over
# 0.4..2.0. `iribarren()` is fed the offshore height, so this must be the xi_0 band.
PLUNGING_BAND: tuple[float, float] = (0.5, 3.3)

# Beach slope assumed by the steepness fallback, ~1:33. Used only when the spot has
# no measured slope, and every Component built this way says so in its basis. Never
# written back to a Spot.
NOMINAL_SLOPE = 0.030

# Wind below this is glass regardless of direction.
CALM_MPS = 1.5
# Wind at or above this expresses its direction fully.
FULL_WIND_MPS = 8.0
# Offshore wind past this starts holding waves up and then wrecking take-offs.
GALE_OFFSHORE_MPS = 12.0
STORM_OFFSHORE_MPS = 20.0
GALE_OFFSHORE_FLOOR = 0.6

# Nearshore height at which SIZE reads 0.5. Saturating, never capped: no holding
# ceiling is modelled, so bigger never scores worse here.
SIZE_HALF_M = 1.2

# One model cannot disagree with itself.
SINGLE_MODEL_CONFIDENCE = 0.4

# Spread at which each disagreement axis has burned all its confidence.
HEIGHT_CV_FULL = 0.5       # relative height spread
PERIOD_CV_FULL = 0.35      # relative period spread
DIRECTION_SPREAD_FULL = 45.0  # degrees between the extreme model directions


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def iribarren(height_m: float, period_s: float, slope: float) -> float:
    """Surf-similarity parameter xi = tan(beta) / sqrt(H / L0), deep-water form:
    H is the offshore significant height, L0 = g T^2 / 2pi.

    xi ~ H^-0.5, so at fixed slope and period this FALLS as the swell grows. That
    is the physics, not a bug: bigger belongs to SIZE, not to barrel likelihood.
    """
    if height_m <= 0.0 or period_s <= 0.0 or slope <= 0.0:
        return 0.0
    steepness = height_m / deep_water_wavelength(period_s)
    return slope / math.sqrt(steepness)


def classify_breaker(xi: float) -> str:
    low, high = PLUNGING_BAND
    if xi <= 0.0:
        return "none"
    if xi < low:
        return "spilling"
    if xi <= high:
        return "plunging"
    return "surging"


def _band_score(xi: float) -> float:
    """1.0 at the centre of the plunging band, 0.5 at its edges, decaying outside.
    Log-space because the band is multiplicative, and smooth so the edges are not
    cliffs where the physics has a slope.
    """
    if xi <= 0.0:
        return 0.0
    low, high = PLUNGING_BAND
    centre = (math.log(low) + math.log(high)) / 2.0
    half_width = (math.log(high) - math.log(low)) / 2.0
    sigma = half_width / math.sqrt(2.0 * math.log(2.0))
    z = (math.log(xi) - centre) / sigma
    return math.exp(-0.5 * z * z)


def _usable_slope(slope: Derived | None) -> bool:
    # provenance 'default' is the placeholder in the spot row, not a measurement.
    return slope is not None and slope.value > 0.0 and slope.provenance in ("derived", "manual")


def barrel(partition: SwellPartition | None, slope: Derived | None) -> Component:
    """Iribarren where a measured slope exists; otherwise the same curve at a stated
    nominal slope, so a long-period groundswell still outscores wind chop."""
    if partition is None or partition.height_m <= 0.0 or partition.period_s <= 0.0:
        return Component(0.0, "no swell energy", raw=None)

    if _usable_slope(slope):
        assert slope is not None
        xi = iribarren(partition.height_m, partition.period_s, slope.value)
        basis = (
            f"Iribarren xi={xi:.2f} ({classify_breaker(xi)}), "
            f"slope tan(beta)={slope.value:.4f} [{slope.provenance}]"
        )
        return Component(_clamp01(_band_score(xi)), basis, raw=xi)

    xi = iribarren(partition.height_m, partition.period_s, NOMINAL_SLOPE)
    steepness = partition.height_m / deep_water_wavelength(partition.period_s)
    basis = (
        f"steepness proxy H/L0={steepness:.4f} -> xi={xi:.2f} "
        f"({classify_breaker(xi)}) at assumed slope {NOMINAL_SLOPE:.3f}; "
        "no measured beach slope for this spot"
    )
    return Component(_clamp01(_band_score(xi)), basis, raw=xi)


def cleanness(wind: Wind | None, spot: Spot) -> Component:
    """Wind direction relative to the shore normal, tempered by speed. Offshore is
    the bearing wind blows FROM when it comes off the land, i.e. shore_normal + 180."""
    if wind is None:
        return Component(0.5, "no wind data — cleanness unknown, held neutral", raw=None)

    offshore = spot.offshore_wind_bearing
    off_angle = angle_between(wind.direction_deg, offshore)  # 0 = dead offshore
    directional = (1.0 + math.cos(math.radians(off_angle))) / 2.0

    strength = _clamp01((wind.speed_mps - CALM_MPS) / (FULL_WIND_MPS - CALM_MPS))
    value = 1.0 - strength * (1.0 - directional)

    note = ""
    if off_angle < 90.0 and wind.speed_mps > GALE_OFFSHORE_MPS:
        over = _clamp01(
            (wind.speed_mps - GALE_OFFSHORE_MPS) / (STORM_OFFSHORE_MPS - GALE_OFFSHORE_MPS)
        )
        value *= 1.0 - over * (1.0 - GALE_OFFSHORE_FLOOR)
        note = "; offshore gale, hard to get into"

    quarter = "offshore" if off_angle < 45 else "cross" if off_angle < 135 else "onshore"
    basis = (
        f"{wind.speed_mps:.1f} m/s from {wind.direction_deg:.0f} deg, "
        f"{off_angle:.0f} deg off the offshore bearing "
        f"({offshore:.0f} deg) — {quarter}{note}"
    )
    return Component(_clamp01(value), basis, raw=off_angle)


def _transmitted_height_m(
    partitions: Sequence[SwellPartition],
    matrix: Response | None,
) -> tuple[float, list[str]]:
    # Transmission is an energy fraction, so height scales with its square root and
    # trains combine in energy: H = sqrt(sum(H_i^2 * t_i)).
    energy = 0.0
    lines: list[str] = []
    for p in partitions:
        if p.height_m <= 0.0:
            continue
        t = 1.0 if matrix is None else _clamp01(matrix.transmission(p.direction_deg, p.period_s))
        energy += p.height_m * p.height_m * t
        lines.append(
            f"{p.height_m:.1f}m@{p.period_s:.0f}s from {p.direction_deg:.0f} deg "
            f"x{t:.2f} ({p.kind})"
        )
    return math.sqrt(energy), lines


def size(
    field: WaveField | None,
    matrix: Response | None = None,
    *,
    include_windwave: bool = True,
) -> Component:
    """Nearshore energy once the response matrix has taken its cut. Saturating and
    never capped downward at the top: this says "big", not "too big"."""
    if field is None:
        return Component(0.0, "no wave field", raw=None)

    usable = [
        p for p in field.partitions
        if include_windwave or p.kind != "windwave"
    ]
    if not usable and field.total_height_m:
        usable = [
            SwellPartition(
                height_m=field.total_height_m,
                period_s=field.total_period_s or 0.0,
                direction_deg=field.partitions[0].direction_deg if field.partitions else 0.0,
                kind="total",
            )
        ]
    if not usable:
        return Component(0.0, "no partitions and no total height", raw=None)

    height, lines = _transmitted_height_m(usable, matrix)
    value = height / (height + SIZE_HALF_M)
    method = "unrefracted (no response matrix)" if matrix is None else f"matrix:{matrix.method}"
    basis = f"nearshore {height:.2f} m from " + " + ".join(lines) + f" [{method}]"
    return Component(_clamp01(value), basis, raw=height)


def _spread(values: Sequence[float]) -> float:
    # Max minus min: with three or four models this says more than a stdev.
    return max(values) - min(values) if values else 0.0


def _direction_spread(directions: Sequence[float]) -> float:
    worst = 0.0
    for i, a in enumerate(directions):
        for b in directions[i + 1:]:
            worst = max(worst, angle_between(a, b))
    return worst


def confidence(fields: Sequence[WaveField]) -> Component:
    """Model disagreement on height, period and direction — not precision, not
    source quality. One model on its own cannot produce it."""
    primaries = [(f, f.primary) for f in fields]
    usable = [(f, p) for f, p in primaries if p is not None]
    if not usable:
        return Component(0.0, "no model produced a swell partition", raw=None)
    if len(usable) == 1:
        model = usable[0][0].model or "unnamed model"
        return Component(
            SINGLE_MODEL_CONFIDENCE,
            f"single model ({model}) — disagreement not measurable",
            raw=0.0,
        )

    heights = [p.height_m for _, p in usable]
    periods = [p.period_s for _, p in usable]
    directions = [p.direction_deg for _, p in usable]

    mean_h = sum(heights) / len(heights)
    mean_t = sum(periods) / len(periods)
    h_cv = _spread(heights) / mean_h if mean_h > 0 else 1.0
    t_cv = _spread(periods) / mean_t if mean_t > 0 else 1.0
    d_spread = _direction_spread(directions)

    agree_h = 1.0 - _clamp01(h_cv / HEIGHT_CV_FULL)
    agree_t = 1.0 - _clamp01(t_cv / PERIOD_CV_FULL)
    agree_d = 1.0 - _clamp01(d_spread / DIRECTION_SPREAD_FULL)
    value = (agree_h + agree_t + agree_d) / 3.0

    names = ",".join(f.model or "?" for f, _ in usable)
    basis = (
        f"{len(usable)} models ({names}): height spread {_spread(heights):.2f} m, "
        f"period spread {_spread(periods):.1f} s, direction spread {d_spread:.0f} deg"
    )
    return Component(_clamp01(value), basis, raw=d_spread)


def reference_field(fields: Sequence[WaveField]) -> WaveField | None:
    """The model with the median primary height. Median rather than mean because
    averaging directions and periods invents a swell no model forecast."""
    with_primary = [f for f in fields if f.primary is not None]
    if not with_primary:
        return fields[0] if fields else None
    ordered = sorted(with_primary, key=lambda f: (f.primary.height_m, f.model))  # type: ignore[union-attr]
    return ordered[len(ordered) // 2]


def score_hour(
    spot: Spot,
    fields: Sequence[WaveField],
    matrix: Response | None = None,
    *,
    slope: Derived | None = None,
) -> Components:
    """`fields` is one WaveField per model for the same hour; a partial set is
    normal, and the shrinking set is what confidence reports."""
    if not fields:
        empty = Component(0.0, "no model returned this hour", raw=None)
        return Components(barrel=empty, cleanness=empty, size=empty, confidence=empty)

    ref = reference_field(fields)
    wind = next((f.wind for f in fields if f.wind is not None), None)
    used_slope = slope if slope is not None else spot.beach_slope

    return Components(
        barrel=barrel(ref.primary if ref else None, used_slope),
        cleanness=cleanness(wind, spot),
        size=size(ref, matrix),
        confidence=confidence(fields),
    )
