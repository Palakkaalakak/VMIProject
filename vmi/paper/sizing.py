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
    shares_next_tranche: int
    shares_to_full: int
    price: float
    fractional_shares_next: float
    warning: str = ""

    def to_dict(self):
        return asdict(self)


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
    shares_next = math.floor(next_val / price) if price > 0 else 0
    return SizePlan(equity, n, multiplier, round(full, 2), round(tranche, 2), t, round(current_value, 2),
                    round(remaining, 2), shares_next, math.floor(remaining / price) if price > 0 else 0, price,
                    round(next_val / price, 4) if price > 0 else 0.0, warning)


def option_contracts_for_csp(cash: float, strike: float, max_fraction: float = 1.0) -> int:
    """Cash-secured put: each contract needs strike × 100 cash collateral."""
    return int(cash * max_fraction // (strike * 100)) if strike > 0 else 0


def option_contracts_for_cc(shares: float) -> int:
    """Covered call: one contract per 100 shares owned."""
    return int(shares // 100)
