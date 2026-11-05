"""Moat evidence computed from a company's own statements (Step 3). Evidence only: the verdict is the reviewer's.

Adam gives no numbers for "very high / average / low margins", so margins are shown, not graded. Two tests were
proposed by the assistant and approved by the owner (docs/MOAT_PROPOSALS.md): the pricing-power test and the
"review due" alert; their settings are in rules.moat and labelled in docs/CRITERIA_AUDIT.md. The alert follows
Adam's moat-deterioration signal: "profit margins decline consistently for at least 2–3 years" (master doc l.11030).

    margin_history(f)     gross / operating / net / free-cash-flow margin by year
    pricing_power(f)      did margin hold through the 2021–23 cost-inflation shock? (approved proposal #3)
    margin_decline(f)     profit margins and ROIC that fell N years in a row (approved proposal #7)
    switching_costs(f)    deferred revenue and contracted backlog relative to sales (recurring, prepaid business)
    intensity(f)          R&D / SG&A / capex as a share of sales (economies of scale, reinvestment)
    review_status(...)    the verdict's date and age, plus every reason it is due for a fresh look
"""
from __future__ import annotations

from datetime import date

from vmi.analysis.trends import mean
from vmi.data.models import Fundamentals
from vmi.rules import RULES, VMIRules

MARGINS = (("gross margin", "gross_profit"), ("operating margin", "operating_income"),
           ("net margin", "net_income"), ("free-cash-flow margin", "fcf"))
PROFIT_MARGINS = ("gross margin", "operating margin", "net margin")  # Adam's 'profit margins' (Steps 1 and 4)


def _ratio_by_year(f: Fundamentals, top: str, bottom: str = "revenue") -> dict[int, float]:
    """{calendar year the fiscal period ends in: top/bottom}."""
    den = {int(p.end[:4]): p.value for p in f.annual.get(bottom, []) if p.value}
    return {int(p.end[:4]): p.value / den[int(p.end[:4])] for p in f.annual.get(top, [])
            if int(p.end[:4]) in den}


def margin_history(f: Fundamentals, years: int = 10) -> dict[str, dict[int, float]]:
    """{margin name: {year: value}} for the last `years` years with data (empty series are left out)."""
    out = {}
    for label, concept in MARGINS:
        series = _ratio_by_year(f, concept)
        if series:
            out[label] = {y: round(series[y], 4) for y in sorted(series)[-years:]}
    return out


def pricing_power(f: Fundamentals, rules: VMIRules = RULES) -> dict:
    """Margin before vs during the stress window (default 2018–20 vs 2021–23, the cost-inflation shock).

    Gross margin is the measure; companies that report no gross profit (or too short a history, e.g. Visa) fall
    back to operating margin. held = the worst stress-year margin is within `pricing_tolerance` of the baseline
    average (or better). None when no measure has enough history; the reviewer then judges from the series."""
    m = rules.moat
    measure, margins = "gross_profit", _ratio_by_year(f, "gross_profit")
    covered = lambda d: (sum(y in d for y in m.pricing_baseline_years) >= 2  # noqa: E731
                         and any(y in d for y in m.pricing_stress_years))
    if not covered(margins):
        alt = _ratio_by_year(f, "operating_income")
        if covered(alt):
            measure, margins = "operating_income", alt
    base = [margins[y] for y in m.pricing_baseline_years if y in margins]
    stress = [margins[y] for y in m.pricing_stress_years if y in margins]
    out = {"measure": measure.replace("_profit", " margin").replace("_income", " margin"),
           "margins": {y: round(v, 4) for y, v in sorted(margins.items())}, "held": None,
           "baseline": None, "stress_min": None, "latest": round(margins[max(margins)], 4) if margins else None}
    if len(base) < 2 or not stress:
        return out
    out.update(baseline=round(mean(base), 4), stress_min=round(min(stress), 4))
    out["held"] = min(stress) >= mean(base) - m.pricing_tolerance
    return out


def _fell(values: list[float], n: int) -> bool:
    return len(values) > n and all(values[-i] < values[-i - 1] for i in range(1, n + 1))


def margin_decline(f: Fundamentals, rules: VMIRules = RULES) -> list[str]:
    """Profit margins and ROIC that fell in each of the last `review_decline_years` years.

    No minimum size for a fall (Adam gives none). A prompt to check WHY (discounting = lost pricing power; higher
    cost of sales; one-offs), not a verdict. Free-cash-flow margin is information, not one of his profit margins."""
    n = rules.moat.review_decline_years
    out = []
    for label, series in margin_history(f).items():
        values = [series[y] for y in sorted(series)]
        if label in PROFIT_MARGINS and _fell(values, n):
            out.append(f"{label} fell {n} years in a row ({values[-n - 1]:.1%} → {values[-1]:.1%})")
    roic = [p.value for p in f.ratios.get("roic", []) if p.end != "TTM"]
    if _fell(roic, n):
        out.append(f"ROIC fell {n} years in a row ({roic[-n - 1]:.1%} → {roic[-1]:.1%})")
    return out


def _trend_word(xs: list[float], tolerance: float) -> str:
    if len(xs) < 3:
        return ""
    drift = xs[-1] - mean(xs[:-1])
    return "rising" if drift > tolerance else "falling" if drift < -tolerance else "stable"


def switching_costs(f: Fundamentals) -> dict:
    """Recurring/prepaid revenue signals: deferred revenue and remaining performance obligations vs sales."""
    deferred, rpo = _ratio_by_year(f, "deferred_revenue"), _ratio_by_year(f, "rpo")
    series = lambda d: [round(v, 4) for _, v in sorted(d.items())][-6:]  # noqa: E731
    return {"deferred_revenue_pct": series(deferred), "deferred_trend": _trend_word(series(deferred), 0.01),
            "rpo_pct": series(rpo), "rpo_trend": _trend_word(series(rpo), 0.05),
            "available": bool(deferred or rpo)}


def intensity(f: Fundamentals) -> dict:
    """Reinvestment and scale: R&D, SG&A and capex as a share of sales, latest value and 5-year average."""
    out = {}
    for name in ("rd", "sga", "capex"):
        series = [round(abs(v), 4) for _, v in sorted(_ratio_by_year(f, name).items())][-6:]
        out[name] = {"latest": series[-1] if series else None,
                     "avg_5y": round(mean(series[-5:]), 4) if series else None, "trend": _trend_word(series, 0.005)}
    return out


def review_status(verdict_date: str | None, f: Fundamentals, rules: VMIRules = RULES,
                  today: date | None = None, reviewed: bool = True) -> dict:
    """The verdict's date and age, and every reason it is due for a fresh look: older than `review_max_age_days`,
    no date recorded, or the margin / ROIC decline signal. Without a verdict nothing is due."""
    if not reviewed:
        return {"reviewed_on": None, "age_days": None, "due": False, "reasons": []}
    if not rules.moat.review_alerts_enabled:
        return {"reviewed_on": verdict_date, "age_days": None, "due": False, "reasons": []}
    reasons, age = [], None
    if verdict_date:
        try:
            age = ((today or date.today()) - date.fromisoformat(verdict_date)).days
        except ValueError:
            reasons.append(f"unreadable review date '{verdict_date}'")
        else:
            if age > rules.moat.review_max_age_days:
                reasons.append(f"verdict is {age} days old (limit {rules.moat.review_max_age_days})")
    else:
        reasons.append("no review date recorded")
    reasons += margin_decline(f, rules)
    return {"reviewed_on": verdict_date, "age_days": age, "due": bool(reasons), "reasons": reasons}
