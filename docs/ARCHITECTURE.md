# Architecture

What the system is, how the code is laid out, and what gets built next.

## Goal

Build a surf research system that lets an AI answer natural questions with
deterministic scientific tools, backtested evidence, and explicit uncertainty.

## Philosophy

The AI should work like a strong field researcher, not a chat wrapper around a
forecast API. Start with imagery and broad geometry, eliminate impossible zones
cheaply, then use measured waves, wind, bathymetry and history to corroborate
what appears plausible. A candidate remains a hypothesis until independent
evidence supports the mechanism and a held-out test beats the baseline.

Use tools real coastal researchers use, but keep the loop tight. Expensive
physics earns its place only after cheap evidence has isolated a real question.
Automation comes after a setup is understood well enough to state and test.
Rank zones by the historical overlap of required conditions, not isolated
averages. A swell climate is irrelevant when the matching wind rarely occurs.

Examples:

- "I have a week off. Where should I fly tomorrow?"
- "Where on the northeast Brazil coast gets repeatable long-period swell?"
- "How does this weather pattern change the season, and why are we flat now?"
- "Show coastline exposed to a 180 degree swell in Google Earth."
- "Alert me when this reef's exact swell, wind, and tide setup appears."

The AI is the researcher and interface. The `surf` package is the auditable
calculation layer. Claude skill, MCP, mobile, and scheduled jobs should all call
the same tools and receive the same evidence.

```text
natural prompt
    -> explicit objective and constraints
    -> cheap geographic and climate screen
    -> candidate verification
    -> historical backtest
    -> current forecast
    -> one decision, visual artifact, or saved alert
    -> later verification against what happened
```

Do not build separate logic for chat, CLI, KMZ, and alerts.

## The four jobs

### Decide

Choose a place and time for a real trip. Inputs include departure point, travel
window, cost, access, desired wave type and tolerance for uncertainty. Output
one call, alternatives only when the evidence is close, and what would make the
call wrong.

### Discover

Narrow a coastline to plausible zones, then prove or reject them. Output can be
a KMZ, candidate coordinates, bathymetric profiles, or a dated research note.
A dramatic ledge is not automatically a surf spot.

### Diagnose

Compare a weather system with the historical seasonal baseline. Explain whether
a run of surf or a flat spell comes from swell generation, track, period,
direction, blocking, local wind or their failure to overlap. Rank zones by the
frequency and duration of complete surfable setups, not swell alone.

### Watch

Save a verified setup as conditions, not as prose: swell partitions, direction,
period, size band, wind, tide, model agreement and lead-time limits. Scheduled
jobs evaluate the same condition and send an alert only when the evidence clears
its threshold.

## Where the code lives

`surf/` is the auditable calculation layer. Every entry point is a CLI
subcommand in `cli.py`; nothing else is a public surface.

| Module | Holds |
|---|---|
| `cli.py` | Every subcommand and its argument parsing. The only entry point. |
| `call.py` | The decision: rank a region and window, commit to one answer. |
| `score.py` | The four axes. Iribarren, breaker classification, band scores. |
| `waves.py` | Shared wave arithmetic — dispersion, wavelength, bearings, units. |
| `geometry.py` | Beach slope fitted from the sea floor, cached to `spots.tsv`. |
| `bathymetry.py` | Sea floor sampling and its stated resolution. |
| `exposure.py` | Coastline segments, seaward normals, land shadow, KMZ. |
| `spots.py` | Reads `data/spots.tsv`, name normalisation, provenance. |
| `sessions.py` | Reads and appends `data/sessions.tsv`. |
| `calibrate.py` | Scores the log against the model. The personal backtest lives here. |
| `forecast.py` | Model forecast assembly and status. |
| `open_meteo.py`, `ndbc.py`, `tides.py`, `surfline.py` | One source each. |
| `sources.py` | Preflight, circuit breaking, per-source status. |
| `response.py` | The labelled result object every command returns. |
| `daylight.py` | Sunrise, sunset, usable light. |

Two rules hold this together. A source module knows only its own endpoint and
never scores anything. A scoring module never fetches. Anything that reaches the
network returns a labelled status, never a bare number.

New work lands as a subcommand with a test, or it stays in the scratchpad. A
one-off that answered a question is not a deliverable; the answer is.

## Product model

Settled 2026-09-03. These are decisions, not options. Change them by writing a
correction here, not by quietly building something else.

### Two tiers, not three

