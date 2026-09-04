# Working in this repo

The physics lives in the `surf` package. Read `README.md` for what the tool
does, `docs/DATA-SOURCES.md` before touching any endpoint, and
`docs/CALIBRATION.md` before touching scoring.

## Product direction

This is the calculation layer for an AI surf researcher. The system should turn
natural prompts into an explicit decision, a defensible investigation, a visual
artifact, or a saved alert. It should work like a careful human researcher:
look broadly, narrow cheaply, measure, corroborate, backtest, then decide.

For trip selection, coastline discovery, seasonal weather or flat-spell
analysis, bathymetry, backtesting, KMZ output, MCP/mobile access, or alerts,
read `docs/ARCHITECTURE.md` first. It is the source of truth for the
architecture, product model and research loop.

## Where a thing goes

The most common failure here is a finding landing in the wrong place, or in no
place, and being re-derived three sessions later.

| You learned | It goes in |
|---|---|
| A spot's position, aspect, slope, access | `data/spots.tsv`, one row, with provenance |
| A session and what it was actually like | `data/sessions.tsv` via `surf session add` |
| An endpoint lies, 404s, shifts columns, rate-limits | `docs/DATA-SOURCES.md` |
| The model ranked a session wrong | `docs/CALIBRATION.md` |
| A survey result — how big a coast gets, which places are worth a row | `docs/RECON.md` |
| Codebase layout, the research workflow, product boundary or build order | `docs/ARCHITECTURE.md` |
| How the answer is shaped for a human | `skill/SKILL.md` |

If it does not fit a row of that table, it probably belongs in the conversation
and nowhere else. Do not create a new top-level doc to hold one paragraph.

## What `data/` is

Two committed files, `spots.tsv` and `sessions.tsv`, and they are the source of
truth. Everything else under `data/` is generated and gitignored: `cache/`,
`imagery/`, `overlays/`, `exposure/` and `climate/`. `climate/` holds the derived
reanalysis and bathymetry cache — it is expensive to rebuild and worthless to
review in a diff, so it is generated, never committed, and never authoritative. Generated output never goes next to the TSVs — if a
script emits KML, GeoJSON, PNGs or JSON dumps, it emits them into a gitignored
directory or into the session scratchpad, never into `data/` root and never into
`docs/`.

Scratch scripts stay in the scratchpad. A one-off that answered a question is
not a deliverable; the answer is. If a one-off is worth keeping, it becomes a
CLI subcommand with a test, or it does not exist.

## Invariants

These are load-bearing. Breaking one silently is worse than failing loudly.

**Never fill a hole with an estimate.** A source that is down produces
`degraded` or `failed` with what it dropped, not a plausible fallback. Outside
US DEM coverage the sea floor grid is ~460 m, so those spots report *no* slope
rather than a confident meaningless one.

**Every value carries its provenance.** `source`, `status`, `fetched_at`, and
where it applies `model_run`, `confidence`, `dropped`. Geometry carries
`derived` / `manual` / `default`. A number without its label is not evidence.

**Separate decision axes.** BARREL, SIZE, CLEANNESS and CONFIDENCE stay visible.
A natural prompt may make one axis decisive, but there is no universal weighting;
the first fused score ranked a 1/5 session above three 5/5s.

**No angular cutoff.** Transmission falls off with angle and rises with period.
Any rule that zeroes a spot past a fixed off-axis angle is wrong physics, and
`tests/test_skill_doc.py` fails the build if the skill doc reintroduces one.

**Exit status is real.** Zero means the command answered. A source being down is
a degraded answer that still exits zero and says so.

## Traps that have already cost time

**BARREL falls as the swell gets bigger.** `ξ = tanβ/√(H/L₀)` scales with
`H^-½`. That is the physics, not an inverted sign.

**The DEM cannot see reef.** It resolves a sand profile, not boulders.
`fit_beach_slope` averages a reef into gentle sand and the resulting Iribarren
number says a reef point closes out at every size, which is false. Size reef and
point breaks by depth-limited breaking and say the gradient is unresolved.

**Parse NDBC historical by header, never by fixed index.** Files before 2005
have no `mm` column and every field shifts, so you read wind gusts as wave
height and get a 54.7 ft sea.

**A single sample is not a wave.** Require a peak to survive a 3-sample centred
median before reporting it.

**Offshore Hs is not face height.** Three different numbers get called "size".
Prefer nearshore Hs from `score.size()`. Face is not computed; ~1.5× nearshore
is a stated convention, never a bare figure.

**Do not re-diagnose Surfline with curl.** A direct curl gets 403 from the WAF;
httpx with a normal User-Agent succeeds.

## Changing things

Geometry is measured and cached, never guessed per query. Fixing a spot means
measuring it and writing it to `data/spots.tsv` with provenance, not estimating
a bearing by eye in a script.

`skill/SKILL.md` is under test — it must keep frontmatter, document every CLI
subcommand, and teach the labelling vocabulary. Change the CLI surface and that
test tells you what the doc now owes.

When a survey turns up a result that contradicts an earlier one, record the
correction in `docs/RECON.md` rather than quietly replacing the number. The
wrong answer and why it was wrong is the reusable part.

```sh
pip install -e ".[dev]"
pytest                    # offline
pytest -m network         # hits the live APIs
```
