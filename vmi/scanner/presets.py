"""Scanner presets. A preset = scan options + rule overrides that apply to ONE scan only (nothing is saved).

  current          whatever is on the Settings page (default)
  adam             Adam's course rules: every rule back to its course default (the Settings page is ignored for this
                   scan), 10-year uptrend required, large caps (>= $10B, his personal preference, l.235)
  adam_excellent   as `adam` with his "excellent" bars: ROE and ROIC >= 15% (l.1237)
  adam_speculative Adam's speculative-growth entry (l.2095): revenue growth >= 50%, profits may be missing, the long
                   uptrend filter is dropped because such companies are young
  custom           the owner edits any scan option and ANY rule on the scanner page; those values ride in `rules`

Each preset may also carry `filters`: values for the RESULTS filter panel (growth profile, yield, category ...) that the scanner
page applies when the preset is chosen; they only change what is shown, all results stay saved.
More presets, each tied to a passage of the master document (line numbers): predictable (l.2822), large growth (l.2846),
dividend (l.2789), turnaround (l.2898), Adam's Finviz screen (l.3002).

Per-scan overrides typed on the scanner page (`rules`) are applied on top of the preset.
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "current": {"label": "Current settings", "note": "Uses the rules as set on the Settings page.",
                "params": {}, "rules": {}, "course_defaults": False},
    "adam": {"label": "Adam: great business (steps 1-5)",
             "note": "All rules at Adam's course defaults, 10-year uptrend required, market cap >= $10B (his personal preference).",
             "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False,
                        "require_steps": [1, 2, 4, 5]},
             "rules": {}, "course_defaults": True},
    "adam_excellent": {"label": "Adam: excellent (ROE and ROIC >= 15%)",
                       "note": "As above with his 'excellent' profitability bars.",
                       "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False,
                        "require_steps": [1, 2, 4, 5]},
                       "rules": {"profitability": {"min_roe": 0.15, "min_roic": 0.15}}, "course_defaults": True},
    "adam_ultra": {"label": "Adam: ULTRA excellent (every step-up bar at once)",
                   "note": "Everything must be at his best tier: ROE and ROIC 15%+ (l.1237), ALL 3 core debt ratios (not 2 of 3; he says ideally all three, l.1140), interest coverage 5+ (his 'very safe', l.1136), 10 years of record (5-10, 10 better, l.2065), margins not below their 5-year average, ROE not falling, sales growing at least as fast as receivables, cash conversion cycle not rising, REIT gearing under 40% (safest), and NO speculative shortcut in Step 1. Moat is still a manual wide-only review; expect very few names.",
                   "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False,
                              "require_steps": [1, 2, 4, 5]}, "rules": {"profitability": {"min_roe": 0.15, "min_roic": 0.15, "require_efficiency_checks": True},
                                              "debt": {"min_core_ratios_passed": 3, "min_interest_coverage": 5.0, "require_interest_coverage": True,
                                                       "max_reit_gearing": 0.40},
                                              "track": {"min_years": 10, "margin_tolerance": 0.0},
                                              "speculative": {"step1_exception": False}},
                   "course_defaults": True},
    "adam_speculative": {"label": "Adam: speculative growth",
                         "note": "Revenue growing >= 50%, profits not required yet, no 10-year chart filter (young companies); half allocation.",
                         "params": {"include_speculative": True, "require_ten_year_uptrend": False, "min_market_cap": 1e9},
                         "rules": {}, "course_defaults": True},
    "adam_predictable": {"label": "Adam: predictable (5-10% growth, large, steady)",
                         "note": "His 'predictable' category (l.2822: PEP, CB, MCD, WM, SPGI, MA ...): large, predictable earnings and cash flow, growth about 5-10%. Shows only stocks whose average analyst growth is 5% to 15%.",
                         "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False, "require_steps": [1, 2, 4, 5]}, "rules": {}, "course_defaults": True,
                         "filters": {"profile": "defensive_balanced", "profile_threshold": "15", "min_growth": "5"}},
    "adam_large_growth": {"label": "Adam: large growth (20%+)",
                          "note": "His 'large growth' category (l.2846): growing above 20-25% a year, profitable 5+ years, wide or narrow moat. Shows only stocks whose LOWEST analyst estimate (the number in the Growth column) is at least 20%; switch the growth profile to balanced or optimistic to use the average or highest estimate.",
                          "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False, "require_steps": [1, 2, 4, 5]}, "rules": {}, "course_defaults": True,
                          "filters": {"profile": "growth_conservative", "profile_threshold": "20"}},
    "adam_dividend": {"label": "Adam: dividend stocks",
                      "note": "His dividend category (l.2789): yield well above the market (about 5%+ in Singapore, 3%+ screen for US), steady earnings and cash flow, debt servicing under 30%, current ratio above 1. Shows yield >= 3%.",
                      "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False, "require_steps": [1, 2, 4, 5]}, "rules": {}, "course_defaults": True,
                      "filters": {"min_yield": "3"}},
    "adam_turnaround": {"label": "Adam: turnaround (great company, profits down)",
                        "note": "His turnaround category (l.2898): a great business whose profits fell more than 25% in a year or two years in a row, moat intact. Step 1 is NOT required (profits dipped); steps 2, 4 and 5 are. Shows only stocks the scan classes as turnarounds.",
                        "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": False, "include_speculative": False, "require_steps": [2, 4, 5]},
                        "rules": {}, "course_defaults": True, "filters": {"category": "turnaround"}},
    "adam_finviz": {"label": "Adam: his Finviz screen",
                    "note": "The screen he shows (l.3002): ROE above 10%, EPS growth next 5 years above 10%, PEG below 2, 10-year uptrend. Market cap from $2B. Steps are not enforced (it is a first sieve).",
                    "params": {"min_market_cap": 2e9, "require_ten_year_uptrend": True, "include_speculative": False},
                    "rules": {"profitability": {"min_roe": 0.10}}, "course_defaults": True,
                    "filters": {"min_growth": "10", "max_peg": "2"}},
    "custom": {"label": "Custom", "note": "Edit any scan option and any rule below; nothing is saved to Settings.",
               "params": {}, "rules": {}, "course_defaults": False},
}


def rule_changes(preset: str, extra: dict | None) -> tuple[dict, bool]:
    """(rule overrides for this scan, apply course defaults first?) for a preset plus the owner's per-scan edits."""
    pr = PRESETS.get(preset or "current")
    if pr is None:
        raise ValueError(f"unknown preset '{preset}'; choose from {sorted(PRESETS)}")
    merged = {sec: dict(v) for sec, v in pr["rules"].items()}
    for sec, vals in (extra or {}).items():
        merged.setdefault(sec, {}).update(vals)
    return merged, bool(pr["course_defaults"])


def resolved_params(preset: str, overrides: dict | None = None) -> dict:
    pr = PRESETS[preset]
    return {**pr["params"], **(overrides or {})}
