"""Daily journal (store.DailyMark) and full raw export: the time series later reviews and what-ifs are built on.

record(pid)    upsert today's marks for one portfolio: a "__portfolio__" row (equity, cash, P&L …) and one row per
               held position or planned stock (price, value, weight, intrinsic value, MOS, trend, option IV …).
               Called from the app's background loop (throttled), so the day's row ends up as the last state seen.
export(pid)    everything stored about a portfolio in one JSON-able dict (trades with context, audit log, daily marks,
               tranche plans, option snapshots) for manual analysis outside the app.
"""
from __future__ import annotations

import math
import time
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, time as clock, timedelta
from typing import Any, Callable

import pandas as pd

from sqlalchemy import select

from vmi import store
from vmi.data.cache import get_cache
from vmi.data.market_hours import ET
from vmi.paper import ledger

PORTFOLIO_KEY = "__portfolio__"
THROTTLE_SECS = 30 * 60


def _upsert(s, day: str, pid: int, key: str, **fields) -> None:
    row = s.scalar(select(store.DailyMark).where(store.DailyMark.day == day, store.DailyMark.portfolio_id == pid,
                                                 store.DailyMark.key == key))
    if row is None:
        row = store.DailyMark(day=day, portfolio_id=pid, key=key)
        s.add(row)
    for k, v in fields.items():
        setattr(row, k, v)


def _atm_option_iv(symbol: str, spot: float | None) -> dict | None:
    """Implied vol of the at-the-money contract in the cached chains (no network call)."""
    if not spot:
        return None
    from vmi.options import chain

    best = None
    with chain._lock:
        for ck, rows in chain._snapshots.items():
            if not ck.startswith(f"{symbol.upper()}:"):
                continue
            for r in rows.values():
                if r.get("iv"):
                    d = abs(float(r.get("strike") or 0) - spot)
                    if best is None or d < best[0]:
                        best = (d, {"expiry": ck.split(":")[1], "strike": r.get("strike"), "right": r.get("right"),
                                    "iv": r.get("iv")})
    return best[1] if best else None


def _stock_view(symbol: str) -> dict:
    """Valuation/trend state of a stock today (cached analysis; errors recorded, never raised)."""
    try:
        from vmi.analysis.pipeline import analyse_ticker

        r = analyse_ticker(symbol, with_technicals=True)
        tech = r.get("technicals") or {}
        return {"intrinsic_value": r.get("intrinsic_value"),
                "conservative_value": (r.get("valuation") or {}).get("conservative_value"),
                "method": (r.get("valuation") or {}).get("selected"),
                "margin_of_safety": (r.get("metrics") or {}).get("margin_of_safety"),
                "growth": (r.get("metrics") or {}).get("growth"),
                "steps": {str(s["step"]): s["passed"] for s in r.get("steps") or []},
                "moat": r.get("moat"), "category": r.get("category"),
                "trend_daily": (tech.get("daily") or {}).get("state"),
                "trend_weekly": (tech.get("weekly") or {}).get("state"),
                "buy_levels": [b.get("price") for b in tech.get("buy_levels") or []],
                "iv_low_confidence": (r.get("iv_confidence") or {}).get("low")}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def record(pid: int, day: str | None = None, analyse: bool = True) -> dict:
    from vmi.paper import engine

    day = day or datetime.now(ET).date().isoformat()
    summ = engine.summary(pid)
    observed_at = time.time()
    with store.session() as s:
        planned = [p.symbol for p in s.scalars(select(store.TranchePlan).where(
            store.TranchePlan.portfolio_id == pid, store.TranchePlan.status == "active"))]
    views: dict[str, dict] = {}
    held = {r["symbol"] for r in summ["positions"] if r["sec_type"] == "STK"}
    for sym in sorted(held | set(planned)):
        views[sym] = _stock_view(sym) if analyse else {}
    with store.session() as s:
        _upsert(s, day, pid, PORTFOLIO_KEY, symbol="", qty=0.0, price=None, value=summ["equity"],
                data={k: summ.get(k) for k in ("cash", "free_cash", "reserved_cash", "market_value", "unrealized_pnl",
                                                "realized_pnl", "total_return", "n_stocks", "full_allocation")}
                | {"n_positions": len(summ["positions"]), "ts": observed_at})
        for r in summ["positions"]:
            data: dict[str, Any] = {k: r.get(k) for k in ("avg_cost", "unrealized_pnl", "return_pct", "weight",
                                                           "allocation_used", "tranches_filled", "sec_type",
                                                           "expiry", "strike", "right")}
            data["ts"] = observed_at
            if r["sec_type"] == "STK":
                data.update(views.get(r["symbol"], {}))
                data["option_iv"] = _atm_option_iv(r["symbol"], r.get("price"))
            _upsert(s, day, pid, r["key"], symbol=r["symbol"], qty=r["qty"], price=r.get("price"),
                    value=r.get("market_value"), data=data)
        for sym in planned:
            if sym in held:
                continue
            try:
                from vmi.data import market
                px = market.last_price(sym)
            except Exception:
                px = None
            _upsert(s, day, pid, f"plan:{sym}", symbol=sym, qty=0.0, price=px, value=0.0,
                    data={"planned": True, **views.get(sym, {}), "option_iv": _atm_option_iv(sym, px)})
        s.commit()
    return {"day": day, "positions": len(summ["positions"]), "planned": len(planned)}


