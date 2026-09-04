# Recon

Survey results that are too specific for the spot file and too durable to lose.
A spot's geometry belongs in `data/spots.tsv`; an endpoint's quirk belongs in
`DATA-SOURCES.md`. What lands here is the finding neither of those holds: how
big a coast actually gets, how often, and which places are worth a row.

This is the evidence ledger for the discovery workflow in
[`ARCHITECTURE.md`](ARCHITECTURE.md). Record failed hypotheses
and corrections as carefully as successful candidates.

Last survey 2026-09-03.

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

## Open

- Nova Scotia. No Canadian buoy archive on NDBC, so it has never been measured.
- Cashes Ledge, at a finer grid step than 1.1 km.
- The four slab candidates have no measured geometry and no session behind them.
- Global search unfinished: 320 of 1,280 points have 3-year wind consistency,
  and no survivor has been swell-confirmed. Wind-first, then swell on survivors.
- The search is blind to terrain-sheltered coves by construction. Nothing yet
  ranks a spot that works because a ridge grooms the wind.
- Seasonality is unsplit. Every global number above is all-year, so a winner may
  be a three-month window rather than a place.
