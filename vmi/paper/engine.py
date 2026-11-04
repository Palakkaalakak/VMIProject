"""Paper-trading engine: multiple portfolios (growth / defensive / balanced / dividend / speculative),
default $100k cash, stocks + options (CSP / CC / long options). NEVER sends orders to IBKR.

Fill model: vmi.paper.fills (mid + flat slippage; illiquid ⇒ mid debuff). Option assignment/expiry is
settled lazily by `settle_expired()` (called on every portfolio read) using the underlying's last price.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from vmi import store
from vmi.data import market
from vmi.paper import fills, sizing
from vmi.rules import RULES

STYLES = ("growth", "defensive", "balanced", "dividend", "speculative")


class TradeError(ValueError):
    pass


def option_key(symbol: str, expiry: str, strike: float, right: str) -> str:
    return f"{symbol.upper()} {expiry} {strike:g} {right.upper()}"


# --------------------------------------------------------------------------------------- portfolios
def create_portfolio(name: str, style: str = "balanced", cash: float | None = None,
                     target_positions: int | None = None) -> dict:
    if style not in STYLES:
        raise TradeError(f"style must be one of {STYLES}")
    cash = RULES.execution.default_cash if cash is None else float(cash)
    with store.session() as s:
        if s.scalar(select(store.Portfolio).where(store.Portfolio.name == name)):
            raise TradeError(f"portfolio '{name}' already exists")
        p = store.Portfolio(name=name, style=style, cash=cash, starting_cash=cash,
                            target_positions=target_positions or RULES.portfolio.default_target_stocks)
        s.add(p)
        s.commit()
        return store.to_dict(p)


def ensure_default_portfolios() -> None:
    with store.session() as s:
        if s.scalar(select(store.Portfolio).limit(1)):
            return
    for name, style, n in (("Growth", "growth", 15), ("Defensive", "defensive", 15), ("Balanced", "balanced", 20)):
        create_portfolio(name, style, target_positions=n)


def list_portfolios() -> list[dict]:
    with store.session() as s:
        return [summary(p.id, quotes=False) for p in s.scalars(select(store.Portfolio).order_by(store.Portfolio.id))]


def delete_portfolio(pid: int) -> None:
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if p:
            s.delete(p)
            s.commit()


def reset_portfolio(pid: int) -> dict:
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise TradeError("portfolio not found")
        for x in list(p.positions) + list(p.trades):
            s.delete(x)
        p.cash = p.starting_cash
        s.commit()
    return summary(pid)


# --------------------------------------------------------------------------------------- pricing
def _stock_quote(symbol: str):
    q = market.quote(symbol)
    if not (q.mid or q.last or q.close):
        raise TradeError(f"no price for {symbol}")
    return q


def _mark(pos: store.Position, quotes: bool = True) -> float | None:
    if not quotes:
        return None
    try:
        if pos.sec_type == "STK":
            return market.last_price(pos.symbol)
        from vmi.options.chain import option_quote
        oq = option_quote(pos.symbol, pos.expiry, pos.strike, pos.right)
        return oq.mid if oq else None
    except Exception:
        return None


# --------------------------------------------------------------------------------------- trading
def _apply(s, p: store.Portfolio, key: str, symbol: str, sec_type: str, side: str, qty: float, fill: fills.Fill,
           multiplier: int, extra: dict | None = None, note: str = "") -> dict:
    side = side.upper()
    if qty <= 0:
        raise TradeError("quantity must be positive")
    signed = qty if side == "BUY" else -qty
    cash_delta = -signed * fill.price * multiplier
    pos = s.scalar(select(store.Position).where(store.Position.portfolio_id == p.id, store.Position.key == key))
    if pos is None:
        pos = store.Position(portfolio_id=p.id, key=key, symbol=symbol, sec_type=sec_type, qty=0.0, avg_cost=0.0,
                             multiplier=multiplier, meta={}, **(extra or {}))
        s.add(pos)
    if sec_type == "STK" and side == "SELL" and qty > pos.qty + 1e-9:
        raise TradeError(f"cannot sell {qty} — only {pos.qty} held (no shorting stocks)")
    if side == "BUY" and p.cash + cash_delta < -1e-6:
        raise TradeError(f"insufficient cash: need ${-cash_delta:,.2f}, have ${p.cash:,.2f}")
    if sec_type == "OPT" and side == "SELL" and pos.qty - qty < 0:   # opening/adding a short option
        _check_short_option_cover(s, p, pos, symbol, qty - max(pos.qty, 0), extra or {})
    # position accounting (average cost; realised P&L on reductions)
    old = pos.qty
    new = old + signed
    if old == 0 or (old > 0) == (signed > 0):          # opening / adding
        pos.avg_cost = (abs(old) * pos.avg_cost + qty * fill.price) / (abs(old) + qty)
    else:                                              # reducing / closing / flipping
        closing = min(abs(signed), abs(old))
        pnl_per = (fill.price - pos.avg_cost) if old > 0 else (pos.avg_cost - fill.price)
        pos.realized_pnl += pnl_per * closing * multiplier
        if abs(signed) > abs(old):                     # flipped through zero
            pos.avg_cost = fill.price
    pos.qty = round(new, 6)
    if sec_type == "STK" and side == "BUY":
        pos.tranches_filled = (pos.tranches_filled or 0) + 1
    p.cash += cash_delta
    t = store.Trade(portfolio_id=p.id, key=key, symbol=symbol, sec_type=sec_type, side=side, qty=qty,
                    price=fill.price, mid=fill.mid, slippage=fill.slippage_per_share * qty * multiplier,
                    liquidity=fill.liquidity, multiplier=multiplier, note=note)
    s.add(t)
    if abs(pos.qty) < 1e-9:
        pos.qty = 0.0
    s.commit()
    return {"trade": store.to_dict(t), "fill": fill.to_dict(), "cash": p.cash, "position": store.to_dict(pos)}


def _check_short_option_cover(s, p, pos, symbol: str, new_short: float, extra: dict) -> None:
    """Only covered calls and cash-secured puts (Lesson 12) — no naked shorts."""
    right = extra.get("right") or pos.right
    if right == "C":
        shares = sum(x.qty for x in p.positions if x.sec_type == "STK" and x.symbol == symbol)
        short_calls = -sum(min(0, x.qty) for x in p.positions if x.sec_type == "OPT" and x.symbol == symbol
                           and x.right == "C")
        if (short_calls + new_short) * 100 > shares + 1e-9:
            raise TradeError(f"covered call needs {int((short_calls + new_short) * 100)} shares; you hold {shares:g}")
    else:
        strike = extra.get("strike") or pos.strike
        reserved = reserved_cash(p)
        need = new_short * strike * 100
        if p.cash - reserved < need - 1e-6:
            raise TradeError(f"cash-secured put needs ${need:,.0f} free cash; free cash is ${p.cash - reserved:,.0f}")


def reserved_cash(p: store.Portfolio) -> float:
    """Collateral reserved for open short puts."""
    return sum(-x.qty * (x.strike or 0) * 100 for x in p.positions if x.sec_type == "OPT" and x.right == "P" and x.qty < 0)


def trade_stock(pid: int, symbol: str, side: str, qty: float | None = None, dollars: float | None = None,
                note: str = "", quote=None) -> dict:
    symbol = symbol.upper().strip()
    q = quote or _stock_quote(symbol)
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise TradeError("portfolio not found")
        f = fills.stock_fill(side, q)
        if qty is None:
            if not dollars:
                raise TradeError("give qty or dollars")
            qty = round(dollars / f.price, 4)   # fractional shares allowed (Lesson 8 §4.3)
        return _apply(s, p, symbol, symbol, "STK", side, float(qty), f, 1, note=note)


def trade_option(pid: int, symbol: str, expiry: str, strike: float, right: str, side: str, contracts: int,
                 note: str = "") -> dict:
    from vmi.options.chain import option_quote

    oq = option_quote(symbol, expiry, strike, right)
    if oq is None:
        raise TradeError("no option quote available")
    f = fills.option_fill(side, oq.bid, oq.ask, oq.last)
    key = option_key(symbol, expiry, strike, right)
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise TradeError("portfolio not found")
        return _apply(s, p, key, symbol.upper(), "OPT", side, float(contracts), f, 100,
                      extra={"expiry": expiry, "strike": float(strike), "right": right.upper()}, note=note)


def settle_expired(pid: int) -> list[dict]:
    """Expire / assign options past expiry using the underlying's last price (intrinsic-value settlement)."""
    events = []
    today = date.today().strftime("%Y%m%d")
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            return events
        for pos in list(p.positions):
            if pos.sec_type != "OPT" or not pos.expiry or pos.expiry >= today or pos.qty == 0:
                continue
            try:
                und = market.last_price(pos.symbol) or 0.0
            except Exception:
                continue
            itm = (und > pos.strike) if pos.right == "C" else (und < pos.strike)
            n = pos.qty
            if itm:
                shares = n * 100 * (1 if pos.right == "C" else -1)   # long call/short put ⇒ receive shares
                stk = s.scalar(select(store.Position).where(store.Position.portfolio_id == p.id,
                                                            store.Position.key == pos.symbol))
                if stk is None:
                    stk = store.Position(portfolio_id=p.id, key=pos.symbol, symbol=pos.symbol, sec_type="STK",
                                         qty=0.0, avg_cost=0.0, multiplier=1, meta={})
                    s.add(stk)
                if shares > 0:
                    stk.avg_cost = (stk.qty * stk.avg_cost + shares * pos.strike) / (stk.qty + shares)
                else:
                    stk.realized_pnl += (pos.strike - stk.avg_cost) * (-shares)
                stk.qty += shares
                p.cash -= shares * pos.strike
                pos.realized_pnl += ((-pos.avg_cost) if n > 0 else pos.avg_cost) * abs(n) * 100
                events.append({"key": pos.key, "event": "assigned/exercised", "shares": shares, "underlying": und})
                s.add(store.Trade(portfolio_id=p.id, key=pos.symbol, symbol=pos.symbol, sec_type="STK",
                                  side="BUY" if shares > 0 else "SELL", qty=abs(shares), price=pos.strike,
                                  mid=pos.strike, note=f"assignment {pos.key}"))
            else:
                pos.realized_pnl += ((-pos.avg_cost) if n > 0 else pos.avg_cost) * abs(n) * 100
                events.append({"key": pos.key, "event": "expired worthless", "underlying": und})
            pos.qty = 0.0
        s.commit()
    return events


