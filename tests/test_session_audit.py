"""Mechanical session-log repair: no guesses, and a written basis for each edit."""

from __future__ import annotations

from datetime import date, datetime, timezone

from surf.sessions import audit_sessions, load_sessions
from surf.spots import SpotBook
from surf.sources import Reading
from surf.waves import SwellPartition, WaveField


BOOK = SpotBook.load()


def _field(day: date) -> WaveField:
    return WaveField(
        time=datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc),
        partitions=(SwellPartition(1.0, 10.0, 180.0, "swell"),),
        total_height_m=1.0,
        total_period_s=10.0,
        model="audit-test",
    )


class DayArchive:
    name = "audit-test"

    def __init__(self, surf_days: set[date]):
        self.surf_days = surf_days

    def conditions(self, spot, on: date, hour: int):
        value = _field(on) if on in self.surf_days else WaveField(
            time=datetime(on.year, on.month, on.day, hour, tzinfo=timezone.utc),
            partitions=(), total_height_m=0.0, total_period_s=0.0, model="audit-test",
        )
        return Reading(value, self.name, "ok", datetime.now(timezone.utc))


def _write(path, rows: str) -> None:
    path.write_text(
        "# Keep this comment.\n"
        "date\tspot\ttime\trating\tnotes\n" + rows,
        encoding="utf-8",
    )


def test_audit_canonicalizes_collision_and_recovers_unique_leap_candidate(tmp_path):
    path = tmp_path / "sessions.tsv"
    _write(
        path,
        "2024-02-29\tPoint Judith RI\t--\t4\tfun\n"
        "????-02-29\tPoint Judith\t--\t4\tfun\n",
    )
    report = audit_sessions(
        path,
        book=BOOK,
        archive=DayArchive({date(2024, 2, 29)}),
        years=(2023, 2024),
    )

    assert report.before_resolvable == 1
    assert report.after_resolvable == 2
    assert [(r.field, r.after) for r in report.repairs] == [
        ("spot", "point-judith"),
        ("spot", "point-judith"),
        ("date", "2024-02-29"),
    ]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Keep this comment.\n")
    assert text.count("\tpoint-judith\t") == 2
    assert "unique surfable archive candidate" in text
    assert load_sessions(path, book=BOOK)[1].on == date(2024, 2, 29)


def test_audit_refuses_ambiguous_candidate_and_keeps_marker(tmp_path):
    path = tmp_path / "sessions.tsv"
    _write(path, "????-03-03\tLido Beach NY?\t--\t3\tNEEDS YEAR\n")
    report = audit_sessions(
        path,
        book=BOOK,
        archive=DayArchive({date(2023, 3, 3), date(2024, 3, 3)}),
        years=(2023, 2024),
    )

    assert report.after[0].on is None
    assert report.after[0].raw_date == "????-03-03"
    assert report.after[0].raw_spot == "lido-beach"
    assert any("multiple surfable candidates" in q.question for q in report.questions)
    assert "????-03-03\tlido-beach" in path.read_text(encoding="utf-8")


def test_audit_accepts_explicit_permanent_unanswerable(tmp_path):
    path = tmp_path / "sessions.tsv"
    _write(
        path,
        "????-03-03\tlido-beach\t--\t3\tUNANSWERABLE: YEAR — archive candidates are ambiguous\n"
        "2024-12-05\tunknown\t--\t5\tUNANSWERABLE: SPOT — no identifying evidence\n",
    )
    report = audit_sessions(path, book=BOOK)

    assert report.questions == ()
    assert len(report.unanswerable) == 2
    assert report.wrote is False
