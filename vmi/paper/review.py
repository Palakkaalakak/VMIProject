"""Trade review and what-if engine (paper portfolios). Built from the ledger (vmi/paper/ledger.py), the context stored on
each trade (vmi/paper/context.py), daily marks (vmi/paper/journal.py) and daily price history.

lots(pid)                  FIFO lots per instrument: entry/exit, holding time, P&L, entry/exit context
enrich(lots)               + path stats (MFE/MAE, give-back from peak), price 30/90/180/365 days after the exit, "if kept"
summary(pid)               statistics + behaviour flags + breakdowns (tags, category, moat, MOS at entry, origin)
what_if(pid, name, **p)    alternative histories on the same lots, each returns actual vs alternative per lot + totals:
    hold_instead | exit_over_iv(pct) | exit_tranches(levels=[[pct, fraction], …]) | stop_target(stop, target)
    | hold_days(days) | entry_all_at_once | covered_calls(otm, dte, iv) | benchmark(symbol)
equity_curve(pid)          daily equity (daily marks, else replay of the ledger on daily closes) and drawdown

Prices come from `history_fn(symbol) -> DataFrame[open, high, low, close]` (default market.history 10y) so tests and
offline studies can inject their own. What-ifs use daily closes and are approximations: they say so in their output.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from vmi.paper import ledger

HistoryFn = Callable[[str], pd.DataFrame]
AFTER_DAYS = (30, 90, 180, 365)


def _default_history(symbol: str) -> pd.DataFrame:
    from vmi.data import market
    return market.history(symbol, "10y")


def _day(ts: str | datetime) -> date:
    if isinstance(ts, datetime):
        return ts.date()
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()


@dataclass
class Lot:
    key: str
    symbol: str
    sec_type: str
    multiplier: int
    direction: str               # long | short
    qty: float
    entry_ts: str
    entry_price: float
    entry_trade_id: int | None
    entry: dict = field(default_factory=dict)     # context summary at entry
    exit_ts: str | None = None
    exit_price: float | None = None
    exit_trade_id: int | None = None
    exit: dict = field(default_factory=dict)
    fees: float = 0.0
    stats: dict = field(default_factory=dict)

    @property
    def closed(self) -> bool:
        return self.exit_ts is not None

    def pnl(self, exit_price: float | None = None) -> float | None:
        px = self.exit_price if exit_price is None else exit_price
        if px is None:
            return None
        sign = 1 if self.direction == "long" else -1
        return sign * (px - self.entry_price) * self.qty * self.multiplier


def _ctx_summary(row: dict) -> dict:
    """The parts of a trade's context reviews group and filter by."""
    c = row.get("context") or {}
    a = c.get("analysis") or {}
    steps = a.get("steps") or []
    plan = c.get("plan") or {}
    return {"trade_id": row.get("id"), "ts": str(row.get("ts")), "price": row.get("price"),
            "source": row.get("source"), "kind": row.get("kind"), "tags": [t for t in (row.get("tags") or "").split(",") if t],
            "thesis": row.get("thesis") or "", "note": row.get("note") or "",
            "intrinsic_value": a.get("intrinsic_value"), "conservative_value": (a.get("valuation") or {}).get("conservative_value"),
            "method": (a.get("valuation") or {}).get("selected"),
            "margin_of_safety": (a.get("metrics") or {}).get("margin_of_safety"),
            "steps_passed": sum(1 for s in steps if s.get("passed")) if steps else None,
            "category": a.get("category"), "moat": a.get("moat"), "style": a.get("style"),
            "trend": ((a.get("technicals") or {}).get("daily") or {}).get("state"),
            "iv_low_confidence": (a.get("iv_confidence") or {}).get("low"),
            "plan_level": plan.get("level"), "plan_id": plan.get("plan_id")}


