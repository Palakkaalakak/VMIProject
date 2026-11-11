"""The trade ledger is the source of truth: positions and cash are a replay of every trade in time order.

    step(...)                 one fill applied to a position (average cost, realised P&L) — shared with engine._apply
    replay(start_cash, rows)  pure: rebuild positions + cash from trade rows, report impossible states
    rebuild(pid)              write the replay back to the portfolio (after admin edits)
    verify(pid)               compare stored positions/cash with the replay (drift check)
    add_trade / update_trade / delete_trade   admin edits (back-dated orders, typo fixes) — validated by a dry-run
                              replay first, then applied, rebuilt and written to the audit log (before/after rows).

Nothing here talks to a broker.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from vmi import store

EPS = 1e-9
EDITABLE = ("ts", "side", "qty", "price", "mid", "fees", "note", "tags", "thesis", "kind", "symbol", "sec_type",
            "expiry", "strike", "right", "multiplier", "context")


class LedgerError(ValueError):
    pass


@dataclass
class PosState:
    key: str
    symbol: str
    sec_type: str = "STK"
    multiplier: int = 1
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    qty: float = 0.0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0
    tranches_filled: int = 0
    first_ts: str | None = None
    last_ts: str | None = None


def step(qty: float, avg: float, realized: float, side: str, trade_qty: float, price: float,
         mult: int) -> tuple[float, float, float]:
    """Average-cost accounting for one fill. Returns (new qty, new avg cost, new realised P&L)."""
    signed = trade_qty if side.upper() == "BUY" else -trade_qty
    if abs(qty) < EPS or (qty > 0) == (signed > 0):                  # opening / adding
        avg = (abs(qty) * avg + trade_qty * price) / (abs(qty) + trade_qty)
    else:                                                          # reducing / closing / flipping
        closing = min(abs(signed), abs(qty))
        pnl_per = (price - avg) if qty > 0 else (avg - price)
        realized += pnl_per * closing * mult
        if abs(signed) > abs(qty):
            avg = price
    new = round(qty + signed, 6)
    return (0.0 if abs(new) < EPS else new), avg, realized


def cash_delta(side: str, qty: float, price: float, mult: int, fees: float = 0.0) -> float:
    signed = qty if side.upper() == "BUY" else -qty
    return -signed * price * mult - (fees or 0.0)


def option_key(symbol: str, expiry: str, strike: float, right: str) -> str:
    return f"{symbol.upper()} {expiry} {float(strike):g} {right.upper()}"


def _ts(v: Any) -> str:
    """Comparable UTC ISO string for a datetime or ISO string (naive = UTC, as SQLite returns them)."""
    dt = v
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return v
    if not isinstance(dt, datetime):
        return str(v or "")
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _order(rows: Iterable[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (_ts(r.get("ts")), r.get("id") or 10**12))


def replay(starting_cash: float, rows: Iterable[dict], allow_negative_cash: bool = True) -> dict:
    """rows: trade dicts (store.to_dict(Trade) shape; option rows may carry expiry/strike/right). Pure function.
    Errors: selling stock you do not hold at that time, or (if not allowed) cash going negative."""
    cash, pos, errors, low = float(starting_cash), {}, [], (float(starting_cash), None)
    for r in _order(rows):
        key, side, qty, price = r["key"], r["side"].upper(), float(r["qty"]), float(r["price"])
        mult = int(r.get("multiplier") or (100 if r.get("sec_type") == "OPT" else 1))
        p = pos.get(key)
        if p is None:
            p = pos[key] = PosState(key, r["symbol"], r.get("sec_type") or "STK", mult, r.get("expiry"),
                                    r.get("strike"), r.get("right"), first_ts=_ts(r.get("ts")))
            if p.sec_type == "OPT" and not p.expiry:                         # recover from the key
                parts = key.split()
                if len(parts) == 4:
                    p.expiry, p.strike, p.right = parts[1], float(parts[2]), parts[3]
        if side not in ("BUY", "SELL") or qty <= 0:
            errors.append(f"trade {r.get('id')}: side must be BUY/SELL and qty > 0")
            continue
        if p.sec_type == "STK" and side == "SELL" and qty > p.qty + 1e-6:
            errors.append(f"trade {r.get('id')} {_ts(r.get('ts'))[:16]}: sells {qty:g} {key} but only {p.qty:g} held then")
        p.qty, p.avg_cost, p.realized_pnl = step(p.qty, p.avg_cost, p.realized_pnl, side, qty, price, mult)
        if p.sec_type == "STK" and side == "BUY" and (r.get("kind") or "fill") == "fill":
            p.tranches_filled += 1
        p.last_ts = _ts(r.get("ts"))
        cash += cash_delta(side, qty, price, mult, float(r.get("fees") or 0.0))
        if cash < low[0]:
            low = (cash, _ts(r.get("ts")))
        if cash < -1e-6 and not allow_negative_cash:
            errors.append(f"trade {r.get('id')} {_ts(r.get('ts'))[:16]}: cash goes negative ({cash:,.2f})")
    return {"cash": cash, "positions": {k: asdict(v) for k, v in pos.items()}, "errors": errors,
            "lowest_cash": {"cash": low[0], "at": low[1]}}


# ----------------------------------------------------------------------------------------------- DB side
def _rows(s, pid: int) -> list[dict]:
    return [_row(t) for t in s.scalars(select(store.Trade).where(store.Trade.portfolio_id == pid))]


def _row(t: store.Trade) -> dict:
    d = store.to_dict(t)
    if t.sec_type == "OPT":
        parts = t.key.split()
        if len(parts) == 4:
            d.update(expiry=parts[1], strike=float(parts[2]), right=parts[3])
    return d


def _portfolio(s, pid: int) -> store.Portfolio:
    p = s.get(store.Portfolio, pid)
    if not p:
        raise LedgerError("portfolio not found")
    return p


def verify(pid: int) -> dict:
    """Stored state vs replay. `ok` is False when positions or cash drifted (e.g. edited outside the ledger)."""
    with store.session() as s:
        p = _portfolio(s, pid)
        rep = replay(p.starting_cash, _rows(s, pid))
        diffs = []
        stored = {x.key: x for x in p.positions}
        for k in sorted(set(stored) | set(rep["positions"])):
            a, b = stored.get(k), rep["positions"].get(k)
            sq, rq = (a.qty if a else 0.0), (b["qty"] if b else 0.0)
            sa, ra = (a.avg_cost if a else 0.0), (b["avg_cost"] if b else 0.0)
            sr, rr = (a.realized_pnl if a else 0.0), (b["realized_pnl"] if b else 0.0)
            if abs(sq - rq) > 1e-6 or (abs(rq) > EPS and abs(sa - ra) > 1e-4) or abs(sr - rr) > 0.01:
                diffs.append({"key": k, "stored": {"qty": sq, "avg_cost": sa, "realized_pnl": sr},
                              "replay": {"qty": rq, "avg_cost": ra, "realized_pnl": rr}})
        cash_diff = p.cash - rep["cash"]
        return {"ok": not diffs and abs(cash_diff) < 0.01 and not rep["errors"], "position_diffs": diffs,
                "cash_stored": p.cash, "cash_replay": rep["cash"], "cash_diff": cash_diff, "errors": rep["errors"],
                "lowest_cash": rep["lowest_cash"]}


def rebuild(pid: int, reason: str = "rebuild") -> dict:
    """Overwrite positions + cash with the replay (keeps each position's meta). Audited."""
    with store.session() as s:
        p = _portfolio(s, pid)
        before = verify(pid)
        rep = replay(p.starting_cash, _rows(s, pid))
        stored = {x.key: x for x in p.positions}
        for k, st in rep["positions"].items():
            x = stored.get(k)
            if x is None:
                x = store.Position(portfolio_id=pid, key=k, symbol=st["symbol"], sec_type=st["sec_type"],
                                   expiry=st["expiry"], strike=st["strike"], right=st["right"],
                                   multiplier=st["multiplier"], meta={})
                s.add(x)
            x.qty, x.avg_cost, x.realized_pnl = st["qty"], st["avg_cost"], st["realized_pnl"]
            x.tranches_filled = st["tranches_filled"]
        for k, x in stored.items():                       # positions with no trades left
            if k not in rep["positions"]:
                s.delete(x)
        p.cash = rep["cash"]
        s.add(store.TradeAudit(portfolio_id=pid, action="rebuild", reason=reason,
                               before={"cash": before["cash_stored"], "diffs": before["position_diffs"]},
                               after={"cash": rep["cash"], "errors": rep["errors"]}))
        s.commit()
    return {**verify(pid), "replay_errors": rep["errors"]}


def _normalise(d: dict, base: dict | None = None) -> dict:
    """Validated trade fields for an admin add/update (base = current row on update)."""
    out = dict(base or {})
    for k in EDITABLE:
        if k in d and d[k] is not None:
            out[k] = d[k]
    out["side"] = str(out.get("side", "")).upper()
    out["sec_type"] = (out.get("sec_type") or "STK").upper()
    out["symbol"] = str(out.get("symbol", "")).upper().strip()
    if not out["symbol"]:
        raise LedgerError("symbol is required")
    if out["side"] not in ("BUY", "SELL"):
        raise LedgerError("side must be BUY or SELL")
    try:
        out["qty"], out["price"] = float(out["qty"]), float(out["price"])
    except (KeyError, TypeError, ValueError):
        raise LedgerError("qty and price must be numbers")
    if out["qty"] <= 0 or out["price"] < 0:
        raise LedgerError("qty must be > 0 and price >= 0")
    if out["sec_type"] == "OPT":
        if not (out.get("expiry") and out.get("strike") and out.get("right")):
            raise LedgerError("options need expiry (YYYYMMDD), strike and right (C/P)")
        out["key"] = option_key(out["symbol"], str(out["expiry"]), float(out["strike"]), str(out["right"]))
        out["multiplier"] = int(out.get("multiplier") or 100)
    else:
        out["key"], out["multiplier"] = out["symbol"], 1
    ts = out.get("ts")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            raise LedgerError("ts must be an ISO date/time, e.g. 2026-03-02T15:31:00-05:00")
    ts = ts or datetime.now(timezone.utc)
    out["ts"] = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)  # stored as UTC
    out["fees"] = float(out.get("fees") or 0.0)
    out["mid"] = float(out.get("mid") if out.get("mid") is not None else out["price"])
    if isinstance(out.get("tags"), list):
        out["tags"] = ",".join(t.strip() for t in out["tags"] if t.strip())
    return out


