"""Where every number in vmi/rules.py comes from. A rule you cannot trace is a rule you should not trust.

Each setting is exactly one of:
    adam            Adam states this number in the master document (note = where)
    interpretation  Adam states a rule in words only; this number is how we implement it (change it freely)
    owner           the project owner's own rule or spec, not Adam's
    approved        suggested by the assistant and approved by the owner (what was approved is named in the note)
    calibration     chosen with the owner's approval by comparing with Adam's published values, with a stated reason
    model           a technical guard of the software, not an investing rule

The Settings screen shows this badge beside every setting, `python -m vmi.rules_sources` prints the whole table
(docs/CRITERIA_AUDIT.md is generated from it), and a test fails when a rule is added without an entry here.
Line numbers refer to docs/VMI_MASTER_DOCUMENT.txt.
"""
from __future__ import annotations

ADAM, INTERP, OWNER, APPROVED, CALIB, MODEL = "adam", "interpretation", "owner", "approved", "calibration", "model"
KINDS = (ADAM, INTERP, OWNER, APPROVED, CALIB, MODEL)

SOURCES: dict[str, tuple[str, str]] = {
    # ---- Step 1 ------------------------------------------------------------------------------------------
    "track.min_years": (ADAM, "Step 1: sales/NI/CFO rising for 5–10 years (checklist, l.7556)"),
    "track.preferred_years": (ADAM, "5 years, 10 better (l.2688)"),
    "track.max_down_years_5y": (ADAM, "'1–2 down years acceptable; overall uptrend required' (checklist)"),
    "track.min_trend_r2": (MODEL, "optional extra strictness on the trend fit; 0 = off"),
    "track.margin_tolerance": (INTERP, "Adam: current margins 'close to the 5-year average' (no figure given)"),
    "track.reject_if_margin_falls_n_years": (ADAM, "REJECT if margins fell 5 straight years (checklist)"),
    "speculative.min_revenue_growth": (ADAM, "speculative growth: revenue growing 50–100% (checklist)"),
    "speculative.positive_quarters_required": (ADAM, "net income and CFO positive in the last 1–2 quarters (checklist)"),
    "speculative.allocation_multiplier": (ADAM, "half the normal allocation (checklist)"),
    "speculative.upgrade_after_years": (ADAM, "upgrade to normal after 5 years of consistency (checklist)"),
    # ---- Step 2 / growth ----------------------------------------------------------------------------------
    "growth.min_projected_growth": (ADAM, "projected growth must be positive (Step 2)"),
    "growth.cap_years_6_10": (ADAM, "years 6–10 capped at 15% (l.4572)"),
    "growth.years_11_20": (ADAM, "years 11–20 default 4% (l.4467)"),
    "growth.conservative_years_11_20": (ADAM, "Adam's lower option for years 11–20 (2%)"),
    "growth.max_years_1_5": (MODEL, "sanity cap against bad analyst data; not in the course"),
    "growth.growth_stock_threshold": (OWNER, "owner rule: growth ≥15%, defensive below"),
    "growth.large_growth_threshold": (INTERP, "Lesson 8: fast growers 'above 20–25%'"),
    "growth.blend": (OWNER, "owner directive 2026-11-05: take the lowest analyst source (Adam averages them)"),
    "growth.blend_defensive": (CALIB, "median source for slow growers; reasoning and data in docs/CALIBRATION.md"),
    "growth.disagreement_ratio": (CALIB, "sources ≥1.5× apart usually mean one is stale; docs/CALIBRATION.md"),
    "growth.blend_when_disagree": (CALIB, "see growth.disagreement_ratio"),
    # ---- Step 3 / moat ------------------------------------------------------------------------------------
    "moat.min_sources": (ADAM, "at least THREE of the FIVE moat sources (l.6972)"),
    "moat.min_ai_score": (ADAM, "AI moat score ≥7/10; 6/10 is 'not strong enough' (l.6999)"),
    "moat.pricing_stress_years": (APPROVED, "docs/MOAT_PROPOSALS.md #3: did margin hold through the 2021–23 cost inflation? "
                                            "(Adam's pricing-power test itself has no numbers)"),
    "moat.pricing_baseline_years": (INTERP, "the approved test compares with the three years before the stress window"),
    "moat.pricing_tolerance": (INTERP, "how far margin may dip and still count as 'held'; our reading, no figure from Adam or the proposal"),
    "moat.review_alerts_enabled": (OWNER, "owner request 2026-11-05: a switch to turn the 'review due' alert off"),
    "moat.review_max_age_days": (APPROVED, "docs/MOAT_PROPOSALS.md #7: moat check due 'after 12 months'"),
    "moat.review_decline_years": (APPROVED, "docs/MOAT_PROPOSALS.md #7: due when margins/ROIC fall 2 years; Adam (l.11030): "
                                            "profit margins declining 'at least 2–3 years' = deteriorating moat"),
    "moat.no_moat_industries": (INTERP, "Adam lists commodities, airlines, autos, developers, construction, shipping, oil & gas; "
                                        "the individual words are our reading of 'commodities'"),
    # ---- Step 4 -------------------------------------------------------------------------------------------
    "profitability.min_roe": (ADAM, "ROE ≥12% (checklist)"),
    "profitability.excellent_roe": (ADAM, "ROE >15% exceptional (checklist)"),
    "profitability.min_roic": (ADAM, "ROIC ≥12% (checklist)"),
    "profitability.excellent_roic": (ADAM, "ROIC ≥15% excellent (checklist)"),
    "profitability.ccc_max_increase_days": (INTERP, "Adam: cash conversion cycle 'consistent or declining, not sharply rising'"),
    # ---- Step 5 -------------------------------------------------------------------------------------------
    "debt.min_current_ratio": (ADAM, "current ratio >1 (checklist)"),
    "debt.max_debt_to_ebitda": (ADAM, "debt/EBITDA ≤3 (checklist)"),
    "debt.max_debt_servicing": (ADAM, "debt servicing <30% (checklist)"),
    "debt.min_interest_coverage": (ADAM, "interest coverage >3 (checklist)"),
    "debt.safe_interest_coverage": (ADAM, ">5 very safe (checklist)"),
    "debt.min_bank_cet1": (ADAM, "banks: CET1 >10% (checklist)"),
    "debt.max_reit_gearing": (ADAM, "REITs: gearing ≤45% (checklist)"),
    "debt.safe_reit_gearing": (ADAM, "ideally <40% (checklist)"),
    "debt.min_core_ratios_passed": (ADAM, "'Passing 2 out of 3 is acceptable' (l.4026)"),
    # ---- Step 6 / valuation -------------------------------------------------------------------------------
    "valuation.horizon_years": (ADAM, "20-year DCF (years 1–5, 6–10, 11–20)"),
    "valuation.peg_attractive": (ADAM, "PEG target ≤1.5 (l.5177)"),
    "valuation.peg_screen": (INTERP, "PEG above 1.5 'getting expensive' (l.1285); 2.0 is our cut-off for 'expensive'"),
    "valuation.cfo_max_premium_over_ni": (ADAM, "CFO may be at most 20% above net income (l.4587)"),
    "valuation.capex_normalization_years": (ADAM, "5-year average capex (l.4527)"),
    "valuation.capex_spike_ratio": (INTERP, "Adam: capex 'a huge jump from previous years' (Amazon: more than twice normal)"),
    "valuation.base_jump_ratio": (INTERP, "Adam: 'sudden big jump in the last 12 months → don't use it' (no ratio given)"),
    "valuation.base_plunge_ratio": (INTERP, "Adam: 'sudden big plunge → don't use it' (no ratio given)"),
    "valuation.base_avg_years": (ADAM, "use an average of the last 3–4 years (l.8372)"),
    "valuation.bank_pb_fair_low": (ADAM, "banks: P/B 1.2–1.4 fair (l.4846)"),
    "valuation.bank_pb_fair_high": (ADAM, "banks: P/B 1.2–1.4 fair (l.4846)"),
    "valuation.distressed_pb_max": (ADAM, "distressed: buy at P/B ≤0.5 (l.4497)"),
    "valuation.reit_pnav_max": (ADAM, "REITs: no more than 1.2× P/B (l.4853)"),
    "valuation.reit_pnav_max_high_growth": (ADAM, "REITs with high double-digit DPU: up to 1.5× (l.4866)"),
    "valuation.reit_min_yield": (ADAM, "dividend yield ≥5% (SG rule of thumb, l.9758)"),
    "valuation.bank_min_yield": (ADAM, "Singapore banks: dividend yield ≥4.5–5% (l.5211)"),
    "valuation.psg_undervalued": (ADAM, "PSG 0.2–0.3 fair; below 0.2 cheaper (checklist 17)"),
    "valuation.psg_fair": (ADAM, "PSG >0.3 overvalued (checklist 17)"),
    "valuation.beta_table": (ADAM, "Adam's beta → discount rate rows (l.4391)"),
    "valuation.min_discount_rate": (ADAM, "5.8% is the lowest rate in the table (l.4391)"),
    "valuation.max_discount_rate": (MODEL, "guard against extrapolating the table for very high betas"),
    "valuation.doomsday_growth_factor": (ADAM, "growth halves after year 5 (l.4472)"),
    "valuation.iv_haircut": (CALIB, "flat haircut on DCF/DNI; 0 since the lowest-source growth already gives conservatism"),
    "valuation.uncertainty_haircut": (CALIB, "extra haircut for growth stocks and single-source estimates; level from tools/haircut_sweep.py"),
    "valuation.growth_haircut": (CALIB, "alternative single knob (relative cut on growth); off"),
    # ---- Step 7 / technicals ---------------------------------------------------------------------------------
    "technical.sma_periods": (ADAM, "daily: 50, 100, 150, 200 SMA (l.5751)"),
    "technical.ema_periods": (ADAM, "weekly/monthly: 20 and 40 EMA (l.5751)"),
    "technical.trend_slope_lookback": (MODEL, "bars used to measure a moving average's slope"),
    "technical.support_tolerance": (INTERP, "Adam: support/resistance is a zone, not a line"),
    "technical.min_touches_potential": (INTERP, "how many touches make a level worth watching"),
    "technical.min_touches_confirmed": (INTERP, "how many touches confirm a level"),
    "technical.swing_window": (MODEL, "bars either side of a swing high/low"),
    "technical.parabolic_dist_from_50": (INTERP, "Adam: far from the moving average 'snaps back like a rubber band'"),
    "technical.parabolic_drop_pct": (INTERP, "Adam: a 90-degree drop (l.1567); the % is our reading"),
    "technical.double_bottom_reclaim_bars": (MODEL, "bars to reclaim a level after a double bottom"),
    "technical.n_buy_levels": (ADAM, "three or four buy levels (checklist 15)"),
    "technical.near_level_pct": (INTERP, "how close price must be to a level to count as 'at support'"),
    # ---- portfolio / sizing -----------------------------------------------------------------------------------
    "portfolio.min_stocks": (ADAM, "diversification 8–30 positions (l.12102)"),
    "portfolio.max_stocks": (INTERP, "Adam: 8–30 positions (l.12102); the cap here is looser (kept from earlier work; confirm)"),
    "portfolio.default_target_stocks": (OWNER, "default number of positions used for sizing"),
    "portfolio.tranches": (ADAM, "buy in 3–4 tranches (checklist 16)"),
    "portfolio.speculative_multiplier": (ADAM, "speculative growth: ½ or ⅓ of a normal position (l.9347)"),
    "portfolio.turnaround_multiplier": (ADAM, "turnarounds: ½ or ⅓ of a normal position (l.9347)"),
    "portfolio.narrow_moat_multiplier": (INTERP, "Adam: narrow moat = 'smaller positions, especially initially', no figure; 0.75 kept from earlier work (confirm)"),
    "portfolio.max_sector_weight": (INTERP, "warning only; Adam's own largest sector target is 27% (l.10295)"),
    # ---- dividends ---------------------------------------------------------------------------------------------
    "dividend.min_yield": (ADAM, "yield ≥5% (SG) (l.9758)"),
    "dividend.us_min_yield_screen": (ADAM, "US: ~3% is attractive (l.878)"),
    "dividend.min_dps_growth_years": (ADAM, "rising DPS for 5 years (l.10246)"),
    "dividend.payout_min": (ADAM, "payout ratio 20–100% (l.10246)"),
    "dividend.payout_max": (ADAM, "payout ratio 20–100% (l.10246)"),
    # ---- turnaround ----------------------------------------------------------------------------------------------
    "turnaround.profit_drop_one_year": (ADAM, "profits fall more than 25% in one year (l.10024)"),
    "turnaround.consecutive_decline_years": (ADAM, "or decline two years in a row (l.10025)"),
    # ---- paper-trading fills ----------------------------------------------------------------------------------
    **{f"execution.{k}": (OWNER, "paper-trading fill model, owner spec: instant fill at mid plus flat slippage")
       for k in ("stock_slippage_bps", "option_slippage_per_share", "illiquid_spread_pct", "illiquid_option_spread_pct",
                 "illiquid_min_volume", "illiquid_debuff_frac", "no_quote_spread_pct", "commission_per_share",
                 "default_cash")},
}


def source(section: str, key: str) -> tuple[str, str]:
    """(kind, note) for one setting; unlisted ones read as 'unspecified' so gaps are visible, never silent."""
    return SOURCES.get(f"{section}.{key}", ("unspecified", "no provenance recorded — add it to vmi/rules_sources.py"))


def table() -> str:
    """Markdown audit table of every rule (used to generate docs/CRITERIA_AUDIT.md)."""
    from vmi import settings

    labels = {ADAM: "Adam states it", INTERP: "interpretation of Adam's words", OWNER: "owner's rule/spec",
              APPROVED: "assistant's proposal, approved by owner", CALIB: "calibration (owner-approved)", MODEL: "software guard", "unspecified": "UNSPECIFIED"}
    rows = ["| Setting | Value | Kind | Basis |", "|---|---|---|---|"]
    for s in settings.schema():
        kind, note = source(s["section"], s["key"])
        rows.append(f"| `{s['section']}.{s['key']}` | {s['default']} | {labels[kind]} | {note} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(table())