def lots_from_rows(rows: list[dict]) -> list[Lot]:
    """FIFO matching per instrument key (works for long stock, long and short options)."""
    open_: dict[str, list[Lot]] = defaultdict(list)
    done: list[Lot] = []
    for r in ledger._order(rows):
        key, side, qty, px = r["key"], r["side"].upper(), float(r["qty"]), float(r["price"])
        mult = int(r.get("multiplier") or 1)
        fees_per = float(r.get("fees") or 0) / qty if qty else 0.0
        book = open_[key]
        opening_dir = "long" if side == "BUY" else "short"
        while qty > 1e-9 and book and book[0].direction != opening_dir:
            lot = book[0]
            take = min(qty, lot.qty)
            if take < lot.qty - 1e-9:                 # split the lot: the closed part leaves, the rest stays open
                part = Lot(**{**asdict(lot), "qty": take, "fees": lot.fees * take / lot.qty})
                lot.fees -= part.fees
                lot.qty -= take
                lot = part
            else:
                book.pop(0)
            lot.exit_ts, lot.exit_price, lot.exit_trade_id = str(r["ts"]), px, r.get("id")
            lot.exit = _ctx_summary(r)
            lot.fees += fees_per * take
            done.append(lot)
            qty -= take
        if qty > 1e-9:
            book.append(Lot(key, r["symbol"], r.get("sec_type") or "STK", mult, opening_dir, qty, str(r["ts"]), px,
                            r.get("id"), _ctx_summary(r), fees=fees_per * qty))
    return done + [l for b in open_.values() for l in b]


def lots(pid: int) -> list[Lot]:
    from vmi import store
    with store.session() as s:
        rows = ledger._rows(s, pid)
    return lots_from_rows(rows)


# ---------------------------------------------------------------------------------------------- prices
class Prices:
    """Memoised daily bars per symbol (index: date)."""

    def __init__(self, history_fn: HistoryFn | None = None):
        self.fn = history_fn or _default_history
        self.cache: dict[str, pd.DataFrame | None] = {}

    def __call__(self, symbol: str) -> pd.DataFrame | None:
        if symbol not in self.cache:
            try:
                df = self.fn(symbol)
                if df is None or df.empty:
                    df = None
                else:
                    df = df.copy()
                    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                    df = df[~df.index.duplicated(keep="last")].sort_index()
            except Exception:
                df = None
            self.cache[symbol] = df
        return self.cache[symbol]

    def window(self, symbol: str, start: date, end: date | None = None) -> pd.DataFrame | None:
        df = self(symbol)
        if df is None:
            return None
        w = df.loc[pd.Timestamp(start):(pd.Timestamp(end) if end else None)]
        return w if not w.empty else None

    def close_on_or_after(self, symbol: str, d: date) -> tuple[date, float] | None:
        df = self(symbol)
        if df is None:
            return None
        w = df.loc[pd.Timestamp(d):]
        return (w.index[0].date(), float(w["close"].iloc[0])) if not w.empty else None

    def last(self, symbol: str) -> float | None:
        df = self(symbol)
        return float(df["close"].iloc[-1]) if df is not None else None


def enrich(lot_list: list[Lot], prices: Prices) -> list[Lot]:
    for lot in lot_list:
        if lot.sec_type != "STK":
            continue
        start, end = _day(lot.entry_ts), (_day(lot.exit_ts) if lot.closed else None)
        w = prices.window(lot.symbol, start, end)
        st: dict[str, Any] = {"hold_days": ((end or date.today()) - start).days}
        if w is not None:
            hi, lo = float(w["high"].max()), float(w["low"].min())
            peak = float(w["close"].max())
            st.update(mfe=hi / lot.entry_price - 1, mae=lo / lot.entry_price - 1, peak_close=peak,
                      peak_date=str(w["close"].idxmax().date()))
            ref = lot.exit_price if lot.closed else float(w["close"].iloc[-1])
            st["giveback_from_peak"] = 1 - ref / peak if peak else None
        if lot.closed:
            st["return"] = lot.exit_price / lot.entry_price - 1
            st["pnl"] = lot.pnl() - lot.fees
            for n in AFTER_DAYS:
                hit = prices.close_on_or_after(lot.symbol, end + timedelta(days=n))
                if hit and hit[0] <= date.today():
                    st[f"after_{n}d"] = hit[1] / lot.exit_price - 1
            last = prices.last(lot.symbol)
            if last:
                st["after_today"] = last / lot.exit_price - 1
                st["if_kept_extra_pnl"] = (last - lot.exit_price) * lot.qty * lot.multiplier
        else:
            last = prices.last(lot.symbol)
            if last:
                st["return"] = last / lot.entry_price - 1
                st["unrealized_pnl"] = lot.pnl(last)
        iv = lot.entry.get("intrinsic_value")
        if iv:
            st["entry_vs_iv"] = lot.entry_price / iv - 1
            if lot.closed:
                st["exit_vs_entry_iv"] = lot.exit_price / iv - 1
        if lot.closed and lot.exit.get("intrinsic_value"):
            st["exit_vs_exit_iv"] = lot.exit_price / lot.exit["intrinsic_value"] - 1
        lot.stats = st
    return lot_list