# --------------------------------------------------------------------------------------- reporting
def summary(pid: int, quotes: bool = True) -> dict[str, Any]:
    if quotes:
        settle_expired(pid)
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        if not p:
            raise TradeError("portfolio not found")
        rows, mv, unreal, realized = [], 0.0, 0.0, 0.0
        for pos in p.positions:
            realized += pos.realized_pnl
            if pos.qty == 0:
                continue
            px = _mark(pos, quotes)
            value = (px if px is not None else pos.avg_cost) * pos.qty * pos.multiplier
            u = ((px - pos.avg_cost) * pos.qty * pos.multiplier) if px is not None else 0.0
            mv += value
            unreal += u
            rows.append({**store.to_dict(pos), "price": px, "market_value": value, "unrealized_pnl": u,
                         "return_pct": (px / pos.avg_cost - 1) if px and pos.avg_cost and pos.qty > 0 else None})
        equity = p.cash + mv
        for r in rows:
            r["weight"] = r["market_value"] / equity if equity else 0
        full_alloc = equity / max(1, p.target_positions)
        for r in rows:
            if r["sec_type"] == "STK":
                r["full_allocation"] = full_alloc
                r["allocation_used"] = r["market_value"] / full_alloc if full_alloc else None
        return {**store.to_dict(p), "equity": equity, "market_value": mv, "unrealized_pnl": unreal,
                "realized_pnl": realized, "total_return": equity / p.starting_cash - 1 if p.starting_cash else 0,
                "reserved_cash": reserved_cash(p), "free_cash": p.cash - reserved_cash(p),
                "full_allocation": full_alloc, "positions": sorted(rows, key=lambda r: -abs(r["market_value"])),
                "n_stocks": sum(1 for r in rows if r["sec_type"] == "STK")}


def trades(pid: int, limit: int = 200) -> list[dict]:
    with store.session() as s:
        q = select(store.Trade).where(store.Trade.portfolio_id == pid).order_by(store.Trade.id.desc()).limit(limit)
        return [store.to_dict(t) for t in s.scalars(q)]


def size_for(pid: int, symbol: str, multiplier: float = 1.0) -> dict:
    """Auto order sizing per VMI rules for this portfolio."""
    summ = summary(pid)
    price = market.last_price(symbol) or 0
    cur = sum(r["market_value"] for r in summ["positions"] if r["symbol"] == symbol.upper() and r["sec_type"] == "STK")
    return sizing.plan(summ["equity"], price, cur, summ["target_positions"], multiplier,
                       cash=summ["free_cash"]).to_dict()
