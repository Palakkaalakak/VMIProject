"""VMI position sizing (Lesson 8 + Step 7).

  full allocation = portfolio equity ÷ target number of stocks           (equal-weight framework)
  × category multiplier: speculative / turnaround ½, narrow moat ¾       (rules.portfolio)
  tranche = full allocation ÷ 3–4                                         (never buy a full position at once)
  never exceed the full allocation; never rebalance down/up purely on price moves.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from vmi.rules import RULES, PortfolioRules


@dataclass
class SizePlan:
    equity: float
    target_positions: int
    multiplier: float
    full_allocation: float        # $
    tranche_value: float          # $
    tranches: int
    current_value: float          # $ already held
    remaining_value: float        # $ still allowed
    shares_next_tranche: float
    shares_to_full: float
    price: float
    fractional_shares_next: float
    warning: str = ""

    def to_dict(self):
        return asdict(self)


def _shares(value: float, price: float, rules: PortfolioRules) -> float:
    """Whole shares, or down to 2 decimals when fractional shares are allowed (never rounds up past the money)."""
    if price <= 0:
        return 0
    if not rules.fractional_shares:
        return math.floor(value / price)
    return math.floor(value / price * 100 + 1e-9) / 100


def plan(equity: float, price: float, current_value: float = 0.0, target_positions: int | None = None,
         multiplier: float = 1.0, tranches: int | None = None, cash: float | None = None,
         rules: PortfolioRules = RULES.portfolio) -> SizePlan:
    n = max(rules.min_stocks, min(rules.max_stocks, target_positions or rules.default_target_stocks))
    t = tranches or rules.tranches
    full = equity / n * multiplier
    tranche = full / t
    remaining = max(0.0, full - current_value)
    next_val = min(tranche, remaining)
    warning = ""
    if cash is not None and next_val > cash:
        warning = f"insufficient cash (${cash:,.0f}) for a full tranche"
        next_val = max(0.0, cash)
    if remaining <= 0:
        warning = "full allocation reached — do not add (Lesson 8 discipline rule)"
    shares_next = _shares(next_val, price, rules)
    return SizePlan(equity, n, multiplier, round(full, 2), round(tranche, 2), t, round(current_value, 2),
                    round(remaining, 2), shares_next, _shares(remaining, price, rules), price,
                    round(next_val / price, 4) if price > 0 else 0.0, warning)


def option_contracts_for_csp(cash: float, strike: float, max_fraction: float = 1.0) -> int:
    """Cash-secured put: each contract needs strike × 100 cash collateral."""
    return int(cash * max_fraction // (strike * 100)) if strike > 0 else 0


def option_contracts_for_cc(shares: float) -> int:
    """Covered call: one contract per 100 shares owned."""
    return int(shares // 100)
