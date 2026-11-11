"""Option position payoff maths (pure, offline): Black-Scholes value of every leg on any date, spot and IV shift.

A leg is a dict:
  {"type": "OPT", "right": "C"|"P", "strike": 100.0, "expiry": "20261218", "qty": -1 (contracts, short < 0),
   "entry": 2.10 (premium per share paid/received), "iv": 0.31, "multiplier": 100}
  {"type": "STK", "qty": 100 (shares), "entry": 95.0}
P&L of a leg = (value − entry) × qty × multiplier. Valuation date `as_of` (ISO date); options past expiry are worth
intrinsic value. Rate default: vmi.options.chain.RISK_FREE. Greeks reuse chain.bs_greeks.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from vmi.options.chain import RISK_FREE, _ncdf, bs_greeks

MOVES = (-0.30, -0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.30)
IV_SHIFTS = (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15)


def _d(v) -> date:
    if isinstance(v, date):
        return v
    s = str(v)
    return datetime.strptime(s, "%Y%m%d").date() if len(s) == 8 and s.isdigit() else date.fromisoformat(s[:10])


def years(expiry: str, as_of) -> float:
    return max((_d(expiry) - _d(as_of)).days, 0) / 365.0


def bs_price(spot: float, strike: float, t: float, iv: float, right: str, r: float = RISK_FREE) -> float:
    intrinsic = max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)
    if t <= 0 or iv <= 0 or spot <= 0:
        return intrinsic
    st = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / st
    d2 = d1 - st
    if right == "C":
        return spot * _ncdf(d1) - strike * math.exp(-r * t) * _ncdf(d2)
    return strike * math.exp(-r * t) * _ncdf(-d2) - spot * _ncdf(-d1)


def implied_vol(price: float, spot: float, strike: float, t: float, right: str, r: float = RISK_FREE) -> float | None:
    """Bisection on [1%, 500%]; None when the price is below intrinsic or the contract has expired."""
    if t <= 0 or price <= 0:
        return None
    lo, hi = 0.01, 5.0
    if bs_price(spot, strike, t, lo, right, r) > price or bs_price(spot, strike, t, hi, right, r) < price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_price(spot, strike, t, mid, right, r) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def leg_value(leg: dict, spot: float, as_of, iv_shift: float = 0.0, r: float = RISK_FREE) -> float:
    if leg.get("type", "OPT") == "STK":
        return spot
    iv = max(0.01, float(leg.get("iv") or 0.3) + iv_shift)
    return bs_price(spot, float(leg["strike"]), years(leg["expiry"], as_of), iv, leg["right"], r)


def _mult(leg: dict) -> float:
    return float(leg.get("multiplier") or (1 if leg.get("type") == "STK" else 100))


def pnl(legs: list[dict], spot: float, as_of, iv_shift: float = 0.0, r: float = RISK_FREE) -> float:
    return sum((leg_value(l, spot, as_of, iv_shift, r) - float(l.get("entry") or 0)) * float(l["qty"]) * _mult(l)
               for l in legs)


def value(legs: list[dict], spot: float, as_of, iv_shift: float = 0.0, r: float = RISK_FREE) -> float:
    return sum(leg_value(l, spot, as_of, iv_shift, r) * float(l["qty"]) * _mult(l) for l in legs)


def greeks(legs: list[dict], spot: float, as_of, r: float = RISK_FREE) -> dict:
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        n = float(l["qty"]) * _mult(l)
        if l.get("type") == "STK":
            out["delta"] += n
            continue
        g = bs_greeks(spot, float(l["strike"]), years(l["expiry"], as_of), float(l.get("iv") or 0.3), l["right"], r)
        for k in out:
            out[k] += g.get(k, 0.0) * n
    return out          # $ per $1 spot (delta, gamma), $ per day (theta), $ per 1 vol point (vega)


def _breakevens(xs: list[float], ys: list[float]) -> list[float]:
    out = []
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if y0 == 0:
            out.append(x0)
        elif y0 * y1 < 0:
            out.append(x0 + (x1 - x0) * (-y0) / (y1 - y0))
    return [round(x, 2) for x in out]


def profile(legs: list[dict], spot: float, as_of=None, r: float = RISK_FREE, width: float = 0.4, points: int = 81,
            day_steps: tuple[int, ...] = (0, 7, 14, 30), moves=MOVES, iv_shifts=IV_SHIFTS) -> dict:
    """Curves (P&L vs spot) today, at each day step and at the first expiry; breakevens; max profit/loss inside the
    plotted range; net greeks; scenario grids (spot move × IV shift) for each day step and at expiry."""
    as_of = _d(as_of or date.today())
    expiries = sorted(_d(l["expiry"]) for l in legs if l.get("type", "OPT") == "OPT")
    first_exp = expiries[0] if expiries else as_of
    xs = [spot * (1 - width + 2 * width * i / (points - 1)) for i in range(points)]
    steps = sorted({d for d in day_steps if as_of + timedelta(days=d) < first_exp} | {0})
    dates = {f"+{d}d": as_of + timedelta(days=d) for d in steps}
    dates["expiry"] = first_exp
    curves = {k: [round(pnl(legs, x, d, 0.0, r), 2) for x in xs] for k, d in dates.items()}
    exp_curve = curves["expiry"]
    grids = {}
    for k, d in dates.items():
        grids[k] = [[round(pnl(legs, spot * (1 + m), d, s, r), 2) for s in iv_shifts] for m in moves]
    cost = sum(float(l.get("entry") or 0) * float(l["qty"]) * _mult(l) for l in legs)
    return {"as_of": as_of.isoformat(), "spot": spot, "rate": r, "first_expiry": first_exp.isoformat(),
            "spots": [round(x, 4) for x in xs], "curves": curves, "breakevens": _breakevens(xs, exp_curve),
            "max_profit_in_range": max(exp_curve), "max_loss_in_range": min(exp_curve),
            "unbounded_upside": exp_curve[-1] > exp_curve[-2] + 1e-9, "unbounded_downside_risk": exp_curve[0] < exp_curve[1] - 1e-9,
            "pnl_now": round(pnl(legs, spot, as_of, 0.0, r), 2), "value_now": round(value(legs, spot, as_of, 0.0, r), 2),
            "net_entry_cost": round(cost, 2), "greeks": greeks(legs, spot, as_of, r),
            "scenarios": {"moves": list(moves), "iv_shifts": list(iv_shifts), "grids": grids}}
