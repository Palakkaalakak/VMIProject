"""Flag intrinsic values that are unlikely to match Adam's (our own heuristic, NOT an Adam rule).

Why: on 42 reference stocks (docs/CALIBRATION.md, Log.md 2026-11-07) the DCF/DNI/P-S values of one company often
disagree widely, and those are the companies where our IV later turned out far from Adam's (BKNG, MELI, NVO ...).
When the applicable methods differ by `SPREAD` or more, the choice of method/base decides the answer, so the IV is
shown as "low confidence". Measured on that set: 89% of the large misses (>30%) were flagged; 2 of 15 unflagged
stocks were large misses. It is a warning only: it never changes the IV or any step.
"""
from __future__ import annotations

SPREAD = 1.5                      # max/min of the comparable method values
COMPARED = ("dcf_fcf", "dni", "ps_mean")


def iv_confidence(methods: dict, selected: str | None) -> dict:
    """methods = ValuationReport.to_dict()["methods"]. Returns {"low": bool, "spread": float|None, "reasons": [...]}."""
    use = ["dcf_normalized" if selected == "dcf_normalized" and m == "dcf_fcf" else m for m in COMPARED]
    vals = {}
    for m in use:
        r = methods.get(m) or {}
        if r.get("applicable") and (r.get("intrinsic_value") or 0) > 0:
            vals[m] = r["intrinsic_value"]
    if len(vals) < 2:
        return {"low": False, "spread": None, "reasons": []}
    hi, lo = max(vals, key=vals.get), min(vals, key=vals.get)
    spread = vals[hi] / vals[lo]
    reasons = []
    if spread >= SPREAD:
        reasons.append(f"methods disagree {spread:.1f}×: {hi} {vals[hi]:,.0f} vs {lo} {vals[lo]:,.0f}; "
                       "the result depends on which base/method is judged right, so it may not match Adam's")
    return {"low": bool(reasons), "spread": round(spread, 2), "reasons": reasons}
