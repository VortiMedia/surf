# Data sources

Everything here is free and needs no account. Status is what each endpoint
actually did when last tested (2026-09-03), not what its docs claim.

## Open-Meteo Marine — forecast

`https://marine-api.open-meteo.com/v1/marine`

Most of the model IDs in circulation do not exist. Working ones:

| Model | Status | Swell partitions |
|---|---|---|
| `gwam` (DWD) | 200 | populated |
| `best_match` | 200 | populated |
| `ncep_gfswave025` | 200 | populated, zeros at some points |
| `ecmwf_wam025` | 200 | **all null** — total height and period only |
| `gfswave025`, `gfswave016`, `meteofrance_wam` | **400** | name does not exist |

So the swell/windwave split comes from `gwam` or `best_match`. ECMWF still earns
a call as an independent opinion on total height, which is what the confidence
number is made of. Each model is fetched on its own URL rather than through the
compare flag, so one dead model degrades the set instead of killing it.

The marine endpoint carries no wind — that is a second call to the weather
endpoint. Under load it answers HTTP 200 with the plain text
`Unexpected error while streaming data: timeoutReached`, so a 200 is not proof
of a JSON body.

## Open-Meteo Archive — history

`https://archive-api.open-meteo.com/v1/archive` — back to 1940, global.

This is what makes a session log worth keeping: any past date anywhere recovers
its conditions, so every row becomes a scored test case.

## NDBC — observed

`https://www.ndbc.noaa.gov/data/realtime2/<id>.<ext>`

| File | Contents | Status |
|---|---|---|
| `.txt` | Hs, dominant period, mean direction, wind | 200 |
| `.spec` | swell and windwave **already separated**, plus steepness | 200 |
| `.data_spec` | energy by frequency | 200 |
| `.swr1` `.swr2` `.swdir` `.swdir2` | directional Fourier coefficients | 200 |
| `.swden` | — | **404, does not exist** (use `.data_spec`) |

`.spec` gives the partition split for free, e.g. `1.2m total, 0.2m@10.0s SE
swell, 1.2m@6.2s SE windwave, STEEP`. Wind is only in `.txt`, which is why both
are fetched. Missing values are the literal string `MM`.

Northeast buoys: 44097 Block Island, 44025 Long Island, 44008 Nantucket.

### Historical archive

`https://www.ndbc.noaa.gov/data/historical/stdmet/<id>h<year>.txt.gz`

Twenty-plus years per buoy, gzipped, one row every 30–60 min. This is where any
"how big does it get" or "how often" question gets answered.

**The column layout changed and the file does not say so.** Files before 2005
have no `mm` column, so every field after `hh` shifts one place left. Reading by
fixed index then returns `GST` where `WVHT` was meant, which looks like a 16 m
sea rather than a parse error — four Northeast buoys appeared to have recorded
54.7 ft. Parse the `#YY MM DD hh mm WDIR ...` header line and map by name.

**A single sample is not a wave.** The raw maximum at 44098 is 43.8 ft, one
30-minute record between neighbours of 28.2 and 27.9 ft. Require a peak to
survive a 3-sample centred median before reporting it; the true record there is
31.3 ft.

No Canadian buoy has a historical archive here — 44258, 44150, 44137 and 44139
all 404 — so Nova Scotia cannot be answered from NDBC.

## NOAA CO-OPS — tide

`https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`

Predictions, MLLW datum, `interval=hilo`, JSON. Returns HTTP 200 with an error
body when the request is bad. Only US stations exist, so everywhere else falls
back to Open-Meteo sea level, which is MSL — a curve read against the wrong
datum is off by half the tidal range and looks entirely plausible, so the datum
is printed with the curve.

`observed water level − predicted tide = storm surge`, which after a storm is
the difference between the table and the actual water.

## NOAA NCEI — bathymetry

`https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/ImageServer`

The `getSamples` operation, not `exportImage`: it samples points along a bearing
without a raster reader, and it reports the resolution of the grid each point
landed on. That resolution is the whole game. US coastal DEMs come back at
~3 m; everywhere else falls through to a 15 arc-second global grid at ~460 m,
which is wider than the surf zone and cannot describe a beach face. Fitting a
slope to it would produce a confident number with no physical content, so those
spots report no slope at all.

