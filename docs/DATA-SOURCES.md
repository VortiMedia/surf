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
