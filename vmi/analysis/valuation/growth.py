"""Consensus growth for years 1–5 from the available analyst 5-year EPS growth estimates (FinViz, Zacks,
Yahoo LTG, IB/LSEG when it answers).

How the sources are combined is rules.growth.blend, overridable per ticker:
  * "lowest"  (default since 2026-11-05, owner directive): the most conservative source
  * "average" Adam's literal rule (Lesson 5 §4.6) — he averages FactSet, FinViz and Zacks
  * "median"

Only data hygiene is applied — no fitted adjustments:
  * impossible values (< −20% or > 100%) are discarded as bad data
  * hard sanity cap rules.growth.max_years_1_5
  * fallbacks when no 5-year estimate exists: median next-year EPS growth, then 5y revenue CAGR
No fitted adjustments: conservatism comes from the blend choice (and the optional flat
rules.valuation.iv_haircut), never from reshaping the growth input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from vmi.data.models import Estimates, Fundamentals
from vmi.rules import RULES, VMIRules


@dataclass
class GrowthChoice:
    value: float | None
    method: str
    sources: dict[str, float] = field(default_factory=dict)
    low: float | None = None
    high: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _cagr(vals: list[float]) -> float | None:
    if len(vals) >= 3 and vals[0] > 0 and vals[-1] > 0:
        return (vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1
    return None


BLENDS = {
    "lowest": lambda vals: vals[0],
    "average": lambda vals: sum(vals) / len(vals),
    "median": lambda vals: (vals[(len(vals) - 1) // 2] + vals[len(vals) // 2]) / 2,
}


def choose_growth(est: Estimates, f: Fundamentals | None = None, rules: VMIRules = RULES,
                  blend: str | None = None, exclude: tuple[str, ...] = ()) -> GrowthChoice:
    """`blend` (per-ticker override) beats rules.growth.blend; unknown names fall back to the rule.
    `exclude` drops named sources (per-ticker override, e.g. one source is stale)."""
    cap = rules.growth.max_years_1_5
    per_ticker = blend in BLENDS
    blend = blend if per_ticker else rules.growth.blend
    srcs = {k: v.get("eps_growth_5y") for k, v in (est.sources or {}).items() if k not in exclude}
    srcs = {k: float(v) for k, v in srcs.items() if v is not None and -0.20 < v < 1.0}
    if srcs:
        vals = sorted(srcs.values())
        notes = []
        if not per_ticker and vals[0] > 0 and vals[-1] / vals[0] >= rules.growth.disagreement_ratio:
            blend = rules.growth.blend_when_disagree
            notes.append(f"sources disagree ({vals[0]:.1%}–{vals[-1]:.1%}) → {blend}")
        g = BLENDS[blend](vals)
        notes += [f"capped at {cap:.0%}"] if g > cap else []
        return GrowthChoice(min(g, cap), blend, srcs, vals[0], vals[-1], notes)
    nxt = sorted(float(v["eps_growth_next_year"]) for k, v in (est.sources or {}).items() if k not in exclude
                 if v.get("eps_growth_next_year") is not None and -0.5 < v["eps_growth_next_year"] < 1.0)
    if nxt:
        return GrowthChoice(min(nxt[len(nxt) // 2], cap), "next_year_median",
                            notes=["no 5-year estimates — used median next-year EPS growth"])
    if f is not None:
        rc = _cagr(f.series("revenue")[-6:])
        if rc is not None:
            return GrowthChoice(min(rc, cap), "historical_revenue",
                                notes=["no estimates — used 5y historical revenue CAGR"])
    return GrowthChoice(None, "none", notes=["no growth data"])
