# Test results — docs/TEST_PLAN.md run, 2026-11-19

App: http://localhost:8000, version `ca5f6cd 2026-11-19 Test plan: model and effort to use` (newer than required `2d8099d`).
IB: paused / not connected, Yahoo fallback. Model: Sonnet 5.5, medium effort. Browser console: no errors.
Owner state: unchanged (no settings changed, TEST scan saved then removed, MSFT verdict untouched, no condition filters left).

## Bugs
0. **FIXED in 8b84ac6 (download completed, 9.0 GB model + CUDA 13.5 runtime; AI answered MSFT in ~34 s on the GPU, 11.5 GB VRAM). AI download fails: "no Windows llama.cpp build found in the latest release (install Ollama instead)"** (blocker for the built-in AI).
   Steps: Settings → "Download the built-in AI". `/api/ai/status` → `builtin.download.error` = that text, nothing downloaded.
   Root cause: `vmi/ai_runtime.py:30` `RELEASES_API` = `.../ggml-org/llama.cpp/releases/latest`; GitHub's "latest" is currently tag `v1.0.0`
   with no Windows assets, while the real builds are `b12541` etc. (38 assets each incl. `llama-b12541-bin-win-cuda-12.4-x64.zip`,
   `cudart-llama-bin-win-cuda-13.5-x64.zip`). `pick_assets` therefore returns None. Suggested fix: query `/releases?per_page=10` and use the
   first release for which `pick_assets` is not None. PC: RTX 5070 Ti Laptop 12227 MiB, 75 GB free, so requirements are met. Model/steps 2-3
   of section 6 could not run.
1. **FIXED in 4a60f0e (now "narrow-looking"; DAL still weak, V wide-looking, COST narrow-looking). MSFT moat "At first sight" = weak.** Cause: `first_sight.assess` used `bad >= 2` so 2 warnings beat 4 strengths; now weak needs bad >= good. `#/moat/MSFT`: "weak (more warning signs than strengths)". Against: margin fell 2 years
   in a row; Step 1 fails (earnings or margins not consistently rising). For: gross margin 68%, op-margin rank 1 of 7, industry leader,
   pricing power held. Plan expects MSFT not weak. Saved verdict: wide, score 9, sources brand/switching_costs/network_effect/scale,
   reviewed 2026-11-05. (DAL = weak via no-moat industry list: correct.) Severity: wrong label.
2. **FIXED 2026-11-20 (Reset now clears the condition rows and their hidden value; checked in the browser). Scanner Filters "Reset" does not clear Conditions.** Steps: Filters → + Add condition (steps = 5, ROE >=) → Reset.
   Actual: 2 condition rows remain, hidden `conds` value unchanged, count stays "67 of 105 shown". Expected: all cleared (105 of 105).
   Removed manually via ✕. Severity: cosmetic/functional.

## Observations
- FIXED for scanner text (missed/Why dropped now "revenue vs receivables"); moat-page text from the AI is plain words. Raw snake_case keys shown to the user: scanner "missed Step 4: revenue_vs_receivables, cash_conversion_cycle"; Why dropped? reasons
  (`cfo_consistent`, `gross_margin_stable`, `current_ratio`…); moat text (`switching_costs`, `network_effect`, `pricing_power`).
- FIXED (timer stops when the scan ends; checked: 3.8 s stays 3.8 s). `/api/scan/status` `elapsed` keeps growing after a scan is done (215 s for a 6 s scan); scanner header shows "· 204s" while idle.
- FIXED (counter is N of N). Guided evaluation counter says "question 7 of 8" (plan: 7 questions). "What the app already knows" also on question 2 (plan: 1, 6, 7).
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

## Follow-up run (remaining items)
- **3a.5 size floor:** Adam preset, custom list AOS, ARE, APTV → all dropped "Size: market cap $8.7B / $7.4B / $7.8B < $10B". PASS.
- **RDDT page:** type speculative, rate 10.0%; 10-year only → "10-YEAR ONLY" and "only 6 years of data (<10)". PASS.
  Observation: header shows raw `speculative_growth`.
- **JPM page:** type bank, "moat unreviewed", no "rate N%" line (bank method, expected). Observation: JPM Step 3 passes (True) with no
  moat review and no override.
- **4.4 pricing-power rule** (done on JPM with a DB override, MSFT verdict untouched, override deleted afterwards, `{}` confirmed):
  brand + pricing_power + scale, wide, 8 → Step 3 False (2 slots); pricing_power + scale + barriers → Step 3 True (3 slots). PASS.
- **Chart hover:** readout for 04 Jun '26 = O 435.81 H 436.15 L 426.41, C ~428.05 (+0.17%); `/api/bars` 2026-06-04 = 435.81 / 436.15 /
  426.41 / 428.05. PASS (close digit read from a small zoom). Stochastic readout shows %K/%D + "neutral"; 80/20 lines and two lines
  visible. PASS.
- **Ranges:** 3M and 5Y visibly change the window (axis labels differ). PASS.
- **Drawings:** Horizontal line draws and saves (`vmi.chart.draw.MSFT.1d=[{"kind":"hline","price":498.86}]`, localStorage, per browser).
  Clear drawings empties it (`[]`). Trend line: 3 attempts by automated clicks did not store anything (code needs both clicks on a bar
  time); UNVERIFIED, may be click targeting. Reload persistence read from localStorage, not re-screenshotted.

## Final items
- **Trend line:** draws and saves (`[{"kind":"trend","a":{"time":"2026-02-09",...},"b":{"time":"2026-05-08",...}}]`), still drawn after a
  page reload (yellow line seen). PASS. Quirk: with the browser tool the first chart click after choosing the tool was not registered
  (needed 3 clicks); probably the harness (first click only moves the mouse), not confirmed. Drawings cleared afterwards.
- **Guided evaluation save (MSFT):** final screen shows "4 of 5 sources", answers prefilled from the existing verdict; "Save the moat
  evaluation" with "save to config" unticked wrote a DB override (reviewed 2026-11-19) and the Step 3 line updated ("PASS · wide · 9/10 ·
  reviewed 2026-11-19"). Restored by deleting the DB override; MSFT is back to the committed judgement (reviewed 2026-11-05), git tree clean.
- **Section 6:** FAILED at step 1, see bug 0.

## Not covered
- A scan row with a loss-year ROE note (none appeared in the scans run).
