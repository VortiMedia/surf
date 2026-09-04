from dataclasses import dataclass

from surf.lexicon import (
    LexiconSample,
    PhysicalFilter,
    apply_filters,
    build_lexicon,
    resolve_phrase,
)


def sample(notes: str, **metrics: float | None) -> LexiconSample:
    return LexiconSample(notes, metrics)


def test_each_term_has_physics_filters_support_and_status() -> None:
    entries = build_lexicon((
        sample("grovel", nearshore_height_m=0.5),
        sample("another grovel", nearshore_height_m=0.7),
    ))
    assert all(entry.filters and entry.physics for entry in entries)
    grovel = next(entry for entry in entries if entry.term == "grovel")
    assert grovel.supporting_sessions == 2
    assert grovel.status == "measurement"


def test_non_clustering_sessions_contradict_the_claim() -> None:
    entries = build_lexicon((
        sample("logable but clean", nearshore_height_m=0.5, wind_angle_deg=20),
        sample("logable but clean", nearshore_height_m=0.6, wind_angle_deg=100),
    ))
    entry = next(item for item in entries if item.term == "logable but clean")
    assert entry.status == "contradicted"


def test_sparse_or_unmeasurable_terms_stay_conventions() -> None:
    entries = build_lexicon((sample("walled out", peel_angle_deg=None),))
    entry = next(item for item in entries if item.term == "walled out")
    assert entry.supporting_sessions == 1
    assert entry.status == "convention"


def test_negated_word_does_not_become_support() -> None:
    entries = build_lexicon((sample("not steep/punchy", wave_energy=99),))
    punchy = next(item for item in entries if item.term == "punchy")
    assert punchy.supporting_sessions == 0


def test_natural_phrase_resolves_to_filters_the_ranking_seam_can_apply() -> None:
    entries = build_lexicon(())
    filters = resolve_phrase("I want something clean but just a grovel", entries)
    assert filters == (PhysicalFilter("nearshore_height_m", maximum=0.8),)

    @dataclass
    class Candidate:
        height: float

    candidates = (Candidate(0.6), Candidate(1.2))
    assert apply_filters(candidates, filters, lambda item: {"nearshore_height_m": item.height}) == (candidates[0],)
