# Criteria audit: where every number comes from

Generated from `vmi/rules_sources.py` (`python -m vmi.rules_sources`). **Adam states it** = a number he gives in the
master document (line references in the basis). **Interpretation** = he gives the rule in words only and the number
is how the software implements it: change it freely in Settings. **Owner** / **calibration** are not Adam's.
A test fails when a setting is added without an entry, so nothing enters `vmi/rules.py` untraceable.

Removed on 2026-11-05 because neither Adam nor the owner said them (I had invented them): the 1-point minimum margin
move, the margin cut-offs (40% gross, 20% operating, 10% net/FCF), the 3-point gross-margin stability limit, the
"≥80% supportive signals = wide moat" hint, and mapping ≥4 sources to "wide" and score ≥8 to "wide".
Kept or restored because the owner approved the proposal (kind **approved**): the pricing-power test over 2021–23,
the 12-month review age and the 2-year margin/ROIC decline alert. The 0.75 narrow-moat size and 60-position cap are
earlier values I changed without being asked; they are restored and marked for the owner to confirm.

| Setting | Value | Kind | Basis |
|---|---|---|---|
| `track.min_years` | 5 | Adam states it | Step 1: sales/NI/CFO rising for 5–10 years (checklist, l.7556) |
| `track.preferred_years` | 10 | Adam states it | 5 years, 10 better (l.2688) |
| `track.max_down_years_5y` | 2 | Adam states it | '1–2 down years acceptable; overall uptrend required' (checklist) |
| `track.min_trend_r2` | 0.0 | software guard | optional extra strictness on the trend fit; 0 = off |
| `track.margin_tolerance` | 0.15 | interpretation of Adam's words | Adam: current margins 'close to the 5-year average' (no figure given) |
| `track.reject_if_margin_falls_n_years` | 5 | Adam states it | REJECT if margins fell 5 straight years (checklist) |
| `speculative.min_revenue_growth` | 0.5 | Adam states it | speculative growth: revenue growing 50–100% (checklist) |
| `speculative.positive_quarters_required` | 1 | Adam states it | net income and CFO positive in the last 1–2 quarters (checklist) |
| `speculative.allocation_multiplier` | 0.5 | Adam states it | half the normal allocation (checklist) |
| `speculative.upgrade_after_years` | 5 | Adam states it | upgrade to normal after 5 years of consistency (checklist) |
| `growth.min_projected_growth` | 0.0 | Adam states it | projected growth must be positive (Step 2) |
| `growth.cap_years_6_10` | 0.15 | Adam states it | years 6–10 capped at 15% (l.4572) |
| `growth.years_11_20` | 0.04 | Adam states it | years 11–20 default 4% (l.4467) |
| `growth.conservative_years_11_20` | 0.02 | Adam states it | Adam's lower option for years 11–20 (2%) |
| `growth.max_years_1_5` | 0.4 | software guard | sanity cap against bad analyst data; not in the course |
| `growth.growth_stock_threshold` | 0.15 | owner's rule/spec | owner rule: growth ≥15%, defensive below |
| `growth.large_growth_threshold` | 0.2 | interpretation of Adam's words | Lesson 8: fast growers 'above 20–25%' |
| `growth.blend` | lowest | owner's rule/spec | owner directive 2026-11-05: take the lowest analyst source (Adam averages them) |
| `growth.blend_defensive` | median | calibration (owner-approved) | median source for slow growers; reasoning and data in docs/CALIBRATION.md |
| `growth.disagreement_ratio` | 1.5 | calibration (owner-approved) | sources ≥1.5× apart usually mean one is stale; docs/CALIBRATION.md |
| `growth.blend_when_disagree` | median | calibration (owner-approved) | see growth.disagreement_ratio |
| `moat.min_sources` | 3 | Adam states it | at least THREE of the FIVE moat sources (l.6972) |
| `moat.min_ai_score` | 7 | Adam states it | AI moat score ≥7/10; 6/10 is 'not strong enough' (l.6999) |
| `moat.pricing_baseline_years` | (2018, 2019, 2020) | interpretation of Adam's words | the approved test compares with the three years before the stress window |
| `moat.pricing_stress_years` | (2021, 2022, 2023) | assistant's proposal, approved by owner | docs/MOAT_PROPOSALS.md #3: did margin hold through the 2021–23 cost inflation? (Adam's pricing-power test itself has no numbers) |
| `moat.pricing_tolerance` | 0.02 | interpretation of Adam's words | how far margin may dip and still count as 'held'; our reading, no figure from Adam or the proposal |
| `moat.review_alerts_enabled` | True | owner's rule/spec | owner request 2026-11-05: a switch to turn the 'review due' alert off |
| `moat.review_max_age_days` | 365 | assistant's proposal, approved by owner | docs/MOAT_PROPOSALS.md #7: moat check due 'after 12 months' |
| `moat.review_decline_years` | 2 | assistant's proposal, approved by owner | docs/MOAT_PROPOSALS.md #7: due when margins/ROIC fall 2 years; Adam (l.11030): profit margins declining 'at least 2–3 years' = deteriorating moat |
| `moat.no_moat_industries` | ('airline', 'oil & gas', 'oil and gas', 'crude', 'petroleum', 'shipping', 'marine shipping', 'deep sea', 'auto manufacturer', 'automobile', 'motor vehicle', 'construction', 'homebuild', 'property developer', 'real estate develop', 'steel', 'metal mining', 'gold', 'silver', 'copper', 'coal', 'aluminum', 'commodity chemicals', 'drilling') | interpretation of Adam's words | Adam lists commodities, airlines, autos, developers, construction, shipping, oil & gas; the individual words are our reading of 'commodities' |
| `profitability.min_roe` | 0.12 | Adam states it | ROE ≥12% (checklist) |
| `profitability.excellent_roe` | 0.15 | Adam states it | ROE >15% exceptional (checklist) |
| `profitability.min_roic` | 0.12 | Adam states it | ROIC ≥12% (checklist) |
| `profitability.excellent_roic` | 0.15 | Adam states it | ROIC ≥15% excellent (checklist) |
| `profitability.ccc_max_increase_days` | 30.0 | interpretation of Adam's words | Adam: cash conversion cycle 'consistent or declining, not sharply rising' |
| `debt.min_current_ratio` | 1.0 | Adam states it | current ratio >1 (checklist) |
| `debt.max_debt_to_ebitda` | 3.0 | Adam states it | debt/EBITDA ≤3 (checklist) |
| `debt.max_debt_servicing` | 0.3 | Adam states it | debt servicing <30% (checklist) |
| `debt.min_interest_coverage` | 3.0 | Adam states it | interest coverage >3 (checklist) |
| `debt.safe_interest_coverage` | 5.0 | Adam states it | >5 very safe (checklist) |
| `debt.min_bank_cet1` | 0.1 | Adam states it | banks: CET1 >10% (checklist) |
| `debt.max_reit_gearing` | 0.45 | Adam states it | REITs: gearing ≤45% (checklist) |
| `debt.safe_reit_gearing` | 0.4 | Adam states it | ideally <40% (checklist) |
| `debt.min_core_ratios_passed` | 2 | Adam states it | 'Passing 2 out of 3 is acceptable' (l.4026) |
| `valuation.horizon_years` | 20 | Adam states it | 20-year DCF (years 1–5, 6–10, 11–20) |
| `valuation.peg_attractive` | 1.5 | Adam states it | PEG target ≤1.5 (l.5177) |
| `valuation.peg_screen` | 2.0 | interpretation of Adam's words | PEG above 1.5 'getting expensive' (l.1285); 2.0 is our cut-off for 'expensive' |
| `valuation.cfo_max_premium_over_ni` | 0.2 | Adam states it | CFO may be at most 20% above net income (l.4587) |
| `valuation.capex_normalization_years` | 5 | Adam states it | 5-year average capex (l.4527) |
| `valuation.capex_spike_ratio` | 1.5 | interpretation of Adam's words | Adam: capex 'a huge jump from previous years' (Amazon: more than twice normal) |
| `valuation.base_jump_ratio` | 1.3 | interpretation of Adam's words | Adam: 'sudden big jump in the last 12 months → don't use it' (no ratio given) |
| `valuation.base_plunge_ratio` | 0.7 | interpretation of Adam's words | Adam: 'sudden big plunge → don't use it' (no ratio given) |
| `valuation.base_avg_years` | 4 | Adam states it | use an average of the last 3–4 years (l.8372) |
| `valuation.iv_flag_enabled` | True | owner's rule/spec | owner asked for an on/off switch for the 'IV may be high' warning (2026-11-07) |
| `valuation.iv_flag_ratio` | 1.3 | assistant's proposal, approved by owner | our heuristic, not Adam: selected IV >= 1.3x the lowest credible alternative (Log 2026-11-07) |
| `valuation.iv_flag_ni_jump` | 1.5 | interpretation of Adam's words | net income TTM > 1.5x last FY = abnormal (Adam l.2502 idea), not used as a comparator |
| `valuation.iv_flag_ps_max_growth` | 0.15 | assistant's proposal, approved by owner | P/S only compared below 15% growth (it undervalues fast growers) |
| `valuation.iv_flag_dni_max_fcf_to_ni` | 2.0 | assistant's proposal, approved by owner | net income only compared when FCF <= 2x NI (SBC/tax distort NI) |
| `valuation.bank_pb_fair_low` | 1.2 | Adam states it | banks: P/B 1.2–1.4 fair (l.4846) |
| `valuation.bank_pb_fair_high` | 1.4 | Adam states it | banks: P/B 1.2–1.4 fair (l.4846) |
| `valuation.distressed_pb_max` | 0.5 | Adam states it | distressed: buy at P/B ≤0.5 (l.4497) |
| `valuation.reit_pnav_max` | 1.2 | Adam states it | REITs: no more than 1.2× P/B (l.4853) |
| `valuation.reit_pnav_max_high_growth` | 1.5 | Adam states it | REITs with high double-digit DPU: up to 1.5× (l.4866) |
| `valuation.reit_min_yield` | 0.05 | Adam states it | dividend yield ≥5% (SG rule of thumb, l.9758) |
| `valuation.bank_min_yield` | 0.045 | Adam states it | Singapore banks: dividend yield ≥4.5–5% (l.5211) |
| `valuation.psg_undervalued` | 0.2 | Adam states it | PSG 0.2–0.3 fair; below 0.2 cheaper (checklist 17) |
| `valuation.psg_fair` | 0.3 | Adam states it | PSG >0.3 overvalued (checklist 17) |
| `valuation.beta_table` | ((0.28, 0.058), (0.83, 0.061), (1.1, 0.066), (1.4, 0.074), (1.49, 0.077)) | Adam states it | Adam's beta → discount rate rows (l.4391) |
| `valuation.min_discount_rate` | 0.058 | Adam states it | 5.8% is the lowest rate in the table (l.4391) |
| `valuation.max_discount_rate` | 0.11 | software guard | guard against extrapolating the table for very high betas |
| `valuation.doomsday_growth_factor` | 0.5 | Adam states it | growth halves after year 5 (l.4472) |
| `valuation.iv_haircut` | 0.0 | calibration (owner-approved) | flat haircut on DCF/DNI; 0 since the lowest-source growth already gives conservatism |
| `valuation.uncertainty_haircut` | 0.075 | calibration (owner-approved) | extra haircut for growth stocks and single-source estimates; level from tools/haircut_sweep.py |
| `valuation.growth_haircut` | 0.0 | calibration (owner-approved) | alternative single knob (relative cut on growth); off |
| `technical.sma_periods` | (50, 100, 150, 200) | Adam states it | daily: 50, 100, 150, 200 SMA (l.5751) |
| `technical.ema_periods` | (20, 40) | Adam states it | weekly/monthly: 20 and 40 EMA (l.5751) |
| `technical.trend_slope_lookback` | 20 | software guard | bars used to measure a moving average's slope |
| `technical.support_tolerance` | 0.02 | interpretation of Adam's words | Adam: support/resistance is a zone, not a line |
| `technical.min_touches_potential` | 2 | interpretation of Adam's words | how many touches make a level worth watching |
| `technical.min_touches_confirmed` | 3 | interpretation of Adam's words | how many touches confirm a level |
| `technical.swing_window` | 5 | software guard | bars either side of a swing high/low |
| `technical.parabolic_dist_from_50` | 0.25 | interpretation of Adam's words | Adam: far from the moving average 'snaps back like a rubber band' |
| `technical.parabolic_drop_pct` | 0.15 | interpretation of Adam's words | Adam: a 90-degree drop (l.1567); the % is our reading |
| `technical.double_bottom_reclaim_bars` | 3 | software guard | bars to reclaim a level after a double bottom |
| `technical.n_buy_levels` | 4 | Adam states it | three or four buy levels (checklist 15) |
| `technical.near_level_pct` | 0.03 | interpretation of Adam's words | how close price must be to a level to count as 'at support' |
| `portfolio.min_stocks` | 8 | Adam states it | diversification 8–30 positions (l.12102) |
| `portfolio.max_stocks` | 60 | interpretation of Adam's words | Adam: 8–30 positions (l.12102); the cap here is looser (kept from earlier work; confirm) |
| `portfolio.default_target_stocks` | 20 | owner's rule/spec | default number of positions used for sizing |
| `portfolio.tranches` | 4 | Adam states it | buy in 3–4 tranches (checklist 16) |
| `portfolio.speculative_multiplier` | 0.5 | Adam states it | speculative growth: ½ or ⅓ of a normal position (l.9347) |
| `portfolio.turnaround_multiplier` | 0.5 | Adam states it | turnarounds: ½ or ⅓ of a normal position (l.9347) |
| `portfolio.narrow_moat_multiplier` | 0.75 | interpretation of Adam's words | Adam: narrow moat = 'smaller positions, especially initially', no figure; 0.75 kept from earlier work (confirm) |
| `portfolio.max_sector_weight` | 0.3 | interpretation of Adam's words | warning only; Adam's own largest sector target is 27% (l.10295) |
| `dividend.min_yield` | 0.05 | Adam states it | yield ≥5% (SG) (l.9758) |
| `dividend.us_min_yield_screen` | 0.03 | Adam states it | US: ~3% is attractive (l.878) |
| `dividend.min_dps_growth_years` | 5 | Adam states it | rising DPS for 5 years (l.10246) |
| `dividend.payout_min` | 0.2 | Adam states it | payout ratio 20–100% (l.10246) |
| `dividend.payout_max` | 1.0 | Adam states it | payout ratio 20–100% (l.10246) |
| `turnaround.profit_drop_one_year` | 0.25 | Adam states it | profits fall more than 25% in one year (l.10024) |
| `turnaround.consecutive_decline_years` | 2 | Adam states it | or decline two years in a row (l.10025) |
| `execution.stock_slippage_bps` | 5.0 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.option_slippage_per_share` | 0.01 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.illiquid_spread_pct` | 0.005 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.illiquid_option_spread_pct` | 0.1 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.illiquid_min_volume` | 200000 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.illiquid_debuff_frac` | 0.5 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.no_quote_spread_pct` | 0.002 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.commission_per_share` | 0.0 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
| `execution.default_cash` | 100000.0 | owner's rule/spec | paper-trading fill model, owner spec: instant fill at mid plus flat slippage |