def record_all_if_due() -> list[dict]:
    """Background-loop entry: marks for every portfolio at most every THROTTLE_SECS."""
    cache = get_cache()
    if cache.get("journal:last_run", THROTTLE_SECS):
        return []
    cache.set("journal:last_run", time.time())
    out = []
    with store.session() as s:
        ids = [p.id for p in s.scalars(select(store.Portfolio))]
    for pid in ids:
        try:
            out.append(record(pid))
        except Exception as exc:
            out.append({"portfolio_id": pid, "error": str(exc)[:200]})
    return out


def marks(pid: int, key: str | None = None, since: str | None = None) -> list[dict]:
    with store.session() as s:
        q = select(store.DailyMark).where(store.DailyMark.portfolio_id == pid)
        if key:
            q = q.where(store.DailyMark.key == key)
        if since:
            q = q.where(store.DailyMark.day >= since)
        return [store.to_dict(m) for m in s.scalars(q.order_by(store.DailyMark.day, store.DailyMark.key))]


BENCHMARKS = ("SPY", "QQQ", "VTI")
HISTORY_SOURCE = "ledger replay by effective time · latest eligible daily closes · recorded option marks where available"


def _instant(ts) -> datetime:
    return datetime.fromisoformat(ledger._ts(ts)).astimezone(ET)


def _end_of_day(day: date) -> datetime:
    return datetime.combine(day, clock.max, ET)


def _load(pid: int, cutoff: datetime):
    with store.session() as s:
        port = store.to_dict(ledger._portfolio(s, pid))
        rows = [(dt, row) for row in ledger._order(ledger._replay_rows(s, pid))
                if (dt := _instant(row["ts"])).timestamp() <= cutoff.timestamp()]
        # Marks supply prices, never cash, quantities or equity. A late admin entry cannot alter these price observations.
        m = store.DailyMark
        raw = list(s.execute(select(m.day, m.key, m.price, m.data).where(m.portfolio_id == pid,
                             m.day <= cutoff.date().isoformat(), (m.price.is_not(None)) | (m.key == PORTFOLIO_KEY))))
    times = {day: (data or {}).get("ts") for day, key, _, data in raw if key == PORTFOLIO_KEY}
    observed = {}
    for day, key, price, data in raw:
        if price is None or not math.isfinite(price) or price < 0:
            continue
        stamp = (data or {}).get("ts", times.get(day))
        dt = datetime.fromtimestamp(stamp, ET) if stamp is not None else _end_of_day(date.fromisoformat(day))
        if dt.date().isoformat() == day and dt.timestamp() <= cutoff.timestamp():
            observed[day, key] = (dt, price)
    return port, rows, observed


