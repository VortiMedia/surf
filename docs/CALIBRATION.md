# Calibration

Every other input to this system is a prediction. `data/sessions.tsv` is what
actually happened, so it is the only thing that can prove the model wrong.

Recovered reanalysis can test scoring against past sessions; it is not an
operational forecast backtest. Forecast skill requires freezing a prediction at
issue time and later joining it to observations, as defined in
[`ARCHITECTURE.md`](ARCHITECTURE.md#operational-forecasts).

## The log

42 sessions, 2022–2025, across the US Northeast, South Africa, Portugal, Brazil
and Costa Rica. Date, spot, time, rating 1–5, notes — dumb enough that a row
takes ten seconds to add.

Ambiguous fields keep their question marks. `2025-08-05?` is a date I am not
sure of and `????-02-22` has no year at all; both stay out of checks that need
them. The session audit tested each yearless date against the archive and found
multiple surfable candidates every time, so those years are explicitly marked
`UNANSWERABLE` rather than guessed.

## Why 42 rows are worth more than they look

Past conditions anywhere are free (Open-Meteo Archive, back to 1940), so each
row expands into swell height, period, direction, wind and tide for that hour.
A validation set that cost nothing.

## What it is used for

**No fitting.** 42 sessions over ~18 spots is two per spot; weights fitted to
that overfit on contact. Two mechanisms instead, both of which work at n=41:

**Ranking check.** Recover the conditions behind every usable session, score
them, and require that no 1/5 beats a 5/5 on *every* component at once. Pareto
dominance rather than a fused score, because there is no defensible way to
weight the components against each other and the first version of this check
failed for exactly that reason (see below).

**Nearest neighbour.** "Thursday at Lido resembles your 2024-03-24 session."
That answer comes out of my own history, fits no parameters, and sharpens with
every row.

## Anchors

| Type | Example | What it pins |
|---|---|---|
| Ideal | Llandudno 2025-03-12, "exactly what we're looking for" | the target |
| Lower bound | Stonewall 06-19, "about as small as we'd want" | where rideable starts |
| Failure | Spring Lake 2024-12-12, slabby, over the falls | what to avoid |

Lower bounds are rare and worth the most: forty good days cannot tell you where
too small begins.

Documented historical swells can be added tagged `source=public`. They are never
merged into my ratings — a famous day is "this was notable", not "I scored this
a 5", and merging the two redefines the scale everything else is measured on.

## Falsifiable checks

A rating agrees or disagrees. A mechanism can be checked, so it is worth more.

The current at Lido normally pulls west; on one 03-03 it pulled east. Longshore
current direction is set by swell angle against the shore normal, so that one
sentence is a direct test of Lido's stored bearing. It is still the sharpest
thing in the log and it is still skipped, because that row has no year.

## What the last run found

29 usable sessions, conditions from the archive:

```
[PASS] no 1/5 dominates a 5/5: 6/6 pairs clear (6 sessions at 5/5 vs 1 at 1/5;
       only 1 low anchor, so the pairs are not independent)
       rho(rating, barrel)    = -0.07
       rho(rating, size)      = +0.61
       rho(rating, cleanness) = -0.14
[PASS] Lido current sets west on typical swell (8 sessions, mean 144 deg)
[SKIP] Lido current sets east on ????-03-03 — no swell direction recovered
```

Two things worth stating plainly.

**The first failure was the referee, not the model.** The original check ranked
sessions by `barrel * size * cleanness`. BARREL falls with wave height and SIZE
rises with it, so that product measured whichever normalisation happened to be
steeper, and a 1/5 outranked three 5/5s. Fusing components is the thing this
system is built not to do, and it did it in its own test harness.

**SIZE carries the signal; BARREL currently carries none.** ρ = −0.07 over 29
sessions is indistinguishable from zero. Deriving real beach slopes moved it
from −0.31, so the anti-correlation was an artefact of every spot sharing one
nominal slope — but nothing has shown BARREL to be informative either. Either
barrel potential is genuinely orthogonal to whether I enjoyed a session, or
Iribarren from offshore height is too blunt to rank spots. Those are not
separable at n=28, so it stays untuned. More low-rated sessions is the only
honest way to tell them apart.

## Gaps

The audit leaves 13 permanent unanswerables: years for 02-22, 05-21, 08-17,
09-14, 09-21, 03-03, 06-24, 07-07, 07-11 and 06-19, plus spots for 2017-01-04,
2024-12-05 and 2024-08-19. The archive has multiple surfable candidates for
each missing year; the log and video notes do not identify the three missing
spots. `2017-01-04` is the one hand date resolution, taken from the existing
note `jan 4 17`; its spot remains unanswerable. `surf session audit` reports zero
outstanding questions and names these permanent ones.

## Audit result, 2026-09-03

| | before audit | after audit |
|---|---:|---:|
| rows with a date, spot and rating | 29 | 29 |
| rows with a usable date | 31 | 32 |
| ranking pairs clear | 6/6 | 6/6 |
| rho(rating, SIZE) | +0.60 | +0.61 |

The hand date is now provenance-carrying, but its spot is unknown, so it cannot
enter calibration. No ranking moved; the gate still passes. The small SIZE
change is a fresh archive recovery, not a new session or a fitted parameter.

## Corrections to the log, 2026-09-03

Three rows were wrong in ways that changed conclusions. All were caught by
reading findings back to David, not by any check in the code.

**Sandy Bay 2025-02-05 was 5/5, now 3/5.** Logged as "sick punchy tube". It was
a lucky one-off on a mess-around day — a sketchy shore break he doggy-doored out
of, not a clean cylinder and not a session. As a 5/5 it was the single strongest
evidence that David wants heavy sucking slabs, and it was carrying that
conclusion alone.

**Kommetjie 2025-02-05's 3/5 is about that day, not the spot.** The spot could
not hold the swell and he barely surfed. He rates the place highly, so the note
now says so and points at the row below.

**Kommetjie 2023-02-25 16:45, 5/5** added — "best day ever there". 10.8 ft at
12 s from 209°, wind 14.7 kt at 158°.

Effect on the component correlations:

| | before | after |
|---|---|---|
| ρ(rating, size) | +0.67 | +0.60 |
| ρ(rating, barrel) | −0.06 | −0.07 |
| ρ(rating, cleanness) | −0.19 | −0.14 |

BARREL is the stated target and is the one component that does not track his
ratings. SIZE does. That is not an argument for fusing them — it is an argument
for naming the size band before quoting any component.

## What the 4s and 5s actually share

| r | spot | Hs ft | T | wind kt | off-axis |
|---|---|---|---|---|---|
| 5 | Beliche | 10.8 | 15 | 8.4 | 66° |
| 5 | Kommetjie | 10.8 | 12 | 14.7 | 48° |
| 5 | Llandudno | 10.3 | 11 | 14.7 | 62° |
| 5 | Belmar | 7.8 | 8 | 10.9 | 17° |
| 5 | Lido | 7.2 | 10 | 13.6 | 0° |
| 5 | Belmar | 6.4 | 8 | 15.9 | 18° |

**Wind speed 8.4–15.9 kt on every one; off-axis angle 0–66° and useless.** Two
regimes, not one: East Coast at 6–8 ft / 8–10 s with dead-offshore wind, and
overseas at 10–11 ft / 11–15 s with wind that is cross-shore on paper and
groomed by terrain in fact. A gate built from either half alone misreads the
other — the failure recorded in `RECON.md`.

Sub-3 ft is a grovel in every row that has one; the notes say "barely rippable"
and "grovel", and none rates above 3.

## The wrap score did not find what David's eye found

**2026-09-04.** `surf/wrapmap.py` scores each 200 m of coast by how fast
exposure changes along the shore, on the reasoning that a sharp gradient means
refraction and refraction means a peeling wave. Tested against eleven zones
David marked by hand from satellite imagery, it fails.

Nine of his eleven marks score **wrap ≤ 0.20**, the band the map paints as
"flat, straight beach". Taíba — a spot he has surfed and rates as working all
year — sits at exposure 0.99, wrap 0.13. Mundaú reads 0.95 / 0.08. Only the
Jeri mark, at 0.38, scores as anything.

The metric is not wrong so much as aimed at the wrong layer. It sees the plan
shape of the shoreline and nothing else. What David is marking is **sea floor**
— sand bars, reef outcrops and a slab — which is invisible to a coastline
polygon by construction. Taíba reads as plain open beach because the thing that
makes it break is underwater.

So: do not use wrap as a spot finder on a straight coast. It ranks headlands
and it is honest about headlands, and Jeri Point is the one place it and David
agree. Finding the rest needs a layer that sees the bottom — imagery, or
bathymetry finer than the 463 m grid, and `RECON.md` records that Sentinel-2
can barely see this coast during the months that matter.

The earlier claim in this session that the whole-coast scan had "found" the
Flecheiras cluster was too generous: the model's high-wrap segment is 700 m
from his mark, and the segment he actually marked scores 0.19.

## The BARREL axis is measuring the wrong thing, and the literature says so

**2026-09-04.** The session log already reports `rho(rating, barrel) = -0.07`
against `rho(rating, size) = +0.60`, so the Iribarren band in `score.py` carries
no signal about the axis it is named for. The surfing-science literature says
why. Mead and Black (2001) reject the surf-similarity parameter for surfing
waves explicitly — it describes every breaker from spilling to collapsing and is
too general to rank rides — and replace it with a field measurement over 28
world-class breaks: the **orthogonal seabed gradient** predicts the vortex ratio
of the plunging wave, which is the shape of the barrel.

    Y = 0.065 X + 0.821        R² = 0.71

`Y` is the vortex ratio, `X` the orthogonal seabed gradient. Their published
classification schedule runs extreme 1.6–1.9, very high 1.9–2.2, high 2.2–2.5,
medium/high 2.5–2.8, medium 2.8–3.1, and a **low** ratio is the violent barrel.
Inverting the fit against that schedule puts the classes at X = 12–17, 17–21,
21–26, 26–30 and 30–35, which is self-consistent only if `X` is the gradient
*denominator* — a 1:X slope. That reading is what `surf/tube.py` implements. It
was not read out of the paper directly and the units are an inference from the
two published numbers agreeing; treat it as such.

The relation is a useful sanity check on its own. A 1:33 sand beach — the
`NOMINAL_SLOPE` this repo assumes where nothing is measured — gives Y = 2.97,
the mild end of "medium". Belmar's measured 1:38 gives 3.29, off the bottom of
the schedule entirely. That is the same verdict the log's own language gives
those spots: weak tubes, not barrels.

## The panel: seabed gradient separates tubes from mush, but only above ~10 m DEM

**2026-09-04.** Held-out test, 29 named breaks the model has never seen, split
into world-class tube breaks and breaks nobody travels to for a barrel. The
statistic is exactly what `surf tube` ships: snap to the nearest 2–8 m cell
within 400 m, then take the **median** seabed gradient of every cell between 1
and 12 m of water in a 360 m box. Median, not a high percentile — the tail of a
coastal gradient distribution is cliff and rock platform, and on the 90th
percentile Bondi and Kommetjie read "extreme".

Three coordinates were rejected outright with no 2–8 m cell within 400 m (The
Box, Mullaghmore, Spring Lake). That is a rejection of the coordinate, not of
the break.

| DEM | source | n barrel | n control | AUC |
|---|---|---:|---:|---:|
| ~3.4 m | NCEI US mosaic | 4 | 5 | **1.000** |
| ~61 m | GMRT GridServer | 10 | 7 | **0.500** |

At 3.4 m the separation is total and the gap is wide: Ala Moana 1:15, Waimea
shorebreak 1:20, Pipeline 1:26, Backdoor 1:37, against Belmar 1:62,
Waikiki Canoes 1:65, Cocoa Beach 1:67, Waikiki 1:79, Lido Beach 1:105. Nine
points is encouraging, not proof.

At 61 m it is a coin toss, and the failures are not subtle. Muizenberg — the
beginner beach in Cape Town — reads 1:12, steeper than any barrel in the panel
bar Shipstern Bluff. Thurso East reads 1:60 and Skeleton Bay 1:397. A 61 m cell
averages the ledge into the sand either side of it, exactly as `CLAUDE.md`
already warns, and the number that comes out is not a weak version of the right
answer; it is unrelated to it.

So `surf tube` reports the gradient at any resolution the grid supports and
emits a breaker-intensity class only below 10 m. Between 10 m and 100 m the
measurement stands and the claim is withheld.

**The panel also shows what this screen structurally cannot find.** Skeleton
Bay (1:397), Supertubos (1:87) and Kirra (1:49) are among the best tubes on
earth and all three sit on flat sand. Their barrel comes from a low **peel
angle** — a bar or spit lying oblique to the swell so the break runs away down
the line — not from a steep floor. That is Mead and Black's other parameter and
this screen is blind to it. A separate attempt to measure peel angle from the
same 61 m grid failed worse than the gradient did: the per-cell isobath
orientation on a sandy bottom is DEM noise, and the metric ranked Malibu and
Doheny above every barrel in the panel. Both halves of the barrel problem need
a finer bottom than the free global grid provides.