def _apply_row(t: store.Trade, d: dict) -> None:
    for k in ("ts", "key", "symbol", "sec_type", "side", "qty", "price", "mid", "multiplier", "fees", "note", "tags",
              "thesis", "kind", "context"):
        if k in d and d[k] is not None:
            setattr(t, k, d[k])
    t.slippage = abs(t.price - t.mid) * t.qty * t.multiplier


def _dry_run(s, p: store.Portfolio, rows: list[dict], allow_negative_cash: bool) -> dict:
    rep = replay(p.starting_cash, rows, allow_negative_cash)
    if rep["errors"]:
        raise LedgerError("; ".join(rep["errors"][:5]))
    return rep


def add_trade(pid: int, data: dict, reason: str, allow_negative_cash: bool = False) -> dict:
    """Back-dated / missing order. data: symbol, side, qty, price, ts (ISO), optional sec_type/expiry/strike/right,
    fees, mid, note, tags, thesis, kind, context."""
    if not reason.strip():
        raise LedgerError("a reason is required for every admin change")
    d = _normalise({"kind": "fill", **data})
    with store.session() as s:
        p = _portfolio(s, pid)
        _dry_run(s, p, _rows(s, pid) + [{**d, "id": None}], allow_negative_cash)
        t = store.Trade(portfolio_id=pid, source="admin", edited=True, liquidity="admin", slippage=0.0,
                        context=d.get("context") or {}, note=d.get("note") or "", tags=d.get("tags") or "",
                        thesis=d.get("thesis") or "", kind=d.get("kind") or "fill", key=d["key"], symbol=d["symbol"],
                        side=d["side"], qty=d["qty"], price=d["price"], mid=d["mid"])
        _apply_row(t, d)
        s.add(t)
        s.flush()
        s.add(store.TradeAudit(portfolio_id=pid, trade_id=t.id, action="add", reason=reason, before=None,
                               after=_row(t)))
        s.commit()
        tid = t.id
    out = {"trade_id": tid, "state": rebuild(pid, f"after add #{tid}: {reason}")}
    if d["kind"] == "fill":
        try:                                   # a real order at a plan level fills that level (no double buy)
            from vmi.paper import autotrade
            out["plan_level"] = autotrade.match_manual_fill(pid, tid)
        except Exception:
            out["plan_level"] = None
    return out