def _closes(symbols: set[str], history_fn: Callable | None) -> dict:
    from vmi.data import market

    def load(symbol):
        try:
            df = history_fn(symbol) if history_fn is not None else market.history(symbol, "10y")
            if df is not None and not df.empty:
                values = {day.date(): float(px) for day, px in zip(pd.to_datetime(df.index), df["close"])
                          if pd.notna(day) and pd.notna(px) and math.isfinite(float(px)) and float(px) > 0}
                return sorted(values), values
        except Exception:
            pass
        return [], {}

    if not symbols:
        return {}
    names = sorted(symbols)
    if len(names) == 1:
        return {names[0]: load(names[0])}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
        return dict(zip(names, pool.map(load, names)))


def _valuation(state: ledger.Replay, starting_cash: float, cutoff: datetime, closes: dict, observed: dict,
               *, include_positions: bool, stock_values: dict | None = None) -> dict:
    day = cutoff.date()
    label = day.isoformat()
    last_close = day if cutoff.time() >= clock(16) else max(date.min, day - timedelta(days=day > date.min))
    mv = unreal = reserved = gross = 0.0
    count = stocks = estimates = 0
    positions = []
    for p in state.positions.values():
        if not p.qty:
            continue
        count += 1
        is_stock = p.sec_type == "STK"
        stocks += is_stock
        mark = observed.get((label, p.key))
        days, values = closes.get(p.symbol, ([], {})) if is_stock else ([], {})
        i = bisect_right(days, last_close)
        if mark and mark[0].timestamp() <= cutoff.timestamp() and (not i or days[i - 1] < day):
            px, price_day, src = mark[1], label, "recorded quote"
        elif i:
            px, price_day, src = values[days[i - 1]], str(days[i - 1]), "daily close"
        else:
            px, price_day, src = p.avg_cost, None, "cost estimate"
            estimates += 1
        value = px * p.qty * p.multiplier
        if is_stock and stock_values is not None:
            stock_values[p.symbol] = value
        pnl = (px - p.avg_cost) * p.qty * p.multiplier
        if not is_stock and p.right == "P" and p.qty < 0:
            reserved += -p.qty * (p.strike or 0) * p.multiplier
        mv += value
        gross += abs(value)
        unreal += pnl
        if include_positions:
            positions.append({**asdict(p), "price": px, "price_day": price_day, "price_source": src,
                              "market_value": value, "unrealized_pnl": pnl})
    equity = state.cash + mv
    out = {"day": label, "as_of": cutoff.isoformat(), "equity": equity, "cash": state.cash,
           "free_cash": state.cash - reserved, "reserved_cash": reserved, "market_value": mv, "gross_exposure": gross,
           "unrealized_pnl": unreal, "realized_pnl": sum(p.realized_pnl for p in state.positions.values()),
           "total_return": equity / starting_cash - 1 if starting_cash else None, "fees": state.fees,
           "trade_count": state.trade_count, "n_positions": count, "n_stocks": stocks, "estimated_positions": estimates}
    if include_positions:
        for p in positions:
            p["weight"] = p["market_value"] / equity if equity else None
        out["positions"] = sorted(positions, key=lambda p: -abs(p["market_value"]))
    return out