# --------------------------------------------------------------------------------------------- summary
def _mos_bucket(m):
    if m is None:
        return "unknown"
    return "<0%" if m < 0 else "0-10%" if m < 0.10 else "10-20%" if m < 0.20 else ">=20%"


def _group_stats(items: list[Lot]) -> dict:
    closed = [l for l in items if l.closed and l.stats.get("return") is not None]
    rets = [l.stats["return"] for l in closed]
    pnls = [l.stats.get("pnl") or 0.0 for l in closed]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p <= 0]
    return {"lots": len(items), "closed": len(closed), "win_rate": len(wins) / len(closed) if closed else None,
            "avg_return": sum(rets) / len(rets) if rets else None, "total_pnl": sum(pnls),
            "avg_win": sum(wins) / len(wins) if wins else None, "avg_loss": sum(losses) / len(losses) if losses else None,
            "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
            "expectancy": sum(pnls) / len(pnls) if pnls else None,
            "avg_hold_days": (sum(l.stats.get("hold_days", 0) for l in closed) / len(closed)) if closed else None}


def summary(pid: int, history_fn: HistoryFn | None = None) -> dict:
    prices = Prices(history_fn)
    ls = enrich(lots(pid), prices)
    stock = [l for l in ls if l.sec_type == "STK"]
    opts = [l for l in ls if l.sec_type == "OPT"]
    closed = [l for l in stock if l.closed]
    flags = {
        "sold_too_early": [l.key + " " + l.exit_ts[:10] for l in closed if (l.stats.get("after_90d") or 0) > 0.10],
        "sold_below_iv": [l.key + " " + l.exit_ts[:10] for l in closed if (l.stats.get("exit_vs_exit_iv") or 0) < 0],
        "bought_above_iv": [l.key + " " + l.entry_ts[:10] for l in stock if (l.stats.get("entry_vs_iv") or -1) > 0],
        "deep_drawdown_held": [l.key for l in stock if (l.stats.get("mae") or 0) < -0.30],
    }
    groups: dict[str, dict] = {}
    for name, keyf in (("tag", lambda l: l.entry.get("tags") or ["(none)"]),
                       ("category", lambda l: [l.entry.get("category") or "unknown"]),
                       ("moat", lambda l: [l.entry.get("moat") or "unknown"]),
                       ("mos_at_entry", lambda l: [_mos_bucket(l.entry.get("margin_of_safety"))]),
                       ("method", lambda l: [l.entry.get("method") or "unknown"]),
                       ("origin", lambda l: [l.entry.get("source") or "paper"]),
                       ("trend_at_entry", lambda l: [l.entry.get("trend") or "unknown"])):
        g: dict[str, list[Lot]] = defaultdict(list)
        for l in stock:
            for k in keyf(l):
                g[k].append(l)
        groups[name] = {k: _group_stats(v) for k, v in g.items()}
    with_ledger = ledger.ledger(pid)
    return {"stocks": _group_stats(stock), "options": _group_stats(opts),
            "fees": sum(float(r.get("fees") or 0) for r in with_ledger),
            "slippage": sum(float(r.get("slippage") or 0) for r in with_ledger),
            "flags": flags, "breakdowns": groups,
            "lots": [{**asdict(l), "closed": l.closed} for l in ls],
            "notes": ["Statistics use FIFO lots; returns are per lot, before fees except `pnl` (after fees)."]}


# --------------------------------------------------------------------------------------------- what-ifs
def _path(prices: Prices, lot: Lot) -> pd.DataFrame | None:
    return prices.window(lot.symbol, _day(lot.entry_ts))


