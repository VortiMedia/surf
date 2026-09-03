---
name: surf-intelligence
description: Find and compare surf opportunities by combining forecast, buoy observations, tide, and coastline geometry. Use when the user asks where or when to surf, whether a spot will be working, how a swell will hit a stretch of coast, or to rank spots within a travel radius or trip window.
---

# Surf Intelligence

The answer is a call: a spot, a day, a time, the two or three signals that drove
it, and what would make it wrong. Not a ranked grid.

The physics is in the `surf` CLI. Run it, read the labels honestly, and commit
to an answer. Do not re-derive forecasts in an ad-hoc script and do not narrate
a rating back.

## Commands

| Command | For |
|---|---|
| `surf sources` | Preflight every source and print status per source. Run this first when anything looks wrong. |
| `surf call [--region R] [--days N]` | The product. One recommendation across the region and window. |
| `surf spot <name>` | One spot in depth: components, geometry, provenance, what is missing. |
| `surf calibrate` | Score the session log, check no 1/5 dominates a 5/5, print rank correlation per component. |
| `surf geometry [--write]` | Derive beach slopes from NCEI bathymetry. Read-only without `--write`. Until it has run, BARREL scores off a nominal slope everywhere alike. |
| `surf session add` | Append a row to `data/sessions.tsv`. |

Exit status is real: zero means the command answered. A source being down is not
a failure — it is a degraded answer that still exits zero and says so. Read the
status line, not the exit code, to know what was missing.

## Read the labels before the numbers

Every value carries `source`, `status`, `fetched_at`, and where they apply
`model_run`, `confidence` and what was `dropped`. Four statuses:

- `ok` — got what was asked for
- `degraded` — got less; the label says what was dropped
- `failed` — the source errored; the rest of the answer is unaffected
- `skipped` — never called, because preflight or the breaker said no

Quote the status when it changes the meaning. "Model-only, no buoy in range" is
part of the answer, not a footnote.

## The four components

Reported separately, never fused into one rating.

| Component | Meaning |
|---|---|
| BARREL | Iribarren plunging estimate, `ξ = tanβ / √(H/L₀)`, plunging band 0.5–3.3 |
| CLEANNESS | Wind angle against the spot's stored shore normal |
| SIZE | Nearshore energy after the spot's response matrix |
| CONFIDENCE | How much the models disagree — not how precise the number looks |

The target is stand-up barrels, not general quality, so a big mushy day ranks
below a small hollow one. That inversion is deliberate.

BARREL falls as the swell grows: ξ scales with H^-½, so at fixed slope and
period a bigger wave is a less hollow one. If an explanation wants "bigger is
better", the component it wants is SIZE.

## Swell reaching a spot

`Response.transmission(direction, period)` covers refraction and shadowing
against the spot's stored geometry. Two consequences when explaining a call:

- **There is no angular cutoff.** Long-period energy wraps further around a
  headland than short-period energy, so transmission falls with angle and rises
  with period. Any rule that zeroes a spot past a fixed off-axis angle is wrong
  physics.
- **Geometry is cached, never guessed.** Shore normals and slopes come from
  `data/spots.tsv` with a provenance flag: `derived`, `manual` or `default`. If
  a spot's geometry is `default`, say so. Fixing it means measuring it and
  writing it to the file, not estimating a bearing per query.

Period sorts the swell: `L₀ ≈ 1.56·T²` metres. 14 s and up refracts into
sheltered spots and breaks with force; under 10 s is local windswell.

## Horizon

Five days sharp. Days 6–10 are an arrival heads-up only — direction and timing
of arriving energy, never a size or a session time.

## Weighting

- Observations beat models where they are temporally relevant. A buoy now
  outranks any forecast for now. Buoys are US and Europe only, so most spots are
  model-only and must say so.
- Agreement beats any single model. Disagreement is a finding to report, not
  noise to average away.
- Geometry beats a rating. A rating is a regional model's guess about a spot;
  the response matrix is that spot's own orientation and sea floor.
- History beats a number. `surf calibrate` gives nearest-neighbour matches, and
  "resembles your 2024-03-24 session" is stronger than a score.

## Access is a cost, not a filter

Travel cost and mode ride along with the call and never exclude a spot. Print
the price and let the user decide.

## Surfline

Optional, off by default (`SURF_SURFLINE=1`). It is a second opinion after the
call exists, never an input. If it disagrees, that is a line in the output, not
a reason to change the call. If it is missing or broken, carry on and do not
mention it as a gap.

## When something is missing

Say what was missing and answer anyway. One dead source never kills the rest.
Run `surf sources` and report the statuses rather than guessing at the cause.

Never fill a hole with an estimate. A skipped bathymetry read means BARREL falls
back to the steepness proxy and the call says which basis it used — not that a
slope gets invented.

## Output

Lead with the call: spot, day, time. Then the two or three signals that moved
it. Then the falsifier — the concrete thing that, if it happens, means go
somewhere else. Anything model-only, geometry-defaulted or degraded is stated in
the same breath as the number it qualifies.

A grid of every spot by every day is not the deliverable.
