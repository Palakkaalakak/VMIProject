"""Daily journal (store.DailyMark) and full raw export: the time series later reviews and what-ifs are built on.

record(pid)    upsert today's marks for one portfolio: a "__portfolio__" row (equity, cash, P&L …) and one row per
               held position or planned stock (price, value, weight, intrinsic value, MOS, trend, option IV …).
               Called from the app's background loop (throttled), so the day's row ends up as the last state seen.
export(pid)    everything stored about a portfolio in one JSON-able dict (trades with context, audit log, daily marks,
               tranche plans, option snapshots) for manual analysis outside the app.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any

from sqlalchemy import select

from vmi import store
from vmi.data.cache import get_cache

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

    day = day or date.today().isoformat()
    summ = engine.summary(pid)
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
                | {"n_positions": len(summ["positions"]), "ts": time.time()})
        for r in summ["positions"]:
            data: dict[str, Any] = {k: r.get(k) for k in ("avg_cost", "unrealized_pnl", "return_pct", "weight",
                                                           "allocation_used", "tranches_filled", "sec_type",
                                                           "expiry", "strike", "right")}
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


def export(pid: int) -> dict:
    from vmi.paper import ledger

    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise ValueError("portfolio not found")
        plans = [store.to_dict(x) for x in s.scalars(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid))]
        snaps = [store.to_dict(x) for x in s.scalars(select(store.OptionSnapshot).where(
            store.OptionSnapshot.portfolio_id == pid))]
        port = store.to_dict(p)
    return {"exported_at": time.time(), "portfolio": port, "ledger": ledger.ledger(pid), "audit": ledger.audit(pid, 10_000),
            "verify": ledger.verify(pid), "daily_marks": marks(pid), "tranche_plans": plans, "option_snapshots": snaps}
