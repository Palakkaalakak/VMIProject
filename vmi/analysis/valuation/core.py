"""Valuation primitives: Adam's discount-rate table and the 20-year discounted-stream engine."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from vmi.rules import RULES, ValuationRules


def discount_rate(beta: float | None, rules: ValuationRules = RULES.valuation) -> float:
    """Discount rate = rf + β × MRP, read from Adam's beta table (Lesson 5 §4.7).

    Linear interpolation between observed rows; linear extrapolation above the top row using the
    slope of the last segment, clamped to [min_discount_rate, max_discount_rate].
    """
    table = sorted(rules.beta_table)
    if beta is None or beta != beta:
        beta = 1.0
    if beta <= table[0][0]:
        return rules.min_discount_rate
    for (b0, r0), (b1, r1) in zip(table, table[1:]):
        if b0 <= beta <= b1:
            return round(r0 + (r1 - r0) * (beta - b0) / (b1 - b0), 4)
    (b0, r0), (b1, r1) = table[-2], table[-1]
    slope = (r1 - r0) / (b1 - b0)
    return round(min(rules.max_discount_rate, r1 + slope * (beta - b1)), 4)


@dataclass
class GrowthPath:
    g1_5: float
    g6_10: float
    g11_20: float

    def to_dict(self):
        return asdict(self)


def growth_path(g: float, rules: ValuationRules = RULES.valuation, *, g6_10: float | None = None,
                g11_20: float | None = None) -> GrowthPath:
    """Years 1–5 = consensus; 6–10 = same, capped at 15%; 11–20 = 4% (Lesson 5 §4.6)."""
    from vmi.rules import RULES as R

    g1 = max(-0.5, min(g, R.growth.max_years_1_5))
    g2 = min(g1, R.growth.cap_years_6_10) if g6_10 is None else g6_10
    g3 = R.growth.years_11_20 if g11_20 is None else g11_20
    return GrowthPath(g1, g2, g3)


def discounted_value(base: float, path: GrowthPath, rate: float, debt: float, cash: float,
                     shares: float, years: int = 20) -> float | None:
    """Intrinsic value per share = (PV of `years` of growing cash flow + cash − debt) / shares.
    Matches Adam's Intrinsic Value Calculator (validated against the MA/AMZN/AAPL/BLK worked examples)."""
    if not shares or shares <= 0:
        return None
    pv, cf = 0.0, base
    for t in range(1, years + 1):
        g = path.g1_5 if t <= 5 else path.g6_10 if t <= 10 else path.g11_20
        cf *= 1 + g
        pv += cf / (1 + rate) ** t
    return (pv + cash - debt) / shares


@dataclass
class Scenario:
    name: str
    value: float | None
    growth: GrowthPath | None = None
    note: str = ""

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class ValuationResult:
    method: str
    label: str
    applicable: bool
    intrinsic_value: float | None = None          # base case
    scenarios: list[Scenario] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # e.g. ±1σ band, max price for yield

    @property
    def conservative(self) -> float | None:
        for s in self.scenarios:
            if s.name == "conservative":
                return s.value
        return None

    def to_dict(self):
        d = asdict(self)
        d["conservative"] = self.conservative
        return d