def history(pid: int, start: date | None = None, end: date | None = None, *, history_fn: Callable | None = None,
            include_positions: bool = False, now: datetime | None = None, include_performance: bool = False,
            benchmark: str | None = None, include_attribution: bool = False) -> dict:
    """Read-only daily timeline. Replaying orders once keeps past corrections immediately visible everywhere."""
    now = (now or datetime.now(ET)).astimezone(ET)
    end = end or now.date()
    if end > now.date() or (start and start > end):
        raise ValueError("Choose a valid range ending no later than today (New York time).")
    cutoff = min(now, _end_of_day(end))
    port, rows, observed = _load(pid, cutoff)
    created = _instant(port["created_at"]).date()
    first = min(created, rows[0][0].date()) if rows else created
    start = start or min(first, end)
    if (end - start).days > 36_600:
        raise ValueError("Select a range of no more than 100 years.")
    state = ledger.Replay(port["starting_cash"])
    # Replay the opening balance before fetching history. Only price symbols relevant to the requested window.
    i = 0
    while i < len(rows) and rows[i][0].date() < start:
        state.apply(rows[i][1])
        i += 1
    symbols = {p.symbol for p in state.positions.values() if p.qty and p.sec_type == "STK"}
    symbols.update(row["symbol"] for _, row in rows[i:] if row["sec_type"] == "STK")
    if benchmark and (not include_performance or benchmark not in BENCHMARKS):
        raise ValueError("Choose SPY, QQQ or VTI as the benchmark.")
    closes = _closes(symbols | ({benchmark} if benchmark else set()), history_fn)
    opening_values = {}
    opening_day = start - timedelta(days=1) if start > date.min else None
    opening_point = (_valuation(state, port["starting_cash"], _end_of_day(opening_day), closes, observed,
                                include_positions=include_attribution, stock_values=opening_values)
                     if opening_day else {"equity": port["starting_cash"], "cash": port["starting_cash"], "positions": []})
    opening = opening_point["equity"]
    exposure: dict[str, float] = defaultdict(float)
    exposure_days = 0
    flows: dict[str, float] = defaultdict(float)
    stock_pnl = {sym: [] for sym in sorted(symbols)} if include_performance else {}
    peak, points = opening, []
    for n in range((end - start).days + 1):
        at = min(cutoff, _end_of_day(start + timedelta(days=n)))
        while i < len(rows) and rows[i][0].timestamp() <= at.timestamp():
            row = rows[i][1]
            state.apply(row)
            if include_performance and row["sec_type"] == "STK" and row["side"] in ("BUY", "SELL") and row["qty"] > 0:
                flows[row["symbol"]] += ledger.cash_delta(row["side"], row["qty"], row["price"], row["multiplier"] or 1,
                                                          row["fees"] or 0.0)
            i += 1
        values = {} if include_performance else None
        point = _valuation(state, port["starting_cash"], at, closes, observed,
                           include_positions=include_positions or (include_performance and n == (end - start).days),
                           stock_values=values)
        if values is not None:
            for sym, series in stock_pnl.items():
                series.append(values.get(sym, 0.0) - opening_values.get(sym, 0.0) + flows[sym])
        equity = point["equity"]
        if include_attribution and equity > 0:
            exposure_days += 1
            for sym, value in (values or {}).items():
                exposure[sym] += value / equity
        peak = max(peak, equity)
        point["drawdown"] = 1 - equity / peak if peak > 0 else 0.0
        points.append(point)
    period_return = points[-1]["equity"] / opening - 1 if opening else None
    report = {"source": HISTORY_SOURCE, "timezone": "America/New_York", "first_day": str(first), "points": points,
              "period_return": period_return, "max_drawdown": max(p["drawdown"] for p in points),
              "estimated_days": sum(p["estimated_positions"] > 0 for p in points)}
    if include_performance:
        report["portfolio_name"] = port["name"]
        report["opening_equity"] = opening
        report["range_trades"] = sum(dt.date() >= start for dt, _ in rows)
        report["range_fees"] = sum((r["fees"] or 0.0) for dt, r in rows if dt.date() >= start)
        report["stocks"] = [{"symbol": sym, "pnl": series, **_price_path(closes[sym], opening_day, points)}
                            for sym, series in stock_pnl.items()]
        report["benchmark"] = {"symbol": benchmark, **_price_path(closes[benchmark], opening_day, points)} if benchmark else None
    if include_performance and include_attribution:
        first_positions = {p["symbol"]: p for p in opening_point.get("positions", []) if p["sec_type"] == "STK"}
        last_positions = {p["symbol"]: p for p in points[-1]["positions"] if p["sec_type"] == "STK"}
        for stock in report["stocks"]:
            sym = stock["symbol"]
            first_pos, last_pos = first_positions.get(sym), last_positions.get(sym)
            stock.update(opening_qty=first_pos["qty"] if first_pos else 0, closing_qty=last_pos["qty"] if last_pos else 0,
                         opening_weight=first_pos["weight"] if first_pos else 0, closing_weight=last_pos["weight"] if last_pos else 0,
                         avg_weight=exposure[sym] / exposure_days if exposure_days else None,
                         contribution_pct_points=100 * stock["pnl"][-1] / opening if opening else None)
        weights = [p["cash"] / p["equity"] for p in points if p["equity"] > 0]
        report["attribution"] = {
            "opening_cash": opening_point["cash"], "ending_cash": points[-1]["cash"],
            "average_daily_cash_weight": sum(weights) / len(weights) if weights else None,
            "stock_pnl": sum(row["pnl"][-1] for row in report["stocks"]),
            "equity_change": points[-1]["equity"] - opening,
        }
        report["attribution"]["non_stock_and_other_residual"] = report["attribution"]["equity_change"] - report["attribution"]["stock_pnl"]
    return report