A **zone** is a region that shares a swell window and a wind regime — Sagres,
the Ceará north coast, Point Judith. Climatology attaches here: a 32-year ERA5
swell/wind overlap is a zone-level fact and running it per break is waste.

A **setup** is a mechanism at a piece of geometry — a slab, a bar, a wedge, a
reef, a point. Bathymetry, aspect and slope attach here. `data/spots.tsv` is the
curated, provenance-carrying subset of setups; discovery proposes candidates,
a human promotes them to rows.

One setup on two different swells is still one setup. The regime is a field on
the session, not a new object. The log already needs this: Kommetjie is a 5/5
and a 3/5, and the note says the 3 is about one oversized day, not the spot.

### The band is a floor, never a target

The session log defines the **minimum** worth the user's time, per setup type.
It does not define the top. The log is dominated by Lido Beach and NJ beach
breaks, so its upper edge encodes what was reachable from where the user lived,
not what he wants. Ratings also track SIZE (+0.67), not BARREL.

Bands are per setup type. Beach breaks and bars have real data. Slabs and points
have almost none, so their band is a stated assumption from the physics —
Iribarren, depth-limited breaking, the shelf criterion — labelled as convention.

### The ceiling comes from events and archetypes, below sessions

A **reference event** is a named swell with hindcast conditions attached, whether
or not the user was there: Monster Monday NJ 2023-12-18, the Long Island swell he
watched from Montauk, the Portugal day on the same storm. An **archetype** is a
canonical setup with its bathymetry and working conditions: Uluwatu, J-Bay,
Tonel, The Box, Shipsterns.

Both sit *below* sessions on the evidence ladder. An archetype says what a wave
is. The log says what the user likes. Conflating them recommends Shipsterns to
someone whose own log carries the note "do NOT use as evidence he wants slabs."

Open: `RECON.md` has 44091 Barnegat maxing at 24.5 ft / 11.8 s on 2016-01-23,
while 44008 Nantucket hit 34.3 ft / 14.8 s on 2023-12-19 — the Monster Monday
storm. Whether NJ's best-known modern event was also its biggest offshore is
unsettled and needs a direct 44091 pull. Belmar carries 27.1 ft of Hs at 100 m,
so NJ is not depth-capped at that size; the ocean is the constraint, not the sand.

### REACH is a separate axis

Track what the user can actually ride, and move it. The ratchet keys off his
largest session rated **4 or better**, not his largest session — the biggest day
in the log is a 3/5 where he was not really surfing, and ratcheting off that
clears him for something he already demonstrated he could not ride.

Surface conditions at most one step above that mark. Every logged session moves
it with no extra input. REACH stays visible next to SIZE, BARREL, CLEANNESS and
CONFIDENCE and is never multiplied into them.

Logistics are costs, not filters. Cold water is a tax that a big enough wave can
outrank — 5 mm boots and gloves are acceptable, not disqualifying. Hard-filter
only what makes a trip not happen: unreachable in the travel window, or unsafe
or illegal to enter.

### Imagery does two jobs with different reliability

Pixels are georeferenced, so a swell line's wavelength is measurable in metres
and `L₀ = gT²/2π` gives deep-water period from the image alone. Scale is the
whole game: an unscaled crop cannot tell a 4 s lake ripple from a 13 s point.

**Static geometry** — reef outline, channel, bar shape, how far the NJ groins
push the bars, rock versus sand. Readable on any cloud-free pass, 30+ frames a
year per candidate. Runs on everything the shelf scan proposes and kills most of
it cheaply.

**Dynamic wave state** — swell lines, measured wavelength, whitewash fraction,
clean A-frame versus mush. Needs a clear pass coincident with swell. For a setup
that fires six days a year that is roughly one usable frame every year or two,
so it is opportunistic confirmation on survivors, never the primary screen.

Report them separately. Merged, a null result cannot distinguish "the reef is
unresolvable" from "no swell arrived during a clear pass."

### The lexicon is a built artifact

The log's densest signal is its language. *Walled out, racy, spitting, grovel,
sucking up, punchy, mushy, closed out, logable but clean, weak tubes, could not
hold the swell, needed a gun.* Each is a claim about physics: peel angle,
Iribarren, size-to-capacity ratio, depth-limited breaking at that setup.

Build the mapping so a natural query becomes a physical filter. Physics first,
the user's usage as a sanity check — with 22 cleanly resolvable sessions most
terms have one to three examples. A term without enough sessions is labelled
convention, not measurement. If the sessions using a word do not cluster in the
quantity claimed, the mapping is wrong and says so.

