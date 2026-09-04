"""The CLI, run offline against fake sources handed in through `Console`."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from surf import cli
from surf.spots import Derived, Spot
from surf.waves import Forecast, SwellPartition, TidePoint, WaveField, Wind
from surf.sources import Reading, Window
from surf.forecast import Sources
from surf.spots import SpotBook

UTC = timezone.utc
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

POINT_JUDITH = Spot(
    id="point-judith",
    name="Point Judith",
    lat=41.3612,
    lon=-71.4812,
    shore_normal=Derived(160.0, "manual", "faces south-southeast"),
    beach_slope=Derived(0.035, "derived"),
    offshore_lat=41.32,
    offshore_lon=-71.48,
    region="US-RI",
    break_type="reef",
    buoys=("44097",),
    tide_station="8452660",
    access="car only, ~1h45 from Boston; rental ~$150",
    aliases=("point jude",),
)

# No buoy in range of this one, so it is model-only.
LLANDUDNO = Spot(
    id="llandudno",
    name="Llandudno",
    lat=-34.008,
    lon=18.341,
    shore_normal=Derived(250.0, "manual"),
    beach_slope=Derived(0.05, "default"),
    offshore_lat=-34.02,
    offshore_lon=18.32,
    region="ZA-WC",
    access="flight to Cape Town + car",
)

BOOK = SpotBook((POINT_JUDITH, LLANDUDNO))


def clock() -> datetime:
    return NOW


def wave(at: datetime, model: str, height: float, period: float = 13.0) -> WaveField:
    return WaveField(
        time=at,
        partitions=(SwellPartition(height, period, 165.0, "swell"),),
        wind=Wind(3.0, 340.0),
        total_height_m=height,
        total_period_s=period,
        model=model,
    )


class FakeModel:
    """Answers with a per-spot height, so one spot wins the call."""

    def __init__(self, name: str, heights: dict[str, float], hours: int = 36):
        self.name = name
        self._heights = heights
        self._hours = hours

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", NOW)

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        start = window.start
        fields = tuple(
            wave(start + timedelta(hours=i), self.name, self._heights.get(spot.id, 0.6))
            for i in range(min(self._hours, window.hours))
        )
        return Reading(Forecast(spot.id, self.name, fields), self.name, "ok", NOW)


class FakeBuoy:
    name = "ndbc"

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", NOW)

    def latest(self, buoy_id: str) -> Reading[WaveField]:
        return Reading(
            wave(NOW, f"ndbc/{buoy_id}", 1.5), f"ndbc/{buoy_id}", "ok", NOW
        )


class FakeTides:
    name = "tides"

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", NOW)

    def curve(self, spot: Spot, day) -> Reading[tuple[TidePoint, ...]]:
        base = datetime(day.year, day.month, day.day, tzinfo=UTC)
        points = tuple(
            TidePoint(base + timedelta(hours=h), 0.5, "rising") for h in range(0, 24)
        )
        return Reading(points, self.name, "ok", NOW, note="datum=MLLW predicted")


class Dead:
    """Raises on everything, preflight included."""

    def __init__(self, name: str):
        self.name = name

    def preflight(self) -> Reading[bool]:
        raise RuntimeError("network unreachable")

    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]:
        raise RuntimeError("network unreachable")

    def latest(self, buoy_id: str) -> Reading[WaveField]:
        raise RuntimeError("network unreachable")

    def curve(self, spot: Spot, day) -> Reading[tuple[TidePoint, ...]]:
        raise RuntimeError("network unreachable")


def live_sources() -> Sources:
    return Sources(
        forecast=(
            FakeModel("gwam", {"point-judith": 1.6, "llandudno": 0.7}),
            FakeModel("ncep_gfswave025", {"point-judith": 1.5, "llandudno": 0.7}),
        ),
        observations=FakeBuoy(),
        tides=FakeTides(),
    )


def run(*argv: str, sources: Sources | None = None, book: SpotBook | None = BOOK):
    """Run one command and hand back (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    console = cli.Console(
        out=out, err=err, sources=sources, book=book, clock=clock
    )
    code = cli.main(list(argv), console=console)
    return code, out.getvalue(), err.getvalue()


# --- surf sources ----------------------------------------------------------

def test_sources_prints_one_labelled_line_per_source():
    code, out, _ = run("sources", sources=live_sources())
    assert code == cli.EXIT_OK
    for name in ("gwam", "ncep_gfswave025", "ndbc", "tides"):
        assert name in out
    assert "4/4 sources live" in out


def test_sources_offline_is_readable_and_exits_non_zero():
    """Nothing reachable is a real failure, and has to look like one to a script."""
    dead = Sources(forecast=(Dead("gwam"),), observations=Dead("ndbc"), tides=Dead("tides"))
    code, out, err = run("sources", sources=dead)
    assert code == cli.EXIT_FAILED
    assert "failed" in out
    assert "RuntimeError: network unreachable" in out
    assert "every source is down" in err
    assert "Traceback" not in out + err


def test_sources_degrades_rather_than_dies_when_one_source_is_down():
    mixed = Sources(forecast=(FakeModel("gwam", {}), Dead("ncep_gfswave025")), tides=FakeTides())
    code, out, _ = run("sources", sources=mixed)
    assert code == cli.EXIT_OK
    assert "2/3 sources live" in out


# --- surf call -------------------------------------------------------------

def test_call_commits_to_a_spot_a_window_signals_and_falsifiers():
    code, out, _ = run("call", "--days", "2", sources=live_sources())
    assert code == cli.EXIT_OK
    assert "CALL  POINT JUDITH" in out       # the bigger spot wins
    assert "UTC" in out
    assert "why" in out and "wrong if" in out
    # four axes, printed apart, never fused.
    for axis in ("BARREL", "SIZE", "CLEANNESS", "CONFIDENCE"):
        assert axis in out
    assert "rating" not in out.lower()


def test_call_carries_access_as_a_cost_not_a_filter():
    code, out, _ = run("call", "--days", "2", sources=live_sources())
    assert code == cli.EXIT_OK
    assert "rental ~$150" in out
    assert "a cost, not a filter" in out


def test_call_never_prints_a_ranked_grid():
    """Alternatives are capped at two; a third is a ranking in disguise."""
    _, out, _ = run("call", "--days", "2", sources=live_sources())
    listed = 0
    if "also in play" in out:
        for line in out.split("also in play")[1].splitlines()[1:]:
            if not line.strip():
                break
            listed += 1
    assert listed <= 2


def test_call_flags_a_model_only_spot():
    """Llandudno has no buoy in range, and the call has to say so."""
    code, out, _ = run("call", "--spot", "Llandudno", "--days", "2", sources=live_sources())
    assert code == cli.EXIT_OK
    assert "model-only" in out
    assert "no buoy in range of Llandudno" in out


def test_call_offline_exits_non_zero_and_says_why():
    dead = Sources(forecast=(Dead("gwam"),), tides=Dead("tides"))
    code, out, err = run("call", "--days", "2", sources=dead)
    assert code == cli.EXIT_FAILED
    assert "no call:" in err
    assert "Traceback" not in out + err


def test_call_reports_a_name_that_resolved_to_nothing():
    """A typo that shrinks the search is announced, not absorbed."""
    code, _, err = run("call", "--spot", "Trestles", "--days", "2", sources=live_sources())
    assert code == cli.EXIT_FAILED
    assert "no spot matches 'Trestles'" in err


def test_call_prints_human_units_beside_the_si_ones():
    """Human units at the edge only — and never instead of the metres."""
    _, out, _ = run("spot", "point-judith", "--days", "1", sources=live_sources())
    assert " m (" in out and "ft)" in out


# --- surf spot -------------------------------------------------------------

def test_spot_prints_geometry_with_provenance():
    code, out, _ = run("spot", "point jude", "--days", "1", sources=live_sources())
    assert code == cli.EXIT_OK
    assert "160 deg (manual)" in out
    assert "0.035 (derived)" in out
    assert "44097" in out
    assert "(fixed)" in out


def test_spot_says_what_is_missing_rather_than_filling_it_in():
    code, out, _ = run("spot", "llandudno", "--days", "1", sources=live_sources())
    assert code == cli.EXIT_OK
    assert "none — model-only" in out
    assert "0.050 (default)" in out          # a default slope is a warning, not a value
    assert "Open-Meteo sea level" in out


def test_spot_unknown_name_exits_non_zero_and_lists_the_ids():
    code, _, err = run("spot", "Pipeline", sources=live_sources())
    assert code == cli.EXIT_FAILED
    assert "no spot matches 'Pipeline'" in err
    assert "point-judith" in err


def test_spot_shows_every_source_label():
    _, out, _ = run("spot", "point-judith", "--days", "1", sources=live_sources())
    assert "sources" in out
    assert "gwam:ok" in out
    assert "ndbc/44097:ok" in out


# --- surf calibrate --------------------------------------------------------

def test_calibrate_runs_offline_from_the_cache(tmp_path, monkeypatch):
    """With an empty cache the ranking check is SKIP, printed rather than
    counted as agreement."""
    monkeypatch.setenv("SURF_CACHE_DIR", str(tmp_path))
    code, out, err = run("calibrate", sources=Sources(), book=None)
    assert "[SKIP]" in out
    assert "offline" in out
    assert "Traceback" not in out + err
    assert code in (cli.EXIT_OK, cli.EXIT_FAILED)


def test_calibrate_exit_code_follows_the_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("SURF_CACHE_DIR", str(tmp_path))
    out_buf, err_buf = io.StringIO(), io.StringIO()
    console = cli.Console(out=out_buf, err=err_buf, sources=Sources(), clock=clock)
    code = cli.main(["calibrate"], console=console)
    failed = "[FAIL]" in out_buf.getvalue()
    assert code == (cli.EXIT_FAILED if failed else cli.EXIT_OK)


# --- surf session add ------------------------------------------------------

def _log(tmp_path: Path) -> Path:
    path = tmp_path / "sessions.tsv"
    path.write_text(
        "# Ground-truth surf log — David.\ndate\tspot\ttime\trating\tnotes\n"
        "2025-09-30\tSpring Lake NJ\t08:00?\t2\twalled out\n",
        encoding="utf-8",
    )
    return path


def test_session_add_appends_and_keeps_the_comment_header(tmp_path):
    path = _log(tmp_path)
    code, out, _ = run(
        "session", "add", "--date", "2026-09-11", "--spot", "Point Judith",
        "--time", "07:00", "--rating", "4", "--notes", "chest high, offshore",
        "--path", str(path), sources=Sources(),
    )
    assert code == cli.EXIT_OK
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#")                      # the format doc survives
    assert lines[-1] == "2026-09-11\tPoint Judith\t07:00\t4\tchest high, offshore"
    assert "resolves to point-judith" in out


def test_session_add_keeps_uncertainty_instead_of_resolving_it(tmp_path):
    """`????-03-03` is a real row: month and day known, year not. The CLI has to
    be able to write what the loader can read."""
    path = _log(tmp_path)
    code, _, _ = run(
        "session", "add", "--date", "????-03-03", "--spot", "Point Judith",
        "--time", "early", "--path", str(path), sources=Sources(),
    )
    assert code == cli.EXIT_OK
    assert path.read_text(encoding="utf-8").splitlines()[-1].startswith("????-03-03\t")


def test_session_add_rejects_a_date_it_cannot_parse(tmp_path):
    path = _log(tmp_path)
    before = path.read_text(encoding="utf-8")
    code, _, err = run(
        "session", "add", "--date", "sept 3", "--spot", "Point Judith",
        "--path", str(path), sources=Sources(),
    )
    assert code == cli.EXIT_FAILED
    assert "not written" in err
    assert path.read_text(encoding="utf-8") == before


def test_session_add_rejects_a_rating_outside_the_scale(tmp_path):
    path = _log(tmp_path)
    code, _, err = run(
        "session", "add", "--date", "2026-09-11", "--spot", "Point Judith",
        "--rating", "9", "--path", str(path), sources=Sources(),
    )
    assert code == cli.EXIT_FAILED
    assert "not written" in err


def test_session_add_warns_but_keeps_an_unresolved_spot(tmp_path):
    """Nothing is dropped quietly — an unresolvable name is still ground truth."""
    path = _log(tmp_path)
    code, _, err = run(
        "session", "add", "--date", "2026-09-11", "--spot", "Somewhere New",
        "--path", str(path), sources=Sources(),
    )
    assert code == cli.EXIT_OK
    assert "does not resolve" in err
    assert path.read_text(encoding="utf-8").splitlines()[-1].startswith("2026-09-11\tSomewhere New")


def test_outlook_from_regroups_merged_hours_into_one_forecast_per_model():
    """The forecast service merges models per hour; the call service wants one
    forecast per model. This transpose is the only place that knows both."""
    from surf.forecast import ForecastService

    service = ForecastService(live_sources(), clock=clock)
    window = Window(start=NOW, hours=6)
    outlook = cli.outlook_from(service.outlook(POINT_JUDITH, window))

    assert {f.model for f in outlook.forecasts} == {"gwam", "ncep_gfswave025"}
    assert all(len(f.hours) == 6 for f in outlook.forecasts)
    assert outlook.observed is not None          # the buoy answered, so not model-only
    assert outlook.model_only is False
    assert outlook.tide


def test_outlook_from_marks_a_spot_with_no_buoy_model_only():
    from surf.forecast import ForecastService

    service = ForecastService(live_sources(), clock=clock)
    outlook = cli.outlook_from(service.outlook(LLANDUDNO, Window(start=NOW, hours=6)))
    assert outlook.model_only is True


def test_unknown_command_is_a_usage_error_not_a_failure():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["surfline-please"])
    assert exit_info.value.code == cli.EXIT_USAGE


