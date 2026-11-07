"""Flag intrinsic values that are probably too HIGH compared with Adam's (our heuristic, NOT an Adam rule).

Rule: the selected IV is `SPREAD`× or more above the lowest credible alternative method. A comparator counts only when it
is meaningful for the company:
  - net-income DCF (DNI): net income is credible only if FCF <= 2× net income (SBC / tax effects make NI useless beyond that);
  - mean P/S: only below 15% growth (price-based, it always undervalues fast growers);
  - cash-flow DCF: when the selected method is a different one.
Measured on the 42 reference stocks with Adam's own growth (Log.md 2026-11-07): 5 of the 7 stocks we value >30% above
Adam were flagged (BKNG, VEEV, DSGX, ACGL, NVO), 8 stocks flagged in all, 2 of them within ~15% of Adam. Three thresholds were
read off the same 42 stocks, so expect it to be weaker on new ones. Too-LOW values (conservative) are not flagged.
Warning only: never changes the IV or any step.
"""
from __future__ import annotations

SPREAD = 1.5
PS_MAX_GROWTH = 0.15
DNI_MAX_FCF_TO_NI = 2.0
CASH_FLOW_METHODS = ("dcf_fcf", "dcf_normalized")


def iv_confidence(methods: dict, selected: str | None, growth: float | None, fcf: float | None,
                  net_income: float | None) -> dict:
    """methods = ValuationReport.to_dict()["methods"]. Returns {"low": bool, "ratio": float|None, "reasons": [...]}."""
    def value(m):
        r = methods.get(m) or {}
        return r["intrinsic_value"] if r.get("applicable") and (r.get("intrinsic_value") or 0) > 0 else None

    sel = value(selected) if selected in (*CASH_FLOW_METHODS, "dni", "ps_mean") else None
    if sel is None:
        return {"low": False, "ratio": None, "reasons": []}
    alt = {}
    if selected not in CASH_FLOW_METHODS and value("dcf_fcf"):
        alt["dcf_fcf"] = value("dcf_fcf")
    if selected != "dni" and value("dni") and net_income and net_income > 0 and (fcf or 0) <= DNI_MAX_FCF_TO_NI * net_income:
        alt["dni"] = value("dni")
    if selected != "ps_mean" and value("ps_mean") and growth is not None and growth < PS_MAX_GROWTH:
        alt["ps_mean"] = value("ps_mean")
    if not alt:
        return {"low": False, "ratio": None, "reasons": []}
    low = min(alt, key=alt.get)
    ratio = sel / alt[low]
    reasons = []
    if ratio >= SPREAD:
        reasons.append(f"{selected} {sel:,.0f} is {ratio:.1f}× the {low} value {alt[low]:,.0f}; the choice of method/base "
                       "decides this result, so it may be well above Adam's")
    return {"low": bool(reasons), "ratio": round(ratio, 2), "reasons": reasons}
