"""The spot database and the session log, read from the shipped data files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from surf.spots import Spot
from surf import sessions as sess
from surf import spots as spotstore
from surf.spots import SpotBook, SpotFileError

SPOTS_PATH = spotstore.default_spots_path()
SESSIONS_PATH = sess.default_sessions_path()


@pytest.fixture(scope="module")
def book() -> SpotBook:
    return SpotBook.load(SPOTS_PATH)


@pytest.fixture(scope="module")
def log(book: SpotBook):
    return sess.load_sessions(SESSIONS_PATH, book=book)


# --- the spot file --------------------------------------------------------

def test_seed_covers_every_cluster_the_ticket_names(book: SpotBook) -> None:
    required = {
        # David's log spots
        "lido-beach", "spring-lake", "bay-head", "belmar", "manasquan",
        "point-judith", "camp-cronin", "little-compton", "camp-hero",
        # Newburyport cluster
        "plum-island", "salisbury", "hampton-nh", "rye-nh",
        # Martha's Vineyard
        "aquinnah", "squibnocket", "stonewall",
        # international, so calibration can reach the 5/5 sessions
        "llandudno", "sandy-bay", "kommetjie", "carcavelos", "beliche",
        "meio-noronha", "playa-langosta",
    }
    assert required <= {s.id for s in book}
    assert len(book) >= 19


def test_no_cape_cod(book: SpotBook) -> None:
    """No ground truth there, so no rows."""
    banned = ("cape cod", "nauset", "marconi", "wellfleet", "truro", "ballston")
    for spot in book:
        haystack = " ".join((spot.id, spot.name, *spot.aliases)).lower()
        assert not any(b in haystack for b in banned), spot.id


def test_every_geometric_value_carries_provenance(book: SpotBook) -> None:
    """A number without its provenance is a guess wearing a measurement's clothes."""
    for spot in book:
        for field in (spot.shore_normal, spot.beach_slope):
            assert field.provenance in ("derived", "manual", "default"), spot.id
            if field.provenance != "derived":
                assert field.note, f"{spot.id}: undated guess with no note"


def test_geometry_is_in_range_and_offshore_is_seaward(book: SpotBook) -> None:
    for spot in book:
        assert -90 <= spot.lat <= 90 and -180 <= spot.lon <= 180, spot.id
        assert 0 <= spot.shore_normal.value < 360, spot.id
        assert 0 < spot.beach_slope.value < 1, spot.id
        # the sample point is fixed and stored, and it must sit off the
        # beach in the direction the beach faces, not on top of it.
        assert (spot.offshore_lat, spot.offshore_lon) != (spot.lat, spot.lon), spot.id
        d_north = spot.offshore_lat - spot.lat
        d_east = spot.offshore_lon - spot.lon
        import math

        bearing = (math.degrees(math.atan2(d_east * math.cos(math.radians(spot.lat)), d_north)) + 360) % 360
        offset = abs((bearing - spot.shore_normal.value + 180) % 360 - 180)
        assert offset < 2.0, f"{spot.id}: offshore point is {offset:.1f}deg off the shore normal"


def test_offshore_wind_bearing_is_the_reciprocal(book: SpotBook) -> None:
    lido = book.get("lido-beach")
    assert lido is not None
    assert lido.offshore_wind_bearing == (lido.shore_normal.value + 180) % 360


def test_model_only_spots_are_visible_as_such(book: SpotBook) -> None:
    """No free buoy data outside US/Europe, and the flag has to be readable
    from the row so the call can say so."""
    for spot in book:
        if not spot.region.startswith("US"):
            assert not spot.has_observations, f"{spot.id} claims a buoy"
    assert book.get("llandudno").has_observations is False
    assert book.get("lido-beach").has_observations is True


def test_non_us_spots_have_no_hardcoded_coops_station(book: SpotBook) -> None:
    """CO-OPS tide stations are US-only."""
    for spot in book:
        if not spot.region.startswith("US"):
            assert spot.tide_station is None, spot.id


