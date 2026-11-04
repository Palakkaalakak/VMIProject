"""Offline calibration grid: collect valuation inputs once, then evaluate many estimator strategies fast.

    PYTHONPATH=. python tools/calib_grid.py collect     # fetch inputs → data/calib_inputs.json
    PYTHONPATH=. python tools/calib_grid.py eval        # score strategies vs Adam's IVs
"""
from __future__ import annotations

import itertools
import json
import sys

from vmi.config import get_settings

INPUTS = get_settings().data_dir / "calib_inputs.json"


def collect() -> None:
    from vmi.analysis.calibrate import load_reference
    from vmi.analysis.consistency import consistent
    from vmi.analysis.valuation.methods import ValuationContext, capex_is_lumpy, normalised_fcf
    from vmi.analysis.classify import classify
    from vmi.data import market
    from vmi.data.estimates import get_estimates
    from vmi.data.fundamentals import resolve

    ref = load_reference()
    rows = []
    for sym, r in ref.items():
        if not r["iv"] or not sym.isalpha():
            continue
        try:
            f = resolve(sym)
            e = get_estimates(sym)
            px = market.last_price(sym) or 0
            ctx = ValuationContext(f, e, px, None)
            rev, eps = f.series("revenue")[-6:], f.series("eps_diluted")[-6:]

            def cagr(v):
                return (v[-1] / v[0]) ** (1 / (len(v) - 1)) - 1 if len(v) >= 3 and v[0] > 0 and v[-1] > 0 else None
            biz = classify(f.sic, f.sic_description, e.sector, e.industry).value
            rows.append({
                "s": sym, "adam": r["iv"], "price": px, "biz": biz, "currency": f.currency,
                "fcf": f.last("fcf"), "norm": normalised_fcf(f), "lumpy": capex_is_lumpy(f),
                "cfo": f.last("cfo"), "ni": f.last("net_income"),
                "cfo_ok": consistent(f, "cfo"), "ni_ok": consistent(f, "net_income"),
                "g5": {k: v.get("eps_growth_5y") for k, v in e.sources.items()},
                "g1": {k: v.get("eps_growth_next_year") for k, v in e.sources.items()},
                "rev_cagr": cagr(rev), "eps_cagr": cagr(eps), "rev_next": e.revenue_growth_next_year,
                "beta": e.beta, "rate": ctx.rate, "debt": ctx.debt, "cash": ctx.cash, "shares": ctx.shares,
            })
            print("ok", sym, flush=True)
        except Exception as exc:
            print("ERR", sym, exc, flush=True)
    INPUTS.write_text(json.dumps(rows, indent=1, default=str))


# ------------------------------------------------------------------------------------- strategies
def growth_est(r: dict, mode: str) -> float | None:
    vals = sorted(v for v in r["g5"].values() if v is not None and -0.2 < v < 1.0)
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2
    lo = vals[0]
    if mode == "mean":
        return mean
    if mode == "median":
        return med
    if mode == "low":
        return lo
    if mode == "robust":  # mean, but when sources disagree by >6pp lean to the low side
        return mean if vals[-1] - lo <= 0.06 else lo + (vals[-1] - lo) / 3
    if mode == "robust_hist":  # robust, but never above max(historical EPS CAGR, revenue CAGR) + 5pp
        g = mean if vals[-1] - lo <= 0.06 else lo + (vals[-1] - lo) / 3
        hist = [x for x in (r.get("rev_cagr"), r.get("eps_cagr")) if x is not None]
        if hist:
            g = min(g, max(hist) + 0.05)
        return g
    raise ValueError(mode)


def base_est(r: dict, mode: str) -> float | None:
    b = r["norm"] if r["lumpy"] else r["fcf"]
    ni = r["ni"]
    if b is None:
        return None
    if mode == "plain":
        return b
    if mode.startswith("cap"):  # cap the cash-flow base at k × net income (float / SBC / WC inflation)
        k = float(mode[3:])
        return min(b, k * ni) if ni and ni > 0 else b
    raise ValueError(mode)


