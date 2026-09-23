# Recon

Survey results that are too specific for the spot file and too durable to lose.
A spot's geometry belongs in `data/spots.tsv`; an endpoint's quirk belongs in
`DATA-SOURCES.md`. What lands here is the finding neither of those holds: how
big a coast actually gets, how often, and which places are worth a row.

This is the evidence ledger for the discovery workflow in
[`ARCHITECTURE.md`](ARCHITECTURE.md). Record failed hypotheses
and corrections as carefully as successful candidates.

Last survey 2026-09-04.

## US East Coast — how big, how often

NDBC historical, header-parsed, 3-sample median. Sustained peaks, not spikes.

| Buoy | Location | Max Hs | Period | Dir | Date |
|---|---|---|---|---|---|
| 44011 | Georges Bank *(bank, not a coast)* | 41.4 ft | 13.8 s | — | 2007-11-04 |
| 44007 | Portland ME | 36.1 ft | 12.1 s | 125° | 2010-02-26 |
| 44008 | Nantucket SE | 34.3 ft | 14.8 s | 164° | 2023-12-19 |
| 44098 | Jeffreys Ledge | 31.3 ft | 13.3 s | 71° | 2013-02-09 |
| 44025 | Long Island | 30.9 ft | 13.8 s | 81° | 2012-10-29 |
| 44065 | NY Harbor Ent | 30.7 ft | 14.8 s | 102° | 2012-10-29 |
| 44097 | Block Island | 29.4 ft | 14.3 s | 218° | 2011-08-28 |
| 44027 | Jonesport ME | 29.1 ft | 13.8 s | 172° | 2023-12-19 |
| 44005 | Gulf of Maine | 28.9 ft | 12.9 s | 157° | 2023-12-18 |
| 44013 | Boston MA | 27.9 ft | 12.9 s | 86° | 2021-10-27 |
| 44018 | SE Cape Cod | 26.5 ft | 12.1 s | 85° | 2024-04-04 |
| 44091 | Barnegat NJ | 24.5 ft | 11.8 s | 85° | 2016-01-23 |
| 44017 | Montauk Point | 22.7 ft | 10.0 s | — | 2010-12-27 |

### Correction — 44091 during Monster Monday

