from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .bathymetry import NceiBathymetry
from .calibrate import ConditionCache, calibrate
from .call import (
    HEADS_UP_DAYS,
    SHARP_DAYS,
    Call,
    Candidate,
    SpotOutlook,
    falsifiers_for,
    make_call,
    score_outlook,
    signals_for,
)
from .forecast import ForecastService, Sources, SpotForecast
from .geometry import GeometryCache, beach_slope
from .ndbc import NdbcObservations
from .open_meteo import MarineModelSet, OpenMeteoArchive
from .score import Components
from .sessions import (
    COLUMNS as SESSION_COLUMNS,
    SessionFileError,
    default_sessions_path,
    parse_date,
    parse_rating,
    parse_time,
)
from .sources import Archive, Http, Reading, Window
from .spots import Derived, Spot, SpotBook, save_spots
from .tides import TideAdapter
from .waves import Forecast, TidePoint, WaveField, m_to_ft, mps_to_kt

PROGRAM = "surf"

EXIT_OK = 0
# The command ran and the answer is "no" — distinct from a crash and from usage.
EXIT_FAILED = 1
# argparse's own code for a malformed command line.
EXIT_USAGE = 2

# `????-03-03` is a legal log date: month and day known, year not.
_PARTIAL_DATE = re.compile(r"^\?{4}-\d{2}-\d{2}\??$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def height(metres: float) -> str:
    """Both units: the spot list is global and readers think in either."""
    return f"{metres:.1f} m ({m_to_ft(metres):.1f} ft)"


def speed(mps: float) -> str:
    return f"{mps:.1f} m/s ({mps_to_kt(mps):.0f} kt)"


def _bearing(deg: float) -> str:
    return f"{deg:.0f} deg"


def _derived(value: Derived | None, fmt: str = "{:.3f}") -> str:
    """A derived number is never printed without its provenance."""
    if value is None:
        return "unknown"
    text = fmt.format(value.value) + f" ({value.provenance})"
    return f"{text} — {value.note}" if value.note else text


def _components(components: Components) -> str:
    c = components
    return (
        f"BARREL {c.barrel.value:.2f}   SIZE {c.size.value:.2f}   "
        f"CLEANNESS {c.cleanness.value:.2f}   CONFIDENCE {c.confidence.value:.2f}"
    )


def _water(field: WaveField | None) -> str:
    if field is None:
        return "no wave field"
    swell = field.primary
    bits: list[str] = []
    if swell is not None:
        bits.append(
            f"{height(swell.height_m)} at {swell.period_s:.0f} s from "
            f"{_bearing(swell.direction_deg)}"
        )
    elif field.total_height_m is not None:
        bits.append(f"{height(field.total_height_m)} total")
    if field.wind is not None:
        bits.append(f"wind {speed(field.wind.speed_mps)} from {_bearing(field.wind.direction_deg)}")
    bits.append(f"[{field.model or 'unnamed model'}]")
    return "  ".join(bits)


def build_sources(
    *,
    http: Http | None = None,
    surfline: bool | None = None,
    models: Sequence[str] | None = None,
) -> Sources:
    """One shared HTTP client on purpose: the circuit breakers live on the
    client, so sources hitting the same host back off together.
    """
    http = http if http is not None else Http()
    marine = MarineModelSet(http) if models is None else MarineModelSet(http, models)
    return Sources(
        forecast=marine.sources,
        observations=NdbcObservations(http),
        tides=TideAdapter(http),
        depth=NceiBathymetry(http),
        benchmark=_benchmark(http, surfline),
    )


def _benchmark(http: Http, enabled: bool | None) -> Any:
    """Loaded by name rather than imported: the Surfline module is optional and
    deleting it must leave a working program.
    """
    try:
        module = import_module(f"{__package__}.surfline")
    except ImportError:
        return None
    return module.benchmark(http, enabled=enabled)


def outlook_from(forecast: SpotForecast) -> SpotOutlook:
    """Transpose a fetched `SpotForecast` into the `SpotOutlook` the call scores.

    `SpotForecast` merges models per hour, which is what CONFIDENCE needs;
    scoring wants one `Forecast` per model instead.
    """
    by_model: dict[str, list[WaveField]] = {}
    for hour in forecast.hours:
        for wave in hour.fields:
            by_model.setdefault(wave.model, []).append(wave)

    tide: dict[datetime, TidePoint] = {}
    for hour in forecast.hours:
        if hour.tide is not None:
            tide[hour.tide.time] = hour.tide

    observed = next((h.observed for h in forecast.hours if h.observed is not None), None)
    return SpotOutlook(
        spot=forecast.spot,
        forecasts=tuple(
            Forecast(forecast.spot.id, model, tuple(waves))
            for model, waves in sorted(by_model.items())
        ),
        observed=observed,
        tide=tuple(tide[at] for at in sorted(tide)),
        slope=forecast.slope,
        notes=forecast.notes,
    )


@dataclass
class Console:
    """Everything impure a command touches arrives through here. Built lazily so
    `surf session add` constructs no network stack at all.
    """

    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    sources: Sources | None = None
    book: SpotBook | None = None
    archive: Archive | None = None
    clock: Callable[[], datetime] = _now
    surfline: bool | None = None

    def say(self, line: str = "") -> None:
        print(line, file=self.out)

    def warn(self, line: str) -> None:
        print(line, file=self.err)

    def spots(self) -> SpotBook:
        if self.book is None:
            self.book = SpotBook.load()
        return self.book

    def ports(self) -> Sources:
        if self.sources is None:
            self.sources = build_sources(surfline=self.surfline)
        return self.sources

    def bathymetry(self) -> Any:
        depth = self.ports().depth
        if depth is None:
            raise SystemExit("no bathymetry source configured; cannot derive geometry")
        return depth

    def service(self) -> ForecastService:
        return ForecastService(self.ports(), cache=GeometryCache(), clock=self.clock)


def _select(book: SpotBook, region: str | None, names: Sequence[str]) -> tuple[list[Spot], list[str]]:
    """Spots to scan, plus the names that resolved to nothing — returned rather
    than skipped, so a typo cannot silently shrink the scan.
    """
    if names:
        found: list[Spot] = []
        missing: list[str] = []
        for name in names:
            spot = book.resolve(name)
            (found.append(spot) if spot is not None else missing.append(name))
        return found, missing
    if region:
        return list(book.in_region(region)), []
    return list(book), []


def cmd_sources(args: argparse.Namespace, console: Console) -> int:
    """Preflight every source once: one call each, one line each."""
    service = console.service()
    health = service.health(refresh=True)
    if not health:
        console.warn("no sources configured")
        return EXIT_FAILED

    width = max(len(name) for name in health)
    console.say(f"{'SOURCE'.ljust(width)}  STATUS    DETAIL")
    for name, reading in health.items():
        detail = reading.note or ("reachable" if reading.ok and reading.value else "")
        if reading.dropped:
            detail = (detail + " dropped=" + ",".join(reading.dropped)).strip()
        console.say(f"{name.ljust(width)}  {reading.status:<8}  {detail}".rstrip())

    live = service.live_sources()
    console.say()
    console.say(f"{len(live)}/{len(health)} sources live at {console.clock():%Y-%m-%d %H:%M}Z")
    if not live:
        console.warn("every source is down — no forecast can be built right now")
        return EXIT_FAILED
    return EXIT_OK


def _fetch(
    console: Console, spots: Sequence[Spot], window: Window
) -> tuple[list[SpotOutlook], list[Reading[Any]], list[SpotForecast]]:
    service = console.service()
    outlooks: list[SpotOutlook] = []
    readings: list[Reading[Any]] = []
    fetched: list[SpotForecast] = []
    for spot in spots:
        forecast = service.outlook(spot, window)
        fetched.append(forecast)
        readings.extend(forecast.readings)
        outlooks.append(outlook_from(forecast))
    return outlooks, readings, fetched


def _unique(lines: Sequence[str]) -> list[str]:
    """Same caveat, once: a source that failed at every spot yields one identical
    label per spot, which reads as many problems instead of one."""
    seen: list[str] = []
    for line in lines:
        if line not in seen:
            seen.append(line)
    return seen


def _candidate_line(candidate: Candidate) -> str:
    return (
        f"{candidate.spot_name}  {_when(candidate)}  "
        f"{_components(candidate.components)}"
    )


def render_call(call: Call, console: Console) -> None:
    """One call: spot, day, time, why, and what would make it wrong."""
    winner = call.winner
    console.say(f"CALL  {winner.spot_name.upper()}  {call.window or f'{winner.at:%a %d %b %H:%M} UTC'}")
    console.say(f"  {_components(winner.components)}")
    if winner.tide_note:
        console.say(f"  tide: {winner.tide_note}")
    if winner.access_note:
        console.say(f"  access: {winner.access_note} — a cost, not a filter")
    if winner.model_only:
        console.say("  model-only: no buoy observation covers this spot")

    console.say()
    console.say("why")
    for signal in call.signals:
        console.say(f"  - {signal.text}")

    console.say()
    console.say("wrong if")
    for falsifier in call.falsifiers:
        console.say(f"  - {falsifier}")

    if call.neighbour:
        console.say()
        console.say("resembles")
        console.say(f"  {call.neighbour}")

    if call.runners_up:
        console.say()
        console.say("also in play")
        for runner in call.runners_up:
            console.say(f"  - {_candidate_line(runner)}")

    if call.horizon_note:
        console.say()
        console.say("beyond the sharp horizon")
        console.say(f"  {call.horizon_note}")

    if call.caveats:
        console.say()
        console.say("caveats")
        for caveat in _unique(call.caveats):
            console.say(f"  - {caveat}")


def _when(candidate: Candidate) -> str:
    if candidate.timezone:
        try:
            return f"{candidate.at.astimezone(ZoneInfo(candidate.timezone)):%a %d %b %H:%M %Z}"
        except ZoneInfoNotFoundError:
            pass
    return f"{candidate.at:%a %d %b %H:%M} UTC"


def cmd_call(args: argparse.Namespace, console: Console) -> int:
    """Scan the spots, score every hour, commit to one. Exits non-zero when no
    spot produced a scoreable hour.
    """
    book = console.spots()
    spots, missing = _select(book, args.region, args.spot)
    for name in missing:
        console.warn(f"no spot matches {name!r} — try `surf spot <name>` or check data/spots.tsv")
    if not spots:
        console.warn("no spots selected; nothing to call")
        return EXIT_FAILED

    now = console.clock()
    window = Window(start=now.replace(minute=0, second=0, microsecond=0), hours=args.days * 24)
    sharp = min(args.days, SHARP_DAYS)
    heads_up = max(args.days, sharp)

    console.say(
        f"scanning {len(spots)} spot{'s' if len(spots) != 1 else ''} "
        f"({args.region or 'every region'}) over {args.days} days from "
        f"{window.start:%Y-%m-%d %H:%M}Z"
    )
    console.say()

    outlooks, readings, _ = _fetch(console, spots, window)
    reading = make_call(
        outlooks,
        now=now,
        sharp_days=sharp,
        heads_up_days=heads_up,
        daylight_only=not args.any_hour,
        readings=readings,
    )

    call = reading.value
    if call is not None and heads_up <= sharp:
        # Nothing was fetched past the sharp horizon, so a heads-up here would
        # report an absence that was never looked for.
        call = replace(call, horizon_note="")

    if reading.value is None:
        console.warn(f"no call: {reading.note or 'nothing scoreable'}")
        for line in reading.dropped:
            console.warn(f"  dropped: {line}")
        for failure in (r for r in readings if not r.ok):
            console.warn(f"  {failure.label()}")
        return EXIT_FAILED

    render_call(call, console)
    console.say()
    console.say(f"[{reading.label()}]")
    return EXIT_OK


def _geometry_lines(spot: Spot) -> list[str]:
    """Geometry is cached, never guessed, so a `default` provenance here is a
    warning rather than a value."""
    return [
        f"  id            {spot.id}",
        f"  position      {spot.lat:.4f}, {spot.lon:.4f}  ({spot.region}, {spot.break_type})",
        f"  shore normal  {_derived(spot.shore_normal, '{:.0f} deg')}",
        f"  offshore wind {_bearing(spot.offshore_wind_bearing)} (dead offshore here)",
        f"  beach slope   {_derived(spot.beach_slope)}",
        f"  offshore pt   {spot.offshore_lat:.4f}, {spot.offshore_lon:.4f} (fixed)",
        "  buoys         " + (", ".join(spot.buoys) if spot.buoys else "none — model-only"),
        f"  tide station  {spot.tide_station or 'none — falls back to Open-Meteo sea level'}",
        f"  access        {spot.access or 'unrecorded'}",
    ]


def cmd_spot(args: argparse.Namespace, console: Console) -> int:
    """One spot in depth: geometry with provenance, then what the sources said
    and what is missing — a spot with no buoy and a default slope still scores.
    """
    book = console.spots()
    spot = book.resolve(args.name)
    if spot is None:
        console.warn(f"no spot matches {args.name!r}")
        console.warn(f"known ids: {', '.join(s.id for s in book)}")
        return EXIT_FAILED

    console.say(spot.name)
    for line in _geometry_lines(spot):
        console.say(line)

    now = console.clock()
    window = Window(start=now.replace(minute=0, second=0, microsecond=0), hours=args.days * 24)
    forecast = console.service().outlook(spot, window)

    console.say()
    console.say("sources")
    for line in forecast.label_lines() or ("  none attempted",):
        console.say(f"  {line}")
    console.say()
    console.say(f"slope for scoring  {forecast.slope_basis or 'stored value'}")
    console.say(f"hours              {len(forecast.hours)} of {window.hours} asked")
    console.say(f"models             {', '.join(forecast.models) or 'none answered'}")
    console.say(f"status             {forecast.status}")
    for note in forecast.notes:
        console.say(f"  note: {note}")

    if not forecast.hours:
        console.warn("no hour could be assembled for this spot")
        return EXIT_FAILED

    outlook = outlook_from(forecast)
    hours, dropped = score_outlook(
        outlook, start=now, end=now + timedelta(days=min(args.days, SHARP_DAYS))
    )
    for line in dropped:
        console.say(f"  dropped: {line}")
    if not hours:
        console.warn("nothing scoreable inside the sharp horizon")
        return EXIT_FAILED

    best = max(hours, key=lambda h: (h.key, -h.at.timestamp()))
    console.say()
    console.say(f"best hour  {best.at:%a %d %b %H:%M} UTC")
    console.say(f"  {_components(best.components)}")
    console.say(f"  {_water(best.reference)}")
    console.say("  why")
    for signal in signals_for(best, outlook):
        console.say(f"    - {signal.text}")
    console.say("  wrong if")
    for falsifier in falsifiers_for(best, outlook):
        console.say(f"    - {falsifier}")
    return EXIT_OK


def cmd_calibrate(args: argparse.Namespace, console: Console) -> int:
    """Offline by default, reading the condition cache; `--online` opts in to
    reaching the archive and filling that cache.
    """
    archive: Archive | None = None
    if args.online:
        archive = console.archive if console.archive is not None else OpenMeteoArchive(Http())

    report = calibrate(
        archive=archive,
        book=console.spots(),
        cache=ConditionCache(),
        refresh=args.refresh,
        matrix=not args.no_matrix,
    )
    console.say(report.render())
    if not archive:
        console.say()
        console.say("(offline: conditions came from the cache only; --online refills it)")
    if not report.passed:
        console.warn(f"{len(report.failed)} check(s) failed")
        return EXIT_FAILED
    return EXIT_OK


def _check_date(raw: str) -> str:
    """Accept exactly what the loader accepts: `2025-09-30`, `2025-09-30?` and
    `????-03-03`. Rejected here rather than written, because `parse_date` answers
    "unknown" for a typo and for a genuine gap alike.
    """
    text = raw.strip()
    if _PARTIAL_DATE.match(text):
        return text
    on, _ = parse_date(text)
    if on is None:
        raise SessionFileError(
            f"date {raw!r} is neither YYYY-MM-DD (a trailing ? is fine) nor ????-MM-DD"
        )
    return text


def exposure_module():
    """Imported lazily: it needs shapely, which is not a package dependency."""
    return import_module("surf.exposure")


def cmd_exposure(args: argparse.Namespace, console: Console) -> int:
    """Swell exposure per 200 m of coast, written as a styled KMZ.

    Geometry only — facing times the unblocked fraction of the arriving fan.
    No bathymetry, refraction, wind or forecast enters this number.
    """
    module = exposure_module()
    try:
        return module.run(args, console.say)
    except module.ExposureError as exc:
        console.warn(f"{PROGRAM} exposure: {exc}")
        return EXIT_FAILED


def cmd_geometry(args: argparse.Namespace, console: Console) -> int:
    """Derive per-spot geometry from the sea floor and, with --write, store it.

    Until this has run, every spot carries `provenance='default'` and BARREL
    scores off the same nominal slope everywhere. A spot the sea floor cannot
    answer for keeps its default and says why.
    """
    book = console.spots()
    wanted = [s for s in book if not args.spot or s.id == args.spot or s.name == args.spot]
    if not wanted:
        console.say(f"no spot matches {args.spot!r}")
        return 2

    source = console.bathymetry()
    updated: list[Spot] = []
    changes = 0
    console.say(f"{'SPOT':<16} {'SLOPE':<10} {'PROV':<9} BASIS")
    for spot in book:
        if spot not in wanted:
            updated.append(spot)
            continue
        reading = beach_slope(spot, source, refresh=args.refresh)
        slope = reading.value.as_derived() if reading.value else None
        if slope is None:
            note = (reading.value.basis if reading.value else reading.note) or "no profile"
            console.say(f"{spot.id:<16} {'—':<10} {'default':<9} {note}")
            updated.append(spot)
            continue
        console.say(f"{spot.id:<16} {slope.value:<10.5f} {'derived':<9} {slope.note}")
        updated.append(replace(spot, beach_slope=slope))
        changes += 1

    console.say()
    console.say(f"{changes}/{len(wanted)} spots answered by the sea floor")
    if not args.write:
        console.say("(nothing written; --write stores these in the spot database)")
        return 0
    save_spots(updated)
    console.say(f"wrote {changes} derived slopes to the spot database")
    return 0


def cmd_session(args: argparse.Namespace, console: Console) -> int:
    """A raw append, not a load-and-save: rewriting the file through the parser
    would drop its comment header.
    """
    path = Path(args.path) if args.path else default_sessions_path()
    try:
        on = _check_date(args.date)
        parse_time(args.time)
        rating = parse_rating(args.rating)
    except SessionFileError as exc:
        console.warn(f"not written: {exc}")
        return EXIT_FAILED

    if "\t" in "".join((args.date, args.spot, args.time, args.rating, args.notes)):
        console.warn("not written: a field contains a tab, which would split the row")
        return EXIT_FAILED

    row = "\t".join(
        (on, args.spot.strip(), args.time.strip(), "" if rating is None else str(rating), args.notes.strip())
    )
    if path.exists():
        text = path.read_text(encoding="utf-8")
        prefix = "" if text.endswith("\n") or not text else "\n"
    else:
        prefix = "\t".join(SESSION_COLUMNS) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + row + "\n")

    console.say(f"appended to {path}")
    console.say(f"  {row}")

    spot = console.spots().resolve(args.spot)
    if spot is None:
        console.warn(
            f"warning: {args.spot!r} does not resolve to a spot — the row is kept and will "
            "show up in `surf calibrate` as unresolved, never dropped"
        )
    else:
        console.say(f"  resolves to {spot.id} ({spot.name})")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Forecast the ocean from open physical data. A call, not a table.",
    )
    parser.add_argument("--debug", action="store_true", help="re-raise instead of reporting")
    parser.add_argument(
        "--surfline",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="opt in to the Surfline benchmark (default: $SURF_SURFLINE). Never a dependency",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sources = sub.add_parser("sources", help="preflight every source once and print its status")
    sources.set_defaults(run=cmd_sources)

    call = sub.add_parser("call", help="where to surf and when, with what would make it wrong")
    call.add_argument("--region", default=None, help="region prefix, e.g. US or US-RI")
    call.add_argument("--spot", action="append", default=[], help="name or id; repeatable")
    call.add_argument(
        "--days",
        type=int,
        default=SHARP_DAYS,
        help=f"days to fetch. Only the first {SHARP_DAYS} are sharp; "
        f"{SHARP_DAYS + 1}-{HEADS_UP_DAYS} are an arrival heads-up",
    )
    call.add_argument(
        "--any-hour", action="store_true",
        help="score hours in the dark too; by default the call only offers hours you "
             "could actually surf, computed per spot and date",
    )
    call.set_defaults(run=cmd_call)

    spot = sub.add_parser("spot", help="one spot in depth: geometry, provenance, what is missing")
    spot.add_argument("name", help="spot id, name or alias")
    spot.add_argument("--days", type=int, default=3, help="days to fetch")
    spot.set_defaults(run=cmd_spot)

    calibrate_cmd = sub.add_parser("calibrate", help="check the model against the session log")
    calibrate_cmd.add_argument(
        "--online", action="store_true", help="reach the archive to fill the condition cache"
    )
    calibrate_cmd.add_argument("--refresh", action="store_true", help="ignore cached conditions")
    calibrate_cmd.add_argument(
        "--no-matrix", action="store_true", help="score without the response matrix"
    )
    calibrate_cmd.set_defaults(run=cmd_calibrate)

    geometry = sub.add_parser("geometry", help="derive per-spot geometry from the sea floor")
    geometry.add_argument("--spot", default="", help="one spot id or name; default is all")
    geometry.add_argument("--write", action="store_true", help="store the derived values")
    geometry.add_argument("--refresh", action="store_true", help="ignore the geometry cache")
    geometry.set_defaults(run=cmd_geometry)

    session = sub.add_parser("session", help="append a row to the session log")
    session.add_argument("action", choices=("add",))
    session.add_argument("--date", required=True, help="YYYY-MM-DD, YYYY-MM-DD? or ????-MM-DD")
    session.add_argument("--spot", required=True, help="how you name the spot; resolved by alias")
    session.add_argument("--time", default="", help="HH:MM, a word like 'early', or empty")
    session.add_argument("--rating", default="", help="1-5, your own call. Empty means unrated")
    session.add_argument("--notes", default="", help="what it was actually like")
    session.add_argument("--path", default=None, help="session file to append to")
    session.set_defaults(run=cmd_session)

    exposure = sub.add_parser(
        "exposure", help="colour a coastline GeoJSON by exposure to one swell direction"
    )
    exposure_module().add_arguments(exposure)
    exposure.set_defaults(run=cmd_exposure)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    console: Console | None = None,
    sources: Sources | None = None,
    book: SpotBook | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Parse, dispatch, and turn anything that escapes into one line and code 1;
    `--debug` re-raises instead.
    """
    args = build_parser().parse_args(argv)
    if console is None:
        console = Console(
            out=out if out is not None else sys.stdout,
            err=err if err is not None else sys.stderr,
            sources=sources,
            book=book,
            surfline=args.surfline,
        )
    try:
        return int(args.run(args, console))
    except KeyboardInterrupt:  # pragma: no cover — interactive only
        console.warn("interrupted")
        return EXIT_FAILED
    except Exception as exc:
        if args.debug:
            raise
        console.warn(f"{PROGRAM} {args.command}: {type(exc).__name__}: {exc}")
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
