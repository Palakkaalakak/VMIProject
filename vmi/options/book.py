"""Option payoff book: saved payoff profiles (store.OptionSnapshot) that stay usable without IBKR or live quotes.

snapshot_portfolio(pid, symbol)  legs = the portfolio's open options on `symbol` + its shares (covered calls), IV per leg
                                 from the live quote, else implied from the option's mid, else from the entry premium
snapshot_legs(symbol, legs, spot)  manual what-if position (no portfolio)
recompute(sid, spot=, iv_shift=, as_of=)  rerun the maths from the SAVED inputs only (offline)
snapshot_all(reason="daily")    one snapshot per underlying with open options in every portfolio
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from vmi import store
from vmi.options import payoff


def _iv_for(symbol: str, pos, spot: float) -> tuple[float, str]:
    t = payoff.years(pos.expiry, date.today())
    try:
        from vmi.options.chain import option_quote
        oq = option_quote(symbol, pos.expiry, pos.strike, pos.right)
    except Exception:
        oq = None
    if oq is not None and oq.iv:
        return float(oq.iv), "quote"
    mid = None
    if oq is not None and oq.bid and oq.ask:
        mid = (oq.bid + oq.ask) / 2
    for price, src in ((mid, "implied from mid"), (pos.avg_cost, "implied from entry premium")):
        if price:
            iv = payoff.implied_vol(price, spot, pos.strike, t, pos.right)
            if iv:
                return iv, src
    return 0.30, "default 30% (no quote, no usable premium)"


def legs_from_portfolio(pid: int, symbol: str, spot: float) -> list[dict]:
    symbol = symbol.upper()
    legs = []
    with store.session() as s:
        rows = list(s.scalars(select(store.Position).where(store.Position.portfolio_id == pid,
                                                           store.Position.symbol == symbol)))
    for p in rows:
        if not p.qty:
            continue
        if p.sec_type == "STK":
            legs.append({"type": "STK", "qty": p.qty, "entry": p.avg_cost, "multiplier": 1, "key": p.key})
        else:
            iv, src = _iv_for(symbol, p, spot)
            legs.append({"type": "OPT", "right": p.right, "strike": p.strike, "expiry": p.expiry, "qty": p.qty,
                         "entry": p.avg_cost, "iv": iv, "iv_source": src, "multiplier": p.multiplier or 100,
                         "key": p.key})
    return legs


def _save(symbol: str, legs: list[dict], spot: float, pid: int | None, reason: str, label: str, notes: str,
          as_of: str | None = None) -> int:
    inputs = {"symbol": symbol.upper(), "legs": legs, "spot": spot, "as_of": as_of or date.today().isoformat(),
              "rate": payoff.RISK_FREE}
    result = payoff.profile(legs, spot, inputs["as_of"], inputs["rate"])
    with store.session() as s:
        row = store.OptionSnapshot(portfolio_id=pid, symbol=symbol.upper(), label=label, reason=reason, inputs=inputs,
                                   result=result, notes=notes)
        s.add(row)
        s.commit()
        return row.id


def snapshot_portfolio(pid: int, symbol: str, reason: str = "manual", label: str = "", notes: str = "",
                       spot: float | None = None) -> int | None:
    if spot is None:
        from vmi.data import market
        spot = market.last_price(symbol)
    if not spot:
        raise ValueError(f"no spot price for {symbol}; pass spot= to snapshot offline")
    legs = legs_from_portfolio(pid, symbol, spot)
    if not any(l["type"] == "OPT" for l in legs):
        return None
    return _save(symbol, legs, spot, pid, reason, label or f"{symbol.upper()} position", notes)


def snapshot_legs(symbol: str, legs: list[dict], spot: float, label: str = "", notes: str = "",
                  pid: int | None = None, as_of: str | None = None) -> int:
    clean = []
    for l in legs:
        l = dict(l)
        l["type"] = (l.get("type") or "OPT").upper()
        if l["type"] == "OPT":
            l["right"] = l["right"].upper()
            if not l.get("iv") and l.get("entry"):
                l["iv"] = payoff.implied_vol(float(l["entry"]), spot, float(l["strike"]),
                                             payoff.years(l["expiry"], as_of or date.today()), l["right"]) or 0.30
        clean.append(l)
    return _save(symbol, clean, spot, pid, "manual", label or f"{symbol.upper()} what-if", notes, as_of)


def get(sid: int) -> dict:
    with store.session() as s:
        row = s.get(store.OptionSnapshot, sid)
        if not row:
            raise ValueError("snapshot not found")
        return store.to_dict(row)


def list_snapshots(pid: int | None = None, symbol: str | None = None, limit: int = 200) -> list[dict]:
    with store.session() as s:
        q = select(store.OptionSnapshot)
        if pid is not None:
            q = q.where(store.OptionSnapshot.portfolio_id == pid)
        if symbol:
            q = q.where(store.OptionSnapshot.symbol == symbol.upper())
        rows = s.scalars(q.order_by(store.OptionSnapshot.id.desc()).limit(limit))
        return [{k: v for k, v in store.to_dict(r).items() if k != "result"} for r in rows]


def delete(sid: int) -> None:
    with store.session() as s:
        row = s.get(store.OptionSnapshot, sid)
        if row:
            s.delete(row)
            s.commit()


def recompute(sid: int, spot: float | None = None, iv_shift: float = 0.0, as_of: str | None = None,
              iv_overrides: dict | None = None, **kw) -> dict:
    """What-if on a saved snapshot, from its stored inputs only. iv_shift is added to every leg's IV;
    iv_overrides = {leg index: iv} replaces single legs."""
    snap = get(sid)
    inp = snap["inputs"]
    legs = [dict(l) for l in inp["legs"]]
    for i, l in enumerate(legs):
        if l.get("type") == "OPT":
            if iv_overrides and str(i) in {str(k) for k in iv_overrides}:
                l["iv"] = float({str(k): v for k, v in iv_overrides.items()}[str(i)])
            l["iv"] = max(0.01, float(l.get("iv") or 0.3) + iv_shift)
    res = payoff.profile(legs, spot or inp["spot"], as_of or inp["as_of"], inp.get("rate", payoff.RISK_FREE), **kw)
    return {"snapshot_id": sid, "inputs_used": {"spot": spot or inp["spot"], "iv_shift": iv_shift,
                                                "as_of": as_of or inp["as_of"]}, "result": res}


def snapshot_all(reason: str = "daily") -> list[int]:
    out = []
    with store.session() as s:
        rows = list(s.scalars(select(store.Position).where(store.Position.sec_type == "OPT", store.Position.qty != 0)))
        pairs = sorted({(p.portfolio_id, p.symbol) for p in rows})
    for pid, sym in pairs:
        try:
            sid = snapshot_portfolio(pid, sym, reason=reason, label=f"{sym} {reason}")
            if sid:
                out.append(sid)
        except Exception:
            continue
    return out
