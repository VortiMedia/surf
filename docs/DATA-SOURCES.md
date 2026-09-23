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
54.7 ft. Parse the `#YY MM DD hh mm WDIR ...` header line and map by name. The
historical files also use numeric missing sentinels (`99`, `999`, `9999`) as
well as `MM`, sometimes formatted with extra decimal places (`99.00`,
`999.00`); all are dropped as missing before a peak is computed.

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

## Open-Meteo Marine — what the archive actually covers, and what it costs

Tested 2026-09-04.

**The swell archive starts December 2021.** A request for `2017-12-01` onward
returns HTTP 200 with the full date range present and every value before
2021-12-01 `null`. Seven surf seasons requested, four came back with data. As
with the weather-archive hole below, a 200 with the keys present is not proof
of a populated column.

**Daily aggregates exist and are far cheaper than hourly.**
`daily=swell_wave_height_max,swell_wave_period_max,swell_wave_direction_dominant`
answers on the same endpoint. Cost is weighted by locations × variables × days,
so finding long-period *events* with one variable over one point costs roughly
a fiftieth of what three variables at three points hourly costs, and events are
all that is needed before spending anything else.

The order that works: get the free constraint first. Satellite passes are the
scarce resource, not swell — Sentinel-2 revisits every ~5 days and most Ceará
frames in the surf season are clouded. Enumerate the usable scenes (free, no
quota), then buy swell only for those dates.

**`sea_level_height_msl` starts later than the swell archive.** At
-2.7929,-40.5209 the tide endpoint answers for 2022-12-02 onward but fails
outright for 2021-12-12, 2021-12-17 and 2022-01-21 — the three oldest frames in
a Jeri imagery set. Sea level, not cloud, is what bounds how far back an
imagery study on this coast can reach. Check it before assuming a frame is
usable, because without instantaneous sea level a macrotidal coast has no depth
datum at all.

### ERA5 Ocean carries no swell partition, and the archive lives on `/v1/marine`

Tested 2026-09-04 during the global barrel search.

**The historical marine endpoint is `/v1/marine`, not `/v1/archive`.** A dated
request to `https://marine-api.open-meteo.com/v1/archive` returns HTTP 404, not
a helpful error. `climate.py` already uses `MARINE_URL` correctly; a scratch
client that guessed `/v1/archive` by analogy with the weather archive lost a
round trip to it.

**`swell_wave_*` comes back entirely null under `models=era5_ocean`.** A 1,461-day
daily request for `swell_wave_period_max` at 16.42,-94.86 answered HTTP 200 with
all 1,461 values `None`. Only the *total* wave fields (`wave_height`,
`wave_period`, `wave_direction`) are populated. This is the same limitation
`OpenMeteoClimate` already labels as `"ERA5 Ocean total wave fields used as a
swell proxy"` — but a caller asking for the swell partition gets nulls rather
than an error, so a long-period screen built on `swell_wave_period_max` silently
counts zero days everywhere. Use the total field and label the result degraded.

**The two Open-Meteo quotas fail differently and it matters.** The *hourly*
archive limit is a soft stop that clears at the top of the hour; a 14-location
4-year hourly wind request tripped it and cleared on its own. Marine was
unaffected in the same minute, confirming the separate-quota note above. Pacing
one request per ~16 s kept a 600-point 1-year sweep at **zero 429s**, against six
backoff stalls when the same sweep ran unpaced — collisions cost wall clock, not
quota, so pacing is worth it purely for time.

## Element84 Earth Search — Sentinel-2 catalogue and imagery

`https://earth-search.aws.element84.com/v1/search`, collection
`sentinel-2-l2a`. STAC POST search, no account, no key, no rate limit hit in
practice. Filter with `query: {"eo:cloud_cover": {"lt": N}}`; `context.matched`
gives the true count when the page caps at 100.

`eo:cloud_cover` is a **whole-scene** average and says nothing about the 5 km
box you care about. A 4% scene put solid cloud over Jeri on 2025-12-31. Always
look at the pixels before believing the number.

`proj:transform` and `proj:shape` come back `null` on these items. Take the
geotransform from the COG's own `ModelPixelScaleTag` / `ModelTiepointTag`
instead, and `proj:epsg` from the item properties.

The `visual` asset (`TCI.tif`) is a public tiled COG on S3 over plain HTTPS. It
supports range requests, so a 5 km window reads in ~2-3 MB and two tiles
without downloading the 10980x10980 scene and without rasterio — a seekable
HTTP file object plus `tifffile.TiffPage.decode` on the tiles the box covers is
enough.

