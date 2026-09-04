"""The session-derived ceiling for conditions a surfer has demonstrated."""

from __future__ import annotations

from dataclasses import dataclass

from .bands import NEARSHORE_STEP_M


# One nearshore-Hs measurement step from the band derivation. It is deliberately
# coarse and is not a claim that the ocean changes at an artificial boundary.
SIZE_STEP_M = NEARSHORE_STEP_M


@dataclass(frozen=True)
class Reach:
    """A ratcheting, evidence-backed nearshore-Hs mark and ceiling."""

    mark_m: float | None = None
    step_m: float = SIZE_STEP_M
    status: str = "unknown"  # "ok", "degraded", or "unknown"
    sample_count: int = 0
    basis: str = ""
    dropped: tuple[str, ...] = ()

    @classmethod
    def unknown(cls, note: str = "no cached rated session conditions") -> "Reach":
        return cls(status="unknown", basis=note)

    @property
    def maximum_m(self) -> float | None:
        """Alias that makes the ratchet's maximum explicit to callers."""
        return self.mark_m

    @property
    def ceiling_m(self) -> float | None:
        if self.mark_m is None or self.status != "ok":
            return None
        return self.mark_m + self.step_m

    def accepts(self, nearshore_m: float | None) -> bool:
        """Whether a forecast is inside the ceiling; unknown data is not guessed."""
        ceiling = self.ceiling_m
        if ceiling is None:
            return True
        return nearshore_m is not None and nearshore_m <= ceiling + 1e-9

    def render(self) -> str:
        if self.mark_m is None:
            detail = self.basis or "no qualifying session conditions"
            if self.dropped:
                detail += "; dropped " + ", ".join(self.dropped)
            return f"{self.status} — {detail}"
        ceiling = self.mark_m + self.step_m
        text = (
            f"mark {self.mark_m:.2f} m + {self.step_m:.2f} m step = "
            f"{ceiling:.2f} m nearshore Hs ({self.basis or 'cached rated sessions'}; "
            f"n={self.sample_count}; {self.status})"
        )
        if self.dropped:
            text += "; dropped " + ", ".join(self.dropped)
        if self.status != "ok":
            text += "; no ceiling enforced while qualifying evidence is incomplete"
        return text


def reach_from_log(book, sessions=None, cache=None) -> Reach:
    """Derive REACH through the same historical recovery/cache path as calibration.

    Only David's rows rated 4 or 5 can move the mark. Missing conditions degrade
    the result instead of being treated as a small or large wave.
    """
    from .calibrate import ConditionCache, recover
    from .response import Response
    from .score import size
    from .sessions import load_sessions

    rows = tuple(sessions) if sessions is not None else load_sessions(book=book)
    qualifying = tuple(
        session for session in rows
        if session.source == "david"
        and session.rating is not None
        and session.rating >= 4
    )
    if not qualifying:
        return Reach.unknown("no David session rated 4 or 5")

    recovered = recover(rows, book=book, cache=cache or ConditionCache())
    candidates: list[float] = []
    missing = 0
    seen = 0
    for item in recovered:
        if item.session.source != "david" or item.rating is None or item.rating < 4:
            continue
        seen += 1
        if item.field is None:
            missing += 1
            continue
        nearshore = size(item.field, Response.for_spot(item.spot)).raw
        if nearshore is not None and nearshore > 0:
            candidates.append(nearshore)
        else:
            missing += 1

    missing += len(qualifying) - seen
    if not candidates:
        return Reach(
            status="degraded",
            basis="rated 4/5 sessions have no cached conditions",
            dropped=(f"{missing} qualifying session(s) missing conditions",),
        )

    status = "degraded" if missing or len(candidates) < len(qualifying) else "ok"
    dropped = (f"{missing} qualifying session(s) missing conditions",) if missing else ()
    return Reach(
        mark_m=max(candidates),
        status=status,
        sample_count=len(candidates),
        basis="largest cached nearshore Hs from sessions rated 4 or 5",
        dropped=dropped,
    )
