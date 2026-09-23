from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .bathymetry import NceiBathymetry
from .bands import bands_from_log
from .calibrate import ConditionCache, calibrate, recover
from .climate import (
    ClimateResult,
    ClimateSource,
    OpenMeteoClimate,
    cache_path,
    load_cache,
    measure_zone,
    save_cache,
)
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
from .evidence import default_evidence
from .geometry import GeometryCache, beach_slope
from .imagery import (
    imagery_cache_path,
    load_frames,
    load_screen,
    save_screen,
    save_wave_state,
    screen_candidates,
    screen_wave_state,
    wave_state_cache_path,
)
from .lexicon import lexicon_from_log, resolve_phrase
from .ndbc import NdbcObservations
from .open_meteo import MarineModelSet, OpenMeteoArchive
from .reach import reach_from_log
from .score import Components
from .snapshots import (
    SnapshotError,
    SnapshotStore,
    load_observations,
    parse_snapshot_time,
    snapshot_from_hour,
    verify_snapshots,
)
from .sessions import (
    SessionFileError,
    append_session,
    audit_sessions,
    default_sessions_path,
    load_sessions,
)
from .sources import Archive, Http, Reading, Window
from .spots import Derived, Spot, SpotBook, data_dir, save_spots
from .tides import TideAdapter
from .tube import BREAKING_BAND_M, Intensity, measure as measure_intensity
from .terrain import (
    TerrainScan,
    TerrainSource,
    bbox_locations,
    load_terrain_cache,
    save_terrain_cache,
    scan_zone,
    terrain_cache_path,
)
from .waves import WaveField, m_to_ft, mps_to_kt
from .watch import SavedSetup, SetupConditions, SetupStore, WatchError, run_watch

PROGRAM = "surf"

EXIT_OK = 0
# The command ran and the answer is "no" — distinct from a crash and from usage.
EXIT_FAILED = 1
# argparse's own code for a malformed command line.
EXIT_USAGE = 2


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


@dataclass
class Console:
    """Everything impure a command touches arrives through here. Built lazily so
    `surf session add` constructs its archive lazily only when a new rated
    session needs conditions for the REACH ratchet.
    """

    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    sources: Sources | None = None
    book: SpotBook | None = None
    archive: Archive | None = None
    climate_source: ClimateSource | None = None
    terrain_source: TerrainSource | None = None
    clock: Callable[[], datetime] = _now
    surfline: bool | None = None
    # Commands may leave their source receipt here for another transport (MCP,
    # mobile) to return without re-running the calculation.
    readings: list[Reading[Any]] = field(default_factory=list)

    def say(self, line: str = "") -> None:
        print(line, file=self.out)

    def warn(self, line: str) -> None:
        print(line, file=self.err)

    def record(self, *readings: Reading[Any]) -> None:
        """Keep the labelled source receipt alongside the human rendering."""
        self.readings.extend(readings)

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


@dataclass
class _RecordingArchive:
    """Pass archive receipts to the shared transport without changing recovery."""

    archive: Archive
    console: Console

    @property
    def name(self) -> str:
        return self.archive.name

    def preflight(self) -> Reading[bool]:
        reading = self.archive.preflight()
        self.console.record(reading)
        return reading

    def conditions(self, spot: Spot, on: date, hour: int) -> Reading[WaveField]:
        reading = self.archive.conditions(spot, on, hour)
        self.console.record(reading)
        return reading


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
    console.record(*health.values())
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
        outlooks.append(SpotOutlook.from_forecast(forecast))
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
    line = (
        f"{candidate.spot_name}  {_when(candidate)}  "
        f"{_components(candidate.components)}"
    )
    return line + (f"  BAND {candidate.band_floor}" if candidate.band_floor else "  BAND none")