Every other band sits at the same S3 prefix: swap `TCI.tif` for `B02.tif`,
`B03.tif`, `B08.tif` or `SCL.tif`. No second catalogue call is needed to reach
reflectance.

### Reflectance, masking and compositing

**Do not apply `BOA_ADD_OFFSET`.** Processing baseline 04.00 (2022-01-25) added
a -1000 DN offset to Sentinel-2 L2A, but these COGs are already harmonised.
Measured over dark water in the Jeri box, un-offset B08 runs 283-326 DN before
the boundary and 401-466 after — 0.028-0.047 reflectance, right for shallow
turbid tropical water. Subtracting 1000 from the later scenes instead gives
-0.06 reflectance, which no water body can have. Applying the offset silently
inverts the sign of every water pixel and turns a log-ratio SDB into noise.

**SCL cirrus (class 10) is not usable over this water.** On 2024-12-26, the
visually cleanest frame in the Jeri record, Sen2Cor labels 4,599 water cells
cirrus that the imagery shows to be clear. Reject cloud shadow (3), cloud
medium (8) and cloud high (9); treating 10 as cloud throws away the best
scenes. SCL is the 20 m product — nearest-neighbour it to the 10 m grid and
crop to the common shape, never pad, since the upsampled window can land a row
short of the bands.

**Per-pixel SCL beats rejecting whole scenes.** A frame 35% clouded over the
box can still have a clear waterline; scene-level rejection cost four frames
and 0.9 m of tidal range before this was noticed.

**Compositing requires a single MGRS tile.** 24MUB and 24MUC have different
grid origins, so the same lon/lat box resolves to a different pixel window
(277 rows against 240) and the stacks will not align. Filter to one tile before
stacking anything.

**S3 resets connections mid-read.** Range requests need retry with backoff; a
reset is not a missing object.

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

## What resolution the sea floor is actually available at

Tested 2026-09-04 while building `surf tube`. The barrel screen needs a DEM cell
under ~10 m; `docs/CALIBRATION.md` has the panel that fixes that threshold.

| Source | Endpoint | Cell where tested | Verdict for the barrel screen |
|---|---|---|---|
| NCEI DEM mosaic | `DEM_mosaics/DEM_all/ImageServer/getSamples` | **3.43 m** at Pipeline, Waikiki, Belmar, Lido, Cocoa Beach | usable; the only sampling endpoint found above the threshold |
| NCEI, outside US coverage | same | **463.3 m** at Thurso East | refuses, correctly |
| GMRT GridServer | `gmrt.org/services/GridServer` | **61.1 m** everywhere tested | measures a gradient, cannot classify a barrel (panel AUC 0.50) |
| EMODnet Bathymetry WCS | `ows.emodnet-bathymetry.eu/wcs` | composite DTM only, ~115 m | too coarse; no finer coverage is published there |
| INFOMAR (Ireland) | `atlas.marine.ie/arcgis/rest/services/INFOMARseabedSurvey/MapServer` | 2 m inshore multibeam **exists** | not sampleable — the REST service is a MapServer with `Survey`, `Sediment Samples` and `Surveyed Areas` layers, no ImageServer and no `getSamples`. Reaching the grid means the download portal or a WCS route, and that is untested. |

**GMRT `GridServer` is fast, free and on its own quota.** A 3 km box comes back
in about half a second as `format=esriascii&resolution=max`; rows run north to
south and the header carries `cellsize` in degrees, which is 5.49e-4 — 61 m — in
every box tested from Tahiti to Caithness. It rejects `format=ascii`. Nothing
about it rate-limited across a few hundred boxes, so it stays the right tool for
a plan-view screen; it just cannot see a reef.

**`getSamples` reports its own resolution per point and that is the field to
trust.** It answers HTTP 200 with a plausible elevation whether the value came
from a 3 m lidar tile or the 463 m global fallback, and the two mean completely
different things. `NceiBathymetry` already surfaces `resolution_m` on every
`Sample`; read it before believing a gradient.

**The US mosaic is the coverage boundary, not a global DEM.** Pipeline, Waikiki,
Belmar, Lido Beach, Spring Lake and Cocoa Beach all answer at 3.43 m. Thurso
East, and by extension every candidate in Ireland, Scotland, Norway and Iceland,
falls straight through to 463 m. Any barrel work outside US waters is blocked on
a national multibeam source, not on the method.