def _first_cross(w: pd.DataFrame, level: float, above: bool) -> tuple[date, float] | None:
    hit = w[w["close"] >= level] if above else w[w["close"] <= level]
    return (hit.index[0].date(), float(hit["close"].iloc[0])) if not hit.empty else None


def _alt_exit_rule(prices: Prices, lot: Lot, rule: Callable[[pd.DataFrame, Lot], tuple[date, float] | None],
                   fallback: str) -> tuple[str, float | None, str]:
    w = _path(prices, lot)
    if w is None:
        return "no price history", None, ""
    hit = rule(w, lot)
    if hit:
        return f"rule exit {hit[0]}", hit[1], str(hit[0])
    if fallback == "actual" and lot.closed:
        return "no trigger: actual exit", lot.exit_price, lot.exit_ts[:10]
    return "no trigger: held to today", float(w["close"].iloc[-1]), str(w.index[-1].date())


def _compare(rows: list[dict], name: str, params: dict, notes: list[str]) -> dict:
    act = sum(r["actual_pnl"] for r in rows if r["actual_pnl"] is not None and r["alt_pnl"] is not None)
    alt = sum(r["alt_pnl"] for r in rows if r["actual_pnl"] is not None and r["alt_pnl"] is not None)
    return {"what_if": name, "params": params, "actual_pnl": act, "alternative_pnl": alt, "difference": alt - act,
            "lots": rows, "notes": notes + ["Daily closes; dividends ignored; fees of the alternative assumed equal."]}


def _actual(prices: Prices, lot: Lot) -> float | None:
    if lot.closed:
        return lot.pnl()
    last = prices.last(lot.symbol)
    return lot.pnl(last) if last else None


def what_if(pid: int, name: str, history_fn: HistoryFn | None = None, **params) -> dict:
    prices = Prices(history_fn)
    stock = [l for l in lots(pid) if l.sec_type == "STK"]
    fn = WHAT_IFS.get(name)
    if fn is None:
        raise ValueError(f"unknown what-if '{name}'; choose from {sorted(WHAT_IFS)}")
    return fn(stock, prices, **params)


def _wi_rule(stock, prices, rule, name, params, fallback="today", notes=()):
    rows = []
    for lot in stock:
        how, px, when = _alt_exit_rule(prices, lot, rule, fallback)
        rows.append({"key": lot.key, "entry": lot.entry_ts[:10], "qty": lot.qty, "actual_exit": lot.exit_ts,
                     "actual_exit_price": lot.exit_price, "actual_pnl": _actual(prices, lot), "alt_exit": when,
                     "alt_exit_price": px, "alt_pnl": lot.pnl(px) if px is not None else None, "how": how})
    return _compare(rows, name, params, list(notes))


def wi_hold_instead(stock, prices, **_):
    return _wi_rule([l for l in stock if l.closed], prices, lambda w, l: None, "hold_instead", {})


def wi_exit_over_iv(stock, prices, pct: float = 0.5, iv: str = "entry", fallback: str = "today", **_):
    """Sell the whole lot at the first close >= intrinsic value × (1 + pct). iv="entry" uses the IV recorded on the
    buy; lots without a recorded IV are skipped (listed)."""
    def rule(w, l):
        v = l.entry.get("intrinsic_value") if iv == "entry" else None
        return _first_cross(w, v * (1 + pct), True) if v else None
    have = [l for l in stock if l.entry.get("intrinsic_value")]
    out = _wi_rule(have, prices, rule, "exit_over_iv", {"pct": pct, "iv": iv, "fallback": fallback}, fallback)
    out["skipped_no_iv"] = [l.key + " " + l.entry_ts[:10] for l in stock if not l.entry.get("intrinsic_value")]
    return out


