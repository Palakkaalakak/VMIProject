"""UIP automation for paper portfolios: sizing modes, tranche plans, automatic (or alert-only) tranche fills, and
backfill of levels that were hit while the app / IBKR was not running. Never sends anything to a broker.

Portfolio settings (store.Portfolio.settings, see DEFAULTS):
  sizing_mode        "watchlist" (equity ÷ stocks in the linked watchlist; default when one is linked) | "target"
                     (equity ÷ target_positions) | "manual" (manual_allocation $ per stock)
  auto_trade         True = levels fill automatically; False = alert only (owner's choice per portfolio)
  market_hours_only  live fills only in the regular US session (backfill uses regular-session daily bars)
  backfill           fill levels touched while offline, back-dated to the day they were touched
Per stock (store.TranchePlan): buy levels [{price, fraction}], sell levels [{price | over_iv, fraction}], intrinsic
value, require_below_iv, allocation override ($), category multiplier, auto override.

run()  one pass over every active plan: backfill since the plan's last check (completed daily bars), then live prices.
Each level fires once; every decision is written to the plan's history and raised as an alert.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from vmi import store
from vmi.data.models import Quote
from vmi.paper import fills, ledger
from vmi.rules import RULES

ET = ZoneInfo("America/New_York")
DEFAULTS: dict[str, Any] = {"sizing_mode": None, "watchlist_id": None, "manual_allocation": None,
                            "tranches": RULES.portfolio.tranches, "auto_trade": False, "market_hours_only": True,
                            "backfill": True, "fill_tolerance": 0.0, "alert_tolerance": RULES.technical.near_level_pct,
                            "max_backfill_days": 120}
SIZING_MODES = ("watchlist", "target", "manual")
MIN_ORDER = 25.0          # $: smaller remaining amounts are skipped, not bought


class PlanError(ValueError):
    pass


# --------------------------------------------------------------------------------------------- settings
def settings(pid: int) -> dict:
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise PlanError("portfolio not found")
        out = {**DEFAULTS, **(p.settings or {})}
    if not out["sizing_mode"]:
        out["sizing_mode"] = "watchlist" if out.get("watchlist_id") else "target"
    return out


def update_settings(pid: int, changes: dict) -> dict:
    bad = set(changes) - set(DEFAULTS)
    if bad:
        raise PlanError(f"unknown settings: {sorted(bad)}")
    if changes.get("sizing_mode") not in (None, *SIZING_MODES):
        raise PlanError(f"sizing_mode must be one of {SIZING_MODES}")
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise PlanError("portfolio not found")
        p.settings = {**(p.settings or {}), **changes}
        s.commit()
    return settings(pid)


def watchlist_size(wid: int | None) -> int | None:
    if not wid:
        return None
    with store.session() as s:
        n = len(list(s.scalars(select(store.WatchItem).where(store.WatchItem.watchlist_id == wid))))
    return n or None


def full_allocation(pid: int, equity: float, plan: store.TranchePlan | None = None, cfg: dict | None = None) -> dict:
    """$ full position for one stock, and how it was decided (shown on every auto order)."""
    cfg = cfg or settings(pid)
    mult = plan.multiplier if plan is not None and plan.multiplier else 1.0
    if plan is not None and plan.allocation:
        return {"full": plan.allocation * mult, "basis": f"plan override ${plan.allocation:,.0f} × {mult:g}"}
    mode = cfg["sizing_mode"]
    if mode == "manual" and cfg.get("manual_allocation"):
        return {"full": float(cfg["manual_allocation"]) * mult, "basis": f"manual ${cfg['manual_allocation']:,.0f} × {mult:g}"}
    if mode == "watchlist":
        n = watchlist_size(cfg.get("watchlist_id"))
        if n:
            return {"full": equity / n * mult, "basis": f"equity ${equity:,.0f} ÷ {n} watchlist stocks × {mult:g}"}
    with store.session() as s:
        n = s.get(store.Portfolio, pid).target_positions or RULES.portfolio.default_target_stocks
    return {"full": equity / n * mult, "basis": f"equity ${equity:,.0f} ÷ {n} target positions × {mult:g}"}


# ------------------------------------------------------------------------------------------------ plans
def _levels(raw: list | None, kind: str) -> list[dict]:
    out = []
    for x in raw or []:
        if isinstance(x, (int, float)):
            x = {"price": float(x)}
        d = {"price": float(x["price"]) if x.get("price") is not None else None,
             "over_iv": float(x["over_iv"]) if x.get("over_iv") is not None else None,
             "fraction": float(x["fraction"]) if x.get("fraction") is not None else None,
             "status": x.get("status", "pending"), "trade_id": x.get("trade_id"), "filled_at": x.get("filled_at"),
             "fill_price": x.get("fill_price"), "note": x.get("note", "")}
        if d["price"] is None and (kind == "buy" or d["over_iv"] is None):
            raise PlanError(f"{kind} level needs a price" + (" or over_iv" if kind == "sell" else ""))
        out.append(d)
    if kind == "buy":
        out.sort(key=lambda d: -d["price"])
    missing = [d for d in out if d["fraction"] is None]
    if missing:
        rest = max(0.0, 1.0 - sum(d["fraction"] for d in out if d["fraction"] is not None))
        for d in missing:
            d["fraction"] = rest / len(missing)
    return out


def _log(plan: store.TranchePlan, event: str, **data) -> None:
    plan.history = [*(plan.history or []), {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **data}]


def upsert_plan(pid: int, symbol: str, **fields) -> dict:
    """fields: buy_levels, sell_levels, intrinsic_value, require_below_iv, allocation, multiplier, auto, status,
    notes, source. Levels: [{price, fraction}] (fractions default to an equal split of what is left)."""
    symbol = symbol.upper().strip()
    allowed = {"buy_levels", "sell_levels", "intrinsic_value", "require_below_iv", "allocation", "multiplier", "auto",
               "status", "notes", "source"}
    bad = set(fields) - allowed
    if bad:
        raise PlanError(f"unknown plan fields: {sorted(bad)}")
    with store.session() as s:
        if not s.get(store.Portfolio, pid):
            raise PlanError("portfolio not found")
        plan = s.scalar(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid,
                                                        store.TranchePlan.symbol == symbol))
        new = plan is None
        if new:
            plan = store.TranchePlan(portfolio_id=pid, symbol=symbol, buy_levels=[], sell_levels=[], history=[],
                                     last_checked=datetime.now(timezone.utc))
            s.add(plan)
        before = store.to_dict(plan) if not new else None
        for k, v in fields.items():
            if k in ("buy_levels", "sell_levels"):
                v = _levels(v, "buy" if k == "buy_levels" else "sell")
            setattr(plan, k, v)
        plan.updated_at = datetime.now(timezone.utc)
        _log(plan, "created" if new else "updated", changes={k: v for k, v in fields.items()},
             before={k: before[k] for k in fields} if before else None)
        s.commit()
        return store.to_dict(plan)


def get_plans(pid: int) -> list[dict]:
    with store.session() as s:
        return [store.to_dict(p) for p in s.scalars(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid)
                                                    .order_by(store.TranchePlan.symbol))]


def delete_plan(pid: int, symbol: str) -> None:
    with store.session() as s:
        p = s.scalar(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid,
                                                     store.TranchePlan.symbol == symbol.upper()))
        if p:
            s.delete(p)
            s.commit()


def plans_from_watchlist(pid: int, wid: int, overwrite: bool = False) -> dict:
    """One plan per watchlist stock: buy levels = its supports below its intrinsic value, equal fractions.
    Links the watchlist to the portfolio (watchlist sizing) if none is linked yet."""
    with store.session() as s:
        items = list(s.scalars(select(store.WatchItem).where(store.WatchItem.watchlist_id == wid)))
        existing = {p.symbol for p in s.scalars(select(store.TranchePlan).where(store.TranchePlan.portfolio_id == pid))}
    cfg = settings(pid)
    if not cfg.get("watchlist_id"):
        update_settings(pid, {"watchlist_id": wid})         # sizing follows the watchlist unless a mode was chosen
    made, skipped = [], {}
    for it in items:
        if it.symbol in existing and not overwrite:
            skipped[it.symbol] = "plan exists"
            continue
        levels = sorted({float(l) for l in (it.supports or []) if not it.intrinsic_value or float(l) < it.intrinsic_value},
                        reverse=True)
        if not levels:
            skipped[it.symbol] = "no support levels below intrinsic value"
            continue
        upsert_plan(pid, it.symbol, buy_levels=[{"price": l} for l in levels], intrinsic_value=it.intrinsic_value,
                    source="watchlist", status="active")
        made.append(it.symbol)
    return {"created": made, "skipped": skipped, "settings": settings(pid)}


# ------------------------------------------------------------------------------------------------- run
def _default_quote(symbol: str):
    from vmi.data import market
    return market.quote(symbol)


def _default_history(symbol: str) -> pd.DataFrame:
    from vmi.data import market
    return market.history(symbol, "1y")


def _in_session() -> bool:
    from vmi.data import market_hours
    return market_hours.session_now() == market_hours.REGULAR


def _held(pid: int, symbol: str, at: datetime | None = None) -> float:
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        rows = ledger._rows(s, pid)
        start = p.starting_cash
    if at is not None:
        rows = [r for r in rows if ledger._ts(r["ts"]) <= ledger._ts(at)]
    return ledger.replay(start, rows)["positions"].get(symbol, {}).get("qty", 0.0)


def _equity(pid: int) -> float:
    from vmi.paper import engine
    try:
        return engine.summary(pid)["equity"]
    except Exception:
        return engine.summary(pid, quotes=False)["equity"]


def _sell_trigger(level: dict, iv: float | None) -> float | None:
    if level.get("price"):
        return level["price"]
    return iv * (1 + level["over_iv"]) if iv and level.get("over_iv") is not None else None


def _plan_ctx(plan: store.TranchePlan, idx: int, kind: str, alloc: dict, how: str, extra: dict | None = None) -> dict:
    return {"plan": {"plan_id": plan.id, "level": idx, "side": kind, "levels": plan.buy_levels if kind == "buy"
                     else plan.sell_levels, "intrinsic_value": plan.intrinsic_value, "allocation": alloc,
                     "trigger": how, **(extra or {})}}


def _alert(symbol: str, kind: str, msg: str, price: float | None) -> None:
    store.add_alert(symbol, kind, msg, price)


def _buy_amount(pid: int, plan, lvl: dict, px: float, equity: float, cfg: dict, held_qty: float) -> tuple[float, dict, str]:
    alloc = full_allocation(pid, equity, plan, cfg)
    have = held_qty * px
    remaining = alloc["full"] - have
    amount = min(alloc["full"] * lvl["fraction"], remaining)
    why = ""
    if remaining <= MIN_ORDER:
        why = f"full allocation reached (${have:,.0f} of ${alloc['full']:,.0f})"
    elif amount < MIN_ORDER:
        why = f"order below ${MIN_ORDER:.0f}"
    return amount, alloc, why


def _fill_backfill(pid: int, plan, idx: int, side: str, bar_day: date, open_px: float, trigger: float,
                   amount_or_qty: float, alloc: dict, is_qty: bool) -> int:
    """Back-dated fill through the ledger at the level (or the open if it gapped through), plus normal slippage."""
    gap = open_px <= trigger if side == "BUY" else open_px >= trigger
    ref = open_px if gap else trigger
    f = fills.stock_fill(side, Quote(plan.symbol, last=ref, avg_volume=None, source="history"))
    when = datetime.combine(bar_day, dtime(9, 30) if gap else dtime(12, 0), ET)
    qty = amount_or_qty if is_qty else round(amount_or_qty / f.price, 4)
    note = (f"auto-backfill: {'gapped through' if gap else 'touched'} {trigger:.2f} on {bar_day} while offline "
            f"(daily bar; intraday time unknown, {'open' if gap else 'level'} used)")
    ctx = _plan_ctx(plan, idx, "buy" if side == "BUY" else "sell", alloc, "backfill",
                    {"bar_day": str(bar_day), "gap": gap, "fill": f.to_dict()})
    res = ledger.add_trade(pid, {"symbol": plan.symbol, "side": side, "qty": qty, "price": f.price, "mid": ref,
                                 "ts": when.isoformat(), "note": note, "context": ctx, "kind": "fill"},
                           reason=f"auto-backfill {plan.symbol} level {idx + 1}")
    with store.session() as s:
        t = s.get(store.Trade, res["trade_id"])
        t.source = "auto-backfill"
        t.liquidity = "backfill"
        s.commit()
    return res["trade_id"]


def run(pid: int | None = None, *, quote_fn: Callable | None = None, history_fn: Callable | None = None,
        in_session: Callable[[], bool] | None = None, now: datetime | None = None) -> list[dict]:
    """One automation pass. Returns the events (also stored in plan history + alerts)."""
    from vmi.paper import engine

    quote_fn, history_fn, in_session = quote_fn or _default_quote, history_fn or _default_history, in_session or _in_session
    now = now or datetime.now(timezone.utc)
    events: list[dict] = []
    with store.session() as s:
        q = select(store.TranchePlan).where(store.TranchePlan.status == "active")
        if pid is not None:
            q = q.where(store.TranchePlan.portfolio_id == pid)
        plan_ids = [p.id for p in s.scalars(q)]
    for plan_id in plan_ids:
        try:
            events += _run_plan(plan_id, engine, quote_fn, history_fn, in_session, now)
        except Exception as exc:
            events.append({"plan_id": plan_id, "event": "error", "error": f"{type(exc).__name__}: {exc}"[:300]})
    return events


def _run_plan(plan_id, engine, quote_fn, history_fn, in_session, now) -> list[dict]:
    events: list[dict] = []
    with store.session() as s:
        plan = s.get(store.TranchePlan, plan_id)
        pid, sym = plan.portfolio_id, plan.symbol
        cfg = settings(pid)
        auto = cfg["auto_trade"] if plan.auto is None else plan.auto
        equity = _equity(pid)
        buys, sells = [dict(l) for l in plan.buy_levels or []], [dict(l) for l in plan.sell_levels or []]
        iv = plan.intrinsic_value

        def done(lvl, status, **kw):
            lvl.update(status=status, **kw)

        # ---- 1. backfill: completed regular-session daily bars since the last check
        last = plan.last_checked or plan.created_at or now
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        start = max(last.astimezone(ET).date(), (now - timedelta(days=cfg["max_backfill_days"])).astimezone(ET).date())
        today = now.astimezone(ET).date()
        if cfg["backfill"] and start < today:
            try:
                bars = history_fn(sym)
            except Exception:
                bars = None
            if bars is not None and not bars.empty:
                bars = bars.copy()
                bars.index = pd.to_datetime(bars.index).tz_localize(None).normalize()
                bars = bars[(bars.index.date >= start) & (bars.index.date < today)]
                for d, bar in bars.iterrows():
                    day = d.date()
                    for i, lvl in enumerate(buys):
                        if lvl["status"] not in ("pending", "alerted") or bar["low"] > lvl["price"]:
                            continue
                        fill_ref = min(float(bar["open"]), lvl["price"])
                        if plan.require_below_iv and iv and fill_ref >= iv:
                            done(lvl, "skipped", note=f"{day}: touched but not below IV {iv:.2f}")
                            continue
                        if not auto:
                            if lvl["status"] != "alerted":
                                msg = f"{sym} touched buy level {lvl['price']:.2f} on {day} while offline (alert only)."
                                _alert(sym, "tranche_level", msg, fill_ref)
                                events.append({"symbol": sym, "event": "backfill_alert", "day": str(day)})
                                done(lvl, "alerted", note=msg)
                            continue
                        held = _held(pid, sym, datetime.combine(day, dtime(23, 59), ET))
                        amount, alloc, why = _buy_amount(pid, plan, lvl, fill_ref, equity, cfg, held)
                        if why:
                            done(lvl, "skipped", note=f"{day}: {why}")
                            _alert(sym, "tranche_skipped", f"{sym} level {lvl['price']:.2f} skipped: {why}", fill_ref)
                            continue
                        try:
                            tid = _fill_backfill(pid, plan, i, "BUY", day, float(bar["open"]), lvl["price"], amount, alloc, False)
                        except ledger.LedgerError as exc:
                            done(lvl, "skipped", note=f"{day}: {exc}")
                            _alert(sym, "tranche_skipped", f"{sym} backfill skipped: {exc}", fill_ref)
                            continue
                        done(lvl, "filled", trade_id=tid, filled_at=str(day), fill_price=fill_ref)
                        _alert(sym, "tranche_filled", f"{sym} tranche {i + 1} back-filled at {fill_ref:.2f} on {day} "
                                                      f"(${amount:,.0f}; app was offline).", fill_ref)
                        events.append({"symbol": sym, "event": "backfill_buy", "day": str(day), "trade_id": tid})
                    for i, lvl in enumerate(sells):
                        trig = _sell_trigger(lvl, iv)
                        if lvl["status"] not in ("pending", "alerted") or trig is None or bar["high"] < trig:
                            continue
                        held = _held(pid, sym, datetime.combine(day, dtime(23, 59), ET))
                        qty = round(held * lvl["fraction"], 4)
                        if qty <= 0:
                            continue
                        if not auto:
                            if lvl["status"] != "alerted":
                                _alert(sym, "sell_level", f"{sym} reached sell level {trig:.2f} on {day} (alert only).", trig)
                                done(lvl, "alerted")
                            continue
                        tid = _fill_backfill(pid, plan, i, "SELL", day, float(bar["open"]), trig, qty, {}, True)
                        done(lvl, "filled", trade_id=tid, filled_at=str(day), fill_price=max(trig, float(bar["open"])))
                        _alert(sym, "tranche_filled", f"{sym} sell level {trig:.2f} back-filled on {day}.", trig)
                        events.append({"symbol": sym, "event": "backfill_sell", "day": str(day), "trade_id": tid})

        # ---- 2. live price
        session_ok = (not cfg["market_hours_only"]) or in_session()
        try:
            qt = quote_fn(sym)
            px = qt.last or qt.close
        except Exception:
            qt, px = None, None
        if px:
            for i, lvl in enumerate(buys):
                if lvl["status"] not in ("pending", "alerted"):
                    continue
                if px > lvl["price"] * (1 + cfg["alert_tolerance"]):
                    continue
                below_iv = not (plan.require_below_iv and iv and px >= iv)
                fill_now = px <= lvl["price"] * (1 + cfg["fill_tolerance"]) and below_iv
                if auto and fill_now and session_ok:
                    held = _held(pid, sym)
                    amount, alloc, why = _buy_amount(pid, plan, lvl, px, equity, cfg, held)
                    if why:
                        done(lvl, "skipped", note=why)
                        _alert(sym, "tranche_skipped", f"{sym} level {lvl['price']:.2f} skipped: {why}", px)
                        continue
                    try:
                        res = engine.trade_stock(pid, sym, "BUY", dollars=amount, quote=qt, journal={
                            "source": "auto", "tags": "auto-tranche",
                            "context": _plan_ctx(plan, i, "buy", alloc, "live price")})
                    except Exception as exc:
                        done(lvl, "skipped", note=str(exc)[:200])
                        _alert(sym, "tranche_skipped", f"{sym} auto-buy failed: {exc}", px)
                        continue
                    done(lvl, "filled", trade_id=res["trade"]["id"], filled_at=now.isoformat(),
                         fill_price=res["trade"]["price"])
                    _alert(sym, "tranche_filled", f"{sym} tranche {i + 1} auto-filled at {res['trade']['price']:.2f} "
                                                  f"(${amount:,.0f}; {alloc['basis']}).", px)
                    events.append({"symbol": sym, "event": "auto_buy", "trade_id": res["trade"]["id"]})
                elif lvl["status"] == "pending":
                    why = ("not below IV" if not below_iv else "outside regular hours" if auto and fill_now else
                           "alert only" if not auto else "near level")
                    _alert(sym, "tranche_level", f"{sym} at {px:.2f} is at/near buy level {lvl['price']:.2f} ({why}).", px)
                    done(lvl, "alerted", note=why)
                    events.append({"symbol": sym, "event": "level_alert", "why": why})
            for i, lvl in enumerate(sells):
                trig = _sell_trigger(lvl, iv)
                if lvl["status"] not in ("pending", "alerted") or trig is None or px < trig:
                    continue
                held = _held(pid, sym)
                qty = round(held * lvl["fraction"], 4)
                if qty <= 0:
                    continue
                if auto and session_ok:
                    res = engine.trade_stock(pid, sym, "SELL", qty=qty, quote=qt, journal={
                        "source": "auto", "tags": "auto-sell", "context": _plan_ctx(plan, i, "sell", {}, "live price")})
                    done(lvl, "filled", trade_id=res["trade"]["id"], filled_at=now.isoformat(),
                         fill_price=res["trade"]["price"])
                    _alert(sym, "tranche_filled", f"{sym} sell level {trig:.2f} auto-filled ({qty:g} shares).", px)
                    events.append({"symbol": sym, "event": "auto_sell", "trade_id": res["trade"]["id"]})
                elif lvl["status"] == "pending":
                    _alert(sym, "sell_level", f"{sym} at {px:.2f} reached sell level {trig:.2f}"
                                              f" ({'alert only' if not auto else 'outside regular hours'}).", px)
                    done(lvl, "alerted")

        plan = s.get(store.TranchePlan, plan_id)          # re-read: ledger/engine used their own sessions
        plan.buy_levels, plan.sell_levels = buys, sells
        plan.last_checked = now
        if buys and all(l["status"] in ("filled", "skipped") for l in buys) and \
                all(l["status"] in ("filled", "skipped") for l in sells):
            plan.status = "done"
        if events:
            _log(plan, "run", events=events)
        s.commit()
    return events
