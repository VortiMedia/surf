from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Literal, get_args

Provenance = Literal["derived", "manual", "default"]
BreakType = Literal["beach", "reef", "point", "jetty", "rivermouth", "unknown"]


@dataclass(frozen=True)
class Derived:
    """A number plus how we got it, so a guess never reads as a measurement."""

    value: float
    provenance: Provenance = "default"
    note: str = ""


@dataclass(frozen=True)
class Spot:
    id: str
    name: str
    lat: float
    lon: float
    shore_normal: Derived           # bearing the beach FACES, degrees true (south-facing is 180)
    beach_slope: Derived            # tan(beta), dimensionless
    offshore_lat: float             # fixed sample point for every forecast call
    offshore_lon: float
    region: str
    break_type: BreakType = "unknown"
    buoys: tuple[str, ...] = ()
    tide_station: str | None = None
    timezone: str = ""              # IANA zone, e.g. "America/New_York". Empty
                                    # falls back to nautical time from longitude.
    access: str = ""                # a cost note, never a filter
    surfline_id: str | None = None  # optional metadata, never the lookup path
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def offshore_wind_bearing(self) -> float:
        """Wind direction (blowing FROM) that is dead offshore here."""
        return (self.shore_normal.value + 180.0) % 360.0

    @property
    def has_observations(self) -> bool:
        # False outside US/Europe coverage; callers must say so rather than imply data.
        return bool(self.buoys)


COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "lat",
    "lon",
    "shore_normal",
    "shore_normal_provenance",
    "shore_normal_note",
    "beach_slope",
    "beach_slope_provenance",
    "beach_slope_note",
    "offshore_lat",
    "offshore_lon",
    "region",
    "break_type",
    "buoys",
    "tide_station",
    "timezone",
    "access",
    "surfline_id",
    "aliases",
)

_PROVENANCES = frozenset(get_args(Provenance))
_BREAK_TYPES = frozenset(get_args(BreakType))
_ALIAS_SEP = "|"
_BUOY_SEP = ","

# Rewritten verbatim on save, so it must stay byte-identical to the header in
# data/spots.tsv.
PREAMBLE = """\
# Spot database — the single source of truth for geography.
# Plain TSV so it reads whole and diffs cleanly. Add a row any time.
#
# shore_normal   bearing the beach FACES, degrees true (a south-facing beach is 180)
# beach_slope    tan(beta) at the break, dimensionless
# offshore_*     the FIXED sample point every forecast call uses, 5 km seaward
# provenance     derived = measured from data | manual = set by hand | default = placeholder
# buoys          NDBC ids, comma-separated. Empty means model-only and the call must say so.
# tide_station   NOAA CO-OPS id, or empty to fall back to Open-Meteo sea level
# timezone       IANA zone. The session log records wall-clock time with no zone, so
#                this is what turns a logged 08:00 into the right hour of ocean. Empty
#                falls back to nautical time (longitude/15), which ignores DST.
# access         a cost note, never a filter
# aliases        pipe-separated; how data/sessions.tsv and humans name this spot
#
# No Outer Cape spots: zero ground truth there.
"""


class SpotFileError(ValueError):
    """The spot file is malformed."""


def data_dir() -> Path:
    """Directory holding the TSVs; `SURF_DATA` overrides it."""
    override = os.environ.get("SURF_DATA")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data"


def default_spots_path() -> Path:
    return data_dir() / "spots.tsv"


_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise(name: str) -> str:
    # A trailing `?` marks an uncertain row and is meaningful upstream, so it is
    # stripped only here, for comparison.
    lowered = name.strip().lower().rstrip("?").strip()
    return " ".join(_PUNCT.sub(" ", lowered).split())


def _split_alternatives(name: str) -> list[str]:
    """Fragments of a name like `Stonewall Beach / Aquinnah, MA`, longest first."""
    parts = [p for p in re.split(r"[/,]", name) if p.strip()]
    parts.sort(key=len, reverse=True)
    return parts


def _provenance(raw: str, field: str, spot_id: str) -> Provenance:
    value = raw.strip() or "default"
    if value not in _PROVENANCES:
        raise SpotFileError(f"{spot_id}: {field} provenance {value!r} not in {sorted(_PROVENANCES)}")
    return value  # type: ignore[return-value]