def _price_path(closes: tuple[list, dict], opening_day: date | None, points: list[dict]) -> dict:
    """Price-only return, carried over non-trading days. Never use a close after that point's cutoff."""
    dates, values = closes
    i = bisect_right(dates, opening_day) - 1 if opening_day else -1
    base = dates[i] if i >= 0 else None
    path = []
    for p in points:
        at = datetime.fromisoformat(p["as_of"])
        eligible = at.date().toordinal() - (at.time() < clock(16))
        while i + 1 < len(dates) and dates[i + 1].toordinal() <= eligible:
            i += 1
        if base is None and i >= 0:
            base = dates[i]
        path.append(values[dates[i]] / values[base] - 1 if base is not None else None)
    return {"base_day": str(base) if base else None, "price_return": path}


def snapshot(pid: int, as_of: str, *, history_fn: Callable | None = None, now: datetime | None = None) -> dict:
    """Exact ledger cutoff; timestamp without an offset uses New York time. A date alone means end of day."""
    now = (now or datetime.now(ET)).astimezone(ET)
    if len(as_of) == 10:
        at = _end_of_day(date.fromisoformat(as_of))
        if at.date() == now.date():
            at = now
    else:
        at = datetime.fromisoformat(as_of)
        at = at.astimezone(ET) if at.tzinfo else at.replace(tzinfo=ET)
    if at.timestamp() > now.timestamp():
        raise ValueError("As-of time cannot be in the future.")
    port, rows, observed = _load(pid, at)
    state = ledger.Replay(port["starting_cash"])
    for _, row in rows:
        state.apply(row)
    closes = _closes({p.symbol for p in state.positions.values() if p.qty and p.sec_type == "STK"}, history_fn)
    return {**_valuation(state, port["starting_cash"], at, closes, observed, include_positions=True), "source": HISTORY_SOURCE}


def export(pid: int, *, include_history: bool = False, start: date | None = None, end: date | None = None,
           as_of: str | None = None) -> dict:

    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise ValueError("portfolio not found")
        plans = [store.to_dict(x) for x in s.scalars(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid))]
        snaps = [store.to_dict(x) for x in s.scalars(select(store.OptionSnapshot).where(
            store.OptionSnapshot.portfolio_id == pid))]
        port = store.to_dict(p)
    out = {"exported_at": time.time(), "portfolio": port, "ledger": ledger.ledger(pid), "audit": ledger.audit(pid, 10_000),
           "verify": ledger.verify(pid), "daily_marks": marks(pid), "tranche_plans": plans, "option_snapshots": snaps}
    if include_history:
        out["history"] = history(pid, start, end, include_positions=True)
        if as_of:
            out["as_of"] = snapshot(pid, as_of)
        out["archive_note"] = "Daily marks and saved option scenarios are observations as captured, not corrected balances. Use history for the effective-date account record."
    return out
