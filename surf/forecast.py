from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .geometry import DepthSource, GeometryCache, beach_slope
from .score import reference_field
from .sources import ForecastSource, Observations, Reading, SourceDown, Status, Tides, Window
from .spots import Derived, Spot
from .waves import Forecast, TidePoint, WaveField

# How far from its timestamp a buoy report still describes the water; NDBC
# itself calls a report stale after 3 h.
OBSERVATION_RELEVANT = timedelta(hours=3)

# CO-OPS returns hourly predictions plus the hi/lo turns, so a point further
# than this from an hour belongs to a different hour.
TIDE_TOLERANCE = timedelta(minutes=30)

MODEL_ONLY_NOTE = "model-only: no buoy observation covers this spot"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(when: datetime) -> datetime:
    # Every source here speaks UTC, so a naive timestamp is UTC; inventing a
    # local zone would silently shift a forecast.
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _status_for(exc: Exception) -> Status:
    # An open circuit breaker is `skipped`, not `failed`: nothing was tried.
    return "skipped" if isinstance(exc, SourceDown) or "breaker open" in str(exc) else "failed"


def _why(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


@dataclass(frozen=True)
class Hour:
    """One hour at one spot. `fields` is one WaveField per model; the buoy is
    kept out of that set so it never reads as agreement between models."""

    at: datetime
    fields: tuple[WaveField, ...] = ()
    observed: WaveField | None = None
    tide: TidePoint | None = None

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(f.model for f in self.fields)

    @property
    def observation_led(self) -> bool:
        return self.observed is not None

    @property
    def reference(self) -> WaveField | None:
        """The buoy where it is temporally relevant, otherwise the median model."""
        if self.observed is not None:
            return self.observed
        return reference_field(self.fields)

    def basis(self) -> str:
        """One line saying who answered for this hour and who led."""
        who = ",".join(self.models) or "no model"
        if self.observed is not None:
            age = abs(self.at - _utc(self.observed.time))
            return (
                f"{self.at:%Y-%m-%d %H:%M}Z observed by {self.observed.model} "
                f"({int(age.total_seconds() // 60)}min away), models {who}"
            )
        return f"{self.at:%Y-%m-%d %H:%M}Z from {who}"


@dataclass(frozen=True)
class SpotForecast:
    """Everything known about one spot over one window. `readings` is the
    receipt: one Reading per source attempt, failures included."""

    spot: Spot
    window: Window
    hours: tuple[Hour, ...] = ()
    readings: tuple[Reading[Any], ...] = ()
    slope: Derived | None = None
    slope_basis: str = ""
    model_only: bool = True
    benchmark: Forecast | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    fetched_at: datetime = field(default_factory=_now)

    @property
    def models(self) -> tuple[str, ...]:
        """Every model that answered for at least one hour."""
        seen: list[str] = []
        for hour in self.hours:
            for name in hour.models:
                if name not in seen:
                    seen.append(name)
        return tuple(seen)

    @property
    def failures(self) -> tuple[Reading[Any], ...]:
        return tuple(r for r in self.readings if not r.ok)

    @property
    def complete(self) -> bool:
        """Every hour that was asked for came back."""
        return len(self.hours) >= self.window.hours

    @property
    def status(self) -> Status:
        # Judged on what arrived. `model_only` is deliberately not degradation:
        # many spots have no buoy at all and never will.
        if not self.hours:
            if self.readings and all(r.status == "skipped" for r in self.readings):
                return "skipped"
            return "failed"
        if self.failures or not self.complete:
            return "degraded"
        return "ok"

    def at(self, when: datetime) -> Hour | None:
        target = _utc(when)
        return next((h for h in self.hours if h.at == target), None)

    def label_lines(self) -> tuple[str, ...]:
        """Every source's one-liner, in call order."""
        return tuple(r.label() for r in self.readings)


@dataclass(frozen=True)
class Sources:
    """Every source is optional; absent is not the same as broken."""

    forecast: tuple[ForecastSource, ...] = ()
    observations: Observations | None = None
    tides: Tides | None = None
    depth: DepthSource | None = None
    benchmark: ForecastSource | None = None   # Surfline, opt-in

    def preflightable(self) -> tuple[tuple[str, Any], ...]:
        """(name, source) for everything that can be health-checked."""
        candidates: list[Any] = [*self.forecast]
        for extra in (self.observations, self.tides, self.depth, self.benchmark):
            if extra is not None:
                candidates.append(extra)
        return tuple(
            (src.name, src) for src in candidates if callable(getattr(src, "preflight", None))
        )


class ForecastService:
    """Assemble one spot's forecast from every source that is still standing.
    Deliberately does not score."""

    def __init__(
        self,
        sources: Sources,
        *,
        cache: GeometryCache | None = None,
        clock: Callable[[], datetime] = _now,
        observation_window: timedelta = OBSERVATION_RELEVANT,
    ):
        self._sources = sources
        self._cache = cache
        self._now = clock
        self._observation_window = observation_window
        self._health: dict[str, Reading[bool]] | None = None

    def health(self, *, refresh: bool = False) -> dict[str, Reading[bool]]:
        """Preflight every source, cached for the life of the service instance.
        `refresh=True` is for `surf sources`, which is explicitly asking again."""
        if self._health is not None and not refresh:
            return self._health
        health: dict[str, Reading[bool]] = {}
        for name, src in self._sources.preflightable():
            try:
                health[name] = src.preflight()
            except Exception as exc:
                health[name] = Reading(False, name, _status_for(exc), self._now(), note=_why(exc))
        self._health = health
        return health

    def live_sources(self) -> tuple[str, ...]:
        """Names that passed preflight, i.e. what the fanout will actually call."""
        return tuple(name for name, r in self.health().items() if r.ok and r.value)

    def outlook(self, spot: Spot, window: Window) -> SpotForecast:
        """The whole picture for one spot: models, buoy, tide, slope. Every step
        is fenced, so no source's failure can reach another."""
        readings: list[Reading[Any]] = []
        notes: list[str] = []

        forecasts = self._models(spot, window, readings)
        observed = self._observation(spot, readings)
        tides = self._tides(spot, window, readings, notes)
        slope, slope_basis = self._slope(spot, readings, notes)
        benchmark = self._benchmark(spot, window, readings)

        hours = self._assemble(forecasts, window, observed, tides)
        if not self._sources.forecast:
            notes.append("no forecast source configured")
        elif not forecasts:
            notes.append("no model answered — every forecast source failed or was skipped")
        elif len(hours) < window.hours:
            notes.append(
                f"window short: asked {window.hours} h, got {len(hours)} h "
                "(model horizon or hourly cap)"
            )

        model_only = not any(h.observation_led for h in hours)
        if model_only:
            notes.append(_model_only_note(spot, observed))

        return SpotForecast(
            spot=spot,
            window=window,
            hours=hours,
            readings=tuple(readings),
            slope=slope,
            slope_basis=slope_basis,
            model_only=model_only,
            benchmark=benchmark,
            notes=tuple(notes),
            fetched_at=self._now(),
        )

    def _gather(self, health_key: str, label: str, call: Callable[[], Reading[Any]]) -> Reading[Any]:
        """Call one source. Never raises. A source that failed its health check
        is not called at all, and the Reading says preflight was the reason."""
        pre = self.health().get(health_key)
        if pre is not None and not (pre.ok and pre.value):
            status: Status = pre.status if pre.status in ("failed", "skipped") else "failed"
            return Reading(
                None, label, status, self._now(),
                note=f"not called: preflight {pre.status}" + (f" ({pre.note})" if pre.note else ""),
            )
        try:
            reading = call()
        except Exception as exc:
            return Reading(None, label, _status_for(exc), self._now(), note=_why(exc))
        if reading is None:  # a source returning nothing is broken, not a forecast
            return Reading(None, label, "failed", self._now(), note="source returned no Reading")
        return reading

    def _models(
        self, spot: Spot, window: Window, readings: list[Reading[Any]]
    ) -> list[Forecast]:
        live: list[Forecast] = []
        for src in self._sources.forecast:
            reading = self._gather(src.name, src.name, lambda s=src: s.partitions(spot, window))
            readings.append(reading)
            if reading.ok and reading.value is not None:
                live.append(reading.value)
        return live

    def _observation(self, spot: Spot, readings: list[Reading[Any]]) -> WaveField | None:
        """The newest report from the first buoy that answers. Later buoys are
        tried only when earlier ones fail, and every attempt is recorded."""
        obs = self._sources.observations
        if obs is None or not spot.buoys:
            return None
        for buoy in spot.buoys:
            reading = self._gather(obs.name, f"{obs.name}/{buoy}", lambda b=buoy: obs.latest(b))
            readings.append(reading)
            if reading.ok and reading.value is not None:
                return reading.value
        return None

    def _tides(
        self, spot: Spot, window: Window, readings: list[Reading[Any]], notes: list[str]
    ) -> list[TidePoint]:
        tides = self._sources.tides
        if tides is None:
            notes.append("no tide source configured")
            return []
        points: list[TidePoint] = []
        for day in _days(window):
            reading = self._gather(
                tides.name, f"{tides.name}/{day.isoformat()}", lambda d=day: tides.curve(spot, d)
            )
            readings.append(reading)
            if reading.ok and reading.value:
                points.extend(reading.value)
        return points

    def _slope(
        self, spot: Spot, readings: list[Reading[Any]], notes: list[str]
    ) -> tuple[Derived | None, str]:
        # Returning None hands scoring its steepness fallback; geometry is
        # cached, never guessed.
        depth = self._sources.depth
        if depth is None:
            return None, "no bathymetry source configured; scoring falls back to steepness"
        reading = self._gather(
            getattr(depth, "name", "bathymetry"),
            f"geometry:{getattr(depth, 'name', 'bathymetry')}",
            lambda: beach_slope(spot, depth, cache=self._cache),
        )
        readings.append(reading)
        slope = reading.value
        if slope is None:
            notes.append("beach slope unavailable; scoring falls back to steepness")
            return None, reading.note or "no slope"
        derived = slope.as_derived()
        if derived is None:
            return None, slope.basis
        return derived, slope.basis

    def _benchmark(
        self, spot: Spot, window: Window, readings: list[Reading[Any]]
    ) -> Forecast | None:
        """Surfline, when someone opted in. A second opinion, never an input."""
        bench = self._sources.benchmark
        if bench is None:
            return None
        reading = self._gather(bench.name, bench.name, lambda: bench.partitions(spot, window))
        readings.append(reading)
        return reading.value if reading.ok else None

    def _assemble(
        self,
        forecasts: Sequence[Forecast],
        window: Window,
        observed: WaveField | None,
        tides: Sequence[TidePoint],
    ) -> tuple[Hour, ...]:
        start, end = _bounds(window)
        buckets: dict[datetime, list[WaveField]] = {}
        for forecast in forecasts:
            for wave in forecast.hours:
                at = _utc(wave.time)
                if not start <= at < end:
                    continue
                buckets.setdefault(at, []).append(
                    wave if wave.model else replace(wave, model=forecast.model)
                )

        hours: list[Hour] = []
        for at in sorted(buckets):
            fields = tuple(sorted(buckets[at], key=lambda w: w.model))
            hours.append(
                Hour(
                    at=at,
                    fields=fields,
                    observed=self._relevant(observed, at),
                    tide=_tide_at(tides, at),
                )
            )
        return tuple(hours)

    def _relevant(self, observed: WaveField | None, at: datetime) -> WaveField | None:
        # A buoy report only speaks for the hours around its own timestamp.
        if observed is None:
            return None
        if abs(at - _utc(observed.time)) <= self._observation_window:
            return observed
        return None


def _model_only_note(spot: Spot, observed: WaveField | None) -> str:
    # Three situations read as "model-only" downstream; only the first is
    # permanent, and the call is allowed to say which one it is.
    if not spot.has_observations:
        return MODEL_ONLY_NOTE
    if observed is None:
        return "model-only: no buoy for this spot answered"
    return (
        "model-only: the newest buoy report "
        f"({observed.time:%Y-%m-%d %H:%M}Z) is outside every hour asked for"
    )


def _bounds(window: Window) -> tuple[datetime, datetime]:
    start = _utc(window.start)
    return start, start + timedelta(hours=window.hours)


def _days(window: Window) -> tuple[date, ...]:
    """Every UTC day the window touches — tides are fetched per day."""
    start, end = _bounds(window)
    days: list[date] = []
    cursor = start.date()
    last = (end - timedelta(seconds=1)).date()
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return tuple(days)


def _tide_at(points: Sequence[TidePoint], at: datetime) -> TidePoint | None:
    nearest = None
    best = TIDE_TOLERANCE
    for point in points:
        gap = abs(_utc(point.time) - at)
        if gap <= best:
            nearest, best = point, gap
    return nearest
