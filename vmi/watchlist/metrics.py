"""Metric columns for a watchlist: the compact analysis (`funnel.compact`) of each symbol, cached 6 hours in the data cache,
fetched with a small thread pool. A symbol that fails gets nulls and an `error` string; it never fails the whole call.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from vmi import store
from vmi.data.cache import get_cache
from vmi.rules import RULES
from vmi.scanner import funnel
from vmi.watchlist import flags, service

TTL = 6 * 3600
FIELDS = ("growth", "roe", "roic", "net_margin", "margin_of_safety", "peg", "pe", "dividend_yield", "steps_passed", "moat",
          "market_cap", "beta", "sector", "category", "name")


def compact_cached(symbol: str) -> dict:
    """Compact analysis row of one symbol (raises when the analysis fails). Cached; shared with the portfolio breakdown."""
    sym = symbol.upper()

    def fetch():
        from vmi.analysis.pipeline import analyse_ticker
        rep = analyse_ticker(sym, with_technicals=False, overrides=store.get_override(sym))
        return funnel.compact(rep)

    return get_cache().get_or_set(f"wlcompact:{sym}", TTL, fetch)


def _row(symbol: str) -> dict:
    try:
        row = compact_cached(symbol)
        return {"symbol": symbol, **{k: row.get(k) for k in FIELDS}, "flags": flags.flags_for(row, RULES), "error": None}
    except Exception as exc:
        return {"symbol": symbol, **{k: None for k in FIELDS}, "flags": {}, "error": f"{type(exc).__name__}: {exc}"[:200]}


def watchlist_metrics(wid: int, workers: int = 4) -> dict:
    w = service.get(wid)                                   # ValueError when the list does not exist
    symbols = sorted({i["symbol"] for i in w["items"] if i.get("stage") != "review"})
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_row, symbols))
    items = {i["symbol"]: i for i in w["items"]}
    for r in rows:        # distance to the next buy level lives on the watchlist item, not in the analysis
        d = items[r["symbol"]].get("distance_to_level")
        r["distance_to_level"] = d
        if (c := flags.flag("distance_to_level", d, RULES)):
            r["flags"]["distance_to_level"] = c
    return {"id": wid, "metrics": {r["symbol"]: r for r in rows}, "rules": {
        "min_roe": RULES.profitability.min_roe, "excellent_roe": RULES.profitability.excellent_roe,
        "peg_attractive": RULES.valuation.peg_attractive, "peg_screen": RULES.valuation.peg_screen,
        "growth_threshold": RULES.growth.growth_stock_threshold, "min_yield": RULES.dividend.min_yield,
        "screen_yield": RULES.dividend.us_min_yield_screen, "near_level_pct": RULES.technical.near_level_pct}}