def wi_exit_tranches(stock, prices, levels: list | None = None, fallback: str = "today", **_):
    """Sell in tranches: levels = [[pct over entry IV, fraction of the lot], …] e.g. [[0.5, 0.5], [1.0, 0.5]]."""
    levels = sorted(levels or [[0.5, 0.5], [1.0, 0.5]])
    rows = []
    for lot in stock:
        v, w = lot.entry.get("intrinsic_value"), _path(prices, lot)
        if not v or w is None:
            continue
        left, alt, legs = 1.0, 0.0, []
        for pct, frac in levels:
            frac = min(frac, left)
            hit = _first_cross(w, v * (1 + pct), True)
            if hit and frac > 0:
                alt += lot.pnl(hit[1]) * frac
                legs.append({"pct": pct, "fraction": frac, "date": str(hit[0]), "price": hit[1]})
                left -= frac
        if left > 1e-9:
            px = lot.exit_price if (fallback == "actual" and lot.closed) else float(w["close"].iloc[-1])
            alt += lot.pnl(px) * left
            legs.append({"rest": left, "price": px, "how": fallback})
        rows.append({"key": lot.key, "entry": lot.entry_ts[:10], "qty": lot.qty, "actual_pnl": _actual(prices, lot),
                     "alt_pnl": alt, "tranches": legs})
    return _compare(rows, "exit_tranches", {"levels": levels, "fallback": fallback},
                    ["Compare with exit_over_iv for the all-at-once version of the same levels."])


def wi_stop_target(stock, prices, stop: float | None = 0.2, target: float | None = None, fallback: str = "actual", **_):
    def rule(w, l):
        hits = []
        if stop:
            h = _first_cross(w, l.entry_price * (1 - stop), False)
            if h:
                hits.append(h)
        if target:
            h = _first_cross(w, l.entry_price * (1 + target), True)
            if h:
                hits.append(h)
        return min(hits) if hits else None
    return _wi_rule(stock, prices, rule, "stop_target", {"stop": stop, "target": target, "fallback": fallback}, fallback)


def wi_hold_days(stock, prices, days: int = 365, **_):
    def rule(w, l):
        return next(((d.date(), float(c)) for d, c in w["close"].items()
                     if d.date() >= _day(l.entry_ts) + timedelta(days=days)), None)
    return _wi_rule(stock, prices, rule, "hold_days", {"days": days})


def wi_entry_all_at_once(stock, prices, **_):
    """Per symbol: the shares actually bought in tranches vs all of them at the FIRST tranche's price and at the lowest
    close between the first and last buy (best possible single entry in that window)."""
    by: dict[str, list[Lot]] = defaultdict(list)
    for l in stock:
        by[l.symbol].append(l)
    rows = []
    for sym, ls in by.items():
        ls.sort(key=lambda l: l.entry_ts)
        qty = sum(l.qty for l in ls)
        avg = sum(l.qty * l.entry_price for l in ls) / qty
        first = ls[0].entry_price
        w = prices.window(sym, _day(ls[0].entry_ts), _day(ls[-1].entry_ts))
        low = float(w["close"].min()) if w is not None else None
        rows.append({"key": sym, "tranches": len(ls), "qty": qty, "actual_avg_cost": avg, "all_at_first_price": first,
                     "best_single_entry_close": low, "actual_pnl": 0.0, "alt_pnl": (avg - first) * qty,
                     "best_case_saving": (avg - low) * qty if low else None})
    return _compare(rows, "entry_all_at_once", {},
                    ["alt_pnl > 0 means one buy at the first tranche's price would have been cheaper than the tranches."])