def test_an_unexpected_exception_becomes_one_line_and_exit_one():
    """A traceback is not an answer. `--debug` is how a developer gets it back."""

    out, err = io.StringIO(), io.StringIO()

    def boom() -> SpotBook:
        raise ValueError("spot file is corrupt")

    console = cli.Console(out=out, err=err, sources=Sources(), clock=clock)
    console.spots = boom  # type: ignore[method-assign]
    code = cli.main(["spot", "anything"], console=console)
    assert code == cli.EXIT_FAILED
    assert "ValueError: spot file is corrupt" in err.getvalue()


def test_surfline_stays_optional():
    """The benchmark is opt-in and import-guarded; absent is normal."""
    from surf.sources import Http

    assert cli._benchmark(Http(), False) is None


def test_every_subcommand_is_wired():
    parser = cli.build_parser()
    actions = [a for a in parser._actions if getattr(a, "choices", None) and hasattr(a.choices, "keys")]
    assert set(actions[0].choices) == {
        "sources", "call", "spot", "calibrate", "session", "geometry", "exposure",
    }


def test_call_prints_the_heads_up_only_when_it_looked_that_far():
    """A three-day scan has no days 6-10 to report, so it must not claim
    there is nothing there."""
    _, short, _ = run("call", "--days", "3", sources=live_sources())
    assert "beyond the sharp horizon" not in short

    _, long_scan, _ = run("call", "--days", "7", sources=live_sources())
    assert "beyond the sharp horizon" in long_scan


def test_call_prints_a_repeated_caveat_once():
    """A source that fell over at every spot is one problem, not three."""
    mixed = Sources(
        forecast=(FakeModel("gwam", {"point-judith": 1.6}), Dead("ncep_gfswave025")),
        tides=FakeTides(),
    )
    _, out, _ = run("call", "--days", "2", sources=mixed)
    caveats = out.split("caveats")[1].splitlines()
    repeated = [c for c in caveats if "ncep_gfswave025" in c]
    assert len(repeated) == 1
