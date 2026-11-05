"""Moat evidence computed from a company's own statements (Step 3). Evidence only: the verdict is the reviewer's.

Every function takes a Fundamentals (and rules) and returns plain data, so each is unit-testable and the
reviewer sees the numbers behind each signal. Peer comparison and filing excerpts, which need the network,
live in vmi/analysis/moat_peers.py and vmi/data/filings.py.

    pricing_power(f)      did gross margin hold through the cost-inflation stress window? (Adam's pricing-power test)
    switching_costs(f)    deferred revenue and contracted backlog relative to sales (recurring, prepaid business)
    intensity(f)          R&D / SG&A / capex as a share of sales (economies of scale, reinvestment)
    review_status(...)    is the recorded verdict stale, or has the evidence deteriorated since?
"""
from __future__ import annotations

from datetime import date

from vmi.analysis.trends import mean
from vmi.data.models import Fundamentals, Point
from vmi.rules import RULES, VMIRules


def _ratio_by_year(f: Fundamentals, top: str, bottom: str = "revenue") -> dict[int, float]:
    """{fiscal year: top/bottom}. The year is the calendar year the fiscal period ends in."""
    den = {int(p.end[:4]): p.value for p in f.annual.get(bottom, []) if p.value}
    return {int(p.end[:4]): p.value / den[int(p.end[:4])] for p in f.annual.get(top, [])
            if int(p.end[:4]) in den}


def _trend_word(xs: list[float], tolerance: float = 0.005) -> str:
    if len(xs) < 3:
        return ""
    drift = xs[-1] - mean(xs[:-1])
    return "rising" if drift > tolerance else "falling" if drift < -tolerance else "stable"


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
    for name, concept in (("rd", "rd"), ("sga", "sga"), ("capex", "capex")):
        series = [round(abs(v), 4) for _, v in sorted(_ratio_by_year(f, concept).items())][-6:]
        out[name] = {"latest": series[-1] if series else None,
                     "avg_5y": round(mean(series[-5:]), 4) if series else None, "trend": _trend_word(series)}
    return out


def review_status(verdict_date: str | None, f: Fundamentals, rules: VMIRules = RULES,
                  today: date | None = None) -> dict:
    """When was the verdict recorded, and does anything say it needs a fresh look?

    due reasons: older than review_max_age_days, or gross margin / returns on capital fell for
    review_decline_years years in a row since (moats erode; the Intel example in the course)."""
    m, today = rules.moat, today or date.today()
    reasons: list[str] = []
    age = None
    if verdict_date:
        try:
            age = (today - date.fromisoformat(verdict_date)).days
        except ValueError:
            reasons.append(f"unreadable review date '{verdict_date}'")
        else:
            if age > m.review_max_age_days:
                reasons.append(f"verdict is {age} days old (limit {m.review_max_age_days})")
    for label, series in (("gross margin", [v for _, v in sorted(_ratio_by_year(f, "gross_profit").items())]),
                          ("operating margin", [v for _, v in sorted(_ratio_by_year(f, "operating_income").items())])):
        n = m.review_decline_years
        if (len(series) > n and all(series[-i] < series[-i - 1] for i in range(1, n + 1))
                and series[-n - 1] - series[-1] >= m.review_decline_min):
            reasons.append(f"{label} fell {n} years in a row ({series[-n - 1]:.1%} → {series[-1]:.1%})")
    if verdict_date is None:
        reasons.append("no review date recorded")
    return {"reviewed_on": verdict_date, "age_days": age, "due": bool(reasons), "reasons": reasons}
