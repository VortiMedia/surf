"""Checks that skill/SKILL.md still matches the CLI it drives."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "SKILL.md"


@pytest.fixture(scope="module")
def text() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(text: str) -> dict[str, str]:
    """YAML-ish frontmatter, parsed by hand — the loader only needs `name` and
    `description`, and a yaml dependency for two keys is not worth it."""
    assert text.startswith("---\n"), "skill must open with a frontmatter block"
    _, block, _ = text.split("---\n", 2)
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_frontmatter_names_and_describes_the_skill(frontmatter):
    assert frontmatter["name"] == "surf-intelligence"
    description = frontmatter["description"]
    # The description is the only thing the model sees before loading the skill;
    # it has to state when to reach for it, not just what it is.
    assert len(description) > 80
    assert "surf" in description.lower()


def test_no_eighty_degree_cutoff(text):
    """No angular cutoff at all: long-period energy wraps further around a
    headland than short-period, so a fixed limit is wrong physics."""
    assert not re.search(r"[±+-]?\s*80\s*(?:°|deg\b|degrees\b)", text)
    # And it must positively teach the replacement, or the next reader reinvents it.
    lowered = text.lower()
    assert "no angular cutoff" in lowered
    assert "period" in lowered and "wrap" in lowered


def test_documents_every_cli_subcommand():
    from surf import cli

    parser = cli.build_parser()
    sub = next(a for a in parser._actions if getattr(a, "choices", None) and hasattr(a.choices, "keys"))
    skill = SKILL.read_text(encoding="utf-8")
    for name in sub.choices:
        assert f"surf {name}" in skill, f"skill does not document `surf {name}`"


def test_teaches_the_labelling_vocabulary(text):
    """The model has to know what the four statuses mean in order to report them."""
    for status in ("ok", "degraded", "failed", "skipped"):
        assert re.search(rf"`{status}`", text), f"status `{status}` unexplained"
    for label in ("source", "status", "fetched_at", "model_run", "confidence"):
        assert label in text


def test_keeps_the_four_components_separate(text):
    """Never one magic number."""
    for component in ("BARREL", "CLEANNESS", "SIZE", "CONFIDENCE"):
        assert component in text
    assert "iribarren" in text.lower()
    # Confidence is model disagreement, not decimal places.
    assert re.search(r"models? (?:dis)?agree", text.lower())


def test_states_the_non_negotiables(text):
    lowered = text.lower()
    assert "never" in lowered and "grid" in lowered          # a call, not a table
    assert "surfline" in lowered and "optional" in lowered
    assert "model-only" in lowered
    assert "cost, not a filter" in lowered
    assert "cached, never guessed" in lowered
    assert re.search(r"\b(?:five|5) days\b", lowered)        # horizon
    assert re.search(r"\b6[–-]10\b", text)


def test_no_hardcoded_exit_codes(text):
    """The CLI owns its exit codes; the skill teaches how to read status instead."""
    assert not re.search(r"exit (?:code )?[1-9]\b", text.lower())
    assert "exit" in text.lower()


