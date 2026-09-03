from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .sources import Http, Reading, SourceDown, explain, now
from .waves import SwellPartition, WaveField, Wind

BASE = "https://www.ndbc.noaa.gov/data/realtime2"
SOURCE = "ndbc"

# `.swden` 404s here; energy density lives in `.data_spec`.
DEAD_EXTENSIONS = {"swden"}

MISSING = "MM"

# Realtime buoys report every 10-60 min; past this an observation no longer
# beats a model.
STALE_AFTER = timedelta(hours=3)

# Wind (`.txt`) and waves (`.spec`) are separate reports; merge them only if
# they describe roughly the same moment.
MERGE_TOLERANCE = timedelta(minutes=60)

_CARDINALS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)
_CARDINAL_DEG = {name: i * 22.5 for i, name in enumerate(_CARDINALS)}


class NdbcParseError(ValueError):
    """The file came back 200 but is not an NDBC realtime table."""


@dataclass(frozen=True)
class SpecRow:
    """A `.spec` record: wave field plus NOAA's steepness class, the fallback
    when bathymetry cannot supply a beach slope."""

    field: WaveField
    steepness: str = ""


def realtime_url(buoy_id: str, ext: str) -> str:
    ext = ext.lstrip(".")
    if ext in DEAD_EXTENSIONS:
        raise ValueError(
            f".{ext} does not exist on NDBC (404). Use .data_spec for energy density."
        )
    return f"{BASE}/{buoy_id}.{ext}"


def _to_deg(raw: str) -> float | None:
    """Directions arrive as degrees in `.txt` and as compass points in `.spec`."""
    if raw in _CARDINAL_DEG:
        return _CARDINAL_DEG[raw]
    try:
        return float(raw) % 360.0
    except ValueError:
        return None


def _to_float(raw: str) -> float | None:
    if raw == MISSING:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _rows(text: str) -> tuple[list[str], list[list[str]]]:
    # Both file types are whitespace-delimited under two `#` header lines (names,
    # then units). Keying off the names lets one parser serve `.txt` and `.spec`
    # and survives NOAA adding a column.
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            if header is None:
                header = line.lstrip("#").split()
            continue
        rows.append(line.split())
    if header is None:
        raise NdbcParseError("no '#' header line; not an NDBC realtime file")
    return header, rows


def _timestamp(cells: dict[str, str]) -> datetime | None:
    try:
        return datetime(
            int(cells["YY"]), int(cells["MM_month"]), int(cells["DD"]),
            int(cells["hh"]), int(cells["mm"]), tzinfo=timezone.utc,
        )
    except (KeyError, ValueError):
        return None


def _cells(header: list[str], row: list[str]) -> dict[str, str] | None:
    if len(row) != len(header):
        return None
    out = dict(zip(header, row))
    # The month column is literally named MM, which is also the missing-value
    # token. Rename it once here so nothing downstream has to know that.
    if header[:5] == ["YY", "MM", "DD", "hh", "mm"]:
        out["MM_month"] = row[1]
    return out


def parse_txt(text: str, buoy_id: str = "") -> tuple[WaveField, ...]:
    """Standard meteorological file: one total wave height plus wind. `.txt`
    has no swell/windwave split, so a single `total` partition is emitted."""
    header, rows = _rows(text)
    fields: list[WaveField] = []
    for row in rows:
        cells = _cells(header, row)
        if cells is None:
            continue
        t = _timestamp(cells)
        if t is None:
            continue
        hs = _to_float(cells.get("WVHT", MISSING))
        dpd = _to_float(cells.get("DPD", MISSING))
        mwd = _to_deg(cells.get("MWD", MISSING))
        partitions: tuple[SwellPartition, ...] = ()
        if hs is not None and dpd is not None and mwd is not None:
            partitions = (SwellPartition(hs, dpd, mwd, kind="total"),)
        wspd = _to_float(cells.get("WSPD", MISSING))
        wdir = _to_deg(cells.get("WDIR", MISSING))
        wind = Wind(wspd, wdir) if wspd is not None and wdir is not None else None
        fields.append(
            WaveField(
                time=t,
                partitions=partitions,
                wind=wind,
                total_height_m=hs,
                total_period_s=dpd,
                model=f"{SOURCE}/{buoy_id}" if buoy_id else SOURCE,
            )
        )
    return tuple(sorted(fields, key=lambda f: f.time, reverse=True))


