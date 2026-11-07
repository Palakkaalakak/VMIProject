"""Two-sleeve withdrawal simulator (all values REAL, portfolio starts at 1.0).

Growth sleeve  : a monthly real-return series (a strategy, see strategies()).
Reserve sleeve : cash / 10y Treasuries; holds `reserve_years` × the annual withdrawal.
Rules (decided once a year, at month 0, 12, 24 …):
  - "reserve mode" when the growth sleeve is in trouble (drawdown from its high-water mark > `dd_trigger`, or its last
    12 months were below `neg12`): that year's withdrawals come from the reserve (growth sleeve untouched);
  - otherwise withdrawals come from the growth sleeve, and if the growth sleeve is within `replenish_dd` of its high
    and returned more than `replenish_min`, the reserve is topped up to target from the growth sleeve (at most
    `replenish_cap` of it per year).
  - if the reserve cannot cover a withdrawal, the rest comes from the growth sleeve; if both are empty: ruin.
All paths are simulated at once (numpy over paths); a path is one 30-year sequence of monthly real returns.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from vmi.research import data

MONTHS = 12


@dataclass(frozen=True)
class Plan:
    withdrawal: float            # initial annual withdrawal, fraction of starting capital (real, constant)
    reserve_years: float = 0.0   # reserve target = this many years of withdrawals
    cash_share: float = 1.0      # reserve split cash vs 10y bonds
    dd_trigger: float = 0.10     # reserve mode if growth sleeve is this far under its high
    neg12: float | None = None   # …or if its trailing-12m real return is below this (None: ignore)
    replenish_dd: float = 0.02
    replenish_min: float = 0.0
    replenish_cap: float = 0.25


def required_real_return(w: float, g: float, years: int = 30) -> float:
    """Constant real return needed so that, after withdrawing w (real, constant) each year, capital grows g real a year."""
    lo, hi = -0.05, 0.30
    for _ in range(80):
        r = (lo + hi) / 2
        v = 1.0
        for _ in range(years):
            v = v * (1 + r) - w
        if v < (1 + g) ** years:
            lo = r
        else:
            hi = r
    return r


def simulate(growth: np.ndarray, bond: np.ndarray, cash: np.ndarray, plan: Plan) -> dict[str, np.ndarray]:
    """growth/bond/cash: [paths, months] real monthly returns. Returns per-path metrics."""
    n, T = growth.shape
    a = plan.withdrawal / MONTHS
    target = plan.reserve_years * plan.withdrawal
    R = np.full(n, target)
    G = np.full(n, 1.0 - target)
    gi = np.ones(n)                       # growth-sleeve return index (flow-free)
    hwm = np.ones(n)
    gi_year = np.ones(n)
    ti = np.ones(n)                       # total-portfolio return index (flow-free)
    ti_peak = np.ones(n)
    ti_dd = np.zeros(n)
    v_peak = np.ones(n)
    v_dd = np.zeros(n)
    under = np.zeros(n)
    under_max = np.zeros(n)
    from_reserve = np.zeros(n)
    short = np.zeros(n)                   # months a reserve-mode withdrawal could not be fully paid by the reserve
    ruined = np.zeros(n, dtype=bool)
    reserve_mode = np.zeros(n, dtype=bool)
    worst_year = np.zeros(n)
    year_start_ti = np.ones(n)
    neg_years = np.zeros(n)
    rr_mix = plan.cash_share * cash + (1 - plan.cash_share) * bond
    for t in range(T):
        if t % MONTHS == 0:               # yearly decision
            dd = 1 - gi / hwm
            tr12 = gi / gi_year - 1
            reserve_mode = (dd > plan.dd_trigger) & (target > 0)
            if plan.neg12 is not None:
                reserve_mode |= (tr12 < plan.neg12) & (target > 0)
            if t > 0:
                yr = ti / year_start_ti - 1
                worst_year = np.minimum(worst_year, yr)
                neg_years += yr < 0
            year_start_ti = ti.copy()
            gi_year = gi.copy()
            ok = (~reserve_mode) & (dd <= plan.replenish_dd) & (tr12 >= plan.replenish_min) & (target > 0) & (t > 0)
            move = np.where(ok, np.minimum(np.maximum(target - R, 0.0), plan.replenish_cap * G), 0.0)
            G -= move
            R += move
        # market moves
        tot_before = G + R
        G = G * (1 + growth[:, t])
        R = R * (1 + rr_mix[:, t])
        gi *= 1 + growth[:, t]
        hwm = np.maximum(hwm, gi)
        tot_after = G + R
        alive = tot_before > 0
        ti = np.where(alive, ti * np.divide(tot_after, tot_before, out=np.ones(n), where=alive), ti)
        # withdrawal
        pay_r = np.where(reserve_mode, np.minimum(R, a), 0.0)
        R -= pay_r
        rest = a - pay_r
        pay_g = np.minimum(G, rest)
        G -= pay_g
        gap = rest - pay_g                # still unpaid: take from reserve even in normal mode
        pay_r2 = np.minimum(R, gap)
        R -= pay_r2
        gap -= pay_r2
        ruined |= gap > 1e-12
        from_reserve += (pay_r + pay_r2) > 0
        short += reserve_mode & (pay_r < a - 1e-12)
        G = np.where(ruined, 0.0, G)
        R = np.where(ruined, 0.0, R)
        v = G + R
        v_peak = np.maximum(v_peak, v)
        v_dd = np.maximum(v_dd, 1 - v / v_peak)
        under = np.where(v >= v_peak - 1e-12, 0.0, under + 1)
        under_max = np.maximum(under_max, under)
        ti_peak = np.maximum(ti_peak, ti)
        ti_dd = np.maximum(ti_dd, 1 - ti / ti_peak)
    years = T / MONTHS
    return {"final": G + R, "ruined": ruined, "cagr": np.where(G + R > 0, (G + R) ** (1 / years) - 1, -1.0),
            "mdd": ti_dd, "capital_mdd": v_dd, "underwater_months": under_max, "reserve_share": from_reserve / T,
            "reserve_short": short, "worst_year": worst_year, "neg_years": neg_years / years,
            "total_real_cagr": ti ** (1 / years) - 1}


def summarise(res: dict[str, np.ndarray], g_target: float, years: int) -> dict[str, float]:
    final = res["final"]
    need = (1 + g_target) ** years
    ok = (~res["ruined"]) & (final >= need)
    pct = lambda x, q: float(np.percentile(x, q))
    return {"p_target": float(ok.mean()), "p_ruin": float(res["ruined"].mean()),
            "p_real_growth": float(((~res["ruined"]) & (final > 1.0)).mean()),
            "cagr_p10": pct(res["cagr"], 10), "cagr_p50": pct(res["cagr"], 50), "cagr_p90": pct(res["cagr"], 90),
            "final_p10": pct(final, 10), "final_p50": pct(final, 50),
            "mdd_p50": pct(res["mdd"], 50), "mdd_p90": pct(res["mdd"], 90),
            "capital_mdd_p50": pct(res["capital_mdd"], 50),
            "underwater_years_p90": pct(res["underwater_months"], 90) / MONTHS,
            "reserve_use": float(res["reserve_share"].mean()), "reserve_short": float((res["reserve_short"] > 0).mean()),
            "neg_years": float(res["neg_years"].mean()), "worst_year_p10": pct(res["worst_year"], 10)}


# --------------------------------------------------------------------------------------------- scenarios
def real_matrix(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame({c: data.real(df[c], df["infl"]) for c in cols})
    return out.dropna()


def rolling_paths(arr: np.ndarray, months: int, step: int = 12) -> np.ndarray:
    """Historical windows: arr [T, k] → [windows, months, k] (start every `step` months)."""
    starts = range(0, arr.shape[0] - months + 1, step)
    return np.stack([arr[s:s + months] for s in starts])


def bootstrap_paths(arr: np.ndarray, months: int, n: int, block: int = 60, seed: int = 7) -> np.ndarray:
    """Stationary-style block bootstrap of joint monthly vectors (keeps cross-asset correlation, ~5y regimes)."""
    rng = np.random.default_rng(seed)
    T = arr.shape[0]
    out = np.empty((n, months, arr.shape[1]))
    for i in range(n):
        got = 0
        while got < months:
            s = rng.integers(0, T - block + 1)
            take = min(block, months - got)
            out[i, got:got + take] = arr[s:s + take]
            got += take
    return out
