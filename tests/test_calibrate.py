"""Calibration, run offline: a fake archive warms the cache, then the checks read
the cache. The session log (data/sessions.tsv, data/spots.tsv) is the fixture.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from surf.sessions import Session
from surf.waves import SwellPartition, WaveField, Wind
from surf.sources import Reading
from surf.calibrate import (
    LIDO_SPOT_ID,
    CalibrationReport,
    ConditionCache,
    calibrate,
    current_check,
    lido_current_check,
    longshore,
    nearest,
    ranking_check,
    recover,
    score_sessions,
)
from surf.sessions import load_sessions
from surf.spots import SpotBook

BOOK = SpotBook.load()
LOG = load_sessions(book=BOOK)


def field(
    height: float,
    period: float,
    direction: float,
    *,
    wind: Wind | None = None,
    model: str = "era5-test",
) -> WaveField:
    return WaveField(
        time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        partitions=(SwellPartition(height, period, direction, "swell"),),
        wind=wind,
        total_height_m=height,
        total_period_s=period,
        model=model,
    )


class FakeArchive:
    """One canned hour per spot, plus a call counter so the cache can be proved
    to have taken over on the second run."""

    name = "fake-archive"

    def __init__(self, by_spot: dict[str, WaveField]):
        self.by_spot = by_spot
        self.calls = 0

    def preflight(self) -> Reading[bool]:
        return Reading(True, self.name, "ok", datetime.now(timezone.utc))

    def conditions(self, spot, on: date, hour: int) -> Reading[WaveField]:
        self.calls += 1
        found = self.by_spot.get(spot.id)
        stamp = datetime.now(timezone.utc)
        if found is None:
            return Reading(None, self.name, "failed", stamp, note="no fixture for this spot")
        moment = datetime(on.year, on.month, on.day, hour, tzinfo=timezone.utc)
        return Reading(
            WaveField(
                time=moment,
                partitions=found.partitions,
                wind=found.wind,
                total_height_m=found.total_height_m,
                total_period_s=found.total_period_s,
                model=found.model,
            ),
            self.name, "ok", stamp, note="fixture",
        )


#: Three real rows from the log with conditions that plausibly produced their
#: ratings: two 5/5s (clean, long-period, offshore wind) and the 1/5 the log calls
#: slabby, walled and closed out (short period, onshore gale).
FIXTURE = {
    "belmar": field(1.5, 11.0, 100.0, wind=Wind(4.0, 280.0)),          # 2024-04-04, 5/5
    "lido-beach": field(1.4, 10.0, 150.0, wind=Wind(3.0, 350.0)),      # 2024-03-24, 5/5
    "spring-lake": field(1.8, 6.0, 60.0, wind=Wind(12.0, 60.0)),       # 2024-12-12, 1/5
}


def sample_sessions() -> tuple[Session, ...]:
    """The rows FIXTURE covers, straight out of the log."""
    wanted = {
        ("belmar", date(2024, 4, 4)),        # 5/5 "spitting tubes"
        ("lido-beach", date(2024, 3, 24)),
        ("spring-lake", date(2024, 12, 12)),
    }
    return tuple(s for s in LOG if (s.spot_id, s.on) in wanted)


def warm_cache(tmp_path) -> tuple[ConditionCache, FakeArchive, tuple]:
    cache = ConditionCache(tmp_path / "calibration")
    archive = FakeArchive(FIXTURE)
    sessions = sample_sessions()
    recover(sessions, archive, book=BOOK, cache=cache)
    return cache, archive, sessions


def test_lido_swell_from_the_southeast_sets_the_current_west():
    """Lido faces 170 and its current normally pulls west; a SE swell arrives
    anticlockwise of that normal."""
    lido = BOOK.get(LIDO_SPOT_ID)
    current = longshore(lido, 140.0)
    assert current.compass == "west"
    assert current.incidence_deg < 0
    assert current.strength > 0


def test_lido_swell_from_the_southwest_sets_the_current_east():
    lido = BOOK.get(LIDO_SPOT_ID)
    current = longshore(lido, 200.0)
    assert current.compass == "east"
    assert current.incidence_deg > 0


def test_longshore_peaks_at_forty_five_degrees_and_vanishes_head_on():
    lido = BOOK.get(LIDO_SPOT_ID)
    assert longshore(lido, 170.0).strength == pytest.approx(0.0, abs=1e-9)
    assert longshore(lido, 170.0 - 45.0).strength == pytest.approx(1.0, abs=1e-9)
    assert longshore(lido, 170.0 - 20.0).strength < longshore(lido, 170.0 - 45.0).strength


def test_offshore_swell_drives_no_current():
    lido = BOOK.get(LIDO_SPOT_ID)
    current = longshore(lido, 350.0)
    assert not current.real
    assert current.strength == 0.0
    assert "offshore of the beach" in current.basis


def test_recovery_caches_so_the_second_run_needs_no_archive(tmp_path):
    cache, archive, sessions = warm_cache(tmp_path)
    assert archive.calls == len(sessions)

    again = recover(sessions, archive, book=BOOK, cache=cache)
    assert archive.calls == len(sessions)          # nothing new was fetched
    assert all(r.status == "cached" for r in again)
    assert all(r.ok for r in again)


def test_offline_run_reports_every_gap_instead_of_dropping_it(tmp_path):
    empty = ConditionCache(tmp_path / "empty")
    out = recover(sample_sessions(), None, book=BOOK, cache=empty)
    assert len(out) == len(sample_sessions())
    assert all(not r.ok and r.status == "skipped" for r in out)
    assert all("offline" in r.note for r in out)


def test_an_hourless_row_is_flagged_not_silently_dated(tmp_path):
    """The 2024-02-24 Lido row carries no time; it is still recovered, with the
    assumed hour on the record."""
    cache = ConditionCache(tmp_path / "c")
    row = next(s for s in LOG if s.spot_id == LIDO_SPOT_ID and s.on == date(2024, 2, 24))
    assert row.hour is None
    rec = recover([row], FakeArchive(FIXTURE), book=BOOK, cache=cache)[0]
    assert rec.hour_assumed is True
    assert rec.ok


def test_local_time_is_converted_to_utc(tmp_path):
    """Belmar's April session is 10:00Z, not 11:00Z: the log is wall clock and New
    Jersey is on EDT (UTC-4) in April. Nautical time (longitude/15) says -5 and
    puts the session an hour off; the spot's IANA zone is what fixes it."""
    cache = ConditionCache(tmp_path / "c")
    row = next(s for s in LOG if s.spot_id == "belmar" and s.on == date(2024, 4, 4))
    rec = recover([row], FakeArchive(FIXTURE), book=BOOK, cache=cache)[0]
    assert (rec.utc_offset_h, rec.hour_utc) == (-4, 10)
    assert rec.on_utc == date(2024, 4, 4)


