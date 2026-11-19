"""Human titles for technical parameter names (e.g. `valuation.reit_pnav_max` -> "REIT maximum price / NAV").

`title(key)` builds a readable title from the snake_case name, expanding the abbreviations below; TITLES overrides
the few where the automatic title would read badly. The help text shown in the (?) tooltip comes from the comments
in vmi/rules.py and the source note in vmi/rules_sources.py (see vmi/settings.py::schema).
"""
from __future__ import annotations

WORDS = {
    "roe": "ROE", "roic": "ROIC", "reit": "REIT", "pnav": "price / NAV", "pb": "price / book", "pe": "P/E", "peg": "PEG",
    "psg": "price / sales ÷ growth", "ps": "P/S", "dni": "discounted net income", "fcf": "free cash flow", "cfo": "operating cash flow",
    "ni": "net income", "iv": "intrinsic value", "dps": "dividend per share", "ccc": "cash conversion cycle", "cet1": "CET1 capital",
    "ebitda": "EBITDA", "sma": "SMA", "ema": "EMA", "r2": "R²", "bps": "basis points", "min": "minimum", "max": "maximum",
    "pct": "%", "n": "number of", "ai": "AI", "avg": "average", "frac": "fraction", "us": "US", "eps": "EPS", "ma": "MA",
    "yrs": "years", "5y": "(5 years)", "1": "1", "dist": "distance",
}
TITLES = {
    "growth.cap_years_1_5": "Cap growth in years 1–5",
    "growth.max_years_1_5": "Maximum growth used for years 1–5",
    "growth.cap_years_6_10": "Growth cap for years 6–10",
    "growth.years_11_20": "Growth for years 11–20",
    "growth.conservative_years_11_20": "Conservative growth for years 11–20",
    "track.max_down_years_5y": "Maximum down years in 5",
    "track.reject_if_margin_falls_n_years": "Reject if margins fall this many years in a row",
    "track.min_trend_r2": "Minimum trend fit (R²)",
    "speculative.step1_exception": "Speculative growth may pass Step 1 on recent quarters",
    "moat.ten_year_min_degrees": "10-year chart: minimum slope (degrees)",
    "moat.chart_aspect": "10-year chart: height/width used for the angle",
    "normalise.enabled": "Normalise (use multi-year averages)",
    "normalise.years": "Years averaged when normalising",
    "valuation.reit_pnav_max": "REIT maximum price / NAV",
    "valuation.reit_pnav_max_high_growth": "REIT maximum price / NAV (high growth)",
    "valuation.beta_table": "Beta → discount rate table",
    "valuation.discount_mode": "Discount rate method",
    "valuation.fixed_discount_rate": "Fixed discount rate",
    "valuation.iv_flag_dni_max_fcf_to_ni": "Flag: discounted net income when FCF/NI below",
    "valuation.cfo_max_premium_over_ni": "Maximum premium of operating cash flow over net income",
    "debt.min_core_ratios_passed": "Core debt ratios that must pass",
    "debt.require_interest_coverage": "Interest coverage must pass",
    "profitability.require_efficiency_checks": "Efficiency checks must pass",
    "profitability.ccc_max_increase_days": "Maximum rise in cash conversion cycle (days)",
    "execution.stock_slippage_bps": "Stock slippage (basis points)",
}


def title(key: str) -> str:
    """'valuation.reit_pnav_max' or 'reit_pnav_max' -> readable title."""
    if key in TITLES:
        return TITLES[key]
    name = key.rsplit(".", 1)[-1]
    words = [WORDS.get(w, w) for w in name.split("_") if w]
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else key
