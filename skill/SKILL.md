---
name: surf-intelligence
description: Research and decide surf opportunities from forecast, observations, history and geometry. Use for where or when to surf, trip planning, coastline discovery, seasonal weather or flat-spell analysis, exposure maps, backtests, or swell alerts.
---

# Surf Intelligence

Work like a constrained surf researcher: make the objective explicit, use the
cheapest evidence that can eliminate bad options, corroborate survivors, compare
against history, then make the requested deliverable and state what would make
it wrong.

Match the answer to the job:

| Job | Deliverable |
|---|---|
| Decide where or when to surf | One place, day and window; alternatives only when close |
| Investigate a coast or hidden break | Evidence-backed zones, rejected hypotheses and the requested KMZ or coordinates |
| Diagnose a season or flat spell | Weather mechanism, historical baseline and limiting condition |
| Understand a setup | Physical mechanism, historical frequency and strongest/average conditions |
| Watch a verified setup | Explicit swell, wind, tide and lead-time conditions for a future alert |

For discovery, seasonal weather, flat spells, bathymetry, backtesting, KMZ, MCP
or alert work, read `docs/ARCHITECTURE.md`. It defines the shared
research loop and build boundary.

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
| `surf exposure <coastline.geojson> --swell D [--output F.kmz] [--land F]` | Colour a coastline by exposure to one swell direction and write a Google Earth KMZ. Also installed as `surf-exposure`. |

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

But the target is not the same at every size — see below.

## Size bands change the question

David: "at certain levels the conditions change and sometimes I need to rip the
twin fin." `surf calibrate` agrees: rho(rating, SIZE) = +0.60,
rho(rating, BARREL) = -0.07. BARREL is the system's target and it is not what
predicts his ratings. Do not fuse them into a score — ask the question the band
poses. Bands are offshore significant height, from his log:

| Band | The question |
|---|---|
| under 3 ft | Is it worth leaving the house? Usually no — every sub-3 ft session rates 2-3, "grovel", "barely rippable". |
| 3-5 ft | Twin-fin zone: is it rippable, or walled? Cleanness, period and open shoulder beat xi. 3.7 ft Lido = 4/5 barrel; 4.1 and 4.5 ft = 2/5 "walled out". |
| 6-8 ft at 8-10 s | His East Coast prime. Every 5/5 on this coast lives here. Lead with the band, not the component. |
| 10 ft+ | Can the spot hold it? Kommetjie 15.6 ft = 3/5 "needed a gun"; Llandudno 10.3 ft = 5/5. |

Name the band before the component: "this is a 2 ft grovel" is the answer, and
"BARREL 0.60" on a 2 ft day is a distraction dressed as precision.

In the twin-fin band a high BARREL can be the bad sign. 5.2 ft at 8 s was a 1/5,
"slabby, sucking up, walled, closed out". When xi is high and the period is under
~10 s on a steep beach, call the closeout risk instead of selling the hollow day.

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

## Exposure maps

`surf exposure` answers a different question from `surf call`: not how good a
spot will be, but which parts of a coast can see a given swell at all. It cuts
the coastline into 200 m segments, probes each segment's seaward side against a
land mask, scores facing as the cosine of the off-axis angle, casts a fan of
rays across the swell direction ±15° and multiplies facing by the fraction that
reaches open water. Green ≥ 0.70, yellow ≥ 0.40, orange ≥ 0.20, red below.

It is geometry and nothing else — no bathymetry, refraction, wind or tide — so
read it as a shortlist of where to point the forecast, never as a call. Two
labels matter in the output: the land mask's `source`, `status` and
`fetched_at`, and the count of segments dropped because the mask could not
settle which side was seaward. Those segments are dropped, never guessed, and
Natural Earth 50m is coarse enough that a finer local mask via `--land` changes
the answer. Output is a KMZ because Google Earth Pro does not read GeoJSON.

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

## Access is a cost, not a filter by default

Apply any travel time, budget or access limit stated in the prompt. Without one,
travel cost and mode ride along with the call instead of silently excluding a
spot. Print the price and let the user decide.

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

A grid is never the deliverable for a decision call. A requested exposure map
or KMZ is the deliverable for a discovery question; do not force it into the
one-call format.

Always give size in feet, and never conflate the three numbers called "size".
Offshore Hs is what the models and the calibration cache store, and a 15 ft
offshore Hs is not a 15 ft wave. Nearshore Hs is `score.size()`'s
`Component.raw`, post-refraction — the honest number, prefer it. Face height is
what a surfer means and the system does not compute it; ~1.5x nearshore is a
convention, flag it as one. Label the axis: "4 ft offshore Hs (~6 ft faces, by
convention)", never a bare "4 ft".

Model wind is blind to terrain. A wind gate from David's East Coast barrel days
(8-20 kt, within 25 deg of offshore) scored Kommetjie 3/5 at 39.9% of days and
Llandudno 5/5 "PERFECT" at 0.0% — an inversion. Llandudno and Sandy Bay are coves
backed by the Twelve Apostles, where the prevailing SE lands offshore in the bay;
a ~25 km 10 m model wind cannot see a mountain. Trust a wind score only on open
coast with no upwind relief; check topography first (GMRT carries it, on a quota
separate from Open-Meteo), and where there is relief say the wind is untrustworthy
rather than scoring the spot zero. Generally: before trusting any global field as
a ranker, score his own logged spots with it. If it cannot reproduce his ratings
on ground he has surfed, it cannot rank ground he hasn't.

A rating means what David said it means. The note is the evidence; do not infer
a reason he did not give, and never read emotion into a rating. Sandy Bay was
corrected from 5/5 to 3/5 because one sketchy doggy-door was not a good session.
Kommetjie 3/5 was "the spot could not hold it and I barely surfed", not "it was
too big for me"; he thought it was super fun. A low rating usually means the day
did not work, not that he was overmatched. When he corrects an interpretation,
write it into the log row — a wrong note poisons every later call and every
calibrate run.

Ground every size in his log. Join `data/cache/calibration/*.json` to
`data/sessions.tsv` and place the forecast on a sorted ladder of his own rated
sessions, with his notes quoted alongside. That visual works; keep using it.

ASCII is for magnitude only — one axis, sorted, bars proportional to a number.
Do not draw coastline schematics, wind roses or propagation maps; David on one:
"this looks like shit." Geometry is a sentence: "106 deg into a 95 deg shore
normal is 11 deg off-axis, so Plum Island takes it nearly square."