def test_fives_outrank_ones(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    scored = score_sessions(recover(sessions, None, book=BOOK, cache=cache))
    result = ranking_check(scored)
    assert result.passed is True
    assert "pairs clear" in result.detail


def test_ranking_check_fails_loudly_and_names_the_inversion(tmp_path):
    """Swap the best day's conditions with the worst and the check must fail."""
    cache = ConditionCache(tmp_path / "inverted")
    swapped = dict(FIXTURE)
    swapped["belmar"], swapped["spring-lake"] = FIXTURE["spring-lake"], FIXTURE["belmar"]
    swapped["lido-beach"] = FIXTURE["spring-lake"]
    sessions = sample_sessions()
    recover(sessions, FakeArchive(swapped), book=BOOK, cache=cache)

    result = ranking_check(score_sessions(recover(sessions, None, book=BOOK, cache=cache)))
    assert result.passed is False
    assert result.evidence
    assert any("dominated" in line for line in result.evidence)


def test_ranking_check_skips_rather_than_passing_when_an_end_is_missing(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    fives_only = [s for s in score_sessions(recover(sessions, None, book=BOOK, cache=cache))
                  if s.rating == 5]
    result = ranking_check(fives_only)
    assert result.passed is None
    assert result.mark == "SKIP"


def test_lido_check_confirms_the_normal_case_from_recovered_sessions(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    recovered = recover(sessions, None, book=BOOK, cache=cache)
    normal, anomaly = lido_current_check(recovered, BOOK, LOG)
    assert normal.passed is True
    assert "west" in normal.name
    assert anomaly.passed is None      # the 03-03 row still has no year


def test_the_undated_03_03_row_states_what_would_confirm_it():
    """With no year on the row the check skips, and names the swell band that
    would settle it."""
    _, anomaly = lido_current_check((), BOOK, LOG)
    assert anomaly.passed is None
    assert "170-260 deg" in anomaly.detail


def test_the_03_03_row_checks_out_once_it_has_a_year(tmp_path):
    """Given a year and a southwest swell, the stored bearing predicts the
    east-setting current the note describes."""
    cache = ConditionCache(tmp_path / "c")
    dated = Session(
        raw_date="2023-03-03", raw_spot="Lido Beach NY?", raw_time="--", rating=3,
        notes="SUPER WEIRD — longshore current running EAST; normally pulls WEST here",
        on=date(2023, 3, 3), hour=None, spot_id=LIDO_SPOT_ID, date_uncertain=False,
        time_uncertain=True,
    )
    archive = FakeArchive({LIDO_SPOT_ID: field(1.2, 9.0, 200.0, wind=Wind(5.0, 200.0))})
    recovered = recover([dated], archive, book=BOOK, cache=cache)

    _, anomaly = lido_current_check(recovered, BOOK, [dated])
    assert anomaly.passed is True
    assert "east" in anomaly.detail


def test_a_wrong_shore_normal_would_be_caught():
    """The check has to be able to fail, or it proves nothing about the bearing."""
    lido = BOOK.get(LIDO_SPOT_ID)
    assert current_check(lido, "west", direction_deg=200.0).passed is False


def test_nearest_neighbour_finds_the_session_it_resembles(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    recovered = recover(sessions, None, book=BOOK, cache=cache)

    hits = nearest(field(1.35, 10.5, 155.0), LIDO_SPOT_ID, recovered, limit=2)
    # Both Lido rows on 2024-03-24 are in the log: the 07:00 5/5 and the 10:30 4/5.
    assert {h.recovered.session.on for h in hits} == {date(2024, 3, 24)}
    sentence = hits[0].sentence("Thursday")
    assert "Thursday at Lido Beach resembles your 2024-03-24 session" in sentence
    assert "which you rated" in sentence
    assert hits[0].similarity > 0.5


def test_nearest_neighbour_stays_at_the_spot_asked_about(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    recovered = recover(sessions, None, book=BOOK, cache=cache)
    hits = nearest(field(1.5, 11.0, 100.0), LIDO_SPOT_ID, recovered, limit=5)
    assert {h.recovered.spot.id for h in hits} == {LIDO_SPOT_ID}

    anywhere = nearest(field(1.5, 11.0, 100.0), LIDO_SPOT_ID, recovered,
                       limit=5, same_spot_only=False)
    assert anywhere[0].recovered.spot.id == "belmar"   # its own conditions, exactly


def test_calibrate_runs_offline_from_the_cache_and_prints_pass_fail(tmp_path):
    cache, _, sessions = warm_cache(tmp_path)
    report = calibrate(None, sessions=sessions, book=BOOK, cache=cache)

    assert isinstance(report, CalibrationReport)
    assert report.passed
    text = report.render()
    assert "[PASS] no 1/5 dominates a 5/5" in text
    assert "[SKIP]" in text                      # the yearless 03-03 half
    assert "conditions recovered: 4/4" in text


def test_calibrate_reports_the_sessions_it_could_not_recover(tmp_path):
    report = calibrate(None, sessions=LOG, book=BOOK, cache=ConditionCache(tmp_path / "empty"))
    assert not report.failed                      # nothing to fail on, nothing pretends to pass
    assert all(c.passed is None for c in report.checks)
    assert "no conditions:" in report.render()


def test_public_anchors_never_enter_davids_scale(tmp_path):
    """A public anchor is a documented swell, not a rating on David's scale, so it
    is held apart from the scored sessions."""
    cache, _, sessions = warm_cache(tmp_path)
    anchor = Session(
        raw_date="2018-03-02", raw_spot="Lido Beach NY", raw_time="08:00", rating=5,
        notes="riggs nor'easter, public anchor", on=date(2018, 3, 2), hour=8,
        spot_id=LIDO_SPOT_ID, source="public",
    )
    report = calibrate(None, sessions=[*sessions, anchor], book=BOOK, cache=cache)
    assert report.public_anchors == 1
    assert all(s.recovered.session.source == "david" for s in report.scored)
    assert "public anchors held separately: 1" in report.render()
