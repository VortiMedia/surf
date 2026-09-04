"""Translate the session log's words into testable physical filters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import inf
from typing import Iterable, Literal, Mapping, Sequence, TypeVar


LexiconStatus = Literal["measurement", "convention", "contradicted"]


@dataclass(frozen=True)
class PhysicalFilter:
    quantity: str
    minimum: float = -inf
    maximum: float = inf

    def matches(self, metrics: Mapping[str, float | None]) -> bool | None:
        value = metrics.get(self.quantity)
        return None if value is None else self.minimum <= value <= self.maximum

    def render(self) -> str:
        low = "any" if self.minimum == -inf else f"{self.minimum:g}"
        high = "any" if self.maximum == inf else f"{self.maximum:g}"
        return f"{self.quantity} {low}..{high}"


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    filters: tuple[PhysicalFilter, ...]
    physics: str
    supporting_sessions: int = 0
    status: LexiconStatus = "convention"


@dataclass(frozen=True)
class LexiconSample:
    notes: str
    metrics: Mapping[str, float | None]


SPECS: tuple[LexiconEntry, ...] = (
    LexiconEntry("walled out", (PhysicalFilter("peel_angle_deg", maximum=30),), "small peel angle makes the line arrive at once"),
    LexiconEntry("racy", (PhysicalFilter("peel_angle_deg", 20, 45),), "moderate peel angle leaves a fast makeable line"),
    LexiconEntry("spitting", (PhysicalFilter("iribarren", 0.5, 3.3),), "a plunging Iribarren regime can throw a tube"),
    LexiconEntry("grovel", (PhysicalFilter("nearshore_height_m", maximum=0.8),), "nearshore height is at the minimum rideable edge"),
    LexiconEntry("sucking up", (PhysicalFilter("iribarren", 0.5, 3.3),), "rapid shoaling raises breaker steepness"),
    LexiconEntry("punchy", (PhysicalFilter("wave_energy", 10),), "height squared times period is an energy proxy"),
    LexiconEntry("mushy", (PhysicalFilter("iribarren", maximum=0.5),), "low Iribarren waves spill rather than plunge"),
    LexiconEntry("closed out", (PhysicalFilter("size_to_capacity", 1),), "incoming size exceeds the setup's holding capacity"),
    LexiconEntry("logable but clean", (PhysicalFilter("nearshore_height_m", maximum=0.9), PhysicalFilter("wind_angle_deg", maximum=60)), "small nearshore height with offshore or cross-offshore wind"),
    LexiconEntry("weak tubes", (PhysicalFilter("nearshore_height_m", maximum=1.0), PhysicalFilter("iribarren", 0.5, 3.3)), "plunging shape with little transmitted height"),
    LexiconEntry("could not hold the swell", (PhysicalFilter("size_to_capacity", 1),), "incoming size exceeds the setup's holding capacity"),
    LexiconEntry("needed a gun", (PhysicalFilter("size_to_reach", 1),), "the session exceeded the rider's demonstrated reach"),
)


def _mentioned(term: str, notes: str) -> bool:
    text = notes.casefold()
    term = term.casefold()
    if term not in text:
        return False
    return f"not {term}" not in text and not (term == "punchy" and "not steep/punchy" in text)


def build_lexicon(
    samples: Iterable[LexiconSample], *, minimum_samples: int = 2
) -> tuple[LexiconEntry, ...]:
    rows = tuple(samples)
    out: list[LexiconEntry] = []
    for spec in SPECS:
        support = tuple(row for row in rows if _mentioned(spec.term, row.notes))
        checks = tuple(
            result
            for row in support
            for constraint in spec.filters
            if (result := constraint.matches(row.metrics)) is not None
        )
        expected = len(support) * len(spec.filters)
        if len(support) >= minimum_samples and len(checks) == expected:
            status: LexiconStatus = "measurement" if all(checks) else "contradicted"
        else:
            status = "convention"
        out.append(replace(spec, supporting_sessions=len(support), status=status))
    return tuple(out)


def resolve_phrase(
    phrase: str, entries: Sequence[LexiconEntry]
) -> tuple[PhysicalFilter, ...]:
    """Resolve every known term in a natural phrase, longest first."""
    found: list[PhysicalFilter] = []
    for entry in sorted(entries, key=lambda item: len(item.term), reverse=True):
        if _mentioned(entry.term, phrase):
            found.extend(entry.filters)
    return tuple(found)


T = TypeVar("T")


def apply_filters(
    values: Iterable[T], filters: Sequence[PhysicalFilter], metrics
) -> tuple[T, ...]:
    """Ranking seam: unknown or failed constraints do not pass silently."""
    return tuple(
        value for value in values
        if all(constraint.matches(metrics(value)) is True for constraint in filters)
    )


def lexicon_from_log(book, sessions=None, cache=None) -> tuple[LexiconEntry, ...]:
    from .calibrate import ConditionCache, recover
    from .response import Response
    from .score import score_hour
    from .sessions import load_sessions

    rows = tuple(sessions) if sessions is not None else load_sessions(book=book)
    recovered = recover(rows, book=book, cache=cache or ConditionCache())
    samples: list[LexiconSample] = []
    for item in recovered:
        if item.field is None:
            continue
        components = score_hour(item.spot, (item.field,), Response.for_spot(item.spot))
        primary = item.field.primary
        samples.append(LexiconSample(item.session.notes, {
            "nearshore_height_m": components.size.raw,
            "iribarren": components.barrel.raw,
            "wind_angle_deg": components.cleanness.raw,
            "wave_energy": primary.energy if primary is not None else None,
            "peel_angle_deg": None,
            "size_to_capacity": None,
            "size_to_reach": None,
        }))
    return build_lexicon(samples)


def metrics_for_hour(hour) -> dict[str, float | None]:
    primary = hour.reference.primary if hour.reference is not None else None
    return {
        "nearshore_height_m": hour.components.size.raw,
        "iribarren": hour.components.barrel.raw,
        "wind_angle_deg": hour.components.cleanness.raw,
        "wave_energy": primary.energy if primary is not None else None,
        "peel_angle_deg": None,
        "size_to_capacity": None,
        "size_to_reach": None,
    }