def update_trade(trade_id: int, changes: dict, reason: str, allow_negative_cash: bool = False) -> dict:
    if not reason.strip():
        raise LedgerError("a reason is required for every admin change")
    with store.session() as s:
        t = s.get(store.Trade, trade_id)
        if not t:
            raise LedgerError("trade not found")
        p = _portfolio(s, t.portfolio_id)
        before = _row(t)
        d = _normalise(changes, before)
        others = [r for r in _rows(s, p.id) if r["id"] != trade_id]
        _dry_run(s, p, others + [{**d, "id": trade_id}], allow_negative_cash)
        _apply_row(t, d)
        t.edited = True
        s.add(store.TradeAudit(portfolio_id=p.id, trade_id=trade_id, action="update", reason=reason, before=before,
                               after=_row(t)))
        s.commit()
        pid = p.id
    return {"trade_id": trade_id, "state": rebuild(pid, f"after update #{trade_id}: {reason}")}


def delete_trade(trade_id: int, reason: str, allow_negative_cash: bool = False) -> dict:
    if not reason.strip():
        raise LedgerError("a reason is required for every admin change")
    with store.session() as s:
        t = s.get(store.Trade, trade_id)
        if not t:
            raise LedgerError("trade not found")
        p = _portfolio(s, t.portfolio_id)
        _dry_run(s, p, [r for r in _rows(s, p.id) if r["id"] != trade_id], allow_negative_cash)
        s.add(store.TradeAudit(portfolio_id=p.id, trade_id=trade_id, action="delete", reason=reason, before=_row(t),
                               after=None))
        s.delete(t)
        s.commit()
        pid = p.id
    return {"trade_id": trade_id, "state": rebuild(pid, f"after delete #{trade_id}: {reason}")}


def ledger(pid: int) -> list[dict]:
    """Every trade with its running position and cash after it (oldest first)."""
    with store.session() as s:
        p = _portfolio(s, pid)
        rows = _order(_rows(s, pid))
        start = p.starting_cash
    out, done = [], []
    for r in rows:
        done.append(r)
        rep = replay(start, done)
        st = rep["positions"].get(r["key"], {})
        out.append({**r, "position_after": st.get("qty"), "avg_cost_after": st.get("avg_cost"),
                    "realized_after": st.get("realized_pnl"), "cash_after": rep["cash"]})
    return out


def audit(pid: int, limit: int = 500) -> list[dict]:
    with store.session() as s:
        q = (select(store.TradeAudit).where(store.TradeAudit.portfolio_id == pid)
             .order_by(store.TradeAudit.id.desc()).limit(limit))
        return [store.to_dict(a) for a in s.scalars(q)]