def test_every_spot_has_an_access_note_and_none_of_them_filter(book: SpotBook) -> None:
    for spot in book:
        assert spot.access.strip(), spot.id


def test_spot_file_round_trips_byte_for_byte(tmp_path: Path, book: SpotBook) -> None:
    out = tmp_path / "spots.tsv"
    spotstore.save_spots(book.spots, out)
    assert out.read_text(encoding="utf-8") == SPOTS_PATH.read_text(encoding="utf-8")
    assert spotstore.load_spots(out) == book.spots


def test_load_rejects_a_bad_provenance(tmp_path: Path, book: SpotBook) -> None:
    out = tmp_path / "spots.tsv"
    spotstore.save_spots(book.spots, out)
    out.write_text(out.read_text().replace("\tmanual\t", "\tvibes\t", 1))
    with pytest.raises(SpotFileError, match="provenance"):
        spotstore.load_spots(out)


def test_load_rejects_a_duplicate_id(tmp_path: Path, book: SpotBook) -> None:
    out = tmp_path / "spots.tsv"
    spotstore.save_spots(book.spots + (book.spots[0],), out)
    with pytest.raises(SpotFileError, match="duplicate"):
        spotstore.load_spots(out)


def test_in_region_prefix_selects_state_then_country(book: SpotBook) -> None:
    assert {s.id for s in book.in_region("US-RI")} == {"point-judith", "camp-cronin", "little-compton"}
    assert len(book.in_region("US")) > len(book.in_region("US-RI"))
    assert book.in_region("ZA") and not book.in_region("AU")


# --- name resolution ------------------------------------------------------

@pytest.mark.parametrize(
    "written,expected",
    [
        ("Lido Beach NY", "lido-beach"),
        ("Lido Beach Town Park NY", "lido-beach"),
        ("Lido Beach NY?", "lido-beach"),          # David's doubt must not block the match
        ("Belmar NJ?", "belmar"),
        ("Camp Cronin, Point Judith RI", "camp-cronin"),
        ("Point Judith RI", "point-judith"),
        ("South Shore Beach, Little Compton RI", "little-compton"),
        ("Little Compton RI", "little-compton"),
        ("Camp Hero, Montauk NY", "camp-hero"),
        ("Stonewall Beach / Aquinnah, Martha's Vineyard MA", "stonewall"),
        ("Llandudno, Cape Town ZA", "llandudno"),
        ("Meio, Fernando de Noronha BR", "meio-noronha"),
        ("  llandudno  ", "llandudno"),
        ("lido-beach", "lido-beach"),
    ],
)
def test_resolve(book: SpotBook, written: str, expected: str) -> None:
    spot = book.resolve(written)
    assert spot is not None and spot.id == expected


def test_resolve_returns_none_rather_than_a_near_miss(book: SpotBook) -> None:
    """No answer beats a confident wrong one."""
    assert book.resolve("unknown") is None
    assert book.resolve("Seal Rocks NSW") is None
    assert book.resolve("") is None


# --- the session log ------------------------------------------------------

def test_the_whole_log_is_accounted_for(log) -> None:
    """Every row either resolves to a spot id or is reported as unresolved."""
    resolved = [s for s in log if s.spot_id]
    reported = sess.unresolved(log)
    assert len(resolved) + len(reported) == len(log)
    assert len(resolved) >= 38
    assert {s.raw_spot for s in reported} == {"unknown"}
    report = sess.resolution_report(log)
    assert f"resolved: {len(resolved)}" in report
    for session in reported:
        assert session.raw_date in report


def test_uncertainty_is_kept_not_guessed(log) -> None:
    by_raw = {(s.raw_date, s.raw_spot): s for s in log}

    hard = by_raw[("2025-09-30", "Spring Lake NJ")]
    assert hard.on == date(2025, 9, 30) and hard.date_uncertain is False
    assert hard.hour == 8 and hard.time_uncertain is True   # "08:00?"

    flagged = by_raw[("2025-08-05?", "Bay Head NJ")]
    assert flagged.on == date(2025, 8, 5) and flagged.date_uncertain is True

    yearless = by_raw[("????-03-03", "Lido Beach NY?")]
    assert yearless.on is None and yearless.date_uncertain is True
    assert yearless.spot_id == "lido-beach"                  # spot still resolves
    assert yearless.usable_for_check is False


