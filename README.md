<p align="center">
  <img src="docs/surf-mark.svg" alt="surf — open-data surf intelligence" width="900">
</p>

<p align="center"><strong>One spot, one window, and what would make it wrong.</strong></p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-242321">
  <img alt="Tests: offline suite" src="https://img.shields.io/badge/tests-offline%20suite-242321">
  <img alt="Data: open, no key" src="https://img.shields.io/badge/data-open%2C%20no%20key-D85A2A">
</p>

The auditable calculation layer for an AI surf researcher. Today it picks one
surf spot and time window from open forecast, buoy, tide and bathymetry data,
then tells you what would make it wrong. No account, API key or vendor.

The broader goal is one evidence loop for natural-language trip decisions,
coastline discovery, seasonal weather and flat-spell analysis, Google Earth
output, historical backtesting and scheduled swell alerts. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Why surf

Surf forecasts hand you a rating and hide the reasoning. This one refuses to.

- Four components print side by side and are never fused into a single score.
- Every value carries its source, and a degraded source names what it dropped.
- Each call states what would make it wrong before you paddle out.
- Geometry is measured and cached with a provenance flag, or reported as absent.
- No account, no API key, no vendor lock.

## Install

```sh
git clone https://github.com/VortiMedia/surf && cd surf
pip install -e .
```

Needs Python 3.11+ and `httpx`. Nothing else.

## Use

```sh
surf sources                        # is anything down?
surf call --region US-NY --days 4   # where and when
surf spot lido-beach                # one spot in depth
surf calibrate                      # check the model against my session log
```

```
$ surf call --region US-NY --days 4

CALL  CAMP HERO, MONTAUK  Sat 05 Sep 07:00-11:00 EDT
  BARREL 0.16   SIZE 0.27   CLEANNESS 1.00   CONFIDENCE 0.03
  tide: falling +0.37 m at 07:00 EDT
  access: LIRR Montauk + taxi, ~$60 — a cost, not a filter

why
  - Iribarren xi=0.27 (spilling), slope tan(beta)=0.0253 [derived]
  - 6.6 m/s from 352 deg, 7 deg off the offshore bearing (345 deg)
  - falling +0.37 m at 07:00 EDT

wrong if
  - already below the plunging band (xi=0.27) — best hour available, not a barrel forecast
  - wind is 7 deg off offshore; a swing past 90 deg before the window blows it out
  - models disagree — height spread 0.24 m, period spread 3.0 s, direction spread 67 deg

caveats
  - ndbc/44025:degraded dropped=swell/windwave split (buoy reports MM),wind
```

Spots live in [`data/spots.tsv`](data/spots.tsv), one row each. Add your own.

## Agent skill

```sh
cp -r skill ~/.claude/skills/surf-intelligence
```

Then ask where or when to surf, investigate a coast, compare a forecast with
history, or define a setup worth watching instead of remembering flags.

## Things that will look like bugs

**BARREL falls as the swell gets bigger.** The Iribarren number is
`ξ = tanβ/√(H/L₀)`, so it scales with `H^-½`. A bigger wave at the same beach is
a less hollow one. That is the physics, not an inverted sign — the component
that rises with height is SIZE. They must remain separate decision axes.

**Nothing is one universal number.** Four components are printed side by side.
There is no defensible universal weighting between them, and the first fused
score ranked a 1/5 session above three 5/5s. The current internal call picker
still uses that product as an ordering key; replacing it requires a backtested
decision rule, not another arbitrary score. See
[docs/CALIBRATION.md](docs/CALIBRATION.md).

**Every value carries where it came from.** Sources report `ok`, `degraded`,
`failed` or `skipped`, and a degraded one names what it dropped. A dead source
degrades the answer instead of killing it; nothing silently falls back to a
plausible-looking guess.

**Geometry is measured, then cached.** Shore normals and beach slopes live in
the spot file with a provenance flag. Outside US high-resolution DEM coverage
the sea floor grid is ~460 m — wider than the surf zone — so those spots report
no slope rather than a confident meaningless one. `surf geometry --write`
derives what it can.

**Surfline is optional and off.** `SURF_SURFLINE=1` turns it on as a second
opinion after the call already exists. Deleting `surf/surfline.py` breaks
nothing but its own test.

## Data

Open-Meteo Marine (four wave models) · Open-Meteo Archive (back to 1940) · NDBC
buoys · NOAA CO-OPS tides · NOAA NCEI bathymetry. Endpoint quirks, including the
model IDs that do not exist and the file that 404s, are in
[docs/DATA-SOURCES.md](docs/DATA-SOURCES.md).

## Tests

```sh
pip install -e ".[dev]"
pytest                    # 310 offline
pytest -m network         # hits the live APIs
```
