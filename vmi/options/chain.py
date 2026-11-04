"""Option chains for CSP / CC work (Lesson 12) — fast and stable.

Design (owner requirement: load in < ~40 s, consistently reliable, data must not "disappear"):
  * Source order: IB (streaming, greeks via model ticks) → Yahoo (yfinance option_chain) fallback.
  * Strike window: only strikes within ±`width` of spot are requested (CSP/CC live there), which keeps IB
    market-data lines under the ~100-line cap and makes the first paint fast.
  * Last-good merge: every refresh is merged into the previous snapshot per contract — if a field comes back
    empty (IB tick not yet arrived, Yahoo hiccup) the last good value is kept and marked `stale`, so rows
    never blank out in the UI.
  * Greeks: taken from IB when present, otherwise computed locally with Black-Scholes from the IV.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict
from datetime import date, datetime

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.ib import gateway
from vmi.data.models import OptionQuote

log = logging.getLogger("vmi.options")
_lock = threading.Lock()
_snapshots: dict[str, dict[str, dict]] = {}   # chain key -> contract key -> last good row
RISK_FREE = 0.04


def _ck(symbol: str, expiry: str) -> str:
    return f"{symbol.upper()}:{expiry}"


def _contract_key(strike: float, right: str) -> str:
    return f"{strike:g}{right}"


def _yf(sym: str) -> str:
    return sym.upper().replace(".", "-")


# ------------------------------------------------------------------------------------- Black-Scholes
def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_greeks(spot: float, strike: float, t_years: float, iv: float, right: str, r: float = RISK_FREE) -> dict:
    if not spot or not strike or not iv or iv <= 0 or t_years <= 0:
        return {}
    st = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / st
    d2 = d1 - st
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    if right == "C":
        delta = _ncdf(d1)
        theta = (-spot * pdf * iv / (2 * math.sqrt(t_years)) - r * strike * math.exp(-r * t_years) * _ncdf(d2)) / 365
        p_itm = _ncdf(d2)
    else:
        delta = _ncdf(d1) - 1
        theta = (-spot * pdf * iv / (2 * math.sqrt(t_years)) + r * strike * math.exp(-r * t_years) * _ncdf(-d2)) / 365
        p_itm = _ncdf(-d2)
    return {"delta": delta, "gamma": pdf / (spot * st), "theta": theta, "vega": spot * pdf * math.sqrt(t_years) / 100,
            "prob_itm": p_itm}


def _years_to(expiry: str) -> float:
    d = datetime.strptime(expiry, "%Y%m%d").date()
    return max((d - date.today()).days, 0) / 365 + 1 / 365


# ------------------------------------------------------------------------------------- expirations
def expirations(symbol: str) -> list[str]:
    def fetch():
        gw = gateway()
        if gw.connected:
            try:
                p = gw.option_params(symbol)
                if p.get("expirations"):
                    return p["expirations"]
            except Exception as exc:
                log.debug("IB option params failed %s: %s", symbol, exc)
        import yfinance as yf
        return [e.replace("-", "") for e in yf.Ticker(_yf(symbol)).options]

    return get_cache().get_or_set(f"opt:exp:{symbol.upper()}", 6 * 3600, fetch) or []


# ------------------------------------------------------------------------------------- chain
def _from_ib(symbol: str, expiry: str, spot: float, width: float) -> list[OptionQuote]:
    gw = gateway()
    params = gw.option_params(symbol)
    strikes = [k for k in params.get("strikes", []) if spot * (1 - width) <= k <= spot * (1 + width)]
    if len(strikes) > 40:  # keep IB line usage bounded: the 40 strikes closest to spot
        strikes = sorted(sorted(strikes, key=lambda k: abs(k - spot))[:40])
    return gw.option_chain(symbol, expiry, strikes)


def _from_yahoo(symbol: str, expiry: str, spot: float, width: float) -> list[OptionQuote]:
    import yfinance as yf

    exp_dash = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
    ch = yf.Ticker(_yf(symbol)).option_chain(exp_dash)
    out = []
    for df, right in ((ch.calls, "C"), (ch.puts, "P")):
        for _, r in df.iterrows():
            k = float(r["strike"])
            if not (spot * (1 - width) <= k <= spot * (1 + width)):
                continue

            def num(col):
                v = r.get(col)
                return float(v) if v is not None and v == v else None
            out.append(OptionQuote(symbol=symbol.upper(), expiry=expiry, strike=k, right=right, bid=num("bid"),
                                   ask=num("ask"), last=num("lastPrice"), volume=num("volume"),
                                   open_interest=num("openInterest"), iv=num("impliedVolatility"), und_price=spot))
    return out


def chain(symbol: str, expiry: str | None = None, width: float = 0.30) -> dict:
    """Full chain snapshot for one expiry: {symbol, expiry, spot, source, rows:[...], expirations, ms}."""
    from vmi.data import market

    t0 = time.time()
    symbol = symbol.upper()
    exps = expirations(symbol)
    if not exps:
        raise ValueError(f"no listed options for {symbol}")
    expiry = expiry or next((e for e in exps if (datetime.strptime(e, "%Y%m%d").date() - date.today()).days >= 25), exps[0])
    spot = market.last_price(symbol) or 0.0
    rows, source = [], ""
    gw = gateway()
    if gw.connected:
        try:
            rows, source = _from_ib(symbol, expiry, spot, width), "ib"
        except Exception as exc:
            log.info("IB chain failed %s %s: %s — falling back to Yahoo", symbol, expiry, exc)
    if not rows:
        try:
            rows, source = _from_yahoo(symbol, expiry, spot, width), "yahoo"
        except Exception as exc:
            log.warning("Yahoo chain failed %s %s: %s", symbol, expiry, exc)
    merged = _merge(symbol, expiry, rows, spot)
    return {"symbol": symbol, "expiry": expiry, "spot": spot, "source": source or "cache",
            "expirations": exps, "dte": max((datetime.strptime(expiry, "%Y%m%d").date() - date.today()).days, 0),
            "rows": merged, "ms": int((time.time() - t0) * 1000)}


def _merge(symbol: str, expiry: str, rows: list[OptionQuote], spot: float) -> list[dict]:
    """Last-good merge + derived fields (mid, greeks fallback, yields for CSP/CC)."""
    key = _ck(symbol, expiry)
    t = _years_to(expiry)
    dte = max(t * 365 - 1, 1)
    with _lock:
        snap = _snapshots.setdefault(key, {})
        fresh = set()
        for q in rows:
            ck = _contract_key(q.strike, q.right)
            fresh.add(ck)
            prev = snap.get(ck, {})
            d = q.to_dict()
            for fld in ("bid", "ask", "last", "iv", "delta", "gamma", "theta", "vega", "open_interest", "volume"):
                if d.get(fld) is None and prev.get(fld) is not None:
                    d[fld] = prev[fld]
                    d["stale"] = True
            d.setdefault("stale", False)
            d["ts"] = time.time()
            snap[ck] = d
        for ck, d in snap.items():      # contracts missing from this refresh stay visible, marked stale
            if ck not in fresh:
                d["stale"] = True
        out = []
        for d in snap.values():
            bid, ask, last = d.get("bid"), d.get("ask"), d.get("last")
            d["mid"] = (bid + ask) / 2 if bid is not None and ask and ask >= bid and ask > 0 else last
            if d.get("delta") is None and d.get("iv"):
                d.update({k: v for k, v in bs_greeks(spot, d["strike"], t, d["iv"], d["right"]).items()
                          if k != "prob_itm"})
            g = bs_greeks(spot, d["strike"], t, d.get("iv") or 0, d["right"])
            d["prob_itm"] = g.get("prob_itm")
            mid = d["mid"] or 0
            d["spread_pct"] = ((ask - bid) / mid) if bid is not None and ask and mid else None
            if d["right"] == "P":   # cash-secured put: premium / collateral (strike)
                d["yield_pct"] = mid / d["strike"] if d["strike"] else None
                d["breakeven"] = d["strike"] - mid
                d["otm_pct"] = (spot - d["strike"]) / spot if spot else None
            else:                   # covered call: premium / spot
                d["yield_pct"] = mid / spot if spot else None
                d["breakeven"] = None
                d["otm_pct"] = (d["strike"] - spot) / spot if spot else None
            d["annualized_pct"] = d["yield_pct"] * 365 / dte if d.get("yield_pct") is not None else None
            out.append(d)
    return sorted(out, key=lambda d: (d["strike"], d["right"]))


def option_quote(symbol: str, expiry: str, strike: float, right: str) -> OptionQuote | None:
    """Single-contract quote for paper fills: uses the last snapshot if fresh (<60 s), else refreshes."""
    key = _ck(symbol, expiry)
    ck = _contract_key(float(strike), right.upper())
    with _lock:
        d = _snapshots.get(key, {}).get(ck)
    if d is None or time.time() - d.get("ts", 0) > get_settings().ttl_option_chain:
        try:
            chain(symbol, expiry, width=max(0.30, abs(float(strike) / max(1e-9, _spot(symbol)) - 1) + 0.05))
        except Exception as exc:
            log.debug("chain refresh failed: %s", exc)
        with _lock:
            d = _snapshots.get(key, {}).get(ck)
    if not d:
        return None
    fields = {k: d.get(k) for k in OptionQuote.__dataclass_fields__ if k in d}
    return OptionQuote(**fields)


def _spot(symbol: str) -> float:
    from vmi.data import market
    return market.last_price(symbol) or 1.0


# ------------------------------------------------------------------------------------- VMI helpers
def suggest(symbol: str, strategy: str, expiry: str | None = None, buy_levels: list[float] | None = None,
            intrinsic_value: float | None = None) -> dict:
    """CSP: puts at/below VMI buy levels (getting assigned = buying a great company at a support level,
    below intrinsic value). CC: calls OTM, ideally above intrinsic value (you'd be happy to sell there).
    Lesson 6 §9.3: best time to write calls is a parabolic move; Adam writes CCs on defensive/moderately
    cyclical names, not on high-growth stocks."""
    c = chain(symbol, expiry)
    spot = c["spot"]
    rows = [r for r in c["rows"] if r.get("mid")]
    picks = []
    if strategy.upper() == "CSP":
        targets = [b for b in (buy_levels or []) if b < spot] or [spot * 0.95, spot * 0.90]
        for lvl in targets:
            puts = [r for r in rows if r["right"] == "P" and r["strike"] <= lvl * 1.01]
            if puts:
                best = max(puts, key=lambda r: r["strike"])
                below_iv = intrinsic_value is None or best["strike"] <= intrinsic_value
                picks.append({**best, "target_level": lvl, "below_iv": below_iv})
    else:
        floor = max(spot * 1.03, intrinsic_value or 0)
        calls = sorted([r for r in rows if r["right"] == "C" and r["strike"] >= floor], key=lambda r: r["strike"])
        picks = calls[:4]
    return {"symbol": c["symbol"], "expiry": c["expiry"], "dte": c["dte"], "spot": spot, "strategy": strategy.upper(),
            "source": c["source"], "picks": picks}
