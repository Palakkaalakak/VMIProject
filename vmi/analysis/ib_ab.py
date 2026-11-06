"""A/B: what does IB's 5-year growth (EPSTRENDGR / LONG_TERM_GROWTH) change in the calibration vs Adam's IVs?

    python -m vmi.analysis.ib_ab [--judged] [TICKER ...]

Runs the calibration twice on the same cache: IB growth dropped (IB beta kept), then IB growth included. Everything
else is identical, so the differences are caused by that one source. Prints both summaries, then every stock whose
IV ratio moved by more than 0.02, biggest move first.
"""
from __future__ import annotations

import argparse
import json

from vmi.analysis import calibrate
from vmi.data import estimates


def _run(symbols, judged: bool, keep_ib_growth: bool) -> dict[str, dict]:
    real = estimates.SOURCES["ib"]

    def patched(ticker: str) -> dict:
        d = dict(real(ticker) or {})
        if not keep_ib_growth:
            d.pop("eps_growth_5y", None)
        return d

    estimates.SOURCES["ib"] = patched
    try:
        return {r["symbol"]: r for r in calibrate.run(symbols, False, judged)}
    finally:
        estimates.SOURCES["ib"] = real


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--judged", action="store_true")
    a = ap.parse_args()
    syms = [s.upper() for s in a.symbols] or None
    off, on = _run(syms, a.judged, False), _run(syms, a.judged, True)
    print("IB growth OFF:", json.dumps(calibrate.summarise(list(off.values()))))
    print("IB growth ON: ", json.dumps(calibrate.summarise(list(on.values()))))
    moved = []
    for s, r in on.items():
        o = off.get(s) or {}
        if r.get("ratio") and o.get("ratio") and abs(r["ratio"] - o["ratio"]) > 0.02:
            moved.append((abs(r["ratio"] - o["ratio"]), s, o, r))
    print(f"{len(moved)} stocks moved by > 0.02 (ratio = our IV / Adam's IV; 1.00 is a match):")
    for _, s, o, r in sorted(moved, reverse=True):
        print(f"  {s:6} ratio {o['ratio']:.3f} -> {r['ratio']:.3f}   growth {o.get('growth')} -> {r.get('growth')}   ({r['method']})")


if __name__ == "__main__":
    main()
