from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Generic, Literal, Protocol, TypeVar

import httpx

from .spots import Spot
from .waves import Forecast, TidePoint, WaveField

T = TypeVar("T")

Status = Literal["ok", "degraded", "failed", "skipped"]


@dataclass(frozen=True)
class Reading(Generic[T]):
    """A source value with its status: ok, degraded (see `dropped`), failed
    (value is None, caller carries on), or skipped (never called)."""

    value: T | None
    source: str
    status: Status
    fetched_at: datetime
    model_run: str | None = None
    confidence: float | None = None
    note: str = ""
    dropped: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "degraded") and self.value is not None

    def label(self) -> str:
        bits = [f"{self.source}:{self.status}"]
        if self.model_run:
            bits.append(f"run={self.model_run}")
        if self.dropped:
            bits.append("dropped=" + ",".join(self.dropped))
        if self.note:
            bits.append(self.note)
        return " ".join(bits)


@dataclass(frozen=True)
class Window:
    start: datetime
    hours: int


class ForecastSource(Protocol):
    name: str
    def preflight(self) -> Reading[bool]: ...
    def partitions(self, spot: Spot, window: Window) -> Reading[Forecast]: ...


class Observations(Protocol):
    name: str
    def preflight(self) -> Reading[bool]: ...
    def latest(self, buoy_id: str) -> Reading[WaveField]: ...


class Tides(Protocol):
    name: str
    def preflight(self) -> Reading[bool]: ...
    def curve(self, spot: Spot, day: date) -> Reading[tuple[TidePoint, ...]]: ...


class Bathymetry(Protocol):
    name: str
    def preflight(self) -> Reading[bool]: ...
    def profile(self, spot: Spot, bearing_deg: float) -> Reading[tuple[float, ...]]: ...


class Archive(Protocol):
    """Past conditions for any date, anywhere, back to 1940."""

    name: str
    def preflight(self) -> Reading[bool]: ...
    def conditions(self, spot: Spot, on: date, hour: int) -> Reading[WaveField]: ...

USER_AGENT = "surf/0.1 (https://github.com/VortiMedia/surf)"
DEFAULT_TIMEOUT = 20.0


def now() -> datetime:
    return datetime.now(timezone.utc)


class SourceDown(Exception):
    """Breaker is open. Callers turn this into a skipped Reading."""


class BadPayload(Exception):
    """HTTP 200 whose body is not what it claims to be.

    Open-Meteo sheds load by answering 200 with the plain text
    `Unexpected error while streaming data: timeoutReached`, so
    `raise_for_status()` passes and `.json()` fails instead.
    """


@dataclass
class Breaker:
    """Open after `threshold` consecutive failures; retry after `cooldown` seconds."""

    name: str
    threshold: int = 3
    cooldown: float = 300.0
    failures: int = 0
    opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self.opened_at is None:
                return False
            if (time.monotonic() - self.opened_at) > self.cooldown:
                self.opened_at = None
                self.failures = 0
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold and self.opened_at is None:
                self.opened_at = time.monotonic()


class Http:
    """A shared client with one breaker per source name."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._breakers: dict[str, Breaker] = {}

    def breaker(self, source: str) -> Breaker:
        return self._breakers.setdefault(source, Breaker(source))

    def get(self, source: str, url: str, params: dict | None = None) -> httpx.Response:
        b = self.breaker(source)
        if b.is_open:
            raise SourceDown(f"{source}: breaker open after {b.failures} failures")
        try:
            r = self._client.get(url, params=params)
            r.raise_for_status()
        except Exception:
            b.record_failure()
            raise
        b.record_success()
        return r

    def get_json(self, source: str, url: str, params: dict | None = None) -> Any:
        """`get`, but the body must parse as JSON."""
        # One retry only: a lying 200 is load-shedding and usually clears at once,
        # while repeated retries against a dead source are the breaker's job.
        last = ""
        for attempt in (1, 2):
            response = self.get(source, url, params)
            try:
                return response.json()
            except ValueError:
                last = response.text.strip().splitlines()[0][:120] if response.text else "empty body"
                self.breaker(source).record_failure()
                if attempt == 2:
                    raise BadPayload(f"HTTP 200 but body was not JSON: {last!r}") from None
        raise BadPayload(last)

    def close(self) -> None:
        self._client.close()


def explain(exc: BaseException) -> str:
    """One short line for a `Reading.note`; httpx's own messages run to three
    lines with a URL and an MDN link."""
    if isinstance(exc, BadPayload):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} from {exc.request.url.path}"
    if isinstance(exc, httpx.TimeoutException):
        return f"timeout after {DEFAULT_TIMEOUT:.0f}s"
    if isinstance(exc, httpx.TransportError):
        return f"unreachable ({type(exc).__name__})"
    text = str(exc).strip().splitlines()
    head = text[0] if text else type(exc).__name__
    return head[:120]