**The grid is smooth even where the sea floor is not.** At 3 m it resolves a
sand profile but not a boulder reef. A 10 m transect across Squibnocket returns
`0.20 -0.09 -0.17 -0.29 -0.70 -1.04 -1.47 -1.84 -2.26 -2.46` — a clean ramp,
where imagery shows reef 200–500 m offshore. `fit_beach_slope` averages that
reef into gentle sand, and an Iribarren number built on it says a reef point
closes out at every size, which is false. Depth the grid does report honestly,
so size a reef or point break by depth-limited breaking (`Hs_max ~ 0.78 x
depth`) and say the gradient is unresolved.

## Surfline — optional benchmark

Off by default; set `SURF_SURFLINE=1` to enable. `/forecasts/wave` was split
into `/forecasts/surf` (breaking face height) and `/forecasts/swells` (offshore
partitions) and the old path now 404s. Units are per-response in
`associated.units`, not per-API. The swells array is fixed-length and padded
with all-zero partitions that are not swell trains.

A direct `curl` gets 403 from the WAF while an httpx client with a normal
User-Agent succeeds. Do not re-diagnose this with curl.

## Not used

- **METAR** — points only at "now", useless for a trip four days out.
- **SWAN** — deferred, not rejected. `Response.transmission` is the seam it
  would fill.

## Open-Meteo — rate limits

Two separate quotas. The marine and archive endpoints do **not** share one, so
an exhausted marine quota still leaves history queryable — that is what makes a
wind-first pipeline possible when swell is capped.

Free tier refuses in two distinct ways, and the body says which:

```
{"reason":"Hourly API request limit exceeded. Please try again in the next hour."}
{"reason":"Daily API request limit exceeded. Please try again tomorrow."}
```

Both are HTTP 429. Only the second is a hard stop — it clears at UTC midnight,
and no amount of backoff or retrying beats it. Read the body before deciding
whether to wait.

Cost is weighted by locations × variables × days, not by request count, so a
3-year 40-location call burns a large multiple of a single-point day. Two years
of hourly wind for 1,355 points is affordable; the same for swell is not.

**Both endpoints accept comma-separated `latitude`/`longitude` and return a JSON
array, one object per location.** Twenty points per request is the difference
between a global sweep and an impossible one. A single location still returns a
bare object, so normalise before zipping against the input.

Concurrency does not help and actively hurts: the quota is per account, so
parallel workers only collide and re-trigger each other's backoff. One process
with one throttle finishes; seven do not.

## GMRT — bathymetry outside US DEM coverage

`https://www.gmrt.org/services/PointServer` (single depth, `format=text/plain`)
`https://www.gmrt.org/services/GridServer` (grid, `format=esriascii&resolution=max`)

Free, no account, and on a quota unrelated to Open-Meteo — usable when
Open-Meteo is capped. `GridServer` rejects `format=ascii`; it wants `esriascii`.
Rows run north to south.

Where NCEI falls back to its ~463 m global grid, GMRT returns **~61 m** cells —
inside the 100 m threshold `geometry.py` needs, so it can carry a beach slope
internationally. Validated against spots where NCEI already has an answer:

| Spot | GMRT | NCEI | Error | Bottom |
|---|---|---|---|---|
| Spring Lake | 0.02848 | 0.02940 | 3.1% | sand |
| Belmar | 0.02463 | 0.02632 | 6.4% | sand |
| Point Judith | 0.01476 | 0.01764 | 16.3% | mixed |
| Rye NH | 0.00580 | 0.00719 | 19.3% | sand |
| Camp Cronin | 0.01427 | 0.05562 | **74.3%** | rock |
| Aquinnah | 0.00778 | 0.03946 | **80.3%** | rock |

**Trustworthy on sand, useless on rock.** It smooths straight over reef the 3 m
NCEI DEM resolves, which is the same failure as the NCEI-at-reef trap one
section up, one order of magnitude coarser. Never let a GMRT slope reach
Iribarren at a reef or point.

The spot coordinate usually sits in water already, so a profile must run
*landward* first to find the zero crossing and fit seaward from there. Starting
at the spot and walking out begins past the surf zone and fits nothing.

GMRT also carries topography, which is what the terrain-shelter horizon in
`RECON.md` is built from.

## Natural Earth — coastline and land mask

`https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/`
— `ne_50m_coastline.geojson` (1,428 features), `ne_50m_land.geojson` (1,420
polygons). Public domain, ~1.6 MB, cache it once.

Coastline segmented at a fixed spacing gives global sample points; land polygons
answer land-or-sea offline by point-in-polygon. That replaces two bathymetry
calls per point with zero — 1,280 seaward normals resolved in 1.2 s. Unlike OSM
`natural=coastline` (used for Ceará), Natural Earth carries no winding-order
guarantee, so the seaward side must be probed rather than assumed.

