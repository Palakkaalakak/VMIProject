# Test results — docs/TEST_PLAN.md run, 2026-11-19

App: http://localhost:8000, version `ca5f6cd 2026-11-19 Test plan: model and effort to use` (newer than required `2d8099d`).
IB: paused / not connected, Yahoo fallback. Model: Sonnet 5.5, medium effort. Browser console: no errors.
Owner state: unchanged (no settings changed, TEST scan saved then removed, MSFT verdict untouched, no condition filters left).

## Bugs
1. **MSFT moat "At first sight" = weak.** `#/moat/MSFT`: "weak (more warning signs than strengths)". Against: margin fell 2 years
   in a row; Step 1 fails (earnings or margins not consistently rising). For: gross margin 68%, op-margin rank 1 of 7, industry leader,
   pricing power held. Plan expects MSFT not weak. Saved verdict: wide, score 9, sources brand/switching_costs/network_effect/scale,
   reviewed 2026-11-05. (DAL = weak via no-moat industry list: correct.) Severity: wrong label.
2. **Scanner Filters "Reset" does not clear Conditions.** Steps: Filters → + Add condition (steps = 5, ROE >=) → Reset.
   Actual: 2 condition rows remain, hidden `conds` value unchanged, count stays "67 of 105 shown". Expected: all cleared (105 of 105).
   Removed manually via ✕. Severity: cosmetic/functional.

## Observations
- Raw snake_case keys shown to the user: scanner "missed Step 4: revenue_vs_receivables, cash_conversion_cycle"; Why dropped? reasons
  (`cfo_consistent`, `gross_margin_stable`, `current_ratio`…); moat text (`switching_costs`, `network_effect`, `pricing_power`).
- `/api/scan/status` `elapsed` keeps growing after a scan is done (215 s for a 6 s scan); scanner header shows "· 204s" while idle.
- Guided evaluation counter says "question 7 of 8" (plan: 7 questions). "What the app already knows" also on question 2 (plan: 1, 6, 7).
- Scanner rows show steps as "6/7" (plan wording assumes 5).
- Scan result count read once right after a scan finished still showed the previous scan (#17) until the UI refreshed.
- Custom-list scan with SMCI under the Adam preset dropped it with "Step 1: cfo_consistent, gross_margin_stable", not a size reason
  (probably cap now ≥ $10B; not confirmed).

## Passed (with evidence)
- **0 Health:** badge "IB offline" matches `ib.connected=false`. IB fundamentals last synced 11/7/2026 (fresh). AI card: "Not downloaded.
  It needs about 10 GB of disk and an NVIDIA GPU with 12 GB of memory."
- **1 Names/help:** 120 rule rows across 13 groups, 0 titles with `_`, 0 empty (?). `valuation.discount_mode`=fixed, fixed rate 0.1.
  REIT picker options read as titles ("REIT maximum price / NAV · Valuation"); picking one adds "Maximum REIT gearing?" with (?).
- **2 Analysis (MSFT):** "rate 10.0%"; header "judged on the latest fiscal year". Normalise tick → "normalise: ON (3y)", "3-year average",
  6 "(NORMALISED)" tags; remembered for MSFT only (AAPL unticked); untick restores. 10-year only → "10-YEAR ONLY"; API: RDDT Step 1
  fails "only 6 years of data (<10)". Settings unchanged (normalise off, min_years 5). Not run: RDDT/JPM pages in the UI.
- **3a presets:** size note ends "(applies to every universe)"; floors $10B Adam presets, $1B speculative, $2B Finviz, $2B current/custom.
- **3a scans (funnels from /api/scan/status):**
  - S&P 500, "Adam: great business": 105 results, 75.9 s. universe 492 (2.6 s) → no_moat_industry 449 → track_record 302 (0.3 s)
    → profitability 219 → long_term_chart 206 (12.7 s) → deep 105 (50.3 s). 19 "Industry: no moat (…)" drops, size drops
    ("Size: market cap $8.7B < $10B").
  - ULTRA on 12-name list, runner-ups on: 6.0 s; funnel 12/12/10/10/10 → deep 0 (4.2 s); 5 runner-ups (NVDA, GOOGL, AAPL, FAST, COST);
    dropped has a reason for all other tickers (WST "net margin fell 4 years in a row", ODFL "revenue 3 down years (>2)").
  - Cache: rerun deep 0 s, "(10 from cache)", 1.8 s total; "Ignore cached analyses": deep 3.3 s, 6.1 s total.
  - Show runner-ups untick: "5 of 5 shown" → "0 of 5 shown".
  - Adam S&P rerun from cache: 8 s, 209 from cache.
- **3b consistency:** NVDA, GOOGL, AAPL, FAST, COST row vs `/api/analysis`: price, IV, ROE, ROIC, net margin, basis identical
  (COST price 1090.57 vs 1089.81 = drift). Rows show "(FY)". No loss-year row seen.
- **3c filters:** ROE between 15–30 → 44 rows, reversed 30–15 → 44; >20 → 74 and >=20 → 74; <20 → 29 and <=20 → 29; steps = 5 → 69.
  0 rows outside range in every case. Conditions restored after reload. "Condition on any column" option adds a row.
- **3d saved scans:** "TEST scan · 105 results" saved; after a different scan, Open → "105 of 105 shown · scan #17"; removed (saved list empty).
- **4 Moat:** MSFT/DAL cards render; signal table rows tagged adam/inferred; verdict form shows "1a. Brand", "1b. Pricing power" and 2–5 with the
  "counts once" note. Guided evaluation walks all questions with search links. AI second-opinion card hidden (AI not installed): correct.
- **5 Chart:** defaults correct (SMA 50/100/150/200 on; EMA 20/40 off; Bollinger, Stochastic, Volume on; EMA note present). 5m/15m/1h/Daily/
  Weekly/Monthly load (4596/1533/5080/2512/1044/489 bars, source Yahoo); Weekly/Monthly auto-tick EMA 20/40. Range buttons present.

## Not tested / UNVERIFIED
- Chart hover readouts and cross-check vs another source, Stochastic pane look, range windows actually changing, drawing tools + persistence.
- Moat pricing-power 3-source rule (4.4) and saving a guided verdict (would modify the owner's MSFT verdict).
- Step 3 line update after save; RDDT/JPM analysis pages in the UI; 3a.5 custom-list size floor with a confirmed < $10B name.
- Section 6 (AI download): not tested, owner did not agree.
