"""Colour flags for the watchlist metric columns, from the app's own rule thresholds (`vmi/rules.py`).

`flag(metric, value, rules)` -> "green" | "yellow" | "red" | None (None = no opinion: value missing or no rule for it).
All flag rules live in the one table `FLAGS` below, so a threshold is changed (in Settings) or a metric added in one place.
"""
from __future__ import annotations

from typing import Callable

from vmi.rules import RULES, VMIRules


def _bands(value, green: bool, yellow: bool) -> str:
    return "green" if green else "yellow" if yellow else "red"


# metric -> rule(value, rules) -> colour | None. Every rule receives a non-None value.
FLAGS: dict[str, Callable] = {
    # growth: the growth-stock bar is green; any positive growth (Step 2 bar) is yellow
    "growth": lambda v, r: _bands(v, v >= r.growth.growth_stock_threshold, v > r.growth.min_projected_growth),
    "roe": lambda v, r: _bands(v, v >= r.profitability.excellent_roe, v >= r.profitability.min_roe),
    "roic": lambda v, r: _bands(v, v >= r.profitability.excellent_roic, v >= r.profitability.min_roic),
    "net_margin": lambda v, r: "red" if v <= 0 else None,                   # no course rule: only a loss is flagged
    "margin_of_safety": lambda v, r: "green" if v > 0 else "red",           # price below intrinsic value (Step 6)
    "peg": lambda v, r: None if v <= 0 else _bands(v, v <= r.valuation.peg_attractive, v <= r.valuation.peg_screen),
    "dividend_yield": lambda v, r: ("green" if v >= r.dividend.min_yield else "yellow" if v >= r.dividend.us_min_yield_screen else None),
    "steps_passed": lambda v, r: _bands(v, v >= 5, v >= 3),                 # steps 1-5 = a great business
    "moat": lambda v, r: {"wide": "green", "narrow": "yellow", "none": "red", "fails": "red"}.get(str(v).lower()),
    "distance_to_level": lambda v, r: ("green" if v <= r.technical.near_level_pct else "yellow" if v <= 3 * r.technical.near_level_pct else None),
}


def flag(metric: str, value, rules: VMIRules = RULES) -> str | None:
    rule = FLAGS.get(metric)
    if rule is None or value is None or value == "":
        return None
    if isinstance(value, float) and value != value:       # NaN
        return None
    try:
        return rule(value, rules)
    except TypeError:                                     # a string where a number was expected
        return None


def flags_for(row: dict, rules: VMIRules = RULES) -> dict[str, str]:
    """{metric: colour} for every flagged value in a compact row (metrics without a colour are left out)."""
    return {m: c for m in FLAGS if (c := flag(m, row.get(m), rules))}
