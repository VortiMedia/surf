---
name: surf-brief
description: Orient in the surf repo with minimal context. Use for "status", "where are we", "what changed", "resume", "catch me up", or before touching spots, scoring, endpoints, research workflow or an agent skill.
---

# Surf Brief

Understand this repo without loading it. Two committed TSVs and a physics
package; everything else is generated or scratch.

## 1. Snapshot

Run once:

```bash
git status --short --branch
git log -5 --oneline --decorate
git diff --stat -- data/ docs/ surf/ skill/
```

`data/spots.tsv` and `data/sessions.tsv` are the source of truth. A diff there
is a real change to what the model knows, not incidental churn — read those
hunks even when the rest of the diff is large.

## 2. Instructions

`CLAUDE.md` is the instruction source for both agents (`AGENTS.md` delegates to
it). If it is already in context, do not reread it; if it is not, read it once.
Its routing table decides where a finding goes — obey it instead of inventing a
new doc.

`README.md` (what the tool does) and `docs/DATA-SOURCES.md` (per-endpoint
quirks) exist. Do not open them for a status check. Open one only when about to
touch the thing it covers, and read the relevant section, not the file.

`docs/ARCHITECTURE.md` is the code layout and product model. Open it for trip decisions,
coastline discovery, seasonal weather or flat-spell analysis, bathymetry,
backtesting, KMZ, MCP/mobile or scheduled-alert work.

## 3. Is it healthy

Only when the answer matters:

```bash
pytest -q -m "not network"        # offline; must be green
surf sources                      # is any endpoint down right now
```

Network tests failing is usually a rate limit, not a regression. Confirm the
offline suite before blaming code.

`tests/test_storage.py` enforces the spot invariants (offshore point seaward of
the shore normal, geometry in range). `tests/test_skill_doc.py` enforces
`skill/SKILL.md` against the CLI surface. If either fails after your change, it
is telling you what the change owes — not something to route around.

## 4. Previous work

Only when the repo does not explain where things stopped, or the user asks to
resume.

Prefer the repo's own memory in this order:

1. `docs/RECON.md` — what was surveyed, and the Open section at the bottom
2. `docs/CALIBRATION.md` — where the model disagreed with the log
3. `docs/DATA-SOURCES.md` — what an endpoint did last time it was tested

If those come up empty and `qmd` exists:

```bash
qmd tsearch "surf <spot|endpoint|task>" -n 5
```

Read at most 2 results. Never dump transcripts into context.

## 5. Drill down

Only when needed, smallest first:

1. `grep -n '<spot-id>' data/spots.tsv`
2. `surf spot <id>` — components, geometry, provenance in one shot
3. `git diff -- <file>`
4. read the narrow range

Never recursively explore `surf/` for a status check. The physics is stable;
the data and the docs are what move.

## Before you start work

Three failure modes this repo has already paid for:

- **A finding lands nowhere and is re-derived later.** Route it by the CLAUDE.md
  table before writing anything.
- **Scratch becomes a deliverable.** One-off scripts stay in the scratchpad;
  generated KML/GeoJSON/PNG goes to a gitignored directory, never `data/` root
  or `docs/`. If a one-off is worth keeping it becomes a CLI subcommand with a
  test.
- **A hole gets filled with an estimate.** A dead source degrades and says what
  it dropped. Geometry is measured and written to `data/spots.tsv` with
  provenance, never guessed per query.

## Output

Maximum 5 bullets:

* **State:** branch + clean/dirty/ahead/behind
* **Data:** any uncommitted change to `spots.tsv` / `sessions.tsv`, in rows
* **Changes:** other meaningful uncommitted work
* **Health:** offline suite, and any source known down — only if checked
* **Next:** obvious next action or blocker, including anything in RECON's Open

Under ~120 words. No tool narration, no file lists, no architecture recap.
