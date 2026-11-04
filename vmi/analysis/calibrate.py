"""Calibration harness: compare our intrinsic values with Adam's reference numbers.

    PYTHONPATH=. python -m vmi.analysis.calibrate            # all US tickers in the fixture
    PYTHONPATH=. python -m vmi.analysis.calibrate AAPL MSFT

Target: ours / Adam in roughly [0.85, 1.02] — conservative side preferred.
Results are written to data/calibration.json for tracking across changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vmi.config import ROOT, get_settings

REF = ROOT / "tests" / "fixtures" / "adam_reference.txt"


def load_reference(path: Path = REF) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym, sup, iv = line.split("|")
        out[sym] = {"supports": [float(x) for x in sup.split(",") if x], "iv": float(iv) if iv else None}
    return out


def run(symbols: list[str] | None = None, with_technicals: bool = False) -> list[dict]:
    from vmi.analysis.pipeline import analyse_ticker

    ref = load_reference()
    rows = []
    for sym, r in ref.items():
        if symbols and sym not in symbols:
            continue
        if not r["iv"] or not sym.isalpha():
            continue
        try:
            rep = analyse_ticker(sym, with_technicals=with_technicals)
        except Exception as exc:
            rows.append({"symbol": sym, "error": f"{type(exc).__name__}: {exc}"[:160]})
            continue
        v = rep["valuation"]
        iv = rep["intrinsic_value"]
        sel = (v.get("methods") or {}).get(v.get("selected")) or {}
        rows.append({"symbol": sym, "adam_iv": r["iv"], "our_iv": round(iv, 2) if iv else None,
                     "ratio": round(iv / r["iv"], 3) if iv else None, "method": v.get("selected"),
                     "biz": rep["biz_type"], "growth": sel.get("inputs", {}).get("growth_1_5"),
                     "price": round(rep["price"], 2),
                     "our_levels": [b["price"] for b in (rep.get("technicals") or {}).get("buy_levels", [])],
                     "adam_levels": r["supports"]})
    return rows


def summarise(rows: list[dict]) -> dict:
    ratios = sorted(r["ratio"] for r in rows if r.get("ratio"))
    if not ratios:
        return {}
    return {"n": len(ratios), "median_ratio": ratios[len(ratios) // 2],
            "in_band_0.85_1.02": sum(1 for x in ratios if 0.85 <= x <= 1.02),
            "within_15pct": sum(1 for x in ratios if 0.85 <= x <= 1.15),
            "above_1.05": sum(1 for x in ratios if x > 1.05), "below_0.75": sum(1 for x in ratios if x < 0.75)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--tech", action="store_true")
    a = ap.parse_args()
    rows = run([s.upper() for s in a.symbols] or None, a.tech)
    for r in rows:
        print(json.dumps(r, default=str))
    summ = summarise(rows)
    print(json.dumps(summ))
    (get_settings().data_dir / "calibration.json").write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))
