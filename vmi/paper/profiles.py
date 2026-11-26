"""Sector / country / category of portfolio holdings for the Breakdown card.

Sector and category come from the cached compact analysis (the same cache as the watchlist metric columns); the country from
the NASDAQ screener list (cached daily). A holding whose analysis fails keeps the screener's sector, else "Unknown"."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from vmi.data import universe

log = logging.getLogger("vmi.paper")


def profiles(symbols: list[str], workers: int = 4) -> dict[str, dict]:
    from vmi.watchlist.metrics import compact_cached
    try:
        screener = {r["symbol"]: r for r in universe.us_market()}
    except Exception as exc:
        log.info("country list unavailable: %s", exc)
        screener = {}

    def one(sym: str) -> tuple[str, dict]:
        row = {}
        try:
            row = compact_cached(sym)
        except Exception as exc:
            log.info("profile %s: analysis failed: %s", sym, exc)
        s = screener.get(sym, {})
        return sym, {"sector": row.get("sector") or s.get("sector"), "category": row.get("category"),
                     "country": s.get("country")}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(ex.map(one, symbols))
