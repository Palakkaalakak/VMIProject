"""US equity trading-session helper (NYSE/Nasdaq regular hours 09:30–16:00 America/New_York, Mon–Fri).

Exchange holidays are not modelled; providers that report their own session (Yahoo `marketState`) take
precedence via `session_from_provider`.
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
REGULAR = "regular"
EXTENDED = "extended"     # pre-market 04:00–09:30 or after-hours 16:00–20:00
CLOSED = "closed"

_YAHOO = {"REGULAR": REGULAR, "PRE": EXTENDED, "POST": EXTENDED, "PREPRE": CLOSED, "POSTPOST": CLOSED,
          "CLOSED": CLOSED}


def session_now(now: datetime | None = None) -> str:
    t = (now or datetime.now(ET)).astimezone(ET)
    if t.weekday() >= 5:
        return CLOSED
    hm = t.time()
    if dtime(9, 30) <= hm < dtime(16, 0):
        return REGULAR
    if dtime(4, 0) <= hm < dtime(20, 0):
        return EXTENDED
    return CLOSED


def session_from_provider(state: str | None) -> str:
    """Map a provider's market-state string; fall back to the clock."""
    return _YAHOO.get((state or "").upper()) or session_now()
