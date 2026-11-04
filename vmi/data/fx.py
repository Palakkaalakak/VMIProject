"""FX conversion for foreign filers / ADRs (Lesson 5 §6.1: statement currency vs share-price currency).

Rates come from IB (when connected, CASH contracts) or Yahoo ("DKKUSD=X"), cached for 12h.
"""
from __future__ import annotations

from vmi.data.cache import get_cache


def rate(from_ccy: str, to_ccy: str = "USD") -> float:
    """Units of `to_ccy` per 1 unit of `from_ccy`. Returns 1.0 for same currency."""
    f, t = (from_ccy or "USD").upper(), (to_ccy or "USD").upper()
    if f == t:
        return 1.0

    def fetch():
        import yfinance as yf

        px = yf.Ticker(f"{f}{t}=X").fast_info.get("lastPrice")
        if not px:
            inv = yf.Ticker(f"{t}{f}=X").fast_info.get("lastPrice")
            px = 1.0 / inv if inv else None
        if not px:
            raise RuntimeError(f"no FX rate {f}->{t}")
        return float(px)

    return float(get_cache().get_or_set(f"fx:{f}{t}", 12 * 3600, fetch))
