"""Single source of truth for "is this series consistently increasing?" (used by Step 1 AND valuation
preconditions, so the two can never disagree).

Adam reads the annual chart incl. the TTM column over the last 5–10 years; 1–2 down years are fine as
long as the general trend is up (Lesson 5 §4.3, Step 1).
"""
from __future__ import annotations

from vmi.analysis.trends import TrendStats, trend
from vmi.data.models import Fundamentals
from vmi.rules import RULES, VMIRules


def history_with_ttm(f: Fundamentals, concept: str, years: int = 10) -> list[float]:
    vals = f.series(concept)[-years:]
    ttm = f.ttm.get(concept)
    if vals and ttm is not None and abs(ttm - vals[-1]) > 0.01 * max(1.0, abs(vals[-1])):
        vals = (vals + [ttm])[-(years + 1):]
    return vals


def series_trend(f: Fundamentals, concept: str, rules: VMIRules = RULES) -> TrendStats:
    r = rules.track
    return trend(history_with_ttm(f, concept, r.preferred_years), r.max_down_years_5y, r.min_years, r.min_trend_r2)


def consistent(f: Fundamentals, concept: str, rules: VMIRules = RULES) -> bool:
    return series_trend(f, concept, rules).consistent
