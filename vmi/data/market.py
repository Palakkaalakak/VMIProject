"""Market data facade: quotes + OHLCV history. IB first (when connected), Yahoo fallback.

All callers use this module — never ib.py / yfinance directly — so providers can be swapped.
"""
from __future__ import annotations

import logging
import time

import pandas as pd

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.ib import gateway
from vmi.data import market_hours
from vmi.data.models import Quote

log = logging.getLogger("vmi.market")


def _yf_symbol(sym: str) -> str:
    return sym.upper().replace(".", "-")


def history(symbol: str, period: str = "10y", interval: str = "1d") -> pd.DataFrame:
    """Daily OHLCV (adjusted for splits; NOT dividend-adjusted — per Lesson 6 §4.7 single-stock view)."""
    key = f"hist:{symbol.upper()}:{period}:{interval}"
    ttl = get_settings().ttl_history

    def fetch():
        gw = gateway()
        if gw.connected and interval == "1d":
            try:
                dur = {"10y": "10 Y", "5y": "5 Y", "2y": "2 Y", "1y": "1 Y"}.get(period, "10 Y")
                rows = gw.history(symbol, dur, "1 day")
                if rows:
                    return rows
            except Exception as exc:
                log.debug("IB history failed for %s: %s", symbol, exc)
        import yfinance as yf

        df = yf.Ticker(_yf_symbol(symbol)).history(period=period, interval=interval, auto_adjust=False,
                                                   actions=False)
        if df is None or df.empty:
            return []
        df = df.reset_index()
        dcol = "Date" if "Date" in df.columns else df.columns[0]
        return [{"date": str(r[dcol])[:10], "open": float(r["Open"]), "high": float(r["High"]),
                 "low": float(r["Low"]), "close": float(r["Close"]), "volume": float(r["Volume"])}
                for _, r in df.iterrows()]

    rows = get_cache().get_or_set(key, ttl, fetch) or []
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def bulk_history(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    """Batch download (yfinance threads) for the scanner's technical pass. Cached per symbol."""
    cache = get_cache()
    ttl = get_settings().ttl_history
    out: dict[str, pd.DataFrame] = {}
    missing = []
    for s in symbols:
        rows = cache.get(f"hist:{s.upper()}:{period}:1d", ttl)
        if rows:
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            out[s] = df.set_index("date").sort_index()
        else:
            missing.append(s)
    if missing:
        import yfinance as yf

        for i in range(0, len(missing), 100):
            chunk = missing[i:i + 100]
            try:
                data = yf.download([_yf_symbol(s) for s in chunk], period=period, interval="1d",
                                   group_by="ticker", auto_adjust=False, threads=True, progress=False)
            except Exception as exc:
                log.warning("bulk download failed: %s", exc)
                continue
            for s in chunk:
                ys = _yf_symbol(s)
                try:
                    sub = data[ys] if len(chunk) > 1 else data
                    sub = sub.dropna(how="all")
                    if sub.empty:
                        continue
                    rows = [{"date": str(idx)[:10], "open": float(r["Open"]), "high": float(r["High"]),
                             "low": float(r["Low"]), "close": float(r["Close"]),
                             "volume": float(r["Volume"]) if r["Volume"] == r["Volume"] else 0.0}
                            for idx, r in sub.iterrows() if r["Close"] == r["Close"]]
                    cache.set(f"hist:{s.upper()}:{period}:1d", rows)
                    df = pd.DataFrame(rows)
                    df["date"] = pd.to_datetime(df["date"])
                    out[s] = df.set_index("date").sort_index()
                except Exception:
                    continue
    return out


def quote(symbol: str) -> Quote:
    symbol = symbol.upper()
    cache = get_cache()
    key = f"quote:{symbol}"
    cached = cache.get(key, get_settings().ttl_quote)
    if cached:
        cached.pop("mid", None)
        return Quote(**cached)
    q: Quote | None = None
    gw = gateway()
    if gw.connected:
        try:
            q = gw.quote(symbol)
            if not (q.last or q.bid or q.close):
                q = None
        except Exception as exc:
            log.debug("IB quote failed %s: %s", symbol, exc)
    if q is None:
        q = _yahoo_quote(symbol)
    cache.set(key, q.to_dict())
    return q


def _yahoo_quote(symbol: str) -> Quote:
    import yfinance as yf

    t = yf.Ticker(_yf_symbol(symbol))
    last = bid = ask = close = vol = avgv = state = None
    try:
        fi = t.fast_info
        last = float(fi["lastPrice"]) if fi.get("lastPrice") else None
        close = float(fi["previousClose"]) if fi.get("previousClose") else None
        avgv = float(fi["threeMonthAverageVolume"]) if fi.get("threeMonthAverageVolume") else None
        vol = float(fi["lastVolume"]) if fi.get("lastVolume") else None
    except Exception:
        pass
    try:
        info = t.info or {}
        bid = info.get("bid") or None
        ask = info.get("ask") or None
        state = info.get("marketState")
        last = last or info.get("regularMarketPrice") or info.get("currentPrice")
        avgv = avgv or info.get("averageVolume")
    except Exception:
        pass
    return Quote(symbol=symbol, last=last, bid=bid, ask=ask, close=close, volume=vol, avg_volume=avgv,
                 ts=time.time(), source="yahoo", session=market_hours.session_from_provider(state))


def last_price(symbol: str) -> float | None:
    q = quote(symbol)
    return q.mid or q.last or q.close
