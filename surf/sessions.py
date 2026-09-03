from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

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