def render_call(call: Call, console: Console) -> None:
    """One call: spot, day, time, why, and what would make it wrong."""
    winner = call.winner
    console.say(f"CALL  {winner.spot_name.upper()}  {call.window or f'{winner.at:%a %d %b %H:%M} UTC'}")
    console.say(f"  {_components(winner.components)}")
    console.say(f"  REACH {winner.reach.render()}")
    console.say(f"  BAND {winner.band_floor or 'none for this setup type'}")
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
    console.record(*readings)
    cache = ConditionCache()
    bands = bands_from_log(book, cache=cache)
    reach = reach_from_log(book, cache=cache)
    entries = lexicon_from_log(book)
    physical_filters = resolve_phrase(args.want, entries) if args.want else ()
    if args.want and not physical_filters:
        console.warn(f"no physical filter is known for {args.want!r}")
        return EXIT_FAILED
    reading = make_call(
        outlooks,
        now=now,
        sharp_days=sharp,
        heads_up_days=heads_up,
        daylight_only=not args.any_hour,
        readings=readings,
        evidence=default_evidence(),
        band_floors={spot.id: bands[spot.break_type].render() for spot in spots if spot.break_type in bands},
        physical_filters=physical_filters,
        reach=reach,
    )
    console.record(reading)

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
        f"  zone          {spot.zone or 'unassigned'} ({spot.zone_provenance})"
        + (f" — {spot.zone_note}" if spot.zone_note else ""),
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
    band = bands_from_log(book).get(spot.break_type)
    console.say(f"  band floor    {band.render() if band else 'none for this setup type'}")

    now = console.clock()
    window = Window(start=now.replace(minute=0, second=0, microsecond=0), hours=args.days * 24)
    forecast = console.service().outlook(spot, window)
    console.record(*forecast.readings)

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

    outlook = SpotOutlook.from_forecast(forecast)
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
        archive = _RecordingArchive(
            console.archive if console.archive is not None else OpenMeteoArchive(Http()),
            console,
        )

    report = calibrate(
        archive=archive,
        book=console.spots(),
        cache=ConditionCache(),
        sessions=load_sessions(args.path, book=console.spots()) if args.path else None,
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


def cmd_lexicon(args: argparse.Namespace, console: Console) -> int:
    """Show how session language becomes physical filters."""
    entries = lexicon_from_log(console.spots())
    wanted = tuple(
        entry for entry in entries
        if not args.phrase or entry.term in args.phrase.casefold()
    )
    if not wanted:
        console.warn(f"no lexicon term in {args.phrase!r}")
        return EXIT_FAILED
    for entry in wanted:
        filters = ", ".join(item.render() for item in entry.filters)
        console.say(
            f"{entry.term}: {entry.status} (n={entry.supporting_sessions}) "
            f"-> {filters} — {entry.physics}"
        )
    return EXIT_OK


def cmd_session_audit(args: argparse.Namespace, console: Console) -> int:
    """Canonicalize spot ids and make only evidence-backed log repairs."""
    archive: Archive | None = console.archive
    if archive is None and args.online:
        archive = OpenMeteoArchive(Http())
    if archive is not None:
        archive = _RecordingArchive(archive, console)
    years = None
    if args.years:
        try:
            years = tuple(int(part.strip()) for part in args.years.split(",") if part.strip())
        except ValueError:
            console.warn("session audit: --years must be comma-separated integers")
            return EXIT_USAGE
    try:
        report = audit_sessions(
            args.path,
            book=console.spots(),
            archive=archive,
            years=years,
            write=not args.dry_run,
        )
    except SessionFileError as exc:
        console.warn(f"session audit: {exc}")
        return EXIT_FAILED

    console.say("SESSION AUDIT")
    console.say(
        f"resolvable before: {report.before_resolvable}  "
        f"after: {report.after_resolvable}"
    )
    if report.repairs:
        console.say("repairs")
        for repair in report.repairs:
            console.say(
                f"  row {repair.row} {repair.field}: {repair.before!r} -> "
                f"{repair.after!r} ({repair.basis})"
            )
    else:
        console.say("repairs: none")
    if report.questions:
        console.say("questions")
        seen: set[tuple[str, str, str]] = set()
        for question in report.questions:
            key = (question.raw_date, question.raw_spot, question.question)
            if key in seen:
                continue
            seen.add(key)
            console.say(
                f"  row {question.row} {question.raw_date}\t{question.raw_spot}: "
                f"{question.question}"
            )
    else:
        console.say("questions: none")
    if report.missing_regime:
        console.say("missing regime")
        for session in report.missing_regime:
            console.say(f"  {session.raw_date}\t{session.raw_spot}")
    if report.unanswerable:
        console.say("permanent unanswerables")
        seen: set[tuple[str, str, str]] = set()
        for question in report.unanswerable:
            key = (question.raw_date, question.raw_spot, question.question)
            if key in seen:
                continue
            seen.add(key)
            console.say(
                f"  row {question.row} {question.raw_date}\t{question.raw_spot}: "
                f"{question.question}"
            )
    hand = [s for s in report.after if "[hand:" in s.notes]
    if hand:
        console.say("hand resolutions")
        for session in hand:
            console.say(f"  {session.raw_date}\t{session.raw_spot}: {session.notes}")
    if report.wrote:
        console.say(f"wrote {args.path or default_sessions_path()}")
    elif args.dry_run:
        console.say("(dry run: nothing written)")
    elif not report.repairs:
        console.say("(nothing written: no repairs were proven)")
    if archive is None:
        console.say("(offline: date recovery requires --online and an archive)")
    return EXIT_OK


def _receipt(result: Any) -> Reading[Any]:
    """A derived result that carries its own provenance, as a source receipt."""
    return Reading(result, result.source, result.status, result.fetched_at, note=result.note, dropped=result.dropped)


def _render_climate(result: ClimateResult, console: Console) -> None:
    console.say(f"CLIMATE  {result.zone}  {result.start} to {result.end}")
    console.say(f"  source         {result.source}:{result.status}")
    console.say(f"  fetched_at     {result.fetched_at.isoformat()}")
    if result.note:
        console.say(f"  basis          {result.note}")
    console.say(f"  terrain shelter {result.terrain_shelter}")
    for dropped in result.dropped:
        console.say(f"  dropped         {dropped}")
    for cell in result.cells:
        console.say()
        console.say(f"  CELL {cell.spot_id}")
        console.say(f"    season             {cell.season}")
        console.say(f"    shared timestamps  {cell.shared_hours} hours")
        console.say(f"    complete overlap   {cell.overlap_hours} hours")
        console.say(f"    days               {cell.days}")
        console.say(f"    independent events {cell.independent_events}")
        console.say(f"    duration           {cell.total_duration_hours:.1f} hours total, {cell.mean_duration_hours:.1f} hours/event")
        local = ", ".join(f"{hour:02d}:00 ({count})" for hour, count in cell.local_hours) or "none"
        console.say(f"    local hour         {local}")
        console.say(f"    years              {len(cell.years_with_event)}/{cell.years_total} with an event ({cell.fraction_years:.1%})")
        if cell.rejected:
            console.say(
                f"    REJECTED for season: no complete swell/wind overlap "
                f"({cell.overlap_hours} of {cell.shared_hours} shared hours)"
            )
    if not result.cells:
        console.say("  no cells answered")


def cmd_climate(args: argparse.Namespace, console: Console) -> int:
    """Measure complete swell/wind hours for every spot cell in a zone."""
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end < start:
        raise ValueError("--end must not precede --start")
    book = console.spots()
    spots = book.in_zone(args.zone)
    if not spots:
        console.warn(f"no spots in zone {args.zone!r}")
        return EXIT_FAILED
    path = cache_path(args.zone, start, end)
    if path.exists() and not args.refresh:
        result = load_cache(path, book)
        console.record(_receipt(result))
        _render_climate(result, console)
        return EXIT_OK if result.status in ("ok", "degraded") else EXIT_FAILED

    source = console.climate_source or OpenMeteoClimate(Http())
    result, samples = measure_zone(args.zone, spots, start, end, source=source, now=console.clock())
    save_cache(path, result, samples)
    console.record(_receipt(result))
    _render_climate(result, console)
    return EXIT_FAILED if result.status == "failed" else EXIT_OK


def _render_terrain(zone: str, source: str, status: str, fetched_at: datetime, scans: tuple[TerrainScan, ...], console: Console) -> None:
    console.say(f"TERRAIN  {zone}")
    console.say(f"  source         {source}:{status}")
    console.say(f"  fetched_at     {fetched_at.isoformat()}")
    for scan in scans:
        console.say()
        console.say(f"  CELL {scan.spot_id}  {scan.status}")
        console.say(f"    resolution     {scan.resolution_m or 'unknown'} m")
        console.say(f"    vertical datum {scan.vertical_datum}")
        if scan.note:
            console.say(f"    note           {scan.note}")
        for dropped in scan.dropped:
            console.say(f"    dropped        {dropped}")
        if not scan.candidates:
            console.say("    candidates     none")
        for candidate in scan.candidates:
            console.say(
                f"    terrain object {candidate.object_type} at "
                f"{candidate.lat:.5f}, {candidate.lon:.5f}; "
                f"{candidate.cells} independent cells, relief {candidate.relief_m:.1f} m"
            )
            console.say(f"      label: {candidate.label}")
            console.say(f"      resolution perturbation stable: {candidate.resolution_survives}")
            console.say(f"      smoothing stable: {candidate.smoothing_survives}")
            console.say(f"      {candidate.promotion}")


def _floats(raw: str, count: int, usage: str) -> tuple[float, ...]:
    """A comma-separated option value holding exactly `count` numbers."""
    values = tuple(float(value.strip()) for value in raw.split(","))
    if len(values) != count:
        raise ValueError(usage)
    return values


def _bbox(raw: str) -> tuple[float, ...]:
    return _floats(raw, 4, "--bbox must be min_lat,min_lon,max_lat,max_lon")


def cmd_terrain(args: argparse.Namespace, console: Console) -> int:
    """Scan feature-resolving bathymetry and propose terrain objects."""
    bbox = _bbox(args.bbox)
    locations = bbox_locations(args.zone, bbox, step_deg=args.step)
    if not locations:
        raise ValueError("--bbox and --step produce no scan cells")
    path = terrain_cache_path(args.zone, bbox)
    if path.exists() and not args.refresh:
        zone, status, fetched_at, scans = load_terrain_cache(path)
        source_name = scans[0].source if scans else "ncei"
        dropped = tuple(item for scan in scans for item in scan.dropped)
        console.record(Reading(scans, source_name, status, fetched_at, dropped=dropped))
        _render_terrain(zone, source_name, status, fetched_at, scans, console)
        return EXIT_OK
    source = console.terrain_source or NceiBathymetry(Http())
    status, fetched_at, scans_tuple = scan_zone(locations, source, now=console.clock())
    save_terrain_cache(path, args.zone, scans_tuple, source.name, status, fetched_at)
    console.record(Reading(scans_tuple, source.name, status, fetched_at, dropped=tuple(item for scan in scans_tuple for item in scan.dropped)))
    _render_terrain(args.zone, source.name, status, fetched_at, scans_tuple, console)
    return EXIT_FAILED if status == "failed" else EXIT_OK


def cmd_tube(args: argparse.Namespace, console: Console) -> int:
    """Can the sea floor here hold a barrel? The sea floor alone answers."""
    band = _floats(args.band, 2, "--band must be shallow,deep in metres")
    spot, label = _tube_target(args, console)
    if spot is None:
        return EXIT_FAILED
    source = console.terrain_source or NceiBathymetry(Http())
    reading = source.grid(
        spot, spacing_m=args.spacing, rows=args.size, cols=args.size,
    )
    console.record(reading)
    if reading.value is None:
        console.say(f"TUBE  {label}")
        console.say(f"  source         {reading.source}:{reading.status}")
        console.say(f"  intensity      unresolved — {reading.note}")
        return EXIT_FAILED
    result = measure_intensity(reading.value, args.spacing, depth_band_m=band)
    _render_tube(label, spot, result, reading, console)
    return EXIT_OK


def _tube_target(args: argparse.Namespace, console: Console) -> tuple[Spot | None, str]:
    """A stored spot, or a bare coordinate wrapped in one. A coordinate carries
    no measured geometry, so nothing derived from it is ever written back."""
    if args.at:
        lat, lon = _floats(args.at, 2, "--at must be lat,lon")
        return (
            Spot(
                id="at", name=f"{lat:.5f}, {lon:.5f}", lat=lat, lon=lon,
                shore_normal=Derived(0.0, "default", "not measured; unused by tube"),
                beach_slope=Derived(0.0, "default", "not measured; unused by tube"),
                offshore_lat=lat, offshore_lon=lon, region="",
            ),
            f"{lat:.5f}, {lon:.5f}",
        )
    if not args.spot:
        console.warn("give --spot or --at lat,lon")
        return None, ""
    book = console.spots()
    spot = book.resolve(args.spot)
    if spot is None:
        console.warn(f"no spot matches {args.spot!r}")
        return None, ""
    return spot, spot.name


def _render_tube(
    label: str, spot: Spot, result: Intensity, reading: Reading[Any], console: Console,
) -> None:
    console.say(f"TUBE  {label}")
    console.say(f"  coordinates    {spot.lat:.5f}, {spot.lon:.5f}")
    console.say(f"  source         {reading.source}:{result.status}")
    console.say(f"  fetched_at     {reading.fetched_at.isoformat()}")
    console.say(f"  resolution     {result.resolution_m or 'unreported'} m")
    console.say(
        f"  depth band     {result.depth_band_m[0]:g}-{result.depth_band_m[1]:g} m, "
        f"{result.band_cells} cells"
    )
    console.say(f"  gradient       {result.ratio}")
    console.say(
        f"  vortex ratio   "
        f"{f'{result.vortex_ratio:.2f}' if result.vortex_ratio is not None else 'unresolved'}"
    )
    console.say(f"  intensity      {result.intensity}")
    console.say(f"  basis          {result.basis}")
    for item in reading.dropped:
        console.say(f"  dropped        {item}")
    console.say(
        "  caveat         a gradient is not a rideable wave: no line, channel, "
        "access, swell or wind is screened here"
    )


def cmd_imagery(args: argparse.Namespace, console: Console) -> int:
    """Review static geometry from cloud-free, georeferenced frame metadata."""
    bbox = _bbox(args.bbox)
    terrain_path = terrain_cache_path(args.zone, bbox)
    if not terrain_path.exists():
        console.warn(f"no terrain cache for {args.zone!r}; run `surf terrain` first")
        return EXIT_FAILED
    _, _, _, scans = load_terrain_cache(terrain_path)
    frames = load_frames(Path(args.frames))
    screen = screen_candidates(scans, frames, args.zone, console.clock())
    console.record(_receipt(screen))
    path = imagery_cache_path(args.zone, bbox)
    save_screen(path, screen)
    console.say(f"IMAGERY  {args.zone}")
    console.say(f"  source         {screen.source}:{screen.status}")
    console.say(f"  fetched_at     {screen.fetched_at.isoformat()}")
    console.say(f"  note           {screen.note}")
    for review in screen.reviews:
        console.say()
        console.say(f"  {review.candidate}  {review.decision}")
        console.say(f"    coordinates   {review.lat:.5f}, {review.lon:.5f}")
        console.say(f"    source        {review.source}")
        console.say(f"    resolution    {review.resolution_m or 'unknown'} m")
        console.say(f"    capture dates {', '.join(review.capture_dates) or 'none'}")
        console.say(f"    frames        {', '.join(review.frames) or 'none'}")
        if review.measurements_m:
            console.say("    geometry      " + ", ".join(f"{name}={value:g} m" for name, value in review.measurements_m))
        console.say(f"    status        {review.status}")
        if review.note:
            console.say(f"    note          {review.note}")
    if not screen.reviews:
        console.say("  no terrain candidates in cache")
    return EXIT_OK


def cmd_wave_state(args: argparse.Namespace, console: Console) -> int:
    """Measure dynamic wave state from clear, coincident imagery only."""
    bbox = _bbox(args.bbox)
    static_path = imagery_cache_path(args.zone, bbox)
    if not static_path.exists():
        console.warn(f"no static imagery cache for {args.zone!r}; run `surf imagery` first")
        return EXIT_FAILED
    static = load_screen(static_path)
    frames = load_frames(Path(args.frames))
    screen = screen_wave_state(static, frames, args.zone, console.clock())
    console.record(_receipt(screen))
    path = wave_state_cache_path(args.zone, bbox)
    save_wave_state(path, screen)
    console.say(f"WAVE STATE  {args.zone}")
    console.say(f"  source         {screen.source}:{screen.status}")
    console.say(f"  fetched_at     {screen.fetched_at.isoformat()}")
    console.say(f"  note           {screen.note}")
    for dropped in screen.dropped:
        console.say(f"  dropped        {dropped}")
    for review in screen.reviews:
        console.say()
        console.say(f"  {review.candidate}  {review.decision}")
        console.say(f"    coordinates   {review.lat:.5f}, {review.lon:.5f}")
        console.say(f"    source        {review.source}")
        console.say(f"    resolution    {review.resolution_m or 'unknown'} m")
        console.say(f"    capture dates {', '.join(review.capture_dates) or 'none'}")
        console.say(f"    frames        {', '.join(review.frames) or 'none'}")
        if review.wavelength_m is not None:
            console.say(f"    wavelength    {review.wavelength_m:g} m")
        if review.period_s is not None:
            console.say(f"    period        {review.period_s:.2f} s (L0 = gT^2/2pi)")
        if review.whitewash_fraction is not None:
            console.say(f"    whitewash     {review.whitewash_fraction:g}")
        if review.wave_shape:
            console.say(f"    wave shape    {review.wave_shape}")
        console.say(f"    status        {review.status}")
        console.say(f"    evidence      {review.evidence_level}")
        if review.note:
            console.say(f"    note          {review.note}")
    if not screen.reviews:
        console.say("  no static-screen survivors")
    return EXIT_OK


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
        console.record(reading)
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
    """Append a raw row or run the mechanical audit."""
    if args.action == "audit":
        return cmd_session_audit(args, console)
    if args.date is None or args.spot is None:
        console.warn("session add requires --date and --spot")
        return EXIT_USAGE
    path = Path(args.path) if args.path else default_sessions_path()
    try:
        row = append_session(
            path, date=args.date, spot=args.spot, time=args.time,
            rating=args.rating, notes=args.notes, regime=args.regime,
        )
    except SessionFileError as exc:
        console.warn(f"not written: {exc}")
        return EXIT_FAILED

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
    book = console.spots()
    sessions = load_sessions(path, book=book)
    cache = ConditionCache()
    added = sessions[-1]
    if added.rating is not None and added.rating >= 4 and added.usable_for_check:
        archive = _RecordingArchive(console.archive or OpenMeteoArchive(Http()), console)
        result = recover((added,), archive=archive, book=book, cache=cache)
        if result and result[0].field is None:
            console.warn(f"warning: REACH did not ratchet: {result[0].note}")
    updated = reach_from_log(book, sessions=sessions, cache=cache)
    console.say(f"  REACH {updated.render()}")
    return EXIT_OK


def cmd_snapshot(args: argparse.Namespace, console: Console) -> int:
    """Issue an append-only forecast snapshot or verify stored snapshots later."""
    store = SnapshotStore(args.path)
    if args.action == "verify":
        observations = load_observations(args.observations)
        sessions = load_sessions(args.sessions, book=console.spots()) if args.sessions else ()
        report = verify_snapshots(store.read(), observations, sessions)
        console.say(f"SNAPSHOT VERIFY  {len(report.rows)} rows  {len(report.scored)} scored")
        for row in report.unscored:
            console.say(f"  {row.snapshot.spot} {row.snapshot.valid_at.isoformat()}: unscored ({row.reason})")
        for group in report.groups:
            console.say(
                f"  group lead={group.lead_hours:g}h region={group.region} "
                f"period={group.period_s if group.period_s is not None else 'unknown'} "
                f"direction={group.direction_deg if group.direction_deg is not None else 'unknown'} "
                f"size={group.size_band or 'unknown'} regime={group.regime or 'unknown'} "
                f"n={group.count} mae_h={group.mae_height_m if group.mae_height_m is not None else 'unknown'}"
            )
        return EXIT_OK

    if not args.spot or not args.valid_at or not args.model_run:
        console.warn("snapshot issue requires --spot, --valid-at and --model-run")
        return EXIT_USAGE
    valid_at = parse_snapshot_time(args.valid_at)
    issued_at = parse_snapshot_time(args.issued_at) if args.issued_at else console.clock()
    spot = console.spots().resolve(args.spot)
    if spot is None:
        console.warn(f"no spot matches {args.spot!r}")
        return EXIT_FAILED
    if valid_at.minute or valid_at.second or valid_at.microsecond:
        console.warn("snapshot issue requires an hourly --valid-at matching the forecast path")
        return EXIT_USAGE
    if issued_at >= valid_at:
        console.warn("snapshot issue must write before valid_at")
        return EXIT_FAILED
    start = issued_at.replace(minute=0, second=0, microsecond=0)
    hours = int((valid_at - start).total_seconds() // 3600) + 1
    forecast = console.service().outlook(spot, Window(start=start, hours=hours))
    console.record(*forecast.readings)
    hour = forecast.at(valid_at)
    if hour is None:
        console.warn(f"forecast has no hour at {valid_at.isoformat()}")
        return EXIT_FAILED
    snapshot = snapshot_from_hour(
        forecast, hour, issued_at=issued_at, model_run=args.model_run,
        height_quantity=args.height_quantity, regime=args.regime,
    )
    snapshot_id = store.write(snapshot, now=console.clock())
    console.say(f"wrote snapshot {snapshot_id} for {snapshot.spot} at {snapshot.valid_at.isoformat()}")
    console.say(f"  lead_hours={snapshot.lead_hours:g} height_quantity={snapshot.height_quantity}")
    console.say(f"  geometry_version={snapshot.geometry_version}")
    return EXIT_OK


def _load_conditions(raw: str) -> dict[str, Any]:
    try:
        path = Path(raw)
        text = path.read_text(encoding="utf-8") if path.exists() else raw
        value = json.loads(text)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise WatchError(f"conditions are not valid JSON or a readable file: {exc}") from exc
    if not isinstance(value, dict):
        raise WatchError("conditions must be a JSON object")
    return value


def cmd_watch(args: argparse.Namespace, console: Console) -> int:
    """Save structured setup conditions or run one scheduled evaluation."""
    store = SetupStore(args.path)
    if args.action == "save":
        if not args.name or not args.spot or not args.conditions:
            console.warn("watch save requires --name, --spot and --conditions")
            return EXIT_USAGE
        try:
            setup = SavedSetup(
                name=args.name,
                spots=tuple(args.spot),
                conditions=SetupConditions.from_dict(_load_conditions(args.conditions)),
            )
            store.save(setup)
        except WatchError as exc:
            console.warn(f"watch save: {exc}")
            return EXIT_FAILED
        console.say(f"saved setup {setup.name!r} for {', '.join(setup.spots)} to {args.path}")
        return EXIT_OK

    try:
        setup = store.load()
        if not args.model_run:
            console.warn("watch run requires --model-run so scheduled snapshots keep real provenance")
            return EXIT_USAGE
        snapshots = SnapshotStore(args.snapshots or (data_dir() / "cache" / "forecast-snapshots.jsonl"))
        result = run_watch(
            setup,
            service=console.service(),
            book=console.spots(),
            now=console.clock(),
            snapshot_store=snapshots,
            model_run=args.model_run,
        )
        console.record(*result.readings)
    except (WatchError, SnapshotError) as exc:
        console.warn(f"watch run: {exc}")
        return EXIT_FAILED
    console.say(f"WATCH  {setup.name}  {len(result.alerts)} spot(s)")
    for alert in result.alerts:
        if alert.fired:
            console.say(f"  ALERT {alert.spot} at {alert.valid_at.isoformat() if alert.valid_at else 'unknown'}")
            for evidence in alert.evidence:
                console.say(f"    evidence: {evidence}")
        else:
            detail = alert.reason or "no match"
            console.say(f"  no alert {alert.spot}: {detail}")
            for item in alert.dropped:
                console.say(f"    dropped: {item}")
    for item in result.dropped:
        console.say(f"  dropped: {item}")
    console.say(f"  snapshots written: {result.snapshots_written}")
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
    call.add_argument("--want", default="", help="session-language physical filter, e.g. grovel")
    call.set_defaults(run=cmd_call)

    spot = sub.add_parser("spot", help="one spot in depth: geometry, provenance, what is missing")
    spot.add_argument("name", help="spot id, name or alias")
    spot.add_argument("--days", type=int, default=3, help="days to fetch")
    spot.set_defaults(run=cmd_spot)

    climate = sub.add_parser(
        "climate", help="measure shared historical swell/wind overlap for a zone"
    )
    climate.add_argument("--zone", required=True, help="exact zone identity from data/spots.tsv")
    climate.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    climate.add_argument("--end", required=True, help="last date, YYYY-MM-DD")
    climate.add_argument("--refresh", action="store_true", help="rebuild the derived climate cache")
    climate.set_defaults(run=cmd_climate)

    lexicon = sub.add_parser("lexicon", help="map session language to physical filters")
    lexicon.add_argument("phrase", nargs="?", default="", help="term or natural phrase; omit for all")
    lexicon.set_defaults(run=cmd_lexicon)

    terrain = sub.add_parser(
        "terrain", help="scan zone bathymetry for stable terrain-object candidates"
    )
    terrain.add_argument("--zone", required=True, help="zone label for the derived scan")
    terrain.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon to scan")
    terrain.add_argument("--step", type=float, default=0.05, help="scan-cell spacing in degrees")
    terrain.add_argument("--refresh", action="store_true", help="rebuild the derived terrain cache")
    terrain.set_defaults(run=cmd_terrain)

    tube = sub.add_parser(
        "tube", help="breaker intensity from the sea floor at one break"
    )
    tube.add_argument("--spot", default="", help="spot id or name from data/spots.tsv")
    tube.add_argument("--at", default="", help="lat,lon to screen instead of a stored spot")
    tube.add_argument(
        "--spacing", type=float, default=40.0, help="grid spacing in metres"
    )
    tube.add_argument(
        "--size", type=int, default=10, help="grid side in cells (max 10 at NCEI)"
    )
    tube.add_argument(
        "--band", default=f"{BREAKING_BAND_M[0]:g},{BREAKING_BAND_M[1]:g}",
        help="breaking depth band in metres, shallow,deep",
    )
    tube.set_defaults(run=cmd_tube)

    imagery = sub.add_parser(
        "imagery", help="screen terrain candidates with static-geometry imagery metadata"
    )
    imagery.add_argument("--zone", required=True, help="zone label used by the terrain scan")
    imagery.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon")
    imagery.add_argument(
        "--frames", required=True,
        help="JSON manifest of cloud-free, georeferenced imagery frames and metre measurements",
    )
    imagery.set_defaults(run=cmd_imagery)

    wave_state = sub.add_parser(
        "wave-state", help="measure dynamic wave state from coincident imagery"
    )
    wave_state.add_argument("--zone", required=True, help="zone label used by the imagery screen")
    wave_state.add_argument("--bbox", required=True, help="min_lat,min_lon,max_lat,max_lon")
    wave_state.add_argument(
        "--frames", required=True,
        help="JSON manifest with clear-pass, swell, scale and wavelength metadata",
    )
    wave_state.set_defaults(run=cmd_wave_state)

    calibrate_cmd = sub.add_parser("calibrate", help="check the model against the session log")
    calibrate_cmd.add_argument(
        "--online", action="store_true", help="reach the archive to fill the condition cache"
    )
    calibrate_cmd.add_argument("--refresh", action="store_true", help="ignore cached conditions")
    calibrate_cmd.add_argument(
        "--no-matrix", action="store_true", help="score without the response matrix"
    )
    calibrate_cmd.add_argument("--path", default=None, help="session file to calibrate")
    calibrate_cmd.set_defaults(run=cmd_calibrate)

    geometry = sub.add_parser("geometry", help="derive per-spot geometry from the sea floor")
    geometry.add_argument("--spot", default="", help="one spot id or name; default is all")
    geometry.add_argument("--write", action="store_true", help="store the derived values")
    geometry.add_argument("--refresh", action="store_true", help="ignore the geometry cache")
    geometry.set_defaults(run=cmd_geometry)

    session = sub.add_parser("session", help="append or audit the session log")
    session.add_argument("action", choices=("add", "audit"))
    session.add_argument("--date", default=None, help="YYYY-MM-DD, YYYY-MM-DD? or ????-MM-DD (add)")
    session.add_argument("--spot", default=None, help="how you name the spot; resolved by alias (add)")
    session.add_argument("--time", default="", help="HH:MM, a word like 'early', or empty")
    session.add_argument("--rating", default="", help="1-5, your own call. Empty means unrated")
    session.add_argument("--notes", default="", help="what it was actually like")
    session.add_argument("--regime", default="", help="explicit swell/wind regime, if known")
    session.add_argument("--path", default=None, help="session file to append to")
    session.add_argument("--online", action="store_true", help="reach the archive for date recovery (audit)")
    session.add_argument("--years", default=None, help="candidate years, comma-separated (audit)")
    session.add_argument("--dry-run", action="store_true", help="report repairs without writing (audit)")
    session.set_defaults(run=cmd_session)

    snapshot = sub.add_parser(
        "snapshot", help="freeze a forecast before validity and verify it against later outcomes"
    )
    snapshot.add_argument("action", choices=("issue", "verify"))
    snapshot.add_argument("--path", required=True, help="append-only snapshot JSONL path")
    snapshot.add_argument("--spot", default=None, help="spot id or name (issue)")
    snapshot.add_argument("--valid-at", default=None, help="forecast validity time in ISO form (issue)")
    snapshot.add_argument("--issued-at", default=None, help="issue time in ISO form; defaults to the clock (issue)")
    snapshot.add_argument("--model-run", default=None, help="source model run identifier (issue)")
    snapshot.add_argument(
        "--height-quantity", choices=("offshore_hs", "nearshore_hs", "face_height"),
        default="offshore_hs", help="height quantity recorded by the snapshot (issue)",
    )
    snapshot.add_argument("--regime", default="", help="explicit regime, if known (issue)")
    snapshot.add_argument("--observations", default=None, help="later buoy observations JSONL (verify)")
    snapshot.add_argument("--sessions", default=None, help="session log to join (verify)")
    snapshot.set_defaults(run=cmd_snapshot)

    watch = sub.add_parser("watch", help="save setup conditions and run a scheduled alert check")
    watch.add_argument("action", choices=("save", "run"))
    watch.add_argument("--path", required=True, help="saved setup JSON path")
    watch.add_argument("--name", default=None, help="setup name (save)")
    watch.add_argument("--spot", action="append", default=[], help="spot id or name; repeatable (save)")
    watch.add_argument("--conditions", default=None, help="conditions JSON object or file (save)")
    watch.add_argument("--snapshots", default=None, help="append-only snapshot JSONL path (run)")
    watch.add_argument("--model-run", default=None, help="explicit model run identifier for snapshots (run)")
    watch.set_defaults(run=cmd_watch)

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
