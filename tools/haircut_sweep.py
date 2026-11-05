"""Sweep one rules setting across levels through the FULL model (judgements applied) vs Adam's IVs.

    PYTHONPATH=. python tools/haircut_sweep.py valuation.uncertainty_haircut 0 0.025 0.05 0.075 0.1 0.15
Prints, per level: median ours/Adam, within ±15 %, above 1.05 / 1.10 (risky side), below 0.75, spread.
"""
from __future__ import annotations

import math
import statistics
import sys

from vmi import store
from vmi.analysis.calibrate import load_reference
from vmi.analysis.pipeline import analyse_ticker
from vmi.rules import RULES


def evaluate(rules) -> dict:
    xs = []
    for sym, ref in load_reference().items():
        if not ref["iv"] or not sym.isalpha():
            continue
        try:
            r = analyse_ticker(sym, with_technicals=False, overrides=store.get_override(sym) or None, rules=rules)
        except Exception:
            continue
        if r["intrinsic_value"]:
            xs.append(r["intrinsic_value"] / ref["iv"])
    xs.sort()
    q = lambda p: xs[int(p * (len(xs) - 1))]  # noqa: E731
    return {"n": len(xs), "median": round(statistics.median(xs), 3), "within15": sum(0.85 <= x <= 1.15 for x in xs),
            "above105": sum(x > 1.05 for x in xs), "above110": sum(x > 1.10 for x in xs),
            "below075": sum(x < 0.75 for x in xs), "log_iqr": round(math.log(q(0.75) / q(0.25)), 3)}


def main(argv: list[str]) -> None:
    section, key = argv[0].split(".")
    for level in map(float, argv[1:]):
        print(f"{argv[0]}={level}: {evaluate(RULES.with_overrides({section: {key: level}}))}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
