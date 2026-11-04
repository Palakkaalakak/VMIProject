"""Consensus growth for years 1–5 — Adam's rule (Lesson 5 §4.6): the AVERAGE of the available analyst
5-year EPS growth estimates (he averages StockOracle/FactSet, FinViz and Zacks; we average the free
sources: FinViz, Zacks, Yahoo LTG and IB/Refinitiv when it answers).

Only data hygiene is applied — no fitted adjustments:
  * impossible values (< −20% or > 100%) are discarded as bad data
  * hard sanity cap rules.growth.max_years_1_5
  * fallbacks when no 5-year estimate exists: median next-year EPS growth, then 5y revenue CAGR
Conservatism is handled separately by ONE flat, documented haircut on the DCF result
(rules.valuation.iv_haircut) — never by reshaping the growth input.
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


def choose_growth(est: Estimates, f: Fundamentals | None = None, rules: VMIRules = RULES) -> GrowthChoice:
    cap = rules.growth.max_years_1_5
    srcs = {k: v.get("eps_growth_5y") for k, v in (est.sources or {}).items()}
    srcs = {k: float(v) for k, v in srcs.items() if v is not None and -0.20 < v < 1.0}
    if srcs:
        vals = sorted(srcs.values())
        g = sum(vals) / len(vals)
        notes = [f"capped at {cap:.0%}"] if g > cap else []
        return GrowthChoice(min(g, cap), "average", srcs, vals[0], vals[-1], notes)
    nxt = sorted(float(v["eps_growth_next_year"]) for v in (est.sources or {}).values()
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
