"""S&P 500 heatmap data: one tile per constituent with its market cap (tile area) and every colour metric.

`build_tiles` is pure (rows in, tiles out, no network). `get_heatmap` assembles the live data - constituents, market caps,
daily history, the latest saved scan's intrinsic values - and caches the result 15 minutes; the metric only picks the colour value.
Tile metrics are fractions (0.012 = +1.2 %). Missing -> None (the tile is drawn grey).
"""
from __future__ import annotations

import logging

import pandas as pd

from vmi.data import market, universe
from vmi.data.cache import get_cache

log = logging.getLogger("vmi.heatmap")
METRICS = ("change_1d", "change_1m", "ytd", "price_vs_iv")
TTL = 15 * 60
MONTH_ROWS = 21            # trading days in about a month


def price_changes(df: pd.DataFrame | None) -> dict:
    """{price, as_of, change_1d, change_1m, ytd} from a daily close series (all None without enough rows)."""
    none = {"price": None, "as_of": None, "change_1d": None, "change_1m": None, "ytd": None}
    if df is None or df.empty or "close" not in df:
        return none
    close = df["close"].dropna()
    if close.empty:
        return none
    last, last_day = float(close.iloc[-1]), close.index[-1]
    ratio = lambda base: (last / float(base) - 1) if base and base == base else None  # noqa: E731
    prior = close[close.index.year < last_day.year]            # YTD: from the last close of the previous year
    return {"price": last, "as_of": str(last_day)[:10],
            "change_1d": ratio(close.iloc[-2]) if len(close) >= 2 else None,
            "change_1m": ratio(close.iloc[-1 - MONTH_ROWS]) if len(close) > MONTH_ROWS else None,
            "ytd": ratio(prior.iloc[-1]) if len(prior) else None}


def build_tiles(constituents: list[dict], caps: dict[str, float], histories: dict[str, pd.DataFrame], ivs: dict[str, float]) -> list[dict]:
    """Tiles for the stocks with a market cap (no cap = no area, so no tile). `ivs`: symbol -> latest scan intrinsic value."""
    tiles = []
    for c in constituents:
        sym = c["symbol"]
        cap = caps.get(sym)
        if not cap or cap <= 0:
            continue
        ch = price_changes(histories.get(sym))
        iv = ivs.get(sym)
        tiles.append({"symbol": sym, "name": c.get("name", ""), "sector": c.get("sector") or "Other", "market_cap": cap,
                      **ch, "intrinsic_value": iv,
                      "price_vs_iv": (ch["price"] - iv) / iv if iv and ch["price"] else None})   # -20% = price 20% below IV (undervalued)
    return tiles


def _latest_scan_ivs() -> tuple[dict[str, float], int | None]:
    from vmi.scanner import funnel
    try:
        res = funnel.latest_results()
    except Exception as exc:
        log.info("no scan results: %s", exc)
        return {}, None
    return {r["symbol"]: r["intrinsic_value"] for r in res.get("results", []) if r.get("intrinsic_value")}, res.get("run_id")


def get_heatmap(metric: str) -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")

    def assemble():
        try:
            members = universe.sp500()
        except Exception as exc:
            raise RuntimeError(f"The S&P 500 list could not be loaded ({exc}).") from exc
        symbols = [m["symbol"] for m in members]
        hist = market.bulk_history(symbols, "2y")
        if not hist:
            raise RuntimeError("Prices could not be downloaded (Yahoo is not answering). Try again in a few minutes.")
        try:
            caps = {r["symbol"]: r["market_cap"] for r in universe.us_market()}
        except Exception as exc:
            raise RuntimeError(f"Market caps could not be loaded ({exc}).") from exc
        ivs, run_id = _latest_scan_ivs()
        tiles = build_tiles(members, caps, hist, ivs)
        if not tiles:
            raise RuntimeError("No S&P 500 stock has both a price and a market cap right now.")
        return {"tiles": tiles, "n_members": len(members), "n_priced": sum(1 for t in tiles if t["price"] is not None),
                "n_iv": sum(1 for t in tiles if t["intrinsic_value"]), "scan_run_id": run_id}

    data = get_cache().get_or_set("heatmap:sp500", TTL, assemble)
    return {"metric": metric, **data, "tiles": [{**t, "value": t.get(metric)} for t in data["tiles"]]}
