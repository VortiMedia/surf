from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from .spots import SpotBook, data_dir

AnchorType = str  # "ideal" | "lower_bound" | "failure" | "" (ordinary row)


@dataclass(frozen=True)
class Session:
    """One row of data/sessions.tsv. Derived fields stay None when the raw row is
    uncertain (`?`/`????`) rather than being guessed at."""

    raw_date: str
    raw_spot: str
    raw_time: str
    rating: int | None
    notes: str
    on: date | None = None
    hour: int | None = None
    spot_id: str | None = None
    date_uncertain: bool = False
    time_uncertain: bool = False
    source: str = "david"  # "public" anchors use a different rating scale and must not be merged in

    @property
    def usable_for_check(self) -> bool:
        """A row can referee the model only with a date, a spot and a rating."""
        return self.on is not None and self.spot_id is not None and self.rating is not None


COLUMNS: tuple[str, ...] = ("date", "spot", "time", "rating", "notes")

UNKNOWN_SPOT = "unknown"

# `????-03-03` — month and day survive; the year is genuinely not known.
_PARTIAL_DATE = re.compile(r"^\?{4}-(\d{2})-(\d{2})$")
_FULL_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")

# Written instead of a clock: real information, but not an hour, so they leave
# `hour` empty rather than inventing 06:00.
_VAGUE_TIMES = frozenset({"early", "sunrise", "sunset", "dawn", "dusk", "morning", "afternoon", "evening"})
_NO_TIME = frozenset({"", "--", "-", "?"})


class SessionFileError(ValueError):
    """The session file is malformed."""


@dataclass(frozen=True)
class SessionRepair:
    """One mechanical edit made by :func:`audit_sessions`."""

    row: int
    field: str
    before: str
    after: str
    basis: str


@dataclass(frozen=True)
class SessionQuestion:
    """A field the audit could not prove and therefore left untouched."""

    row: int
    raw_date: str
    raw_spot: str
    question: str


@dataclass(frozen=True)
class SessionAudit:
    """The before/after evidence for one session-log audit."""

    before: tuple[Session, ...]
    after: tuple[Session, ...]
    repairs: tuple[SessionRepair, ...]
    questions: tuple[SessionQuestion, ...]
    wrote: bool = False

    @property
    def before_resolvable(self) -> int:
        return len(usable(self.before))

    @property
    def after_resolvable(self) -> int:
        return len(usable(self.after))


def _wave_field_is_surfable(field: Any) -> bool:
    """Return whether a source supplied a non-zero wave field.

    This is deliberately only an existence test. The audit is allowed to find a
    unique day with data; it is not allowed to infer a rating or a quality band.
    """
    primary = getattr(field, "primary", None)
    if primary is not None and getattr(primary, "height_m", 0.0) > 0.0:
        return True
    height = getattr(field, "total_height_m", None)
    return height is not None and height > 0.0


def _candidate_years(
    sessions: Sequence[Session], years: Iterable[int] | None,
) -> tuple[int, ...]:
    if years is not None:
        return tuple(sorted({int(year) for year in years}))
    known = [s.on.year for s in sessions if s.on is not None]
    if not known:
        return (date.today().year,)
    # Keep the default bounded by the log. A caller that has a wider candidate
    # window can pass `years=` explicitly; audit must not make an unbounded API
    # crawl a surprise side effect.
    return tuple(range(min(known), max(known) + 1))


def _surfable_candidates(
    archive: Any,
    spot: Any,
    month: int,
    day: int,
    years: Sequence[int],
    hour: int,
) -> tuple[date, ...]:
    candidates: list[date] = []
    for year in years:
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            # 29 February is valid only in a leap year. Dropping an impossible
            # calendar date is a mechanical repair, never an inferred year.
            continue

    # A test/future archive may expose a batch method. Keep the ordinary Archive
    # protocol untouched and use it when available to avoid one request per day.
    batch = getattr(archive, "surfable_days", None)
    if callable(batch):
        found = batch(spot, tuple(candidates))
        return tuple(sorted(set(found) & set(candidates)))

    found: list[date] = []
    for candidate in candidates:
        reading = archive.conditions(spot, candidate, hour)
        value = getattr(reading, "value", reading)
        if getattr(reading, "ok", value is not None) and _wave_field_is_surfable(value):
            found.append(candidate)
    return tuple(found)