def iv(r: dict, g: float, base: float, cap1: float, m6: float) -> float | None:
    from vmi.analysis.valuation.core import GrowthPath, discounted_value

    g1 = min(g, cap1)
    return discounted_value(base, GrowthPath(g1, min(g1 * m6, 0.15), 0.04), r["rate"], r["debt"], r["cash"],
                            r["shares"])


def shrink(g: float, center: float, k: float) -> float:
    return center + k * (g - center)


def evaluate_shrink() -> None:
    """Grid over growth shrinkage toward a center (analyst LTG mean reversion) + base mode."""
    rows = [r for r in json.loads(INPUTS.read_text()) if r["biz"] not in ("bank", "reit")]
    results = []
    for center, k, bm, hc in itertools.product([0.10, 0.11, 0.12, 0.13, 0.14], [0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
                                               ["plain", "cap1.5", "cap2.0"], [1.0, 0.97, 0.94]):
        ratios = []
        for r in rows:
            g, b = growth_est(r, "robust_hist"), base_est(r, bm)
            if g is None or not b or b <= 0 or not r["shares"]:
                continue
            v = iv(r, shrink(g, center, k) * hc, b, 0.40, 1.0)
            if v and v > 0:
                ratios.append(v / r["adam"])
        xs = sorted(ratios)
        n = len(xs)
        if not n:
            continue
        good = sum(1 for x in xs if 0.85 <= x <= 1.05)
        over = sum(1 for x in xs if x > 1.10)
        med = xs[n // 2]
        score = good - 1.5 * over - 10 * abs(med - 0.95)
        results.append((round(score, 2), center, k, bm, hc, n, good, over, round(med, 3)))
    results.sort(reverse=True)
    print("score, center, k, base, haircut, n, in[0.85,1.05], >1.10, median")
    for x in results[:12]:
        print(x)


def evaluate() -> None:
    rows = [r for r in json.loads(INPUTS.read_text()) if r["biz"] not in ("bank", "reit")]
    results = []
    for gm, bm, cap1, m6, hc in itertools.product(
            ["mean", "median", "robust", "robust_hist", "low"], ["plain", "cap1.2", "cap1.5", "cap2.0"],
            [0.30, 0.35, 0.40], [1.0, 0.85], [1.0, 0.95]):
        ratios = []
        for r in rows:
            g, b = growth_est(r, gm), base_est(r, bm)
            if g is None or not b or b <= 0 or not r["shares"]:
                continue
            v = iv(r, g * hc, b, cap1, m6)
            if v and v > 0:
                ratios.append((r["s"], v / r["adam"]))
        xs = sorted(x for _, x in ratios)
        n = len(xs)
        if not n:
            continue
        good = sum(1 for x in xs if 0.80 <= x <= 1.05)
        over = sum(1 for x in xs if x > 1.10)
        # objective: maximise in-band count, heavily penalise over-valuation, keep median slightly <1
        med = xs[n // 2]
        score = good - 1.5 * over - 10 * abs(med - 0.93)
        results.append((round(score, 2), gm, bm, cap1, m6, hc, n, good, over, round(med, 3)))
    results.sort(reverse=True)
    print("score, growth, base, cap1_5, m6_10, haircut, n, in[0.8,1.05], >1.10, median")
    for x in results[:15]:
        print(x)


def detail(gm: str, bm: str, cap1: float, m6: float, hc: float) -> None:
    rows = [r for r in json.loads(INPUTS.read_text()) if r["biz"] not in ("bank", "reit")]
    for r in rows:
        g, b = growth_est(r, gm), base_est(r, bm)
        if g is None or not b or b <= 0 or not r["shares"]:
            print(f"{r['s']:6s} n/a  g={g} base={b}")
            continue
        v = iv(r, g * hc, b, cap1, m6)
        print(f"{r['s']:6s} ratio={v / r['adam']:5.2f} ours={v:9.1f} adam={r['adam']:8.1f} g={g:.3f} "
              f"base={b / 1e9:7.2f}B ni={(r['ni'] or 0) / 1e9:6.2f}B cur={r['currency']} g5={r['g5']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if cmd == "collect":
        collect()
    elif cmd == "shrink":
        evaluate_shrink()
    elif cmd == "detail":
        a = sys.argv[2:]
        detail(a[0], a[1], float(a[2]), float(a[3]), float(a[4]))
    else:
        evaluate()
