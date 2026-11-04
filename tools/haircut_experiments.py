"""Single-knob conservatism experiments vs Adam's reference IVs (owner request 2026-11-04).

Each variant applies ONE fixed number to ONE place in Adam's DCF — nothing per-company, nothing fitted
as a formula. We compare where the haircut is applied:

  iv        IV × (1 − h)                         flat cut on the final intrinsic value
  g_rel     growth(1–5) × (1 − h)                relative cut on the consensus growth rate
  g_abs     growth(1–5) − h (percentage points)  absolute cut on the consensus growth rate
  rate      discount rate + h                    flat add-on to Adam's beta-table rate
  term2     years 11–20 growth = 2%              Adam's own conservative option (no knob)
  low_src   lowest source instead of average     Adam's own "conservative case" (no knob)

Only discounted-stream valuations (DCF FCF / normalised / CFO / DNI) are used — the haircut does not
apply to P/B, P/S or PSG valuations. Metrics: median ours/Adam, count within [0.85, 1.05], count above
1.10 (over-valuation = dangerous), and spread (IQR of log ratio — a knob that only shifts the median
cannot reduce spread; one that hits high-growth names harder can).

    PYTHONPATH=. python tools/haircut_experiments.py collect   # → data/haircut_inputs.json
    PYTHONPATH=. python tools/haircut_experiments.py eval      # → prints table, data/haircut_results.json
"""
from __future__ import annotations

import json
import math
import sys

from vmi.analysis.valuation.core import GrowthPath, discounted_value, growth_path
from vmi.config import get_settings

DATA = get_settings().data_dir
INPUTS = DATA / "haircut_inputs.json"
RESULTS = DATA / "haircut_results.json"
DCF = {"dcf_fcf", "dcf_normalized", "dcf_cfo", "dni"}


def collect() -> None:
    from vmi.analysis.calibrate import load_reference
    from vmi.analysis.pipeline import analyse_ticker

    ref = load_reference()
    rows = json.loads(INPUTS.read_text()) if INPUTS.exists() else []
    done = {r["s"] for r in rows}
    for sym, r in ref.items():
        if not r["iv"] or not sym.isalpha() or sym in done:
            continue
        try:
            rep = analyse_ticker(sym, with_technicals=False)
        except Exception as exc:
            print("ERR", sym, exc, flush=True)
            continue
        v = rep["valuation"]
        sel = v.get("selected")
        m = (v.get("methods") or {}).get(sel) or {}
        inp = m.get("inputs") or {}
        srcs = [x.get("eps_growth_5y") for x in (inp.get("growth_sources") or {}).values()]
        srcs = [x for x in srcs if x is not None and -0.2 < x < 1.0]
        rows.append({"s": sym, "adam": r["iv"], "price": rep["price"], "method": sel,
                     "base": inp.get("base_cash_flow"), "debt": inp.get("debt"), "cash": inp.get("cash"),
                     "shares": inp.get("shares"), "rate": inp.get("discount_rate"), "g": inp.get("growth_1_5"),
                     "g_low": min(srcs) if srcs else inp.get("growth_1_5"),
                     "our_iv_current": rep.get("intrinsic_value")})
        INPUTS.write_text(json.dumps(rows, indent=1))   # incremental: survives interruption
        print("ok", sym, sel, flush=True)


def _iv(r: dict, g: float, rate: float, g11: float = 0.04) -> float | None:
    if None in (r["base"], r["debt"], r["cash"], r["shares"]) or not r["base"] or r["base"] <= 0:
        return None
    return discounted_value(r["base"], growth_path(g, g11_20=g11), rate, r["debt"], r["cash"], r["shares"])


def variant(r: dict, kind: str, h: float) -> float | None:
    g, rate = r["g"], r["rate"]
    if g is None or rate is None:
        return None
    if kind == "none":
        return _iv(r, g, rate)
    if kind == "iv":
        v = _iv(r, g, rate)
        return v * (1 - h) if v else None
    if kind == "g_rel":
        return _iv(r, g * (1 - h), rate)
    if kind == "g_abs":
        return _iv(r, g - h, rate)
    if kind == "rate":
        return _iv(r, g, rate + h)
    if kind == "term2":
        return _iv(r, g, rate, g11=0.02)
    if kind == "low_src":
        return _iv(r, r["g_low"], rate)
    raise ValueError(kind)


def stats(ratios: list[float]) -> dict:
    xs = sorted(ratios)
    n = len(xs)
    if not n:
        return {}
    logs = sorted(math.log(x) for x in xs)
    iqr = logs[int(0.75 * (n - 1))] - logs[int(0.25 * (n - 1))]
    return {"n": n, "median": round(xs[n // 2], 3), "in_0.85_1.05": sum(0.85 <= x <= 1.05 for x in xs),
            "within_15pct": sum(0.85 <= x <= 1.15 for x in xs), "over_1.10": sum(x > 1.10 for x in xs),
            "under_0.75": sum(x < 0.75 for x in xs), "log_iqr": round(iqr, 3),
            "mean_abs_log_err": round(sum(abs(l) for l in logs) / n, 3)}


GRID = {"iv": [0.0, 0.05, 0.10, 0.15, 0.20], "g_rel": [0.0, 0.10, 0.15, 0.20, 0.25, 0.30],
        "g_abs": [0.0, 0.01, 0.02, 0.03, 0.04], "rate": [0.0, 0.005, 0.01, 0.015, 0.02],
        "term2": [0.0], "low_src": [0.0]}


def evaluate(exclude: set[str] | None = None) -> dict:
    rows = [r for r in json.loads(INPUTS.read_text()) if r["method"] in DCF and r["s"] not in (exclude or set())]
    out: dict = {"tickers": [r["s"] for r in rows], "variants": {}, "per_ticker": {}}
    for kind, hs in GRID.items():
        for h in hs:
            ratios, per = [], {}
            for r in rows:
                v = variant(r, kind, h)
                if v and v > 0:
                    ratios.append(v / r["adam"])
                    per[r["s"]] = round(v / r["adam"], 3)
            key = f"{kind}:{h:g}"
            out["variants"][key] = stats(ratios)
            out["per_ticker"][key] = per
    return out


def print_table(res: dict) -> None:
    print(f"DCF/DNI-valued reference tickers: {len(res['tickers'])}")
    print(f"{'variant':12s} {'median':>7s} {'in.85-1.05':>10s} {'±15%':>5s} {'>1.10':>6s} {'<0.75':>6s} "
          f"{'logIQR':>7s} {'MAE(log)':>8s}")
    for k, s in res["variants"].items():
        if s:
            print(f"{k:12s} {s['median']:7.3f} {s['in_0.85_1.05']:10d} {s['within_15pct']:5d} {s['over_1.10']:6d} "
                  f"{s['under_0.75']:6d} {s['log_iqr']:7.3f} {s['mean_abs_log_err']:8.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if cmd == "collect":
        collect()
    else:
        excl = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()
        res = evaluate(excl)
        print_table(res)
        RESULTS.write_text(json.dumps(res, indent=1))