### Backtest in this order

1. **Personal.** Replay the logged sessions and check the tool ranks the 5/5
   days above the 2/5 days. Available today, hours not weeks, and it is the gate
   that already caught a model which inverted the user's own ratings. Nothing
   downstream is trustworthy until this passes.
2. **Climatological.** Hold out whole years and whole areas, beat an orientation
   and swell-only baseline. This is what makes a discovery claim defensible
   rather than a plausible story.
3. **Operational.** Freeze issued forecasts and score them later. A by-product
   of alerts running normally, not a build step.

### The log needs repair before it is the filter

43 rows, **22 cleanly resolvable** to a (date, place) hindcast lookup. The rest
carry `????` dates, `unknown` spots, `NEEDS YEAR`, `NEEDS SPOT` or an ambiguity
note. `Kommetjie` and `Kommetjie, Cape Town ZA` are two strings for one place;
so are `Lido Beach NY`, `Lido Beach NY?` and `Lido Beach Town Park NY`.

Resolve mechanically what can be resolved — name collisions, the leap-year row,
dates recoverable by joining a candidate window against hindcast when only one
day in it had surf. What remains is a short list of questions only the user can
answer, and it is six to eight items, not 21.

## How a real investigation should work

1. **Define the decision.** Turn the prompt into region, dates, travel limits,
   target wave type and acceptable risk. Never hide these choices in a score.
2. **Screen cheaply.** Use coastline orientation, land-shadow ray casting,
   swell-sector climatology and imagery to remove impossible coast quickly.
3. **Join conditions in time.** Wave, wind and tide must come from the same
   timestamps. Swell-only rankings have already failed in Ceará and globally.
   Measure joint overlap by month and weather-system class. If usable swell and
   wind never coincide in a season, reject that spot for that season.
4. **Inspect the place.** Use imagery for coastline shape, access, cliffs,
   channels and visible breaking. Use bathymetry to corroborate underwater
   geometry, at its measured resolution.
5. **Escalate physics only on survivors.** Period-dependent exposure first;
   ray or fast nearshore transformation second; SWAN or phase-resolving models
   only for a finalist whose geometry and observations justify them.
6. **Measure probability honestly.** Report hours, days, independent events,
   duration, season, local hour and fraction of years with an event. A mean can
   hide one freak year.
7. **Backtest against a baseline.** Every new rule competes with the current
   system on held-out years, known breaks and matched non-break controls.
8. **Return a usable object.** A call, KMZ, shortlist or alert condition, plus
   provenance, uncertainty and a falsifier.

## Evidence ladder

Prefer evidence in this order:

1. What happened at the break: structured session note, camera or local sensor.
2. Nearby measured waves and wind: buoy, gauge or station.
3. Feature-resolving bathymetry with source resolution and vertical datum.
4. A validated local transformation from offshore conditions to the break.
5. Regional forecast or reanalysis.
6. Geometry-only or visual inference.

Lower evidence can nominate a place. It cannot silently become confirmation.

## Guardrails learned from failures

- Keep SIZE, SHAPE/BARREL, CLEANNESS, CONFIDENCE, access and cost separate. The
  user's prompt supplies the tradeoff. The live product must not silently
  multiply them into a universal quality score.
- Offshore significant wave height, nearshore significant wave height and face
  height are different quantities. Always name the one being reported.
- Do not use a fixed angular swell cutoff. Refraction and wrap depend on period.
- A regional wind grid cannot resolve a mountain-backed cove. Where terrain can
  redirect wind, mark it unverified instead of scoring it as bad.
- Coarse or interpolated bathymetry cannot prove a reef, slab or channel. A
  feature must span multiple independent source cells and survive smoothing and
  resolution perturbation.
- Bathymetric focusing is not surfability. Reject cliffs, simultaneous
  closeouts, diffuse breaking, inaccessible rocks and features without a usable
  line or channel.
- Do not fit the model to the small personal session log. Use the log to falsify
  rules, anchor preferences and compare a forecast with remembered conditions.
- Preserve missing values. No source failure, unknown datum or uncertain date
  becomes a plausible estimate.
- Every result carries source, fetch time, model run, lead time, spatial
  resolution, status and what was dropped.

## Backtesting means two different things

### Discovery and climatology

