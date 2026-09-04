"""Evidence below the session log.

Reference events and archetypes are context for a ranking, never another score.
The session log remains the only evidence allowed to confirm what David likes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

from .sessions import Session
from .sources import Status
from .waves import WaveField

EvidenceKind = Literal["session", "reference_event", "archetype"]
EVIDENCE_ORDER: dict[EvidenceKind, int] = {
    "session": 0,
    "reference_event": 1,
    "archetype": 2,
}

NDBC_44091_2023 = (
    "https://www.ndbc.noaa.gov/data/historical/stdmet/44091h2023.txt.gz"
)
NDBC_44091_FETCHED_AT = datetime(2026, 9, 3, 22, 32, 15, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Conditions:
    """Conditions attached to an evidence item, with unknowns left unknown."""

    height_m: float | None = None
    period_s: float | None = None
    direction_deg: float | None = None
    wind_speed_mps: float | None = None
    wind_direction_deg: float | None = None

    @classmethod
    def from_field(cls, field: WaveField) -> Conditions:
        primary = field.primary
        return cls(
            height_m=field.total_height_m if field.total_height_m is not None else (
                primary.height_m if primary is not None else None
            ),
            period_s=field.total_period_s if field.total_period_s is not None else (
                primary.period_s if primary is not None else None
            ),
            direction_deg=primary.direction_deg if primary is not None else None,
            wind_speed_mps=field.wind.speed_mps if field.wind is not None else None,
            wind_direction_deg=field.wind.direction_deg if field.wind is not None else None,
        )


@dataclass(frozen=True)
class Provenance:
    source: str
    status: Status = "ok"
    fetched_at: datetime | None = None
    valid_at: datetime | None = None
    model_run: str | None = None
    confidence: float | None = None
    dropped: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceEvent:
    id: str
    name: str
    on: date
    location: str
    conditions: Conditions
    provenance: Provenance
    note: str = ""

    @property
    def kind(self) -> EvidenceKind:
        return "reference_event"


@dataclass(frozen=True)
class Archetype:
    id: str
    name: str
    setup_type: str
    conditions: Conditions
    provenance: Provenance
    note: str = ""
    contradiction_phrases: tuple[str, ...] = ()

    @property
    def kind(self) -> EvidenceKind:
        return "archetype"


@dataclass(frozen=True)
class EvidenceRecord:
    """One ranking-readable item. Lower ``priority`` is stronger evidence."""

    kind: EvidenceKind
    name: str
    conditions: Conditions | None
    provenance: Provenance
    payload: Any = None

    @property
    def priority(self) -> int:
        return EVIDENCE_ORDER[self.kind]

    @property
    def authoritative(self) -> bool:
        return self.kind == "session"

    @property
    def can_confirm(self) -> bool:
        """Only a logged session can confirm a preference or recommendation."""
        return self.authoritative


def _session_record(session: Session) -> EvidenceRecord:
    when = session.on.isoformat() if session.on else session.raw_date
    return EvidenceRecord(
        kind="session",
        name=f"{when} {session.raw_spot}".strip(),
        conditions=None,
        provenance=Provenance(source="data/sessions.tsv"),
        payload=session,
    )


def evidence_order(
    sessions: tuple[Session, ...] | list[Session] = (),
    reference_events: tuple[ReferenceEvent, ...] = (),
    archetypes: tuple[Archetype, ...] = (),
) -> tuple[EvidenceRecord, ...]:
    """Return evidence in the fixed ladder: sessions, events, archetypes.

    This is an evidence view only. It does not produce or change a candidate's
    score or ordering key.
    """
    records = [
        *(_session_record(session) for session in sessions),
        *(
            EvidenceRecord(event.kind, event.name, event.conditions, event.provenance, event)
            for event in reference_events
        ),
        *(
            EvidenceRecord(archetype.kind, archetype.name, archetype.conditions,
                           archetype.provenance, archetype)
            for archetype in archetypes
        ),
    ]
    return tuple(sorted(records, key=lambda item: item.priority))


def contradiction_for(archetype: Archetype, sessions: tuple[Session, ...] | list[Session]) -> str | None:
    """Return the first explicit logged contradiction, if any.

    This intentionally recognizes explicit language only. Absence of a session
    is not a contradiction and an archetype never gets promoted by assumption.
    """
    phrases = tuple(phrase.casefold() for phrase in archetype.contradiction_phrases)
    for session in sessions:
        notes = session.notes.casefold()
        for phrase in phrases:
            if phrase in notes:
                return f"{archetype.name} contradicted by {session.raw_spot}: {phrase}"
    return None


def can_nominate(
    item: ReferenceEvent | Archetype,
    sessions: tuple[Session, ...] | list[Session],
) -> bool:
    """Events nominate freely; an archetype nominates only if the log allows it."""
    if isinstance(item, ReferenceEvent):
        return True
    return contradiction_for(item, sessions) is None


REFERENCE_EVENTS: tuple[ReferenceEvent, ...] = (
    ReferenceEvent(
        id="monster-monday-nj-44091-2023-12-18",
        name="Monster Monday NJ",
        on=date(2023, 12, 18),
        location="NDBC 44091 Barnegat NJ",
        conditions=Conditions(height_m=5.82, period_s=12.5, direction_deg=121.0),
        provenance=Provenance(
            source=NDBC_44091_2023,
            fetched_at=NDBC_44091_FETCHED_AT,
            valid_at=datetime(2023, 12, 18, 11, 56, tzinfo=timezone.utc),
            model_run="NDBC 44091 standard meteorological archive 2023",
        ),
        note="Sustained 3-sample-median peak; not a David session.",
    ),
)

# These two setup records are deliberately narrow: their conditions are copied
# from the existing Open-Meteo archive cache for ideal logged sessions. They are
# not new preference evidence and stay below the session rows in the ladder.
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "belmar-ideal-2024-04-04",
        "Belmar ideal reference setup",
        "beach",
        Conditions(height_m=2.30, period_s=8.05, direction_deg=89.0,
                   wind_speed_mps=5.24, wind_direction_deg=305.0),
        Provenance(
            source=OPEN_METEO_ARCHIVE,
            fetched_at=datetime(2026, 9, 3, 7, 47, 35, tzinfo=timezone.utc),
            valid_at=datetime(2024, 4, 4, 11, tzinfo=timezone.utc),
            model_run="open-meteo-marine reanalysis",
        ),
        note="Cached conditions for the 2024-04-04 ideal Belmar session.",
    ),
    Archetype(
        "kommetjie-ideal-2023-02-25",
        "Kommetjie ideal reference setup",
        "beach",
        Conditions(height_m=3.28, period_s=11.8, direction_deg=209.0,
                   wind_speed_mps=7.54, wind_direction_deg=158.0),
        Provenance(
            source=OPEN_METEO_ARCHIVE,
            fetched_at=datetime(2026, 9, 3, 17, 59, 25, tzinfo=timezone.utc),
            valid_at=datetime(2023, 2, 25, 14, tzinfo=timezone.utc),
            model_run="open-meteo-marine reanalysis",
        ),
        note="Cached conditions for the 2023-02-25 ideal Kommetjie session.",
    ),
)


def default_evidence() -> tuple[EvidenceRecord, ...]:
    """The non-session evidence available to a ranking caller."""
    return evidence_order(reference_events=REFERENCE_EVENTS, archetypes=ARCHETYPES)
