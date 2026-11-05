"""Moat evidence computed from a company's own statements (Step 3). Evidence only: the verdict is the reviewer's.

Adam gives no numbers for "very high / average / low margins" or for pricing power ("can it raise prices every
year without losing share?"), so nothing here passes or fails on an invented threshold: the functions return the
history and the reviewer reads it. The one numeric test he does state is moat DETERIORATION: "profit margins
decline consistently for at least 2–3 years" (master doc l.11030), used as a flag via rules.moat.review_decline_years.

    margin_history(f)     gross / operating / net / free-cash-flow margin by year
    margin_decline(f)     margins that fell for the last N years in a row (Adam's deterioration signal)
    switching_costs(f)    deferred revenue and contracted backlog relative to sales (recurring, prepaid business)
    intensity(f)          R&D / SG&A / capex as a share of sales (economies of scale, reinvestment)
    review_status(...)    the stored verdict's date, plus any deterioration signal since
"""
from __future__ import annotations

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


def margin_decline(f: Fundamentals, rules: VMIRules = RULES) -> list[str]:
    """Profit margins that fell in each of the last `review_decline_years` years (Adam: 'at least 2–3 years').

    He states no minimum size for a fall. This is a prompt for the reviewer to check WHY (discounting = lost
    pricing power; higher cost of sales; one-off items), not a verdict. Free-cash-flow margin is shown as
    information but is not one of his profit margins, so it does not trigger the signal."""
    n = rules.moat.review_decline_years
    out = []
    for label, series in margin_history(f).items():
        if label not in PROFIT_MARGINS:
            continue
        values = [series[y] for y in sorted(series)]
        if len(values) > n and all(values[-i] < values[-i - 1] for i in range(1, n + 1)):
            out.append(f"{label} fell {n} years in a row ({values[-n - 1]:.1%} → {values[-1]:.1%})")
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


def review_status(verdict_date: str | None, f: Fundamentals, rules: VMIRules = RULES) -> dict:
    """The stored verdict's date, and whether margins show Adam's deterioration signal (flag = look again)."""
    reasons = margin_decline(f, rules)
    return {"reviewed_on": verdict_date, "due": bool(reasons), "reasons": reasons}