def _float(raw: str, field: str, spot_id: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise SpotFileError(f"{spot_id}: {field} {raw!r} is not a number") from exc


def parse_row(cells: dict[str, str]) -> Spot:
    # Raises rather than defaulting: a silently defaulted shore normal is wrong
    # in a way nothing downstream can detect.
    missing = [c for c in COLUMNS if c not in cells]
    if missing:
        raise SpotFileError(f"row missing columns: {', '.join(missing)}")
    spot_id = cells["id"].strip()
    if not spot_id:
        raise SpotFileError("row has no id")

    break_type = cells["break_type"].strip() or "unknown"
    if break_type not in _BREAK_TYPES:
        raise SpotFileError(f"{spot_id}: break_type {break_type!r} not in {sorted(_BREAK_TYPES)}")

    return Spot(
        id=spot_id,
        name=cells["name"].strip(),
        lat=_float(cells["lat"], "lat", spot_id),
        lon=_float(cells["lon"], "lon", spot_id),
        shore_normal=Derived(
            value=_float(cells["shore_normal"], "shore_normal", spot_id),
            provenance=_provenance(cells["shore_normal_provenance"], "shore_normal", spot_id),
            note=cells["shore_normal_note"].strip(),
        ),
        beach_slope=Derived(
            value=_float(cells["beach_slope"], "beach_slope", spot_id),
            provenance=_provenance(cells["beach_slope_provenance"], "beach_slope", spot_id),
            note=cells["beach_slope_note"].strip(),
        ),
        offshore_lat=_float(cells["offshore_lat"], "offshore_lat", spot_id),
        offshore_lon=_float(cells["offshore_lon"], "offshore_lon", spot_id),
        region=cells["region"].strip(),
        break_type=break_type,  # type: ignore[arg-type]
        buoys=tuple(b.strip() for b in cells["buoys"].split(_BUOY_SEP) if b.strip()),
        tide_station=cells["tide_station"].strip() or None,
        timezone=cells["timezone"].strip(),
        access=cells["access"].strip(),
        surfline_id=cells["surfline_id"].strip() or None,
        aliases=tuple(a.strip() for a in cells["aliases"].split(_ALIAS_SEP) if a.strip()),
    )


def format_row(spot: Spot) -> list[str]:
    return [
        spot.id,
        spot.name,
        f"{spot.lat:.4f}",
        f"{spot.lon:.4f}",
        f"{spot.shore_normal.value:.1f}",
        spot.shore_normal.provenance,
        spot.shore_normal.note,
        f"{spot.beach_slope.value:.4f}",
        spot.beach_slope.provenance,
        spot.beach_slope.note,
        f"{spot.offshore_lat:.4f}",
        f"{spot.offshore_lon:.4f}",
        spot.region,
        spot.break_type,
        _BUOY_SEP.join(spot.buoys),
        spot.tide_station or "",
        spot.timezone,
        spot.access,
        spot.surfline_id or "",
        _ALIAS_SEP.join(spot.aliases),
    ]


def load_spots(path: Path | str | None = None) -> tuple[Spot, ...]:
    """Read the whole spot file; `#` and blank lines are skipped."""
    path = Path(path) if path is not None else default_spots_path()
    text = path.read_text(encoding="utf-8")

    header: list[str] | None = None
    spots: list[Spot] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if header is None:
            header = [c.strip() for c in cells]
            unknown = set(header) - set(COLUMNS)
            if unknown:
                raise SpotFileError(f"{path}: unknown columns {sorted(unknown)}")
            continue
        if len(cells) != len(header):
            raise SpotFileError(
                f"{path}:{lineno}: {len(cells)} cells for {len(header)} columns"
            )
        try:
            spots.append(parse_row(dict(zip(header, cells))))
        except SpotFileError as exc:
            raise SpotFileError(f"{path}:{lineno}: {exc}") from exc

    if header is None:
        raise SpotFileError(f"{path}: no header row")

    seen: set[str] = set()
    for spot in spots:
        if spot.id in seen:
            raise SpotFileError(f"{path}: duplicate spot id {spot.id!r}")
        seen.add(spot.id)
    return tuple(spots)


def save_spots(spots: Iterable[Spot], path: Path | str | None = None) -> None:
    # Output is byte-identical to the input when nothing changed, so a diff only
    # ever shows a real edit.
    path = Path(path) if path is not None else default_spots_path()
    lines = [PREAMBLE.rstrip("\n"), "\t".join(COLUMNS)]
    lines.extend("\t".join(format_row(s)) for s in spots)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class SpotBook:
    spots: tuple[Spot, ...]

    @classmethod
    def load(cls, path: Path | str | None = None) -> "SpotBook":
        return cls(load_spots(path))

    def __iter__(self) -> Iterator[Spot]:
        return iter(self.spots)

    def __len__(self) -> int:
        return len(self.spots)

    def get(self, spot_id: str) -> Spot | None:
        for spot in self.spots:
            if spot.id == spot_id:
                return spot
        return None

    def in_region(self, region: str) -> tuple[Spot, ...]:
        """Prefix match, so `US` selects every US region and `US-RI` one state."""
        key = region.strip().upper()
        return tuple(s for s in self.spots if s.region.upper().startswith(key))

    def resolve(self, name: str) -> Spot | None:
        """Written name to Spot, or None.

        Exact-first and deterministic: id, then name or alias, then the longest
        alias contained in the string, then each `/`- or `,`-separated fragment.
        No scoring, no fuzziness.
        """
        key = normalise(name)
        if not key:
            return None

        for spot in self.spots:
            if normalise(spot.id) == key:
                return spot
        for spot in self.spots:
            if key in {normalise(a) for a in (spot.name, *spot.aliases)}:
                return spot

        best: tuple[int, Spot] | None = None
        for spot in self.spots:
            for candidate in (spot.name, *spot.aliases):
                ckey = normalise(candidate)
                if ckey and ckey in key and (best is None or len(ckey) > best[0]):
                    best = (len(ckey), spot)
        if best is not None:
            return best[1]

        for fragment in _split_alternatives(name):
            fkey = normalise(fragment)
            if not fkey:
                continue
            for spot in self.spots:
                if fkey in {normalise(a) for a in (spot.name, *spot.aliases)}:
                    return spot
        return None
