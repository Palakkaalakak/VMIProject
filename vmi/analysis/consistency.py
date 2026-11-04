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


def growth_capex_dip(f: Fundamentals, rules: VMIRules = RULES) -> tuple[bool, str]:
    """Doc Lesson 5 (Amazon) + §5.4 (Buffett: growth capex isn't deducted): a falling FCF is acceptable when
    operating cash flow is healthy and the shortfall comes from rising capex — as long as FCF is not
    negative for more than one year. Returns (ok, explanation)."""
    cfo, capex, fcf = (history_with_ttm(f, c, rules.track.preferred_years) for c in ("cfo", "capex", "fcf"))
    if len(cfo) < 5 or len(capex) < 5 or len(fcf) < 5:
        return False, "insufficient history"
    capex = [abs(v) for v in capex]
    lt = trend(cfo, max_down_years=len(cfo), min_years=rules.track.min_years)
    cfo_ok = lt.slope_positive and cfo[-1] > cfo[0] and cfo[-1] > 0
    neg_years = sum(1 for v in fcf[-RECENT_POINTS:] if v <= 0)
    capex_up = capex[-1] > 1.25 * min(capex[-RECENT_POINTS:])
    ok = cfo_ok and capex_up and neg_years <= 1
    why = (f"CFO {'up' if cfo_ok else 'NOT up'} long-term ({cfo[0]:.3g}→{cfo[-1]:.3g}); capex "
           f"{'rising' if capex_up else 'flat'} ({min(capex[-RECENT_POINTS:]):.3g}→{capex[-1]:.3g}); "
           f"{neg_years} negative-FCF yr(s) in window")
    return ok, why
