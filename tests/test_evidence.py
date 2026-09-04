from __future__ import annotations

from datetime import date

from surf.evidence import (
    ARCHETYPES,
    REFERENCE_EVENTS,
    Conditions,
    EvidenceRecord,
    Provenance,
    can_nominate,
    contradiction_for,
    default_evidence,
    evidence_order,
)
from surf.sessions import Session


def session(notes: str = "") -> Session:
    return Session(
        raw_date="2025-01-01", raw_spot="Lido Beach", raw_time="08:00",
        rating=5, notes=notes, on=date(2025, 1, 1), hour=8, spot_id="lido-beach",
    )


def test_evidence_order_keeps_sessions_authoritative():
    records = evidence_order((session(),), REFERENCE_EVENTS, ARCHETYPES)
    assert [record.kind for record in records[:3]] == ["session", "reference_event", "archetype"]
    assert records[0].authoritative and records[0].can_confirm
    assert not records[1].authoritative and not records[1].can_confirm
    assert records[1].conditions.height_m == 5.82
    assert records[1].provenance.source.endswith("44091h2023.txt.gz")
    assert records[1].provenance.status == "ok"
    assert can_nominate(REFERENCE_EVENTS[0], (session(),))


def test_reference_event_and_archetype_conditions_carry_provenance():
    event = REFERENCE_EVENTS[0]
    assert event.conditions.period_s == 12.5
    assert event.conditions.direction_deg == 121.0
    assert event.provenance.fetched_at is not None
    assert all(archetype.conditions == Conditions() for archetype in ARCHETYPES)
    assert all(archetype.provenance.dropped == ("no hindcast attached",) for archetype in ARCHETYPES)


def test_explicit_session_contradiction_blocks_slab_nomination():
    shipsterns = next(archetype for archetype in ARCHETYPES if archetype.id == "shipsterns")
    logged = session("super lucky one-off. Do NOT use as evidence he wants slabs")
    contradiction = contradiction_for(shipsterns, (logged,))
    assert contradiction is not None
    assert not can_nominate(shipsterns, (logged,))
    assert can_nominate(shipsterns, (session("clean beach break"),))


def test_evidence_view_does_not_smuggle_an_ordering_key():
    record = default_evidence()[0]
    assert isinstance(record, EvidenceRecord)
    assert record.priority in (1, 2)
    assert not hasattr(record, "score")