def wi_covered_calls(stock, prices, otm: float = 0.10, dte: int = 30, iv: float | None = None, **_):
    """Write a call every `dte` days at strike = spot × (1+otm) on each lot while held. Premium by Black-Scholes with
    `iv` if given, else the 30-day realised volatility at the time; at expiry the call costs max(0, S − K) (upside
    given away; cash-settled approximation of assignment + buy-back). Fractional contracts allowed (per-share maths)."""
    from vmi.options.payoff import bs_price
    rows = []
    for lot in stock:
        df = prices(lot.symbol)
        if df is None:
            continue
        start, end = pd.Timestamp(_day(lot.entry_ts)), pd.Timestamp(_day(lot.exit_ts)) if lot.closed else df.index[-1]
        closes = df["close"]
        rv = closes.pct_change().rolling(21).std() * math.sqrt(252)
        t, extra, cycles = start, 0.0, []
        while t + pd.Timedelta(days=dte) <= end:
            s0 = closes.loc[t:].iloc[0]
            t0 = closes.loc[t:].index[0]
            past = rv.loc[:t0].dropna()
            vol = iv if iv else (float(past.iloc[-1]) if not past.empty else 0.30)
            k = s0 * (1 + otm)
            prem = bs_price(float(s0), k, dte / 365, vol, "C")
            t1 = t0 + pd.Timedelta(days=dte)
            s1 = float(closes.loc[t1:].iloc[0]) if not closes.loc[t1:].empty else float(closes.iloc[-1])
            per = prem - max(0.0, s1 - k)
            extra += per * lot.qty
            cycles.append({"start": str(t0.date()), "spot": float(s0), "strike": k, "iv": vol, "premium": prem,
                           "spot_at_expiry": s1, "net_per_share": per})
            t = t1
        act = _actual(prices, lot)
        rows.append({"key": lot.key, "entry": lot.entry_ts[:10], "qty": lot.qty, "actual_pnl": act,
                     "alt_pnl": (act + extra) if act is not None else None, "calls_net": extra, "cycles": cycles})
    return _compare(rows, "covered_calls", {"otm": otm, "dte": dte, "iv": iv},
                    ["Black-Scholes premiums from realised volatility unless iv is given: an estimate, not quotes."])


def wi_benchmark(stock, prices, symbol: str = "SPY", **_):
    """Same dollars on the same days into `symbol`, sold on the same days as each lot."""
    rows = []
    for lot in stock:
        a = prices.close_on_or_after(symbol, _day(lot.entry_ts))
        if not a:
            continue
        dollars = lot.entry_price * lot.qty
        units = dollars / a[1]
        b = prices.close_on_or_after(symbol, _day(lot.exit_ts)) if lot.closed else None
        px = b[1] if b else prices.last(symbol)
        rows.append({"key": lot.key, "entry": lot.entry_ts[:10], "qty": lot.qty, "actual_pnl": _actual(prices, lot),
                     "alt_pnl": (px - a[1]) * units if px else None, "benchmark": symbol})
    return _compare(rows, "benchmark", {"symbol": symbol}, [])


WHAT_IFS = {"hold_instead": wi_hold_instead, "exit_over_iv": wi_exit_over_iv, "exit_tranches": wi_exit_tranches,
            "stop_target": wi_stop_target, "hold_days": wi_hold_days, "entry_all_at_once": wi_entry_all_at_once,
            "covered_calls": wi_covered_calls, "benchmark": wi_benchmark}


# ------------------------------------------------------------------------------------------ equity curve
def equity_curve(pid: int, history_fn: HistoryFn | None = None) -> dict:
    from vmi import store
    from vmi.paper import journal

    marks = [m for m in journal.marks(pid, key=journal.PORTFOLIO_KEY)]
    if len(marks) >= 2:
        pts = [(m["day"], m["value"]) for m in marks]
        source = "daily marks"
    else:
        prices = Prices(history_fn)
        with store.session() as s:
            p = s.get(store.Portfolio, pid)
            start_cash = p.starting_cash
            rows = ledger._order(ledger._rows(s, pid))
        if not rows:
            return {"source": "none", "points": []}
        d0, pts = _day(rows[0]["ts"]), []
        days = pd.bdate_range(d0, date.today())
        for d in days:
            rep = ledger.replay(start_cash, [r for r in rows if _day(r["ts"]) <= d.date()])
            val = rep["cash"]
            for k, st in rep["positions"].items():
                if not st["qty"]:
                    continue
                if st["sec_type"] == "STK":
                    hit = prices.window(st["symbol"], d0, d.date())
                    px = float(hit["close"].iloc[-1]) if hit is not None else st["avg_cost"]
                else:
                    px = st["avg_cost"]          # options at cost in this fallback
                val += px * st["qty"] * st["multiplier"]
            pts.append((str(d.date()), val))
        source = "ledger replay on daily closes (options at cost)"
    peak, out = -math.inf, []
    for d, v in pts:
        peak = max(peak, v or 0)
        out.append({"day": d, "equity": v, "drawdown": (1 - v / peak) if peak else 0.0})
    return {"source": source, "points": out, "max_drawdown": max((p["drawdown"] for p in out), default=0.0)}
