"""Single source of truth for "is this series consistently increasing?" (used by Step 1 AND valuation
preconditions, so the two can never disagree).

Adam's rule (Lesson 5 §4.3, Step 1): look at the last 5 years — better 10 — including the latest TTM
column; "consistent" does NOT mean up every year: 1–2 down years are fine as long as the general trend
is up. Implemented as two tests:

  * recent window  — last 5 fiscal years + TTM (≤6 points): ≤ max_down_years declines, last > first,
                     positive log-slope, latest value positive.
  * long-term view — when ≥8 years exist: the full ~10y history must also trend up (last > first and
                     positive slope). Old down years outside the recent window no longer fail a company
                     whose last 5 years are clean (e.g. HCA, V), while a broken long-term trend still does.
"""
from __future__ import annotations

from dataclasses import replace

from vmi.analysis.trends import TrendStats, trend
from vmi.data.models import Fundamentals
from vmi.rules import RULES, VMIRules

RECENT_POINTS = 6  # 5 fiscal years + TTM


def history_with_ttm(f: Fundamentals, concept: str, years: int = 10) -> list[float]:
    vals = f.series(concept)[-years:]
    ttm = f.ttm.get(concept)
    if vals and ttm is not None and abs(ttm - vals[-1]) > 0.01 * max(1.0, abs(vals[-1])):
        vals = (vals + [ttm])[-(years + 1):]
    return vals


def series_trend(f: Fundamentals, concept: str, rules: VMIRules = RULES) -> TrendStats:
    r = rules.track
    full = history_with_ttm(f, concept, r.preferred_years)
    recent = full[-RECENT_POINTS:]
    rt = trend(recent, r.max_down_years_5y, r.min_years, r.min_trend_r2)
    if not rt.consistent or len(full) < 8:
        return rt
    lt = trend(full, max_down_years=len(full), min_years=r.min_years)  # direction only, no decline cap
    if not (lt.slope_positive and (lt.last or 0) > (lt.first or 0)):
        return replace(rt, consistent=False, reason=f"recent 5y ok but 10y trend broken ({lt.reason})")
    return replace(rt, reason=f"consistent uptrend (5y: {rt.declines} down yrs; 10y trend up)")


def consistent(f: Fundamentals, concept: str, rules: VMIRules = RULES) -> bool:
    return series_trend(f, concept, rules).consistent