def _audit_note(notes: str, basis: str) -> str:
    marker = f"[audit: {basis}]"
    return notes if marker in notes else f"{notes.rstrip()} {marker}".strip()


def _rewrite_audited_file(path: Path, sessions: Sequence[Session]) -> None:
    """Replace data rows while preserving the log's comment header and blanks."""
    original = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    index = 0
    header_seen = False
    for line in original:
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        if not header_seen:
            header_seen = True
            out.append(line)
            continue
        if index >= len(sessions):
            raise SessionFileError(f"{path}: audit row count changed while writing")
        out.append("\t".join(format_row(sessions[index])))
        index += 1
    if index != len(sessions):
        raise SessionFileError(f"{path}: audit could not find every session row")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def audit_sessions(
    path: Path | str | None = None,
    *,
    book: SpotBook | None = None,
    archive: Any | None = None,
    years: Iterable[int] | None = None,
    write: bool = True,
) -> SessionAudit:
    """Canonicalize and mechanically repair the session log.

    Spot names become spot ids. A yearless date is filled only when exactly one
    valid candidate year has a non-zero archived wave field. With no archive (the
    normal offline mode), uncertain dates remain uncertain. No score, rating or
    other plausible fallback is written.
    """
    path = Path(path) if path is not None else default_sessions_path()
    book = book if book is not None else SpotBook.load()
    before = load_sessions(path, book=book)
    candidate_years = _candidate_years(before, years)
    repaired: list[Session] = []
    repairs: list[SessionRepair] = []
    questions: list[SessionQuestion] = []

    for row, session in enumerate(before, start=1):
        current = session
        spot = book.resolve(session.raw_spot)
        if spot is not None and session.raw_spot.strip() != spot.id:
            basis = f"canonical spot id from spots.tsv ({spot.id})"
            current = replace(
                current,
                raw_spot=spot.id,
                spot_id=spot.id,
                notes=_audit_note(current.notes, basis),
            )
            repairs.append(SessionRepair(row, "spot", session.raw_spot, spot.id, basis))

        if current.on is None and current.date_uncertain and archive is not None:
            partial = _PARTIAL_DATE.match(current.raw_date.strip().rstrip("?"))
            if partial:
                month, day = (int(value) for value in partial.groups())
                candidates = _surfable_candidates(
                    archive, spot, month, day, candidate_years,
                    current.hour if current.hour is not None else 8,
                ) if spot is not None else ()
                if len(candidates) == 1:
                    recovered = candidates[0]
                    basis = f"unique surfable archive candidate ({recovered.isoformat()})"
                    current = replace(
                        current,
                        raw_date=recovered.isoformat(),
                        on=recovered,
                        date_uncertain=False,
                        notes=_audit_note(current.notes, basis),
                    )
                    repairs.append(SessionRepair(row, "date", session.raw_date, current.raw_date, basis))
                elif len(candidates) > 1:
                    questions.append(SessionQuestion(
                        row, current.raw_date, current.raw_spot,
                        "which year? archive has multiple surfable candidates: "
                        + ", ".join(d.isoformat() for d in candidates),
                    ))

        if current.spot_id is None:
            questions.append(SessionQuestion(row, current.raw_date, current.raw_spot, "which spot?"))
        if current.on is None:
            questions.append(SessionQuestion(row, current.raw_date, current.raw_spot, "which year?"))
        repaired.append(current)

    did_write = bool(write and repairs and path.exists())
    if did_write:
        _rewrite_audited_file(path, repaired)
    return SessionAudit(tuple(before), tuple(repaired), tuple(repairs), tuple(questions), did_write)


def default_sessions_path() -> Path:
    return data_dir() / "sessions.tsv"


def parse_date(raw: str) -> tuple[date | None, bool]:
    """`(date, uncertain)`. Returns `(None, True)` when the year is missing."""
    text = raw.strip()
    uncertain = text.endswith("?")
    text = text.rstrip("?").strip()

    if _PARTIAL_DATE.match(text):
        return None, True
    match = _FULL_DATE.match(text)
    if not match:
        return None, True
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day), uncertain
    except ValueError as exc:
        raise SessionFileError(f"{raw!r} is not a real date: {exc}") from exc


