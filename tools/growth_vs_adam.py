"""Compare our blended consensus growth (years 1-5) against Adam's "Avg. Growth Rate" per ticker, and show
what our DCF IV becomes if fed Adam's growth (isolates growth-input error from model/cash-flow error).

Usage: python3 tools/growth_vs_adam.py            (uses data/haircut_inputs.json for DCF inputs)
Output: data/growth_vs_adam.json + printed table.
"""
from __future__ import annotations

import json
import statistics as st
from pathlib import Path

from vmi.analysis.valuation.core import discounted_value, growth_path
from vmi.rules import RULES

ROOT = Path(__file__).resolve().parents[1]


def load_adam() -> dict[str, dict]:
    out = {}
    for line in (ROOT / "tests/fixtures/adam_growth_reference.tsv").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        t, price, iv, g = (line.split("\t") + ["", "", ""])[:4]
        out[t] = {"price": float(price), "iv": float(iv) if iv else None, "g": float(g) if g else None}
    return out


def iv_with(inp: dict, g: float, haircut: float) -> float | None:
    v = discounted_value(inp["base"], growth_path(g), inp["rate"], inp["debt"], inp["cash"], inp["shares"])
    return None if v is None else v * (1 - haircut)


def main() -> None:
    adam = load_adam()
    inputs = {d["s"]: d for d in json.loads((ROOT / "data/haircut_inputs.json").read_text())}
    hc = RULES.valuation.iv_haircut
    rows = []
    for t, a in adam.items():
        inp = inputs.get(t)
        if not a["g"] or not inp or inp.get("g") is None:
            continue
        r = {"ticker": t, "adam_g": a["g"], "our_g": round(inp["g"], 4), "g_diff_pp": round((inp["g"] - a["g"]) * 100, 1),
             "adam_iv": a["iv"], "our_iv": round(inp["our_iv_current"], 2) if inp.get("our_iv_current") else None,
             "method": inp["method"]}
        if inp["method"] in ("dcf_fcf", "dcf_normalized", "dcf_cfo", "dni"):
            v = iv_with(inp, a["g"], hc)
            r["our_iv_with_adam_g"] = round(v, 2) if v else None
            r["ratio_with_adam_g"] = round(v / a["iv"], 3) if v and a["iv"] else None
        r["ratio"] = round(r["our_iv"] / a["iv"], 3) if r["our_iv"] and a["iv"] else None
        rows.append(r)
    rows.sort(key=lambda r: r["g_diff_pp"])
    print(f"{'tkr':6} {'adam_g':>7} {'our_g':>7} {'diff':>6}  {'ratio':>6} {'ratio@adamG':>11}  method")
    for r in rows:
        print(f"{r['ticker']:6} {r['adam_g']:7.1%} {r['our_g']:7.1%} {r['g_diff_pp']:+6.1f}  "
              f"{r['ratio'] or float('nan'):6.3f} {r.get('ratio_with_adam_g') or float('nan'):11.3f}  {r['method']}")
    diffs = [r["g_diff_pp"] for r in rows]
    ra = [r["ratio"] for r in rows if r.get("ratio")]
    rg = [r["ratio_with_adam_g"] for r in rows if r.get("ratio_with_adam_g")]
    summ = {"n": len(rows), "growth_diff_pp_median": st.median(diffs), "growth_diff_pp_mean": round(st.mean(diffs), 2),
            "within_2pp": sum(1 for d in diffs if abs(d) <= 2), "ratio_median": st.median(ra) if ra else None,
            "ratio_with_adam_growth_median": st.median(rg) if rg else None,
            "within_15pct_now": sum(1 for x in ra if 0.85 <= x <= 1.15),
            "within_15pct_with_adam_growth": sum(1 for x in rg if 0.85 <= x <= 1.15), "n_dcf": len(rg)}
    print(json.dumps(summ, indent=1))
    (ROOT / "data/growth_vs_adam.json").write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
