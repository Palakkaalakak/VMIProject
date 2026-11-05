"""Circuit breakers for optional data sources: after a refusal, skip that source for a while.

    TWS = Breaker("ib_tws", seconds=6 * 3600)
    if TWS.ready:
        try: ...call the source...
        except SomeRefusal as exc: TWS.trip(str(exc))

A scan of thousands of tickers then pays for a failing source once, not once per ticker.
`statuses()` reports every breaker (shown by /api/health).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("vmi.breaker")

_REGISTRY: dict[str, "Breaker"] = {}


class Breaker:
    def __init__(self, name: str, seconds: float = 6 * 3600):
        self.name = name
        self.seconds = seconds
        self.last_error = ""
        self._until = 0.0
        _REGISTRY[name] = self

    @property
    def ready(self) -> bool:
        """True when calls are allowed (never tripped, or the pause has elapsed)."""
        return time.time() >= self._until

    def trip(self, error: str) -> None:
        self._until = time.time() + self.seconds
        self.last_error = error[:300]
        log.info("%s paused for %ss: %s", self.name, int(self.seconds), self.last_error)

    def reset(self) -> None:
        self._until, self.last_error = 0.0, ""

    def status(self) -> dict:
        return {"available": self.ready, "retry_in_s": max(0, int(self._until - time.time())),
                "last_error": self.last_error}


def statuses() -> dict[str, dict]:
    return {name: b.status() for name, b in _REGISTRY.items()}
