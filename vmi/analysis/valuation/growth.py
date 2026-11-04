"""Consensus growth selection for years 1–5 (Lesson 5 §4.6) — the FactSet substitute, made robust.

Adam averages three sources (StockOracle/FactSet, FinViz, Zacks). We have FinViz, Zacks, Yahoo LTG,
stockanalysis and (when it answers) IB/Refinitiv. Free sources occasionally carry stale or extreme
values (e.g. one source at 35% while the others say 12%), so the selection is:

  1. collect 5-year EPS growth estimates from all sources; drop impossible values (< −20% or > 100%)
  2. if the sources agree (spread ≤ AGREE_SPREAD) → plain average (Adam's method)
     else → lean conservative: low + spread/3  (the lowest source dominates, outlier is damped)
  3. sanity cap against the company's own track record: growth ≤ max(5y revenue CAGR, 5y EPS CAGR) + HIST_PREMIUM
     (consensus far above anything the business has ever delivered is not a base case)
  4. hard cap at rules.growth.max_years_1_5
Every step is reported, so the UI can show exactly how the number was chosen and the user can override.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from vmi.data.models import Estimates, Fundamentals
from vmi.rules import RULES, VMIRules

AGREE_SPREAD = 0.06
HIST_PREMIUM = 0.05


@dataclass
class GrowthChoice:
    value: float | None
    method: str
    sources: dict[str, float] = field(default_factory=dict)
    low: float | None = None
    high: float | None = None
    hist_cap: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _cagr(vals: list[float]) -> float | None:
    if len(vals) >= 3 and vals[0] > 0 and vals[-1] > 0:
        return (vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1
    return None


def choose_growth(est: Estimates, f: Fundamentals | None = None, rules: VMIRules = RULES) -> GrowthChoice:
    srcs = {k: v.get("eps_growth_5y") for k, v in (est.sources or {}).items()}
    srcs = {k: float(v) for k, v in srcs.items() if v is not None and -0.20 < v < 1.0}
    notes: list[str] = []
    if not srcs:
        # fall back to next-year growth, then historical revenue CAGR
        nxt = [v.get("eps_growth_next_year") for v in (est.sources or {}).values()]
        nxt = sorted(float(x) for x in nxt if x is not None and -0.5 < x < 1.0)
        if nxt:
            g = nxt[len(nxt) // 2]
            notes.append("no 5-year estimates — used median next-year EPS growth")
            method = "next_year_median"
        elif f is not None and _cagr(f.series("revenue")[-6:]) is not None:
            g = _cagr(f.series("revenue")[-6:])
            notes.append("no estimates at all — used 5y historical revenue CAGR")
            method = "historical_revenue"
        else:
            return GrowthChoice(None, "none", notes=["no growth data"])
        return GrowthChoice(min(g, rules.growth.max_years_1_5), method, {}, notes=notes)
    vals = sorted(srcs.values())
    lo, hi = vals[0], vals[-1]
    if hi - lo <= AGREE_SPREAD:
        g, method = sum(vals) / len(vals), "average"
    else:
        g, method = lo + (hi - lo) / 3, "conservative_blend"
        notes.append(f"sources disagree ({lo:.1%}–{hi:.1%}) — leaning to the low side")
    hist_cap = None
    if f is not None:
        hist = [x for x in (_cagr(f.series("revenue")[-6:]), _cagr(f.series("eps_diluted")[-6:])) if x is not None]
        if hist:
            hist_cap = max(hist) + HIST_PREMIUM
            if g > hist_cap:
                notes.append(f"capped at track record + {HIST_PREMIUM:.0%} ({hist_cap:.1%})")
                g = hist_cap
    if g > rules.growth.max_years_1_5:
        notes.append(f"capped at {rules.growth.max_years_1_5:.0%}")
        g = rules.growth.max_years_1_5
    return GrowthChoice(g, method, srcs, lo, hi, hist_cap, notes)