Use synchronized historical waves, wind and tide. Hold out entire years and
entire geographic areas; adjacent hours from one storm are not independent.
Compare against simple orientation and swell-only baselines. Evaluate precision
among the top candidates, known-break recall, false positives, event frequency
and year-to-year repeatability.

For seasonal diagnosis, compare each weather-system class with the same
month's baseline. Report the change in complete surfable hours, independent
events, duration and fraction of years. Persistent trade winds can eliminate a
zone even when swell exposure looks strong. Do not eliminate terrain-sheltered
spots from coarse wind alone.

### Operational forecasts

Reanalysis of the past is not a forecast backtest. Freeze each issued forecast
before the event with:

```text
issued_at, valid_at, model_run, lead_hours, spot, predicted components,
source status, geometry version
```

Later join it to buoy and session observations. Score error by lead time, region,
period, direction and size band. Scheduled alerts can create this archive as a
by-product of normal operation.

## Shipped: exposure KMZ

Built. `surf/exposure.py`, wired as `surf exposure` and the `surf-exposure`
entry point. Kept here because it is the reference shape for every tool that
follows: one bounded question, one geometric answer, no forecast smuggled in.

It is deliberately simple.

**Input:** coastline GeoJSON and swell direction.

**Stack:** Python, `shapely`, `pyproj`, `simplekml`.

**Process:**

1. Split coastline into 200 m segments.
2. Calculate each segment's seaward normal.
3. Compare the normal with the selected swell direction.
4. Cast rays across `swell_direction +/- 15 degrees`.
5. Mark rays blocked by land polygons.
6. Calculate `exposure = facing_score * unblocked_ray_fraction`.
7. Color segments: `0.70-1.00` green, `0.40-0.69` yellow,
   `0.20-0.39` orange, `0.00-0.19` red.
8. Export a styled KMZ.

```bash
surf-exposure coastline.geojson --swell 180 --output south.kmz
```

Done when south-facing unobstructed coast is green and sheltered or opposing
coast is red.

Bathymetry, refraction, wind, tide, forecast APIs, a UI and a database stay out
of it. Its result is a geometric screen, not a surf forecast.

## Build order

1. Repair the session log to the point where the band is trustworthy, and add
   the regime field. Everything else reads this.
2. Personal backtest: replay the log, refuse to proceed while a 2/5 outranks
   a 5/5.
3. Build the lexicon mapping the log's language to physical quantities.
4. Promote the two reconnaissance calculations that have already run in two
   geographies — the ERA5 joint swell/wind overlap by cell, and the bathymetric
   shelf scan — into tested CLI subcommands over a derived cache. Everything
   else stays scratch.
5. Static-geometry imagery on shelf-scan candidates, as a separate tool from
   dynamic wave state.
6. Reference events and archetypes, kept below sessions on the evidence ladder.
7. Expose the tools through one thin MCP surface for Claude and mobile use.
8. Add frozen forecast snapshots and outcome verification.
9. Add saved-query scheduling and alerts using the same tool calls.
10. Test one physical response table at one instrumented, high-resolution spot.
11. Add heavier nearshore models only when that test beats the baseline.

Do not build a global high-resolution wave simulation, full spectral archive,
ML surf score, UI or database before the smaller evidence loop works.

## Research worth keeping

- Linklater, Morris and Hanslow (2023) show that slope, ruggedness and
  bathymetric position index can extract reefs, banks, scarps and channels from
  2-20 m bathymetry. Their workflow still includes manual review; it proposes
  terrain objects, not surf spots:
  <https://doi.org/10.3389/fmars.2023.1258556>
- Hegermiller et al. demonstrate reusable SWAN lookup tables from offshore
  height, period and direction to thousands of nearshore stations. This supports
  the response-table pattern, not surf-scale accuracy:
  <https://doi.org/10.1594/PANGAEA.880314>
- Siegelman et al. (2025) report that high-resolution spectral refraction around
  Palau beat a roughly 7 km regional hindcast at reef-edge gauges. The result
  depended on years of local observations and should not be transferred as an
  accuracy promise:
  <https://doi.org/10.1029/2025JC022391>
- SnapWave is a credible fast transformation model for a later single-site
  experiment. It is not a reason to add a model stack now, and its current
  single-frequency treatment is a limitation for multimodal seas:
  <https://doi.org/10.5194/gmd-18-9469-2025>

Everything else from the raw research reports was either unrelated, duplicated
these points, outside the current product horizon, or depended on data the
project does not yet possess.
