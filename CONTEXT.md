# Surf

The words this project uses for surf research: where a wave breaks, what the
sea is doing, how good a session was, and how sure the evidence is. Code, docs,
CLI output and agent prompts use these words with these meanings.

## Places

**Zone**:
A stretch of coast that shares one swell window and one wind regime. Climate
facts belong to a zone.
_Avoid_: region (except as the `--region` filter), area, coast

**Setup**:
One wave-making mechanism at one piece of sea floor or coastline: a slab, bar,
wedge, reef or point. Bathymetry, aspect and slope belong to a setup.
_Avoid_: break, wave, spot (until promoted)

**Setup type**:
The class of a setup — beach, bar, reef, point, slab. Bands are set per setup
type.

**Spot**:
A setup that a person has promoted into the spot book, with a measured position
and geometry that carries provenance.
_Avoid_: location, site

**Spot book**:
The curated set of spots. A spot exists only if it is in the spot book.

**Terrain candidate**:
A sea-floor object that a bathymetry scan proposed. It stays a candidate until
a person promotes it to a spot; no scan promotes anything.
_Avoid_: new spot, discovered break

**Promotion**:
The human decision that turns a terrain candidate into a spot.

## Sea state

**Offshore Hs**:
Significant wave height in deep water, before the swell reaches the setup.

**Nearshore Hs**:
Significant wave height at the setup after exposure and transmission. This is
the default meaning of "size".
_Avoid_: wave height, size (without saying which)

**Face height**:
The height a surfer sees on the wave face. Never computed; about 1.5 times
nearshore Hs by stated convention only.

**Swell partition**:
One swell train in a forecast or buoy spectrum, with its own height, period and
direction.

**Regime**:
The swell type behind a session, such as groundswell or windswell. A field on
the session, not a new setup.

**Exposure**:
How much of a swell direction a piece of coast can see, allowing for land in
the way.

**Shelter field**:
For each patch of water, the fraction of the swell fan that reaches it without
crossing land.

**Wrap score**:
How fast exposure changes along the shore. A high wrap score marks coast where
land bends swell.

**Intensity**:
How hard a wave plunges, from the sea-floor gradient in the breaking depth band
through the vortex ratio.

## Judging a wave

**Axis**:
One of the four separate measures of a window: BARREL, SIZE, CLEANNESS and
CONFIDENCE. Axes are shown side by side and never merged into one score.
_Avoid_: score, rating (for model output)

**BARREL**:
How hollow the wave is likely to be, from the Iribarren number. It falls as the
swell gets bigger at the same setup.

**SIZE**:
How big the wave is at the setup, from nearshore Hs.

**CLEANNESS**:
How well the local wind suits the setup: its direction against the offshore
bearing, weighted by its speed.

**CONFIDENCE**:
How closely the forecast models agree on height, period and direction. Not
source quality; one model alone cannot produce it.

**REACH**:
The largest nearshore Hs the surfer has ridden in a session rated 4 or 5, plus
one step. A separate measure, never multiplied into an axis.

**Band**:
The minimum conditions worth the surfer's time for one setup type. A floor,
never a target.

**Call**:
One committed answer: a spot, a time window, the reasons, and what would make
it wrong.
_Avoid_: recommendation, pick, forecast

**Falsifier**:
A stated condition that would make a call wrong. Every call has at least one.
_Avoid_: risk, warning

## Evidence

**Session**:
One logged time in the water, with date, spot, time, rating and notes.

**Session log**:
The record of the surfer's own sessions. The only evidence that can confirm
what the surfer likes.

**Rating**:
The surfer's 1-5 score for a session. Ratings belong to people, not to the
model.

**Lexicon term**:
A word from the session log, such as "walled out" or "spitting", mapped to a
physical filter. The mapping is marked measured, convention or contradicted.

**Reference event**:
A named swell with conditions attached, whether or not the surfer was there.
Below sessions on the evidence ladder.

**Archetype**:
A well-known setup, with its bathymetry and working conditions, used as an
example of what a wave type is. Below sessions on the evidence ladder.

**Evidence ladder**:
The order of trust: what happened at the break, then measured waves and wind,
then bathymetry, then a local transformation, then forecast or reanalysis, then
geometry or visual inference. Lower rungs can nominate; they cannot confirm.

**Reading**:
One value from one source, with its source, status, fetch time and anything it
dropped. A value without a reading is not evidence.

**Source status**:
`ok`, `degraded`, `failed` or `skipped`. A degraded reading names what it
dropped.

**Provenance**:
Where a stored value came from: `derived` (measured by the tool), `manual`
(entered by a person) or `default` (a placeholder).

## Imagery

**Imagery frame**:
One georeferenced image of a place, with its source, capture date and pixel
size.
_Avoid_: screenshot, picture

**Capture date**:
The day the image was taken. Not the release date of a mosaic.

**Static geometry**:
What an imagery frame shows that does not change with the sea: reef outline,
channel, bar shape, rock or sand.

**Dynamic wave state**:
What an imagery frame shows about the sea at capture time: swell lines,
wavelength, whitewash, wave shape. Reported apart from static geometry.

## Watching

**Saved setup**:
A setup's working conditions written as swell, wind and tide ranges, so a
scheduled run can test them.
_Avoid_: alert rule, saved search

**Alert**:
The message a scheduled run sends when a saved setup's conditions are met.

**Snapshot**:
A forecast frozen when it was issued, kept so it can be scored against what
happened.

**Verification**:
Scoring snapshots against buoy observations and sessions after the event.