def parse_time(raw: str) -> tuple[int | None, bool]:
    """`(hour, uncertain)`. Uncertain unless the row gives a confirmed clock time."""
    text = raw.strip()
    uncertain = text.endswith("?")
    text = text.rstrip("?").strip()

    if text.lower() in _NO_TIME:
        return None, True
    if text.lower() in _VAGUE_TIMES:
        return None, True
    match = _CLOCK.match(text)
    if not match:
        return None, True
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SessionFileError(f"{raw!r} is not a real time")
    return hour, uncertain


def parse_rating(raw: str) -> int | None:
    text = raw.strip()
    if not text or text == "?":
        return None
    try:
        rating = int(text)
    except ValueError as exc:
        raise SessionFileError(f"rating {raw!r} is not an integer 1-5") from exc
    if not 1 <= rating <= 5:
        raise SessionFileError(f"rating {rating} outside 1-5")
    return rating


def load_sessions(
    path: Path | str | None = None,
    book: SpotBook | None = None,
    source: str = "david",
) -> tuple[Session, ...]:
    """Read the log and resolve each row's spot name through the spot database.

    Pass `source="public"` for a documented-swell anchor set; those ratings are on
    a different scale and must not be mixed with the logged ones.
    """
    path = Path(path) if path is not None else default_sessions_path()
    if book is None:
        book = SpotBook.load()
    text = path.read_text(encoding="utf-8")

    header: list[str] | None = None
    sessions: list[Session] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if header is None:
            header = [c.strip() for c in cells]
            if header[: len(COLUMNS)] != list(COLUMNS):
                raise SessionFileError(f"{path}: header is {header}, expected {list(COLUMNS)}")
            continue
        if len(cells) < len(COLUMNS):
            cells = cells + [""] * (len(COLUMNS) - len(cells))
        raw_date, raw_spot, raw_time, raw_rating, notes = cells[: len(COLUMNS)]

        try:
            on, date_uncertain = parse_date(raw_date)
            hour, time_uncertain = parse_time(raw_time)
            rating = parse_rating(raw_rating)
        except SessionFileError as exc:
            raise SessionFileError(f"{path}:{lineno}: {exc}") from exc

        spot = None if raw_spot.strip().lower() == UNKNOWN_SPOT else book.resolve(raw_spot)
        sessions.append(
            Session(
                raw_date=raw_date,
                raw_spot=raw_spot,
                raw_time=raw_time,
                rating=rating,
                notes=notes,
                on=on,
                hour=hour,
                spot_id=spot.id if spot else None,
                date_uncertain=date_uncertain,
                time_uncertain=time_uncertain,
                source=source,
            )
        )

    if header is None:
        raise SessionFileError(f"{path}: no header row")
    return tuple(sessions)


def format_row(session: Session) -> list[str]:
    # Only raw fields are written back; the derived ones are re-parsed on load, so
    # a save can never harden a guess into the file.
    return [
        session.raw_date,
        session.raw_spot,
        session.raw_time,
        "" if session.rating is None else str(session.rating),
        session.notes,
    ]


def save_sessions(sessions: Iterable[Session], path: Path | str) -> None:
    # `path` is required so this can never default to overwriting the real log.
    lines = ["\t".join(COLUMNS)]
    lines.extend("\t".join(format_row(s)) for s in sessions)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def unresolved(sessions: Sequence[Session]) -> tuple[Session, ...]:
    """Rows that did not land on a spot. Reported, never dropped."""
    return tuple(s for s in sessions if s.spot_id is None)


def undated(sessions: Sequence[Session]) -> tuple[Session, ...]:
    """Rows with no usable date."""
    return tuple(s for s in sessions if s.on is None)


def usable(sessions: Sequence[Session]) -> tuple[Session, ...]:
    """Rows with a date, a spot and a rating."""
    return tuple(s for s in sessions if s.usable_for_check)


def resolution_report(sessions: Sequence[Session]) -> str:
    """Counts plus every row that failed to resolve, as one readable block."""
    lines = [
        f"sessions: {len(sessions)}  resolved: {len(sessions) - len(unresolved(sessions))}"
        f"  dated: {len(sessions) - len(undated(sessions))}  usable: {len(usable(sessions))}"
    ]
    for session in unresolved(sessions):
        lines.append(f"  unresolved spot: {session.raw_date}\t{session.raw_spot!r}")
    for session in undated(sessions):
        lines.append(f"  no year: {session.raw_date}\t{session.raw_spot}")
    return "\n".join(lines)
