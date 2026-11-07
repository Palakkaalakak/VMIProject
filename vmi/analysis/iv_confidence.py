"""Flag intrinsic values that are probably too HIGH compared with Adam's (our heuristic, NOT an Adam rule).

Rule: the selected IV is `iv_flag_ratio`× (1.3) or more above the lowest credible alternative method. A comparator counts
only when it is meaningful for the company:
  - net-income DCF (DNI): FCF <= 2× net income (SBC / tax effects make NI useless beyond that) and TTM net income not a
    sudden jump (> 1.5× last FY, Adam's "abnormal latest period" idea, l.2502);
  - mean P/S: only below 15% growth (price-based, it always undervalues fast growers);
  - cash-flow DCF: when the selected method is a different one.
Measured on the 42 reference stocks with Adam's own growth (Log.md 2026-11-07): 9 flagged, 7 of them >30% off Adam
(6 of the 7 we value too high: BKNG, VEEV, DSGX, ACGL, NVO, UNH; missed NKE), 2 within ~18% (AZO, LVMUY). Thresholds were read off
the same 42 stocks, so expect it to be weaker on new ones. Too-LOW values (conservative) are not flagged.
Warning only: never changes the IV or any step. Switch: rules.valuation.iv_flag_enabled (Settings page).
"""
from __future__ import annotations

CASH_FLOW_METHODS = ("dcf_fcf", "dcf_normalized")
OFF = {"low": False, "ratio": None, "reasons": []}


def iv_confidence(methods: dict, selected: str | None, growth: float | None, fcf: float | None,
                  net_income: float | None, net_income_last_fy: float | None, rules) -> dict:
    """methods = ValuationReport.to_dict()["methods"]; rules = ValuationRules (thresholds + the on/off switch).
    Returns {"low": bool, "ratio": float|None, "reasons": [...]}."""
    if not rules.iv_flag_enabled:
        return dict(OFF)

    def value(m):
        r = methods.get(m) or {}
        return r["intrinsic_value"] if r.get("applicable") and (r.get("intrinsic_value") or 0) > 0 else None

    sel = value(selected) if selected in (*CASH_FLOW_METHODS, "dni", "ps_mean") else None
    if sel is None:
        return dict(OFF)
    ni_normal = bool(net_income and net_income > 0 and (fcf or 0) <= rules.iv_flag_dni_max_fcf_to_ni * net_income
                     and not (net_income_last_fy and net_income > rules.iv_flag_ni_jump * net_income_last_fy))
    alt = {}
    if selected not in CASH_FLOW_METHODS and value("dcf_fcf"):
        alt["dcf_fcf"] = value("dcf_fcf")
    if selected != "dni" and value("dni") and ni_normal:
        alt["dni"] = value("dni")
    if selected != "ps_mean" and value("ps_mean") and growth is not None and growth < rules.iv_flag_ps_max_growth:
        alt["ps_mean"] = value("ps_mean")
    if not alt:
        return dict(OFF)
    low = min(alt, key=alt.get)
    ratio = sel / alt[low]
    reasons = []
    if ratio >= rules.iv_flag_ratio:
        reasons.append(f"{selected} {sel:,.0f} is {ratio:.1f}× the {low} value {alt[low]:,.0f}; the choice of method/base "
                       "decides this result, so it may be well above Adam's")
    return {"low": bool(reasons), "ratio": round(ratio, 2), "reasons": reasons}