The direct primary-source pull of the [44091 2023 annual standard
meteorological file](https://www.ndbc.noaa.gov/data/historical/stdmet/44091h2023.txt.gz)
was parsed by its `#YY MM DD hh mm ...` header, not fixed column positions. On
2023-12-19 the raw daily maximum was **3.79 m / 12.4 ft**, but it was one sample.
The required centred three-sample median gives **3.51 m / 11.5 ft at 13.33 s
from 139° at 04:56Z**. The adjacent storm peak was on 2023-12-18: a sustained
**5.82 m / 19.1 ft at 12.5 s from 121°** at 11:56Z. The earlier raw-peak
number was wrong as an event maximum because it promoted a single record over
the sustained signal; it remains here as the raw comparison, not the corrected
record. The existing 2016 44091 all-time value of **24.5 ft** remains the
largest sustained value in this ledger.

The prime band of ADR-018 is rarer than it feels: 6–8 ft at 8–10 s runs 10.9
d/yr at 44097, 9.0 at 44091, 5.9 at 44065, 5.8 at 44098. Rhode Island sees about
five times New York's 10 ft+ traffic.

None of that is a rideable height. Sized by depth-limited breaking, ft of Hs the
water carries at distance offshore:

| Spot | 100 m | 200 m | 400 m | 800 m |
|---|---|---|---|---|
| Cape Small outer ledge | 41.8 | 43.0 | 47.1 | 58.0 |
| Camp Hero, Montauk | 25.9 | 29.4 | 36.1 | 47.5 |
| Belmar | 27.1 | 28.6 | 34.2 | 40.6 |
| Camp Cronin | 24.4 | 26.8 | 29.1 | 28.3 |
| Point Judith lighthouse | 13.6 | 17.5 | 27.2 | 29.6 |
| Lido Beach | 11.9 | 13.1 | 14.3 | 16.2 |
| Squibnocket reef | 6.8 | 9.7 | 14.7 | 18.0 |

Camp Cronin carries 24 ft at 100 m — deep water hard against the point, which is
what lets it hold size. Lido tops out near 16 ft whatever is offshore.

## Offshore banks

Grid-scanned 12,400 NCEI points; crests ≥25 km from land.

| Bank | Position | Crest | Offshore |
|---|---|---|---|
| Davis Bank, Great South Channel | 41.2100, −69.5600 | 8.3 m | 35 km |
| Georges Bank Shoal | 41.6600, −67.7300 | 8.8 m | 182 km |

Davis Bank's SE flank drops `−8.3 → −24.0 m within 1 km`. From 44008 it has
sets breaking on the crest ~17 d/yr, of which ~1.4 d/yr carry ≥13 s. Both are in
`spots.tsv` as boat-access rows.

**Cashes Ledge was missed.** Shallowest reading 21.9 m at 42.890, −68.940;
Ammen Rock's ~9 m spire is narrower than the 1.1 km grid step. Rescan finer
before concluding anything about it.

## Slab candidates

Criterion from The Box and Shipsterns: shelf ≤3 m with ≥15 m water inside 500 m.
Statistical chance is hours with Hs ≥6 ft, ≥10 s, within 60° of aspect.

| Candidate | Position | Aspect | ≥6 ft/10 s | ≥8 ft/11 s |
|---|---|---|---|---|
| Cape Ann / Halibut Pt MA | 42.6880, −70.6200 | 90° | 15.5 d/yr | 6.6 |
| Newport RI outer ledge | 41.4600, −71.2480 | 124° | 12.8 d/yr | 5.4 |
| Schoodic Point ME | 44.3280, −68.0340 | 200° | 10.4 d/yr | 2.7 |
| Monhegan NE ME | 43.7740, −69.3020 | 90° | 10.3 d/yr | 2.6 |

Seaward depth every 50 m:

```
Monhegan NE    -0.8  -3.3  -9.5 -15.7 -23.4 -39.9 -56.1 -74.7 -94.4 -101.5
Schoodic Pt    -0.5  -2.4  -5.1  -7.3 -10.6 -18.1 -24.1 -28.6 -34.3  -42.3
Cape Ann       -0.5  -5.2  -7.5 -11.0 -13.1 -16.8 -21.7 -24.7 -25.6  -26.0
Newport ledge  -1.0  -1.1  -7.7 -12.0 -15.4 -17.0 -17.6 -18.0 -18.4  -18.5
```

Newport is the only flat platform — 1.0–1.1 m for 50 m, then an edge — and it
sits 1,118 m offshore with 11–17 m of water on every bearing. Monhegan has the
most extreme bathymetry found anywhere but is a continuous plunge with no
channel, and breaks against the cliff; probably not rideable. None is in
`spots.tsv` yet: no measured geometry, no session, nothing to calibrate against.

### Boston to Maine pass, 2026-09-04

The supplied James McGraghan screenshot says “This time last year” and is dated
August 20. Treating that as the 2024-08-20 Ernesto swell is a working hypothesis,
not a geolocation. Three-sample median event peaks were:

| Buoy | Peak | Hs / DPD / MWD |
|---|---|---|
| 44013 Boston | 2024-08-20 08:40Z | 4.0 ft / 10.8 s / 88° |
| 44098 Jeffreys Ledge | 2024-08-19 19:26Z | 5.3 ft / 12.5 s / 120° |
| 44007 Portland | 2024-08-19 22:40Z | 5.4 ft / 11.4 s / 130° |
| 44027 Jonesport | 2024-08-19 18:40Z | 6.8 ft / 12.9 s / 158° |

That rotation is the useful fingerprint: Boston-area candidates need east
exposure; southern and midcoast Maine candidates need southeast exposure.

NCEI `getSamples`, 3.4 m source cells, found these shallow-to-deep profiles.
Depth is at the candidate and then at 50 m steps along the listed aspect.
The event-days column is a nomination screen: centred-median NDBC Hs and DPD,
period-dependent analytic transmission, and a default 0.03 reef slope. It is
not a break-level hindcast or proof that the line is rideable. Directional
coverage is 44013 for 2012–2025 (14 years), 44098 for 2008–2025 (18 years), and
44007 for 2007–2025 (17 populated years).

| Candidate | Position / aspect | Profile to first −15 m | ≥6 ft / 10 s transmitted | Disposition |
|---|---|---|---:|---|
| Isles of Shoals south ledge | 42.9755, −70.6308 / 170° | −2.2, −8.7, −19.6 (100 m) | 31.5 d/yr | strongest platform edge; boat; wind and line unverified |
| Cape Ann / Halibut Point | 42.6880, −70.6200 / 90° | −0.5, −5.2, −7.5, −11.0, −13.1, −16.8 (250 m) | 25.5 d/yr | Boston-accessible east window; no isolated line confirmed |
| Cape Small ledge | 43.7068, −69.8325 / 140° | −2.4 to −16.0 (450 m) | 24.9 d/yr | best imagery signature: isolated ledges breaking in calmer water |
| Pemaquid tip | 43.8356, −69.5089 / 140° | −2.6 to −15.2 (300 m) | 24.9 d/yr | exposed but no isolated rideable line seen |
| Cape Elizabeth outer ledge | 43.5416, −70.2249 / 150° | −2.3 to −15.9 (300 m) | 23.5 d/yr | repeated whitewater; line may be a closeout; boat review needed |
| Seguin north ledge | 43.7232, −69.7544 / 150° | −2.9 to −16.2 (300 m) | 23.5 d/yr | direct southeast window; boat and line unverified |
| Biddeford Pool outer ledge | 43.4461, −70.3290 / 80° | −2.4 to −15.2 (200 m) | 22.4 d/yr | best new southern-Maine submerged ledge; channel still unverified |
| Monhegan NE | 43.7740, −69.3020 / 90° | −0.8, −3.3, −9.5, −15.7 (150 m) | 19.4 d/yr | extreme plunge into cliff; reject until a safe line and exit exist |

The shortlist is therefore conditional, not one quality number: **Cape Small**
has the strongest static breaking signature, **Isles of Shoals south** has the
sharpest measured platform edge and highest raw exposure, **Cape Ann** is the
best Boston-range east-swell test, and **Biddeford Pool outer** is the best new
southern-Maine target. The photograph is compatible with Cape Small or another
southeast-facing Maine ledge, but there is not enough visual evidence to name it.

Do not use the existing BARREL component on these. It fits one beach slope and
calls Cape Small “spilling”; on a slab the useful geometry is crest depth,
distance to deep water, the platform edge, a peel line and an exit channel.
Until repeated break-level observations exist, keep SHAPE unresolved and rank
EXPOSURE, SIZE, CLEANNESS, ACCESS and CONFIDENCE separately.

The first focused `surf terrain` pass also mixed land relief into underwater
objects; its strongest Cape Ann hits were on land. The scanner now excludes
positive land elevations from relief and smoothing. A below-sea-level quarry or
pond can still look like water in a topobathymetric DEM, so imagery remains a
required rejection step.

### Correction — the Boston-to-Maine shortlist was not slab proof

This pass overclaimed what its evidence could support. A single radial
shallow-to-deep transect finds an edge, not a slab. It does not show the
plan-view crest, abrupt deep-water approach, lateral taper that could produce a
peel line, or a shoulder/channel/exit. The listed Cape Ann, Shoals, Pemaquid,
Cape Elizabeth, Seguin and Biddeford points return to the **bathymetric
candidate** pool; their event-day counts measure swell access to a bearing,
using a default reef slope, not the probability or quality of a breaking slab.

The four aerial JPEGs exported from this pass are withdrawn as evidence. They
showed the sea surface and nearby coast, not the underwater ground responsible
for the wave. Aerial imagery only advances a candidate when the reef outline is
actually visible or a breaker line can be tied to the exact feature. Chasing
the photographer and Instagram post after that failure moved farther away from
the controlling question and produced no geometry.

Use **Small Point / Cape Small** as the user-confirmed working positive. Resolve
the user's recalled intermittent Rhode Island reef, "called like Mohans"
(possibly **Monahan's Dock**), before using it as a second positive control; the
name alone is not evidence. The next scan starts with high-resolution plan-view
bathymetry and matched non-breaking controls. Promote a result only through explicit
states: `bathymetric candidate` -> `observed breaking on the feature` ->
`verified setup` after repeated independent events with aligned swell, wind and
tide. “Definitely works” is reserved for the last state.

## Ceará — the wind decides, not the swell

ERA5 1994–2025 over eight 0.5° cells, Parnaíba to Tibau.

Long-period (≥10 s) days on the north coast are seasonal to the point of being
binary: Mar 3.9%, Jan 3.8%, Apr 3.2%, Dec 2.3%, Feb 2.4% — and **zero** in June,
July, August, September and November across 32 years. The surf window is Dec–Apr
and it is almost exactly anti-correlated with the kite season.

Aspect sets the spot. Transmission, N groundswell against E trade at 7 s:

| Spot | Normal | N groundswell | E trade |
|---|---|---|---|
| Praia da Malhada, Taíba | 350° | 0.97–0.99 | 0.01 |
| Preá | 20° | 1.00 | 0.04 |
| Praia Principal de Jeri | 280° | 0.19–0.70 | 0.00 |
| Mundaú | 45° | 0.59–0.89 | 0.45 |
| Praia do Futuro | 50° | 0.80 | 0.52 |

Jeri's west-facing bay transmits **0.000** of the trade swell, which is why it
is flat kite water, while passing north groundswell up to 0.70. Period is the
whole mechanism there: the wrap runs 0.19 at 7 s and 0.70 at 15 s.

**Swell alone gives the wrong answer.** The trade is E/ESE on 84–95% of days at
21 km/h mean (33 km/h and 88.7% over 25 km/h at Icapuí). Joining wind inverts
the aspect ranking:

```
aspect    swell-only d/yr    wind-clean d/yr
  45            329                11
  60            359                10
 325             38                17   <-- optimum
 335             63                15
```

Clean is ≥3 ft nearshore with wind inside 60° of offshore or under 12 km/h, on
daily-max wind. **The window is 315–335°, NNW-facing** — it gives up nine-tenths
of the swell days to gain offshore wind and nets more rideable ones. An earlier
recommendation of Ponta Grossa came from the swell-only column and was wrong;
300+ swell days there collapse to 2 clean days.

Time of day is not optional either. Dawn runs 13 km/h with 62–65% of hours under
15; by 08:00 that is 34%, by 10:00 22%. Surf before 07:30 or do not go.

### Coastline scan

OSM `natural=coastline` for the Ceará bbox — 305 ways, 7,147 vertices, segmented
at 300 m into 1,720 segments. The seaward normal is way heading + 90°, because
OSM requires *"land on the left side and water on the right side of the way"*;
no offshore test is needed. Validated on 60 random segments against NCEI, the
normal points to the deeper side 59/60.

Scored 35 ideal (≥14 clean d/yr), 447 marginal, 1,238 rejected. Best segment on
the coast is **−2.7885, −40.5120 at 327°**, about 200 m from Jeri Point.
Nineteen ideal segments sit within ATV range of Preá: −40.51 to −40.58 (Jeri and
west), −40.69 to −40.84 (Guriú), and one isolated at −2.8129, −40.2354 at 326°
east of Preá.

Overlays regenerate into `data/overlays/` and are not committed. Google Earth
Pro takes KML, KMZ, SHP and DAT but **not** GeoJSON; GeoJSON is web and mobile
only, capped at 10,000 features or 250,000 vertices.

## Global spot search — wind decides, and the model cannot see terrain

Asked for the spots worldwide with the highest rate of David's good days,
excluding anywhere he has surfed. Not finished; what is settled is below and the
unfinished threads are in Open.

Method: Natural Earth `ne_50m_coastline` segmented at 250 km gives 1,355 coastal
points between 60°S and 66°N. Seaward normal is the perpendicular whose 4 km
probe falls outside `ne_50m_land` — offline, 1,280 of 1,355 resolved in 1.2 s and
zero API calls. The 75 ambiguous ones are fjords and inlets where both
perpendiculars hit land; they are dropped, not guessed.

The gate is calibrated on David's own 5/5 rows, never asserted:

| | Band | Where it comes from |
|---|---|---|
| Size | 6.4–13.0 ft offshore Hs | all six 5/5s fall in 6.4–10.8, headroom above |
| Period | 8–16 s | spans 8–15 in the log, does almost no discriminating |
| Wind | 8–30 kt within 60° of offshore | see below — and David surfs 20–30 kt offshore |
| Window | ≥3 consecutive daylight hours | one good hour is a gust, not a session |

**Wind speed is the constraint, not wind angle.** Every 5/5 sits between 8.4 and
15.9 kt; off-axis angle ranges 0–66° and separates nothing. An earlier gate built
only from the East Coast rows used 25° of angle, because that is the one region
where offshore wind and flat terrain coincide.

### Swell-only ranking is wrong, again

The Ceará finding holds at global scale. Ranked on swell alone, the leaders are
the Southern Ocean; joining wind eliminates all of them.

| | swell %d | wind window %d |
|---|---|---|
| Kerguelen Is. | 87 | 4.9 |
| Limestone Coast SA | 75 | 15.8 |
| NW Tasmania | 75 | 21.3 |
| Shipwreck Coast VIC | 75 | 16.7 |
| **West Tasmania** | **74** | **1.4** |
| Eyre Peninsula SA | 73 | 11.5 |
| Mid West WA | 62 | 21.3 |
| SW Tasmania | 45 | 25.7 |

West Tasmania is the case to remember: 5th in the world on swell, 0.9% of
daylight hours offshore. The Roaring Forties make the swell and then sit on it.
Kommetjie 23.0% and Belmar 20.8% are the bar — those are 5/5 spots — so only
NW Tasmania, Mid West WA and SW Tasmania cleared it, and SW Tasmania is Port
Davey wilderness with no road.

### The wind gate was falsified by his own best spot

Scoring the Cape Town rows before ranking anything caught an inversion:

| | rating | wind window | shelter |
|---|---|---|---|
| Kommetjie | 3/5 *(that day)* | 39.9% | 7/36 |
| Belmar | 5/5 | 27.9% | 0/36 |
| Sandy Bay | 3/5 | 1.4% | 11/36 |
| **Llandudno** | **5/5 "PERFECT"** | **0.0%** | **22/36** |

Llandudno and Sandy Bay sit in coves behind the Twelve Apostles; the prevailing
SE arrives over the ridge and lands offshore in the bay. A ~25 km, 10 m model
wind cannot see a mountain, so it reports the synoptic SE and the gate reads
90° cross-shore. The Sandy Bay row logging 13.5 kt at 90° off offshore is not an
outlier, it is the model failing.

Correction: sample the horizon angle out to 5 km on 36 bearings from GMRT
topography, and where relief upwind exceeds 6°, report the wind as
**unverifiable** rather than scoring it zero. Llandudno is blocked on 22 of 36
bearings and unverifiable 97.8% of hours; Belmar and Lido are 0/36 and their
numbers stand. With the correction the anchors rank Llandudno 32.5, Kommetjie
29.2, Sandy Bay 17.8 — David's own order.

The method therefore **cannot find the next Llandudno**, only the next
Kommetjie. Any cove that works because of terrain reads as unrankable.

### What this cost, and what not to repeat

Four self-inflicted failures, all of them avoidable:

- **Ranked on swell before joining wind.** Produced a confident Southern Ocean
  list that the wind gate then deleted. The Ceará section already said this.
- **Built the gate from one region.** East Coast rows only, so angle looked
  decisive and every sheltered cove scored zero.
- **Ran seven agents in parallel against one rate-limited account.** Quota is
  per-account, so concurrency multiplies 429s; all seven stalled in stage 1 and
  none finished. This was predicted in the same session and done anyway.
- **Filtered on the scarce signal first.** Swell has a hard daily cap and wind
  does not. Wind is also the binding filter. Cheap-and-binding goes first.

None of these were new discoveries. `ARCHITECTURE.md` already says
*"expensive physics earns its place only after cheap evidence has isolated a
real question"* and *"a swell climate is irrelevant when the matching wind
rarely occurs"*, and the Ceará section above had already inverted a swell-only
ranking by joining wind. The rule was written down; it was not read before
scoring 2,942 points the expensive way round.

## Ceará — marks drawn by David, 2026-09-04

Eleven annotations drawn by hand in Google Earth Pro over the wrap maps, read
straight out of `myplaces.kml`. His words are kept verbatim; they are the
evidence, and paraphrasing them loses the judgement.

| His mark | Position | Nearest known spot | Model exposure | Model wrap |
|---|---|---|---|---|
| sick left sand bar | -3.1802, -39.3843 | none within 31 km | 0.68 | 0.19 |
| reef | -3.1711, -39.3619 | none within 30 km | 0.99 | 0.03 |
| reef | -3.2051, -39.3070 | none within 23 km | 0.99 | 0.19 |
| slab | -3.2139, -39.2873 | none within 21 km | 0.93 | 0.10 |
| one of the dopest setups weve seen yet | -3.3443, -39.1328 | Mundaú 2.0 km | 0.95 | 0.08 |
| big white wash | -3.3955, -39.0005 | none within 16 km | 0.96 | 0.11 |
| bigger white wash | -3.3955, -38.9953 | none within 16 km | 0.95 | 0.20 |
| ive surfed here the first time looks good all year | -3.5053, -38.9044 | Taíba 0.3 km | 0.99 | 0.13 |
| potential good option by my crib | -2.7883, -40.5126 | Malhada 0.7 km | 0.74 | 0.38 |
| this is a good zone tide dpeending maybe to flat but looks like in swell seasson maybe | -2.8098, -40.4262 | Preá 2.1 km | 0.98 | 0.04 |

Four of these — the sandbar, both reefs and the slab — sit in a 12 km cluster
between -3.17 and -3.21 with **no spot in the database within 20 km**. They are
now rows `guajiru-sandbar`, `guajiru-reef-w`, `guajiru-reef-e`, `guajiru-slab`,
positioned from his drawing with the shore normal measured off the OSM
coastline rather than inferred from the line. None has been visited.

His lines are inconsistent in what they trace — some run along the wave (the
peel), some run seaward. `big white wash` and `bigger white wash` are drawn
across the shore, the rest along it. So a drawn bearing cannot be read as a
shore normal without knowing which the author meant, and it is not treated as
one anywhere.

### The sea floor here is bimodal, and neither mode is in any grid we have

David's own observation, worth more than the bathymetry we can reach: on this
coast the water **either drops off very fast or stays very shallow a very long
way out**, with little in between. River mouths and channels go deep quickly.
The sand bar fields stay shin-deep hundreds of metres out, and a little south
of Preá the beach goes flat and the water walks out a very long way on a low
tide.

That is a tidal-range and bar-trough regime, and it means two things. A single
"beach slope" number is the wrong shape of answer for this coast — the same
spot is a steep drop and a flat flat depending on which side of the bar you
stand. And the 463 m grid cannot see either mode: it averages the channel and
the bar into one meaningless gradient. Every Ceará row therefore carries a
placeholder slope with `default` provenance, and the Iribarren number must not
be trusted at any of them.

### Sentinel-2 cannot see the surf season

The swell window and the clear-sky window are opposites here. Scenes with
cloud below 10%, 2017-2026:

| | Jul-Oct | Dec-Apr |
|---|---|---|
| Jeri | 75 | 7 |
| Flecheiras | 81 | 0 |

Dry season is kite season. The groundswell months are the wet months, so any
imagery-based confirmation of a Ceará setup is scraping a handful of usable
frames per decade, and must relax cloud cover to ~25-45% to find any at all.
This is a hard ceiling on imagery as evidence here, not a search problem.

Usable long-period frames actually found (swell period at -2.70, -40.45):

| Date | Tp | Cloud | Zone |
|---|---|---|---|
| 2026-01-30 | 14.9 s | 22% | Jeri |
| 2022-12-02 | 12.7 s | 5.6% | Jeri — the cleanest in the record |
| 2025-12-11 | 12.0 s | 25% | Jeri |
| 2022-12-07 | 11.4 s | 21% | Jeri |
| 2022-12-09 | 10.2 s | 18% | Flecheiras |
| 2024-12-18 | 9.8 s | 23% | Flecheiras |

The 2022-12-02 frame shows whitewater wrapping the Jeri point and running down
the west-facing beach; the 2024-04-25 control at 5.8 s over the same box shows
almost none. That is the wrap, photographed.

### Satellite-derived bathymetry at Jeri — relative yes, absolute no

Tested 2026-09-04. Stumpf log-ratio SDB from Sentinel-2 L2A, calibrated against
breaker-line depth inversion, over a 3.3 x 2.7 km box at Jericoacoara. The aim
was a depth grid fine enough to shoal and refract with, replacing the 463 m
GMRT grid. **The relative surface works and the absolute scale does not.**

What worked. A 31-frame composite of `ln(1000*Rblue)/ln(1000*Rgreen)`, tile
24MUC only, each scene levelled on a common 600-1600 m offshore band, median
27 clear looks per cell at 10 m:

| Distance offshore | pSDB | composite SEM |
|---|---|---|
| 50-100 m | 0.9724 | 0.0085 |
| 100-200 m | 0.9791 | 0.0061 |
| 200-400 m | 0.9857 | 0.0044 |
| 400-800 m | 0.9927 | 0.0033 |
| 800-1600 m | 0.9995 | 0.0029 |
| 1600-2400 m | 1.0052 | 0.0034 |

Monotonic across the whole shoreface, signal 0.0320 against a 0.0032 noise
floor — **SNR ~10**. 69% of the box resolves; 4,164 water cells stay
unresolved (turbid, foam or cloud) and are left as holes.

What failed, and why it is structural rather than a tuning problem.

**Breaker-line inversion does not survive its own leave-one-out.** Komar &
Gaughan `Hb = 0.39 g^0.2 (T H0^2)^0.4` on the eleven surf-season frames with
known swell and tide yields only four breaker lines that also have a resolved
pSDB. Dropping any one of the four swings the correlation from -0.99 to +0.99
and the slope from -73 to +457 m per pSDB unit. Across a looser nine-frame set
the fit implies depth *decreasing* offshore. It is noise.

The reason is self-censoring: the breaker line is whitewater by definition, and
whitewater violates the clear-water assumption Stumpf rests on. Cells that are
ever whitewater average **one** clear look; with 7 frames only 41% resolve at
all. The two methods are asked to meet exactly where one of them cannot see.

**Waterline calibration is below the noise floor.** The land/water edge sits at
`d_MSL = -eta`, so 2.18 m of tidal range across eleven frames should trace the
foreshore for free. It spans only 0.0042 of pSDB against a 0.0032 composite
noise floor — SNR 1.3. With eight constraints the correlation is ~0. An earlier
six-point subset gave r=+0.86 and was an artifact; more frames destroyed it.

**Waterline migration is below the pixel.** 2.2 m of tide moves the waterline
0-20 m, i.e. 0-2 cells at 10 m. The `jericoacoara` transect fits r=-0.90 with
the wrong sign. Resolving the foreshore this way needs ~3 m pixels, not 10 m.

**Season mismatch is a confound on top of all of it.** Low-cloud frames are
scarce Dec-Apr (8 usable of 11 queried) and plentiful May-Nov (23 of 56), so
the composite is mostly dry-season while every breaker constraint is
wet-season. On the bar-trough coast described above, the bars need not be in
the same place, and nothing here can tell whether they were.

**The tide dominates the wave signal.** Across the frames `Hb/gamma` spans only
0.65 m while the tide spans 2.05 m, so 76% of each inverted breaker depth is
just sea level — a quantity already known from Open-Meteo. The imagery is
contributing the smaller and noisier quarter.

Consequence: no absolute depth grid was produced, so no shoaling or refraction
was computed at `jeri-point` and nothing was written to `spots.tsv`. Wiring a
relative surface into `Response.transmission` would put a guessed vertical
scale under every size number, which is the estimate-shaped hole the invariants
forbid. `jeri-point` keeps its `default` 0.020 placeholder and its degraded
geometry receipt.

#### Traps this run fell into — do not repeat

Every one of these produced a confident, wrong-looking answer before it was
caught. They cost more time than the physics did.

**Do not count pixels as independent samples.** Every pixel in one scene's
waterline shares a single depth, so a pixel-level fit reported n=4,627 when the
true n was 11. That inflates R² and hides that the whole result rests on a
handful of frames. Aggregate to one constraint per scene per method, then fit.

**Do not choose a quality threshold after seeing the result.** The breaker fit
reads r=-0.21 over 9 frames, +0.70 at cloud<15%, +0.81 at cloud<10%, +0.15 on
another subset. Picking the threshold that produces a positive correlation is
p-hacking a sign into existence. Fix the gate first, or report the whole family.

**Always run leave-one-out on a small fit.** The n=7 breaker fit looked
respectable at r=+0.70 until dropping one frame collapsed it to r=+0.13 and
moved the slope from 1:112 to 1:501. A single frame carried it. With n under
~10 an r value alone means nothing.

**Cloud leaves the water mask rather than showing up in it.** Cloud is
NIR-bright, so a "cloud over water" fraction reads ~0 on a solidly overcast
frame while the water fraction quietly collapses. Judging clarity by that flag
passed two frames whose "breaker line" at 0.5-1.3 km offshore was cloud edge.
Nothing breaks in 20 m of water — a bimodal breaker distance is the tell.

**Foam thresholds must be scene-relative.** A fixed NIR cutoff catches the
turbid tail of a hazy frame and calls it whitewater. Set the threshold from
each scene's own water NIR distribution; ambient turbidity moves between frames
by more than the foam signal.

**Read the drop list against the query pool, not on its own.** Every frame
rejected for cloud fell in May-Nov, which looks like "Dec-Apr is the clear
season" and is the opposite of the truth: Dec-Apr had a high pass rate (8 of
11) over a tiny pool, May-Nov a low rate (23 of 56) over a large one. A
rejection list without its denominator inverts the conclusion.

**Look at the pixels before trusting any mask.** One rendered frame settled in
seconds what the summary statistics had been getting wrong for several
iterations. `eo:cloud_cover` is already known to lie here; so can your own
masks.

What would actually move this: metre-scale imagery (PlanetScope ~3 m) so the
waterline resolves against tide, or a real sounding — a single depth-sounder
track across the point would anchor the whole relative surface in one pass.

## Global warm-water tubes — correction and proof boundary

The 2026-09-04 ranking that called Zicatela, Maresias, Itacoatiara, Mandiri,
Durban, Cacimba and Playa Hermosa consistent tube destinations is withdrawn.
None is a row in `spots.tsv`, and the MCP `climate` tool accepts only a stored
zone with fixed thresholds. The reported custom-band "matching windows" are
therefore not reproducible through the current MCP surface.

The personal evidence is narrower than that ranking implied. The cached MCP
`calibrate` call recovers 29 usable sessions and six resolved 5/5 anchors, but
only two explicitly report an NJ barrel: Belmar on 2024-04-04 ("spitting
tubes") and 2024-04-13 ("got barreled"). Their fixed-offshore-cell reanalysis
was respectively 2.04 m at 6.95–7.05 s from 89–91°, with 5.24–5.59 m/s wind
from 297–305°, and 1.56–1.68 m at 8.1–8.2 s from 142–147°, with 7.72–8.17 m/s
wind from 262–266°. These are offshore reanalysis conditions, not face height.
Two events at one shifting sandbar cannot define a climatological barrel class.
The same run gives `rho(rating, barrel)=-0.07` and `rho(rating, size)=+0.60`;
`lexicon("pumping tubes")` fails, while `spitting` is only an `n=1`
convention. The log anchors taste, but the present barrel score does not learn
it.

`climate` is only a cheap environmental screen. It counts an hour when the
ERA5 Ocean **total** wave field is at least 1 m and 10 s and regional wind is
calm or within 60° of offshore. It does not require swell direction to face the
coast, daylight, consecutive hours, tide, a bar/reef, A-frame geometry, a
breaking-wave transformation or an observed barrel; its event grouping can
bridge gaps up to six hours. Every 2021-12-01–2025-12-31 result is correctly
`degraded` because total wave is substituted for swell and terrain shelter is
unverified. Thus Belmar's 22 events/30 days, Beliche's 247/434 and Kommetjie's
399/696 are potential wave/wind overlaps, not tube counts and not comparable
destination probabilities.

The strongest tropical lead inside the personal log is therefore Playa
Langosta, not one of the unvisited global nominations. David actually surfed
the 2024-01-16 morning there and separately remembers a pumping sunset that
trip as a best-ever day, although its date is unresolved and the note does not
say it barreled. The resolved morning reanalysis agrees with "offshore, kind of
small": a 0.86 m / 9.4 s swell partition from 195° and 4.85 m/s wind from 58°.
Adding the missing direction gate to the coarse climate screen leaves 522 days
in four complete years with at least one >=1 m, >=10 s hour arriving within 60°
of the stored 255° shore normal and calm/offshore regional wind. May has 97 of
those days and September 62 across the four years. This makes Langosta the
best-supported **lead** in the current data, but not a proven consistent tube
destination: the pumping session cannot be joined to a date, and there is no
observed barrel, A-frame, bank state, tide or SST attached to it.

The Zicatela number has the same category error. A direct run through the
repo's `OpenMeteoClimate` adapter at 15.80, -97.08 returned 35,808 shared hours,
status `degraded`, fetched 2026-09-04T05:11:35Z. The 2022 maximum was **4.06 m /
13.3 ft total offshore Hs** (2022-05-30 13:00Z); the four-year 99.9th percentile
was 3.02 m / 9.9 ft. That neither caps nor estimates breaking face height,
maximum individual wave, biggest ridden wave, or the spot's historical record.
The prior 9.1 ft figure was only a maximum inside an arbitrary filter. Outside
the NDBC archive already surveyed above, the current system has no global
measured-wave record from which an all-time spot maximum can be defended.

Warm water is also untested: no MCP tool or stored spot field carries SST.
"A-frame" and "hidden/nobody knows" are untested too; the available dynamic
imagery path requires supplied coincident frames, and no popularity evidence is
in scope. A candidate can be nominated only. Promotion to a destination claim
requires repeated break-level observations across independent events and
years, synchronized local wave/wind/tide, bottom or bar evidence, SST, and a
held-out comparison against known breaks and matched non-break controls.

## Global barrel search, wind-first — 2026-09-04

Asked for a new barrel setup with consistent offshore wind, consistent
long-period swell and a satellite signature matching setups that work, anywhere
not already covered. Run strictly wind-before-swell, which is the ordering three
of the four failures in the section above came from getting backwards.

**Excluded before any API call:** every `spots.tsv` row within 150 km (16 points,
touching `jericoacoara`, `point-judith`, `carcavelos`, `llandudno`, `lido-beach`,
`playa-langosta`, `ponta-grossa`, `spring-lake`, `plum-island`, `cape-small`,
`lawrencetown`, `beliche`) and 17 named RECON regions (36 points: the US East
Coast ledger, Ceara, Cape Town, Algarve/Lisbon, Guanacaste, Noronha, Nova
Scotia, Kerguelen, Tasmania, the SA/VIC coasts, Mid West WA, and the withdrawn
warm-water nominations Zicatela, Maresias, Itacoatiara, Mandiri, Durban and
Playa Hermosa). 1,040 candidate zone points survived.

### The funnel, and what each stage cost

| Stage | In | Out | Cost |
|---|---:|---:|---|
| Natural Earth coastline at 250 km, seaward normal by 4 km probe | 2,481 | 2,127 | offline |
| Open-ocean fetch >= 800 km mean over an 11-ray 150 deg sector | 2,127 | 1,092 | offline |
| Remove covered ground | 1,092 | 1,040 | offline |
| Wind window, 2025 hourly, daylight only | 600 sampled | 103 | 17 requests |
| Swell, daily total-wave period, 4 years | 103 | 12 | 6 requests |
| **Joint overlap in time** | 12 + 2 anchors | 8 | 2 requests |

Sampling 600 of the 1,040 was a quota decision, not a finding: the sample is a
fixed-seed shuffle, so it is geographically even, but **440 points were never
wind-scored** and the survey is therefore incomplete, not exhaustive.

### The gate is his own log, re-derived on this exact statistic

Scored before ranking anything, wind window as a fraction of daylight hours,
2025, gate 8-30 kt within 60 deg of offshore with a >= 3 h run:

| | rating | wind window | >=3 h days/yr | blocked bearings |
|---|---|---|---|---|
| Kommetjie | 5/5 spot | 38.4% | 154 | 6/36 |
| **Belmar** | **5/5** | **22.2%** | 109 | 0/36 |
| Lido Beach | log-dominant | 14.0% | 79 | 0/36 |
| Sandy Bay | 3/5 | 11.4% | 62 | 16/36 |
| **Llandudno** | **5/5 "PERFECT"** | **8.7%** | 49 | 18/36 |

Belmar, his weakest open-coast 5/5, set the survivor threshold at 22.2%. The
Llandudno inversion reproduces exactly as recorded above — his best-ever session
ranks last of the Cape Town three on model wind — so the terrain correction was
applied throughout and sheltered candidates are carried as **unverifiable**, not
rejected. The GMRT horizon reproduces the earlier bearing counts closely
(Kommetjie 6 against 7, Belmar 0, Lido 0) but not exactly (Llandudno 18 against
22, Sandy Bay 16 against 11); treat it as a flag, not a measurement. Sandy Bay's
stored coordinate needed a 1,700 m seaward snap before it sat in water at all.

### Wind-only leaders are trade-wind lee coasts, and swell deletes them

The wind sweep's top of the table is west-facing coast in the trade belt, which
is offshore precisely because it is turned away from the trade swell — the Jeri
mechanism at global scale. Buying wind first meant these cost almost nothing:

| Position | Zone | Wind window | d/yr >= 12 s |
|---|---|---:|---:|
| -5.609, -155.911 | Line Islands | 91.3% | 4.5 |
| -15.957, -5.775 | St Helena | 83.3% | 10.2 |
| 18.091, -63.115 | Anguilla | 86.5% | — |
| -18.990, -169.909 | Niue | 66.9% | 8.0 |

### Joint overlap is the only number that ranks anything

Days per year with a >= 3 h daylight run where nearshore Hs >= 1.0 m after the
repo's own period-dependent transmission, total-wave period >= 10 s, and wind
8-30 kt within 60 deg of offshore — wave and wind on the same UTC timestamps.
ERA5 Ocean total wave substituted for swell, so every row is `degraded`.

| Zone | Position | d/yr | yrs | median Hs nearshore | Aspect swing | Shelter |
|---|---|---:|---:|---|---:|---|
| ANCHOR Kommetjie 5/5 | -34.14, 18.327 | 41.0 | 4/4 | 2.11 m @ 10.7 s | x1.1 | 6/36 |
| **Rapa Nui** | -27.068, -109.391 | **42.5** | 4/4 | 1.38 m @ 11.1 s | x1.5 | 12/36 |
| **Dingle / Blaskets** | 52.272, -10.211 | **28.5** | 4/4 | 2.10 m @ 11.3 s | x1.2 | 20/36 |
| **Kauai NW** | 21.897, -160.221 | **28.2** | 4/4 | 1.57 m @ 10.8 s | **x1.0** | 0/36 |
| Clare, Ireland | 52.781, -9.515 | 21.2 | 4/4 | 1.84 m @ 11.4 s | x1.2 | 0/36 |
| Costa da Morte, Galicia | 42.911, -9.179 | 17.8 | 4/4 | 2.30 m @ 11.2 s | x1.9 | 0/36 |
| Chiapas | 16.054, -93.916 | 14.5 | 4/4 | 1.37 m @ 10.8 s | x1.0 | unresolved |
| Canaries W | 28.118, -17.325 | 11.5 | 4/4 | 1.57 m @ 11.1 s | x1.0 | 17/36 |
| Mayo, Ireland | 54.005, -10.140 | 10.2 | 4/4 | 1.38 m @ 12.1 s | x2.0 | 19/36 |
| ANCHOR Belmar 5/5 | 40.177, -74.008 | 1.0 | 2/4 | 2.95 m @ 11.1 s | x1.2 | 0/36 |

Belmar scoring 1.0 d/yr on the same statistic is the calibration warning: this
metric ranks Kommetjie-shaped places, and a 5/5 can happen at a spot it barely
registers. **The user's own log does not require long-period swell** — Belmar is
a 5/5 at 9.0 total-wave days a year over 10 s. "Consistent long-period" is a
stated objective for this search, not a preference the log demonstrates.

### Zone-level aspect can swing joint overlap 35-fold

The zone normal is a 250 km Natural Earth tangent, not a measured setup aspect,
and it is the weakest input in the chain. Sweeping it in 15 deg steps over the
cached data:

| Zone | At zone normal | At best aspect | Swing |
|---|---:|---:|---:|
| **Juan Fernandez** | 1.5 d/yr | **53.2 d/yr** (300 deg) | **x35.5** |
| Rote / Savu | 0.2 | 1.5 | x7.5 |
| Mayo | 10.2 | 20.5 | x2.0 |
| Galicia | 17.8 | 34.2 | x1.9 |
| Kauai NW, Chiapas, Canaries | — | — | x1.0 |

Juan Fernandez led the whole survey on both marginals (60.4% wind, 60.5 d/yr
over 12 s) and then read as a 1.8 d/yr collapse. That collapse was an artefact
of assuming the island's north-facing tangent; at 300 deg the same cached hours
give 53.2 d/yr. **A zone-level joint overlap must be reported as a range over
aspect, or not at all.** Rote's rejection is the opposite case and survives the
sweep: dead at every aspect.

### Correction — the fetch screen was blind to land inside 50 km

The stage-1 open-ocean screen cast rays in 50 km steps, so it could not see land
nearer than that, and Natural Earth 1:50m includes lagoon and inner-sea
shorelines. **104 of the 1,040 candidate points have land within 25 km straight
out their seaward normal.** Two finalists were withdrawn on it:

- **Salina Cruz / Tehuantepec, 16.420, -94.859** — 25.0 d/yr joint overlap and
  60.1% wind, withdrawn. A 0% cloud Sentinel-2 frame shows the point sits on the
  inner shore of Laguna Superior, not the ocean beach; GMRT reads a flat +9 m
  and the shelter probe found no water within 3 km. Its wave numbers describe an
  ERA5 ocean cell the point does not belong to. The outer barrier beach may well
  be worth a zone point — this rejects the coordinate, not the coast.
- **Caithness, 58.905, -3.272** — 25.5 d/yr, withdrawn. Imagery shows the
  Pentland Firth with Stroma 8 km offshore and Orkney beyond: a strait shadowed
  from the north, not open ocean.

A single-bearing near-field probe screens but does not prove. **Mayo failed it at
19 km and imagery cleared it** — the hit was one headland on one bearing, and the
coast is open Atlantic. Look at the pixels before rejecting, exactly as before.

### Imagery is available here, unlike Ceara

Every finalist zone has ample cloud-free Sentinel-2 coverage (57-591 scenes under
10% cloud, 2019-2026; Kauai 591, Chiapas 483, Canaries 445, Rapa Nui 300). The
Ceara ceiling — where the swell season and the clear season are opposites — does
**not** apply to any of these, so static geometry is confirmable on all of them.
Dynamic wave state still needs a clear pass coincident with swell and remains
opportunistic.

Static geometry actually read, at 0% cloud:

- **Kauai NW** — open ocean, deep water hard against the shore, fringing reef
  flat and a continuous unbroken white line down the whole beach. That continuity
  is a closeout signature, not a defined peak; the reef fringe to the north is
  the part worth a closer look.
- **Dingle / Blaskets** — open Atlantic, deep water against rocky headlands with
  whitewater on the points and one pocket beach. Geometry is promising and the
  wind is unverifiable, which is the combination this method cannot rank.

### Disposition

Nothing here is promoted to `spots.tsv`. These are **zone** nominations at 250 km
resolution; not one is a setup with a measured aspect, slope or bottom, and the
evidence ladder puts geometry-only inference at the bottom. BARREL is reported
**unresolved** for every candidate: outside US DEM coverage the grid is ~460 m
and cannot see reef, the existing component fits one beach slope, and the log
gives `rho(rating, barrel) = -0.07`.

The three worth a setup-level pass next, in order: **Rapa Nui** (highest joint
overlap found, beats the Kommetjie anchor, 4/4 years, but 12/36 sheltered),
**Kauai NW** (the most aspect-robust result in the survey at x1.0 and 0/36
blocked), and **Juan Fernandez** (unrankable until its aspect is measured, and
worth 53 d/yr if the west coast is the working one).

### Correction — the shortlist above was ranked without ever asking if it breaks

Same day, immediately after. The ranking above joins wind and swell at ERA5
cells and stops there. It contains **no breaking-wave evidence of any kind**, and
`ARCHITECTURE.md` already says bathymetric focusing is not surfability: reject
cliffs, simultaneous closeouts, diffuse breaking, inaccessible rocks and features
without a usable line or channel. That step was skipped, and two signals that
should have caught it were printed and walked past:

- The Rapa Nui seaward profile read `+96, 86, 79, 64, 59, 53` — a transect
  running along a **clifftop**, not into water. It was tabulated as a depth
  profile.
- The Rapa Nui Sentinel-2 crop returned a **900x2 pixel** array. The script
  printed "saved" and nothing was ever looked at. "Imagery readable, 300 scenes"
  reported *scene availability*, which is not evidence that anyone looked.

**The surfability screen, calibrated on Kommetjie.** Over each zone's coastal
cells from 61 m GMRT topobathy: inland relief within 300 m (can you stand there,
or is it cliff) and whether a shallow platform has deeper water outside it
(deep -> shallow) rather than a plunge.

| Zone | low-lying | deep->shallow shelves | median inland relief | median depth @ 500 m |
|---|---:|---:|---:|---:|
| **ANCHOR Kommetjie 5/5** | 14/23 | 5 | 12 m | -10 m |
| Kauai NW | 17/19 | 6 | 10 m | -9 m |
| Clare, Ireland | 34/35 | 7 | 7 m | -4 m |
| Galicia | 15/39 | 6 | 25 m | -11 m |
| Mayo | 18/48 | 6 | 38 m | -22 m |
| Dingle / Blaskets | 21/37 | 3 | 13 m | -8 m |
| Juan Fernandez | 16/61 | 4 | 34 m | -48 m |
| Chiapas | 11/12 | **0** | 5 m | -10 m |
| Canaries W | **0/22** | **0** | **302 m** | -26 m |
| Rapa Nui | 29/76 | — | 28 m | -55 m |

**Rapa Nui is rejected, and it was ranked first.** 76 coastal cells, median
inland relief 28 m, median depth 500 m offshore **-55 m** — an oceanic volcano
with no shelf. Two 0% cloud frames over the only low-lying sectors show a thin
continuous ribbon of whitewater **hard against the rock** with deep navy water to
the edge: no offshore breaking line, no reef pass, no channel, no peak. Shore
impact on a boulder and cliff coast. Separately, the shallow platforms that do
exist face 60-120 deg, while the 42.5 d/yr figure was computed at a 306 deg
normal — the number and the only places that could break are on opposite sides
of the island.

**Canaries W is rejected**: zero low-lying coastal cells and 302 m of median
inland relief. Pure cliff. **Chiapas is rejected**: not one deep -> shallow
shelf in the box. **Galicia is withdrawn**: a 0% cloud frame shows the point
sits inside a ria, an estuary rather than open coast — the same error class as
Salina Cruz, and the 25 km near-field probe passed it because the ria mouth
opens along the probed bearing.

**What survives is two zones, both qualified.** *Kauai NW* is the closest match
to the Kommetjie signature (6 shelves, 10 m relief, -9 m at 500 m) and the most
aspect-robust result in the survey, but its one clear frame shows a continuous
unbroken white line down the whole beach — a closeout, not a peak. *Clare* has
the best shelf count on the coast (7) and the shallowest profile, and its clear
frame is flat: good static geometry (headlands, sandy bay, islet) with **no
dynamic wave state at all**, because no swell was running when the satellite
passed. Neither has a confirmed rideable line.

The generalisable failure: **a climate ranking and a surf spot are different
objects, and joining wind to swell does not bridge them.** Every zone in the
table above cleared a joint wind/swell overlap gate calibrated on his own 5/5
sessions, and most of them cannot hold a rideable wave. Surfability is a
separate screen and it belongs before the shortlist is written, not after.

### Open

- 440 of the 1,040 candidate points were never wind-scored.
- Every joint number is 4 years (the marine archive starts Dec 2021) and uses
  total wave as a swell proxy.
- No candidate has a measured shore normal, slope, bottom or a single
  observation. No dynamic wave state was confirmed anywhere.
- The survey is still blind to terrain-sheltered coves by construction; Dingle,
  Mayo, Canaries and Rapa Nui all carry blocked bearings and sit in the
  unverifiable pile rather than being ranked on their model wind.
- No candidate anywhere in this survey has a confirmed breaking line. The two
  survivors need a clear frame coincident with swell, which is the scarce
  resource; Kauai and Clare both have ample cloud-free passes to search.
- Salina Cruz and Galicia reject a coordinate, not a coast. Both zones may be
  worth a point placed on the outer shoreline instead of a lagoon or ria.

## Open

- Nova Scotia. No Canadian buoy archive on NDBC, so it has never been measured.
- Cashes Ledge, at a finer grid step than 1.1 km.
- Slab transects are measured, but only Cape Small is a promoted setup row and
  none has a break-level session or repeated-event observation behind it.
- Global search unfinished: 320 of 1,280 points have 3-year wind consistency,
  and no survivor has been swell-confirmed. Wind-first, then swell on survivors.
- The search is blind to terrain-sheltered coves by construction. Nothing yet
  ranks a spot that works because a ridge grooms the wind.
- Seasonality is unsplit. Every global number above is all-year, so a winner may
  be a three-month window rather than a place.

- The four Guajiru rows have never been visited and have no session behind them.
  Position and normal only.
- Wrap cannot find bar or reef setups. A bottom-aware layer is the next thing
  worth building, and Sentinel-2 can barely see this coast Dec-Apr.
- Ceará slope is unmeasured everywhere and the coast is bimodal (deep channel /
  long shallow bar), so one number may be the wrong shape of answer entirely.
- The swell cone and season split are still unfinished: the marine archive only
  reaches back to Dec 2021, so any Ceará climatology is 4 seasons, not 7.

## Boston-to-Maine BlueTopo plan-view audit, 2026-09-04

**Binary result: B.** No feature reached `verified setup`. The best survivor is
an isolated bank east of Frenchboro that demonstrably breaks, but the dated
images show compact whitewater rather than a rideable peeling line. It stops at
`observed break`; `spots.tsv` is unchanged.

### Coverage, data and controls

The coast-wide pass used the 2026-09-03 [BlueTopo tile
index](https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/_BlueTopo_Tile_Scheme/BlueTopo_Tile_Scheme_20260903_192638.gpkg).
BlueTopo supplies elevation, uncertainty and source-contributor bands in NAVD88;
the [specification](https://nauticalcharts.noaa.gov/data/bluetopo_specs.html)
also warns that it is not for navigation.

The Boston-to-Maine box intersected 381 index tiles. All 352 tiles with a
delivered raster were screened in plan view: **306 at 4 m, 40 at 8 m and 6 at
16 m**. The 29 undelivered index cells contain no raster to inspect. The first
coastal pass produced 1,342 multi-cell nomination components under the <=3 m
crown / >=15 m within 500 m screen. Each then faced size, land separation,
deep-approach, 24-bearing corridor and channel checks. The remaining offshore
tiles were screened separately. The strongest 30 geographically distributed
survivors were inspected in aerial imagery, and the five strongest new bottom
forms were reopened at their finest delivered resolution. This is an exhaustive
screen of the delivered BlueTopo coverage, not proof that BlueTopo contains
every real feature.

The recalled Rhode Island control is resolved as **Monahan's Dock**, also State
Pier #5/Tucker's Dock, Narragansett, at **41.422466, -71.454393**. The name is
documented in the [Rhode Island coastal access
guide](https://repository.library.noaa.gov/view/noaa/39236/noaa_39236_DS1.pdf),
and the coordinate is fixed in [state
regulation](https://www.law.cornell.edu/regulations/rhode-island/250-RICR-90-00-1.13).
A dated [2019 photograph shows a surfer on the right at the named
break](https://www.surf-forecast.com/breaks/Monahans-Dock/photos/20785), while
the [spot guide](https://www.surf-forecast.com/breaks/Monahans-Dock) independently
describes left and better right reef breaks, ESE swell, west wind and submerged
rock hazard. It is sufficient as a control, not as a Boston-to-Maine find.

The ordered gates recover both positives above the matched negatives without
using `BARREL` or a default reef slope:

| Control | Exact evidence | Gate result |
|---|---|---|
| Small Point / Cape Small | user-confirmed working positive; 4 m bottom supports a shallow ledge complex, but the exact ridden crown remains unresolved | positive control only |
| Monahan's Dock | official coordinate, dated ridden-wave photograph and independent reef-break description | positive control |
| Monhegan NE | continuous cliff plunge; no shoulder or exit | negative: cliff |
| Pemaquid / Cape Ann | shallow ground attached to a broad coastal shoal | negative: gradual/attached shoal |
| Cape Elizabeth ledges | broad exposed ledge field; no bounded peeling line or channel | negative: exposed closeout risk |
| Isles of Shoals / Seguin north | real shallow features, but land blocks the Atlantic approach and no safe channel is shown | negative: no open corridor/exit |

### Plan-view failures

The old Shoals point, **42.9755, -70.6308**, is positive-elevation land in the
current grid. A detached substitute at **42.978162, -70.620642** is a roughly
32 by 24 m pinnacle dropping to -15 m inside 100 m, but is too short for a
credible line and sits in an island-shadowed basin. Seguin's substitute at
**43.711180, -69.754945** is similarly shallow and persistent but lies north of
the island without an open Atlantic corridor. Cape Ann is attached and partly
intertidal, Pemaquid misses the <=3 m crown at the tested point, Cape Elizabeth
is a broad irregular shelf, and Monhegan remains a cliff plunge.

The earlier Biddeford Pool survivor at **43.441360, -70.333020** remains real
4 m lidar ground, but it is intertidal and sits in a crowded ledge field. Six
dated Sentinel scenes alternate between exposed rock, a white point and dark
water; none shows a line. It is demoted below the Frenchboro bank. Other
high-scoring coast-wide forms resolved as broad banks, shore-attached shelves,
island-shadowed pinnacles or exposed rocks when reopened in full resolution and
imagery.

### Best survivor: Frenchboro offshore bank

The exact highest cell is **44.162006, -68.313670**, in BlueTopo tile
[`BH5475H9`](https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/BlueTopo/BH5475H9/BlueTopo_BH5475H9_20260709.tiff).
The screening centroid, 127 m north, was 44.163141, -68.313882. Use the crown
coordinate for any further evidence collection.

- 4 m NAVD88 raster; measured topo-bathymetric lidar contributor
  `2022_550000e_4895000n`, surveyed 2022-10-12 through 2023-07-20;
- crown **-0.28 m NAVD88 +/-1.03 m**;
- local MLLW surface **-1.725 m NAVD88 +/-0.117 m** by [NOAA
  VDatum](https://vdatum.noaa.gov/vdatumweb/api/convert?s_x=-68.313882&s_y=44.163141&s_z=0&region=contiguous&s_h_frame=NAD83_2011&s_coor=geo&s_v_frame=NAVD88&s_v_unit=m&s_v_elevation=height&t_h_frame=NAD83_2011&t_coor=geo&t_v_frame=MLLW&t_v_unit=m&t_v_elevation=height),
  so the nominal crown is 1.45 m above MLLW datum;
- connected -3 to 0 m cap: **258 independent cells**, **4,128 m2**, about
  **144 by 50 m**, long axis 158 degrees;
- -15 m water is **124 m from the crown** and **88 m from the cap edge**;
- no positive-elevation cell occurs in the roughly 2 by 2 km source crop, and
  deep water surrounds the bank, but there is no protected shoulder or exit;
- grid perturbation preserves the crown: -0.28 m native, -0.36 and -0.47 m on
  two 8 m origins, and -0.46 m after a 3-by-3 mean. Those differences remain
  smaller than source uncertainty.

The form is an isolated, multi-crown NNW-SSE spine. Its abrupt flanks and open
southerly corridor explain why it breaks. Its narrow 50 m cap and aligned rather
than lateral geometry make a compact peak or closeout at least as plausible as
a peeling slab.

### Exact-feature breaking evidence

Sentinel-2 L2A was joined at acquisition time to NDBC 44027 wave and wind and
NOAA Bar Harbor 8413320 tide. Four independent frames show whitewater on the
mapped crown, while a lower-energy control is dark:

| UTC date | Exact-feature read | Hs / DPD / MWD | Wind | Tide MLLW |
|---|---|---|---|---:|
| [2021-12-07](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2021/12/S2B_19TEJ_20211207_1_L2A/TCI.tif) | compact break | 3.11 m / 9.1 s / 170 deg | 293 deg, 10.3 m/s | 3.02 m |
| [2021-12-17](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2021/12/S2B_19TEJ_20211217_1_L2A/TCI.tif) | compact break | 2.55 m / 9.1 s / 173 deg | 292 deg, 12.7 m/s | 2.88 m |
| [2023-12-12](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2023/12/S2A_19TEJ_20231212_0_L2A/TCI.tif) | large compact break | 2.98 m / 12.9 s / 160 deg | 269 deg, 7.8 m/s | 3.25 m |
| [2024-12-31](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2024/12/S2B_19TEJ_20241231_0_L2A/TCI.tif) | small compact break | 2.17 m / 10.8 s / 181 deg | 251 deg, 6.6 m/s | 3.71 m |
| [2023-09-01](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2023/9/S2B_19TEJ_20230901_0_L2A/TCI.tif) | dark control | 1.05 m / 12.1 s / 154 deg | 277 deg, 3.1 m/s | 3.88 m |

The [2024-02-25](https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/19/T/EJ/2024/2/S2B_19TEJ_20240225_0_L2A/TCI.tif)
frame has a white patch on the bank, but the long straight feature crossing it
is a boat wake, not evidence of peel. A 2022-12-10 edge-of-tile frame is
ambiguous and excluded. No image contains a rider, open face, shoulder or
defined exit. The defensible state is therefore **`observed break`**, not
`verified setup`.

The observed-breaking envelope is **2.17-3.11 m Hs, 9.1-12.9 s DPD,
160-181 degrees, and 2.88-3.71 m MLLW tide**. It is not a working surf envelope.
The four frames had strong west-to-NW wind, so favorable wind is unmeasured; a
north-to-east or <=3 m/s wind is only the geometric hypothesis. Applying the
observed wave/tide band to hourly 44027/8413320 data gives **119 independent
episodes separated by more than 48 hours in 2009-2025, or 7.0/year across the
17-year interval**. Wave data support only 10 of those years. Season counts are
winter 49, spring 41, summer 2 and fall 27. Adding the hypothetical favorable
wind leaves 31 episodes, 1.8/year, but does not make them surfing events.

### Access, hazard and falsifier

This is boat-only open water. The [state ferry reaches Frenchboro on Long
Island](https://www1.maine.gov/dot/programs-services/ferry/frenchboro-ferry/schedule),
not the bank. There is no documented public shore route, protected channel or
safe exit at the feature. Hazards include several intertidal/submerged crowns,
abrupt deep water, cold exposure, tide/current, boat traffic and +/-1 m bottom
uncertainty. BlueTopo is not a navigation product.

**Exact falsifier / completion evidence:** observe the crown from a boat or
georeferenced drone during the 2.2-3.2 m, 9-13 s, 160-181 degree, 2.8-3.8 m
MLLW window. A continuous closeout across the 144 m spine, or no usable exit,
rejects the slab hypothesis. Promotion requires two independent events showing
the same crown produce a clean takeoff, directional peel, usable shoulder/exit
and an actual ride, with swell, wind and tide recorded at matching timestamps.
Until then, **none is verified**.

### Correction — the Frenchboro report did not satisfy outcome B

The section above and the generated PDF are **withdrawn as a completed survey**.
The narrow claim survives: the mapped Frenchboro feature is real ground and
repeated images show whitewater tied to it. The larger conclusion does not. The
method has known blind spots and did not exhaust every credible slab form, so it
met neither completion condition A nor B. The correct state is **incomplete
survey; one observed-break pinnacle; no verified slab found by this method**.

#### Failure report

| Failure | Consequence | Correction |
|---|---|---|
| The report buried the tidal datum consequence. The -0.28 m NAVD88 crown is nominally **1.445 m above MLLW**; subtracting the combined reported bottom/datum uncertainties still leaves it about 0.41 m above MLLW. | A drying/intertidal rock was presented like a submerged slab candidate. The most decision-relevant fact was reduced to a hazard bullet. | Every shallow-feature report leads with crown elevation relative to the local tidal datum and explicitly says `drying`, `intertidal` or `submerged`. |
| Four Sentinel-2 positives were treated as major new confirmation. At the observed 2.88-3.71 m MLLW tides, nominal water over the crown was only 1.44-2.27 m. A 0.78 depth limit implies local breaking near 1.12-1.77 m Hs. | The images mostly corroborate predictable depth-limited whitewater and grid registration. At 10 m they cannot answer peel, face, rider or exit. | Keep `observed break`, but do not let repeated 10 m white blobs raise confidence in surfability. Use imagery capable of resolving a moving breakpoint before promotion. |
| No NOAA ENC/RNC, Coast Pilot or underlying NOS hydrographic survey/H-sheet was checked. | A nominally drying hazard probably has free, independent chart evidence, a least depth and possibly a local name. If chart evidence is absent, the BlueTopo interpretation itself needs scrutiny. | Chart and source-survey lookup is mandatory before climatology or field planning for any intertidal/drying finalist. |
| The event envelope was the bounding box of four positive images. | The 2.17 m lower bound measures Sentinel-2 detectability in this sample, not the physical breaking threshold. Counting inside that box is circular. | Derive thresholds from water depth and a local wave transformation, then validate them on held-out break and non-break observations. Four images may be reported raw, not promoted to an envelope. |
| The report divided 119 events and 31 wind-filtered events by 17 calendar years although usable 44027 wave data existed in only 10. | The published 7.0/year and 1.8/year rates treat seven missing years as zero. Dividing by populated years gives 11.9 and 3.1, but those are also invalid without duty-cycle weighting. | Withdraw both rates. Report raw counts and monitoring coverage until valid observed-hours/event denominators are computed. |
| Raw 44027 waves were assigned to a site more than 40 nautical miles away and inside an island complex. | Offshore Hs and direction are not local Hs and direction; refraction, shoaling and blocking by Swan's Island, Long Island and Mount Desert are uncontrolled. | No local frequency or working envelope until a validated nearshore transform, SWAN-equivalent run or local sensor exists. |
| The hypothetical favorable-wind sector was backwards. | For a face open near 170 degrees, about 350 degrees is dead offshore; NW and W are cross-off/side-off, while E has an onshore component. The filter excluded useful NW/W and included worse easterly wind. The observed west-to-NW directions were not the problem; speed may have been. | Recompute wind relative to the measured breaking-face normal, not a compass label. Do not publish another frequency subset before the local face orientation is observed. |
| Geometry was described as ambiguous when it was evidence against slab morphology. | Crown to -15 m is about 1:8.4; from the -3 m cap edge to -15 m it is about 1:7.3. The 158-degree spine is nearly end-on to 160-181-degree incident swell. That is pinnacle/converging-peak geometry, not a lateral ledge whose breakpoint obviously walks. | Classify morphology before scoring: ledge/step, ridge, cone/pinnacle, shelf or cliff. Frenchboro is a pinnacle control unless observation proves otherwise. |
| The nomination gate required a <=3 m crown and >=15 m water within 500 m. | The sieve preferentially finds steep isolated pinnacles, then rejects them for not peeling. It can miss deeper 3-6 m ledges that activate only with size and slabs sitting on shelves without nearby -15 m water. | Replace the single gate with morphology-specific screens. A slab screen looks for a near-flat ledge and abrupt step with oblique crest-to-swell geometry; a pinnacle screen is a separate class. |
| Small Point and Monahan's were named as positive controls but never measured on the same features used for Frenchboro. | The method was declared calibrated without showing crown depth, cap dimensions, crest/swell angle or distance to deep water for either working break. | Measure both positives and matched negatives first. A screen is not allowed to extrapolate until positives rank above negatives on held-out geometry. |
| The field falsifier jumped directly to winter swell around a drying rock in cold, boat-only water. | A desktop uncertainty was turned into a hazardous operational suggestion without a staged survey, local wave measurement or stand-off plan. | Use the staged plan below. No person or boat enters the break zone on the strength of this report. |
| The PDF promoted effort metrics and point estimates visually. | `352 rasters`, `4 events` and `observed break` read like findings; the +/-1.03 m uncertainty disappeared from the KPI strip; the decision box had weak contrast; several footer captions ran together. | Mark the PDF withdrawn. Future reports lead with the limiting fact, keep uncertainty beside every point estimate, demote effort counts and visually QA extracted text as well as rendered pages. |

The contributing lidar source and dates were present in the report
(`2022_550000e_4895000n`, 2022-10-12 through 2023-07-20); that part was not
missing. The presentation still overemphasised the 2026 BlueTopo delivery/index
date and failed to follow the contributor through to its underlying survey and
chart authority.

#### Revised interpretation of Frenchboro

- **Ground:** high-confidence, multi-cell, nominally drying/intertidal
  pinnacle. Source uncertainty remains large relative to the NAVD88 crown.
- **Breaking:** repeated whitewater is observed at the feature. It is expected
  from depth-limited breaking at the sampled tides and does not demonstrate a
  rideable line.
- **Shape:** steep, narrow, multi-crown spine approached nearly end-on. Current
  geometry weighs against a slab-style peeling ledge.
- **Conditions and frequency:** unknown locally. The four offshore-buoy/tide
  joins remain observations at their respective instruments, not a working
  envelope or climatology for the feature.
- **Survey:** incomplete. The coast cannot be called barren and completion B
  cannot be claimed from a gate biased toward pinnacles.

#### Replacement sequence

1. **Free authority check:** inspect the current NOAA ENC, Coast Pilot,
   applicable historical RNC and the
   contributing NOS survey/H-sheet for charted least depth, rock classification,
   name and survey lineage. Absence is a BlueTopo-integrity warning, not proof
   of discovery.
2. **Calibrate the shape:** measure Small Point and Monahan's on the same datum,
   plan-view dimensions, slope and crest-to-swell angle; add matched cliff,
   shoal, closeout and no-channel negatives. Redesign the slab gate from that
   signature before rescanning.
3. **Model or measure the local sea:** transform offshore hindcast through the
   archipelago with SWAN or equivalent, and validate at the bank with a drifting
   GPS wave buoy or bottom pressure gauge. Duty-cycle-weight any frequency.
4. **Observe safely:** first use summer calm and low water for stand-off sounder
   passes and georeferenced drone stills. Then observe a sub-threshold 1.2-1.8 m
   event for registration. Only after those checks should a full-condition
   event be filmed remotely while the boat remains in charted deep water.
5. **Use better eyes where available:** test the Sentinel-1 SAR archive for
   repeatable break signatures and 3 m Planet imagery only under an existing
   licence. Neither source can replace a rider, peel and exit observation.

Promotion still requires repeated independent events showing a clean takeoff,
directional breakpoint movement, a usable shoulder/exit and an actual ride.
Until the gate is rebuilt and calibrated, the honest output is **method failure,
not a negative finding about the coast**.

## Barrels, wind-first and bottom-second — 2026-09-04

Asked for the barrel opportunities the earlier passes skipped, with **barrel
density inside a travel window** as the objective rather than a spot that works
all year, smaller sizes acceptable if the wave spits, cold water acceptable, and
remote acceptable.

Two separate questions had been run together. *Does the sea floor here make a
barrel* is a bathymetry question. *How often does the ocean deliver a
tube-capable swell and an offshore wind* is a climate question. Every earlier
global pass answered the second and quietly implied the first.

### The bottom question now has a tool and a hard limit

`surf tube` ships: median seabed gradient in the 1-12 m breaking band, converted
to a Mead and Black (2001) vortex ratio and breaker-intensity class, carrying
its DEM cell. `docs/CALIBRATION.md` has the held-out panel of 29 named breaks
and the number that matters:

| DEM | AUC separating tube breaks from soft breaks |
|---|---:|
| ~3.4 m NCEI US mosaic | **1.000** (n=9) |
| ~61 m GMRT | **0.500** (n=17) |

Sixty-one metres is a coin toss and it is not a soft failure: it calls
Muizenberg, a beginner beach, steeper than every barrel in the panel bar
Shipstern Bluff, and puts Thurso East at 1:60 and Skeleton Bay at 1:397. The
command therefore reports the gradient at any resolution and withholds the class
above 10 m. `docs/DATA-SOURCES.md` records what is available where: 3.4 m inside
US coverage, 463 m the moment you leave it, 61 m from GMRT worldwide, ~115 m from
EMODnet, and 2 m Irish inshore multibeam from INFOMAR that is published as a
MapServer with no sampling endpoint.

**So global barrel discovery from bathymetry is not possible with the sources
this project has.** It is possible in US waters today, and it is possible in
Ireland the moment the INFOMAR grid can be sampled. That is the single highest
-value data task on the list.

A second attempt, measuring **peel angle** from the same 61 m grid — refract the
swell with Snell to the local breaking depth, take the angle against the local
isobath — failed worse than the gradient did. On a sandy bottom the per-cell
isobath orientation at 61 m is DEM noise, and the metric ranked Malibu and Doheny
above every barrel in the panel. Recorded so it is not tried again at this
resolution.

### The forcing question, answered by month

ERA5 Ocean total wave and 10 m wind, 2021-12-01 to 2025-11-30, four years, joined
on shared UTC hours at twenty named breaks with hand-placed shore normals. A day
counts when at least one daylight hour has nearshore Hs >= 1.0 m after the repo's
period-dependent transmission, total-wave mean period >= 11 s, and wind either
calm or within 60 deg of offshore and under 30 kt. `degraded` throughout: total
wave substitutes for the swell partition, and no bottom is screened.

| Destination | clean d/yr | best three months (d/yr) |
|---|---:|---|
| Lagundri, Nias | 173.8 | Jun 24.8, Jul 22.8, Aug 22.8 |
| Uluwatu | 126.0 | Apr 14.5, Sep 14.5, Oct 14.2 |
| The Box, WA | 95.8 | Sep 12.2, May 11.2, Oct 9.8 |
| Zicatela | 94.5 | May 18.5, Apr 13.5, Jul 11.0 |
| Shipstern Bluff | 74.0 | Apr 10.2, May 9.5, Jul 7.8 |
| La Graviere | 72.8 | Feb 15.2, Mar 14.2, Jan 10.8 |
| Cloudbreak | 70.0 | Apr 11.2, Mar 8.0, Jun 7.8 |
| Teahupoo | 68.5 | May 11.2, Apr 9.0, Aug 7.0 |
| Skeleton Bay | 64.0 | Aug 12.0, Jul 11.2, Jun 9.0 |
| Mundaka | 61.5 | Feb 14.5, Jan 9.5, Mar 9.2 |
| Supertubos | 59.0 | Feb 13.8, Jan 10.8, Mar 10.5 |
| Pipeline | 47.5 | Jan 15.2, Dec 10.8, Feb 7.8 |
| **Mullaghmore** | **30.8** | Feb 6.8, Mar 5.0, Jan 4.5 |
| **Riley's, Clare** | **27.2** | Mar 6.2, Jan 5.0, Dec 3.8 |
| **Bundoran Peak** | **24.2** | Mar 4.5, Nov 4.0, Feb 3.8 |
| **Thurso East** | **21.8** | Feb 6.8, Mar 3.8, Dec 3.5 |
| **Brimms Ness** | **21.8** | Feb 6.8, Mar 4.0, Jan 3.5 |
| Unstad, Lofoten | 13.5 | Feb 3.2, Jan 2.8, Mar 2.5 |
| ANCHOR Belmar | 3.5 | Sep 1.2, Aug 1.0, Dec 0.5 |
| Kirra | 1.0 | — |

Read as a trip rather than a year: a ten-day window in Nias in June expects
about **eight** tube-capable days, Uluwatu in September about **five**, Zicatela
in May about **six**, and Thurso or Mullaghmore in February about **two and a
half**. Density, which is the stated objective, is a tropical result; the cold
-water leads pay for their density in a much tighter window.

### The 1:30 column is empty everywhere, and that is a finding

Repeating the screen with the plunging criterion attached at four assumed reef
slopes collapses at 1:30: at Hs >= 1 m and T >= 11 s the deep-water steepness is
already too high for `xi = tan(beta)/sqrt(H/L0)` to reach the 0.5 plunging floor
on a 1:30 floor. **A long-period metre-plus swell does not plunge on a sand
beach of ordinary gradient.** It spills. Every sand-bottom barrel in the panel —
Skeleton Bay 1:397, Supertubos 1:87, Kirra 1:49 — makes its tube through a low
peel angle instead, which is the mechanism this project still cannot measure.

The assumed slope is also the biggest lever in the table, and 1:20 is the wrong
assumption for a steep reef: Pipeline drops from 47.5 clean days to 11.8 at 1:20
purely because North Shore swells are large, and a large swell lowers `xi`. Only
the slope-independent "clean" column above should be compared across sites.

### Two calibration warnings that must travel with the table

**The gate excludes his own barrels.** Belmar scores 3.5 clean days a year, and
the two sessions in the log that explicitly report a barrel — 2024-04-04
"spitting tubes" and 2024-04-13 "got barreled" — ran at 6.95-7.05 s and 8.1-8.2 s.
An 11 s floor deletes both. "Consistent long-period" is the objective stated for
this search; it is not what his log demonstrates, and the same inversion is
recorded in the wind-first pass above.

**Kirra at 1.0 d/yr is not credible** and is carried as a suspected shore-normal
or ERA5-cell artefact, not a result.

### Correction — Caithness was rejected on a coordinate, and the coast is real

The wind-first pass withdrew "Caithness, 58.905, -3.272" because imagery showed
the Pentland Firth with Stroma 8 km offshore: a shadowed strait, not open ocean.
That rejection stands for that point. It does **not** reject the coast. Thurso
East at 58.5992, -3.5155 and Brimms Ness at 58.6060, -3.6390 both face the open
Atlantic swell window and score 21.8 clean days a year, 20 of them between
October and March, with February alone at 6.8. Same error class as Salina Cruz
and Galicia: reject the coordinate, keep the coast.

### Disposition and what to do next

Nothing here is promoted to `spots.tsv`. These are named destinations screened on
forcing only; not one has a measured shore normal, slope or bottom in this repo,
and the normals used above were hand-placed for the survey.

In order:

1. **Sample the INFOMAR 2 m grid.** Ireland is the only ground where the barrel
   screen can run at a resolution the panel validated, and it holds the best
   cold-water forcing density found — Mullaghmore, Riley's, Bundoran, Crab
   Island, Easkey. The REST service is a MapServer; the download portal or a WCS
   route needs testing.
2. **Run `surf tube` across US barrel candidates**, where 3.4 m already works
   and the panel scored AUC 1.00. That is the only place the method is presently
   both valid and available.
3. **Build the peel-angle half.** Every sand-bottom barrel in the panel is
   invisible to the gradient screen. It needs a bar or spit orientation, which
   means imagery, not the free bathymetry.
4. Resolve whether the 11 s floor is the right objective before spending more on
   it. His own barrels came at 7-8 s.

### Open

- The forcing table is twenty hand-placed points, not a search. No new coast was
  swept; the 440 unscored candidates from the wind-first pass are still unscored.
- Every number is four years and uses ERA5 total wave as a swell proxy.
- No breaking-wave observation anywhere in this pass. Nothing was seen breaking.
- `surf tube` has been run live at Pipeline (1:29, medium/high), Waikiki (1:78,
  below the schedule) and Thurso East (refused, 463 m). Nothing else.
- The panel is n=9 at the resolution where it works. AUC 1.00 on nine points is
  encouraging and is not proof.
