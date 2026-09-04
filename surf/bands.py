"""Per-setup minimum bands derived from the session log."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal


BandBasis = Literal["measurement", "convention"]

# Nearshore-Hs resolution used when a band measurement becomes a user-facing
# size step. Keep this beside the band derivation rather than inventing a second
# scale in the REACH implementation.
NEARSHORE_STEP_M = 0.5


@dataclass(frozen=True)
class BandObservation:
    setup_type: str
    nearshore_height_m: float
    rating: int


@dataclass(frozen=True)
class BandFloor:
    setup_type: str
    minimum_m: float
    sample_count: int
    basis: BandBasis
    detail: str

    def render(self) -> str:
        return (
            f"minimum {self.minimum_m:.1f} m nearshore Hs "
            f"({self.basis}; n={self.sample_count}) — {self.detail}; no upper cap"
        )


# The log has too little point/reef evidence to measure these. Keep the values
# beside the physics that supplies them so they cannot read as observations.
CONVENTIONS: dict[str, tuple[float, str]] = {
    "point": (
        1.0,
        "depth-limited breaking and a persistent peel line are required",
    ),
    "reef": (
        1.0,
        "depth-limited breaking; the shelf criterion must survive source resolution",
    ),
}


def derive_band_floors(
    observations: Iterable[BandObservation], *, minimum_samples: int = 3
) -> dict[str, BandFloor]:
    """Return floors by setup type; a sparse type never masquerades as measured."""
    grouped: dict[str, list[float]] = defaultdict(list)
    seen_types: set[str] = set()
    for observation in observations:
        seen_types.add(observation.setup_type)
        if observation.rating >= 4 and observation.nearshore_height_m > 0:
            grouped[observation.setup_type].append(observation.nearshore_height_m)

    out: dict[str, BandFloor] = {}
    for setup_type in seen_types | CONVENTIONS.keys():
        heights = grouped.get(setup_type, [])
        if len(heights) >= minimum_samples:
            out[setup_type] = BandFloor(
                setup_type,
                min(heights),
                len(heights),
                "measurement",
                "lowest session rated 4 or 5",
            )
        elif setup_type in CONVENTIONS:
            value, detail = CONVENTIONS[setup_type]
            out[setup_type] = BandFloor(
                setup_type, value, len(heights), "convention", detail
            )
    return out


def bands_from_log(book, sessions=None, cache=None) -> dict[str, BandFloor]:
    """Build observations through the same cached historical path as calibration."""
    # Lazy imports avoid making the scoring/call module graph circular.
    from .calibrate import ConditionCache, recover
    from .response import Response
    from .score import size
    from .sessions import load_sessions

    rows = tuple(sessions) if sessions is not None else load_sessions(book=book)
    recovered = recover(rows, book=book, cache=cache or ConditionCache())
    observations: list[BandObservation] = []
    for item in recovered:
        if item.field is None or item.rating is None:
            continue
        height = size(item.field, Response.for_spot(item.spot)).raw
        if height is not None:
            observations.append(BandObservation(item.spot.break_type, height, item.rating))
    return derive_band_floors(observations)
