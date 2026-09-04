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
sure of and `????-02-22` has no year at all; both stay in the file and both stay
out of the checks that need them. A guessed year would quietly poison the only
referee there is.

## Why 41 rows are worth more than they look

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
[PASS] no 1/5 dominates a 5/5: 6/6 pairs clear (6 at 5/5 vs 1 at 1/5;
       only 1 low anchor, so the pairs are not independent)
       rho(rating, barrel)    = -0.07
       rho(rating, size)      = +0.60
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

Rows needing a year: 09-14, 09-21, 03-03, 06-24, 07-07, 07-11, 06-19, and
several 2025 Cape Town dates. Rows needing a spot: 2024-12-05 (a 5/5, and there
is video, so it can be checked against footage) and 2024-08-19.

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
