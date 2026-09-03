# Calibration

Every other input to this system is a prediction. `data/sessions.tsv` is what
actually happened, so it is the only thing that can prove the model wrong.

## The log

41 sessions, 2022–2025, across the US Northeast, South Africa, Portugal, Brazil
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

**No fitting.** 41 sessions over ~18 spots is two per spot; weights fitted to
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

28 usable sessions, conditions from the archive:

```
[PASS] no 1/5 dominates a 5/5: 6/6 pairs clear (6 at 5/5 vs 1 at 1/5;
       only 1 low anchor, so the pairs are not independent)
       rho(rating, barrel)    = -0.06
       rho(rating, size)      = +0.67
       rho(rating, cleanness) = -0.19
[PASS] Lido current sets west on typical swell (8 sessions, mean 144 deg)
[SKIP] Lido current sets east on ????-03-03 — no swell direction recovered
```

Two things worth stating plainly.

**The first failure was the referee, not the model.** The original check ranked
sessions by `barrel * size * cleanness`. BARREL falls with wave height and SIZE
rises with it, so that product measured whichever normalisation happened to be
steeper, and a 1/5 outranked three 5/5s. Fusing components is the thing this
system is built not to do, and it did it in its own test harness.

**SIZE carries the signal; BARREL currently carries none.** ρ = −0.06 over 28
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