def test_vague_times_do_not_become_invented_hours(log) -> None:
    by_raw = {(s.raw_date, s.raw_spot): s for s in log}
    early = by_raw[("2022-07-29", "South Shore Beach, Little Compton RI")]
    assert early.raw_time == "early"
    assert early.hour is None and early.time_uncertain is True

    dashed = by_raw[("2022-09-10", "Point Judith RI")]
    assert dashed.hour is None and dashed.time_uncertain is True

    exact = by_raw[("2024-04-04", "Belmar NJ")]
    assert exact.hour == 6 and exact.time_uncertain is False


def test_the_anchors_calibration_names_survive_the_load(log) -> None:
    """The three anchors stay findable: the ideal, the lower bound, the failure."""
    ideal = [s for s in log if s.spot_id == "llandudno" and s.on == date(2025, 3, 12)]
    assert ideal and ideal[0].rating == 5

    lower_bound = [s for s in log if s.spot_id == "stonewall"]
    assert lower_bound and "LOWER BOUND" in lower_bound[0].notes

    failure = [s for s in log if s.spot_id == "spring-lake" and s.on == date(2024, 12, 12)]
    assert failure and failure[0].rating == 1


def test_ratings_are_davids_scale_and_stay_tagged(log) -> None:
    assert all(s.source == "david" for s in log)
    assert all(s.rating is None or 1 <= s.rating <= 5 for s in log)
    fives = [s for s in log if s.rating == 5]
    ones = [s for s in log if s.rating == 1]
    assert len(fives) >= 6 and len(ones) >= 2   # calibration needs both ends


def test_public_anchors_load_under_their_own_tag(tmp_path: Path, book: SpotBook) -> None:
    """Documented public swells may be added, never merged into David's scale."""
    path = tmp_path / "public.tsv"
    path.write_text(
        "date\tspot\ttime\trating\tnotes\n"
        "2018-03-02\tLido Beach NY\t09:00\t5\tnor'easter\n",
        encoding="utf-8",
    )
    anchors = sess.load_sessions(path, book=book, source="public")
    assert [a.source for a in anchors] == ["public"]


def test_usable_subset_is_the_calibration_set(log) -> None:
    for session in sess.usable(log):
        assert session.on is not None and session.spot_id and session.rating is not None
    assert len(sess.usable(log)) >= 25
    assert len(sess.undated(log)) == len([s for s in log if s.on is None])


def test_session_file_round_trips(tmp_path: Path, book: SpotBook, log) -> None:
    out = tmp_path / "sessions.tsv"
    sess.save_sessions(log, out)
    reloaded = sess.load_sessions(out, book=book)
    assert [sess.format_row(s) for s in reloaded] == [sess.format_row(s) for s in log]
    assert reloaded == log

    original_rows = [
        line.split("\t")[:5]
        for line in SESSIONS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ][1:]
    assert [sess.format_row(s) for s in log] == original_rows


def test_bad_rating_is_loud(tmp_path: Path, book: SpotBook) -> None:
    path = tmp_path / "sessions.tsv"
    path.write_text(
        "date\tspot\ttime\trating\tnotes\n2024-01-01\tLido Beach NY\t09:00\t9\ttoo good\n",
        encoding="utf-8",
    )
    with pytest.raises(sess.SessionFileError, match="outside 1-5"):
        sess.load_sessions(path, book=book)


def test_load_sessions_defaults_to_the_shipped_files() -> None:
    """The zero-argument path is what the CLI and calibration will call."""
    assert len(sess.load_sessions()) == len(sess.load_sessions(SESSIONS_PATH))
    assert isinstance(spotstore.load_spots()[0], Spot)