def parse_spec(text: str, buoy_id: str = "") -> tuple[SpecRow, ...]:
    """Spectral summary: NOAA's swell/windwave split.

    A partition needs height, period and direction all present, or its `energy`
    would be wrong. Some buoys publish `.spec` with WVHT but `MM` across every
    SwH/SwP/WWH/WWP column, so those rows fall back to a `total` partition.
    """
    header, rows = _rows(text)
    out: list[SpecRow] = []
    for row in rows:
        cells = _cells(header, row)
        if cells is None:
            continue
        t = _timestamp(cells)
        if t is None:
            continue
        partitions: list[SwellPartition] = []
        for h_key, p_key, d_key, kind in (
            ("SwH", "SwP", "SwD", "swell"),
            ("WWH", "WWP", "WWD", "windwave"),
        ):
            h = _to_float(cells.get(h_key, MISSING))
            p = _to_float(cells.get(p_key, MISSING))
            d = _to_deg(cells.get(d_key, MISSING))
            if h is not None and p is not None and d is not None:
                partitions.append(SwellPartition(h, p, d, kind=kind))
        if not partitions:
            h = _to_float(cells.get("WVHT", MISSING))
            p = _to_float(cells.get("APD", MISSING))
            d = _to_deg(cells.get("MWD", MISSING))
            if h is not None and p is not None and d is not None:
                partitions.append(SwellPartition(h, p, d, kind="total"))
        steep = cells.get("STEEPNESS", "")
        if steep in (MISSING, "N/A"):
            steep = ""
        out.append(
            SpecRow(
                field=WaveField(
                    time=t,
                    partitions=tuple(partitions),
                    total_height_m=_to_float(cells.get("WVHT", MISSING)),
                    total_period_s=_to_float(cells.get("APD", MISSING)),
                    model=f"{SOURCE}/{buoy_id}" if buoy_id else SOURCE,
                ),
                steepness=steep,
            )
        )
    return tuple(sorted(out, key=lambda r: r.field.time, reverse=True))


class NdbcObservations:
    name = SOURCE

    #: Probing a real buoy file rather than the station index: a 200 on a file
    #: nobody parses proves nothing about the format.
    preflight_buoy = "44097"

    def __init__(self, http: Http | None = None, *, clock=now):
        self._http = http or Http()
        self._now = clock

    def preflight(self) -> Reading[bool]:
        try:
            r = self._http.get(SOURCE, realtime_url(self.preflight_buoy, "spec"))
            rows = parse_spec(r.text, self.preflight_buoy)
        except SourceDown as exc:
            return Reading(None, SOURCE, "skipped", self._now(), note=str(exc))
        except Exception as exc:
            return Reading(False, SOURCE, "failed", self._now(), note=explain(exc))
        if not rows:
            return Reading(
                False, SOURCE, "failed", self._now(),
                note=f"{self.preflight_buoy}.spec parsed to zero rows",
            )
        return Reading(True, SOURCE, "ok", self._now(), note=f"probe {self.preflight_buoy}.spec")

    def latest(self, buoy_id: str) -> Reading[WaveField]:
        """Newest observation from one buoy: `.spec` partitions plus `.txt` wind."""
        src = f"{SOURCE}/{buoy_id}"
        dropped: list[str] = []
        notes: list[str] = []

        spec, spec_err = self._fetch(buoy_id, "spec", parse_spec)
        txt, txt_err = self._fetch(buoy_id, "txt", parse_txt)
        if spec_err:
            dropped.append(f"spec ({spec_err})")
        if txt_err:
            dropped.append(f"txt ({txt_err})")

        if not spec and not txt:
            status = "skipped" if "breaker open" in f"{spec_err} {txt_err}" else "failed"
            return Reading(
                None, src, status, self._now(),
                note="; ".join(n for n in (spec_err, txt_err) if n),
                dropped=tuple(dropped),
            )

        if spec:
            row = spec[0]
            field = row.field
            if not field.partitions:
                dropped.append("all partitions (MM across the spec row)")
            elif all(p.kind == "total" for p in field.partitions):
                dropped.append("swell/windwave split (this buoy reports MM for it)")
            if row.steepness:
                notes.append(f"steepness={row.steepness}")
            wind_field = txt[0] if txt else None
            if wind_field is not None and wind_field.wind is not None:
                if abs(wind_field.time - field.time) <= MERGE_TOLERANCE:
                    field = _with_wind(field, wind_field.wind, wind_field.total_period_s)
                else:
                    dropped.append("wind (txt report too far from spec report)")
            elif txt:
                dropped.append("wind (MM in txt)")
        else:
            field = txt[0]
            notes.append("no .spec: total only, swell/windwave not separated")

        age = self._now() - field.time
        status = "ok"
        if dropped:
            status = "degraded"
        if age > STALE_AFTER:
            status = "degraded"
            notes.append(f"stale by {age - STALE_AFTER}")
        notes.append(f"age={int(age.total_seconds() // 60)}min")

        return Reading(
            field, src, status, self._now(),
            note="; ".join(notes), dropped=tuple(dropped),
        )

    def _fetch(self, buoy_id: str, ext: str, parse):
        """Return (parsed rows, error string); never raises, so a dead file for one
        buoy does not take the other file or buoy with it."""
        try:
            r = self._http.get(SOURCE, realtime_url(buoy_id, ext))
        except SourceDown as exc:
            return (), str(exc)
        except Exception as exc:
            return (), explain(exc)
        try:
            return parse(r.text, buoy_id), ""
        except NdbcParseError as exc:
            return (), str(exc)


def _with_wind(field: WaveField, wind: Wind, period_s: float | None) -> WaveField:
    return WaveField(
        time=field.time,
        partitions=field.partitions,
        wind=wind,
        total_height_m=field.total_height_m,
        total_period_s=field.total_period_s if field.total_period_s is not None else period_s,
        model=field.model,
    )
