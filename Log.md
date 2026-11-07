# Engineering log

**For every future change (AI or human):** add an entry at the top of "Entries" (newest first) with what
changed, why, the files touched, how it was verified, and what is left open. Update "Current state" when an
entry changes it. Keep the evidence (links, versions, dates) for any claim about an outside system, because
those claims go stale and the next person has to be able to re-check them.

Related docs: `README.md` (overview, architecture, recipes), `docs/GROUND_RULES.md` (owner's rules),
`docs/CALIBRATION.md` (intrinsic-value calibration against Adam's numbers).

---

## Current state (2026-11-05)

- Offline test suite: `python3 -m pytest -q tests`, 89 passing.
- Fundamentals: SEC EDGAR → stockanalysis → Yahoo, merged in `vmi/data/fundamentals.py`. IB is tried first:
  TWS XML (works only if IB still permits it for your login), then the Client Portal Gateway
  (`vmi/data/ibportal/`). **The gateway path is implemented and offline-tested, but it has not been run
  against a real logged-in gateway yet.** The first live run is the `check` command below.
- Open items: a live gateway check on the owner's PC; full-market scanner benchmark; judgement-only
  calibration cases (BKNG/UNH growth input, NKE/LVMUY on P/S); companies with a short history.

### Where to change what

| To change… | Edit |
|---|---|
| an IB route, gateway path or IB field name | `vmi/data/ibportal/routes.py` (only there) |
| how an IB row label maps to our concepts | `LABELS` in `vmi/data/ibportal/parse.py` |
| IB cache keys / TTL / sync behaviour | `vmi/data/ibportal/service.py`, `ttl_ib_portal` in `vmi/config.py` |
| the order IB sources are tried, breaker pauses | `vmi/data/ib_fundamentals.py` |
| a VMI threshold | Settings screen in the UI (stored in `config/rules_settings.json`); defaults in `vmi/rules.py` |
| a data provider or the merge order | `vmi/data/<provider>.py`, `vmi/data/fundamentals.py` |
| business-type classification | `vmi/analysis/classify.py` |
| a per-stock judgement (any input) | `python -m vmi.overrides …`, the UI card, or `config/judgements.json`; new keys in `vmi/overrides.py` |
| how analyst growth sources are combined | `blend` in `vmi/rules.py` (`GrowthRules`) |

---

## Entries

### 2026-11-07 — "IV unlikely Adam-like" flag + scanner filter panel

- `vmi/analysis/iv_confidence.py` (our heuristic, not Adam): flags an IV that is probably too HIGH: the selected IV is
  >= 1.3x the lowest *credible* alternative (DNI only if FCF <= 2x net income and TTM net income <= 1.5x last FY; P/S only if
  growth < 15%; cash-flow DCF if another method was selected). Version 1 (any two methods differ 1.5x) had ~40% false alarms
  (CRWD, PANW, NOW), version 2 (credible comparators, ratio 1.5) 5 of 7 / 1 false. Final, on the 42 reference stocks with
  Adam's growth: 9 flagged, 7 of them >30% off Adam (6 of the 7 we value too high: BKNG, VEEV, DSGX, ACGL, NVO, UNH; missed NKE),
  2 within ~18% (AZO, LVMUY). Ratio 1.5 would give 6 flagged / 5 caught / 1 false: set `iv_flag_ratio` for a stricter flag.
  Thresholds were read off the same 42 stocks: expect it to be weaker on new ones. A turnaround trigger caught NKE too but
  added 3 false alarms (CNSWF, LVMUY, PANW), so it was left out. Too-low values are not flagged.
  On/off: `rules.valuation.iv_flag_enabled` (Settings page, with the thresholds). Warning only, never changes IV or steps;
  off when the owner typed an `iv_override`. Live BKNG (own growth 15.2%, no P/S) is 352 vs DNI 272 = 1.29x: just under the line.
- Scanner results filters (`static/js/views/scanner_filters.js`, client-side, remembered in the browser): each step 1–7
  any/must pass/must fail, min steps, MOS, growth, ROE, ROIC, net margin, PEG, yield, market cap, beta, sector, method, moat,
  style, category, trend, great business, below IV, chart entry, buy signal, moat reviewed, low-confidence IV, has judgement.
- Verified: new tests + valuation tests pass (28); JS syntax-checked. UNVERIFIED in a real browser; full suite was not finished.

### 2026-11-07 — Why Adam's IVs differ for BKNG/VEEV/MELI/NVO/DSGX/EVVTY/CNSWF: no single rule found

Question: with Adam's own growth (`tests/fixtures/adam_growth_reference.tsv`) our DCF is still 1.5–5.8× his on his core stocks.
Tests on all 42 stocks (scratch `combo.py`, Adam growth fed in, ratio = ours/Adam):
- dcf_fcf median 1.03, sd(ln) 0.52, 19 within ±15%; dni 0.97 / 0.71 / 12; dcf_normalized 1.05 / 0.43 / 20.
- min(fcf, dni): median 0.82, sd 0.68 (worse). min of all four: 0.79 / 0.63.
- median(fcf, dni, ps_mean): 1.02 / 0.31 / 22 (best spread), but P/S is price-anchored, so it fits Adam's IVs
  (which sit near price) by construction. Not evidence of his method; NOT adopted.
- GOOGL 2026 worked numbers (doc l.2365-2373) reproduce exactly with our engine when years 6-10 use Stock Oracle's *LT*
  rate (14.3/10.13 → 292.41). Using 14.3 flat gives 332. So Adam's tool uses the LT rate for years 6-10, which we lack for
  most stocks (only Stock Oracle shows it). For BKNG/VEEV/EVVTY even negative years 6-10 growth would not close the gap.
- Earlier: no global bias (implied discount rate median 6.5% vs ours 6.4%); no base rule fits all (9 bases tried).
Conclusion: UNVERIFIED which base/shares/LT-rate Adam's Stock Oracle used for these names; the gap is per-company data,
not a formula bug. Needs his Stock Oracle screen (FCF, shares, LT growth, discount rate) for BKNG, VEEV, MELI to settle.
No code change. Open: optional pin of Adam's IVs for the 6 core outliers via `iv_override` (awaiting owner approval).

### 2026-11-07 — Cash flow vs earnings: a pattern, but no rule
- Our FCF DCF at Adam's growth overshoots more as FCF/NI rises: median ratio to Adam 0.95 (FCF/NI<0.9), 1.04 (0.9-1.15), 1.17
  (1.15-1.5), 1.51 (>1.5: CNSWF DSGX MELI NOW VEEV). Capping the base at k×NI (k 1.0-2.0), averaging FCF and NI, or NI only does NOT
  improve the fit (sd(ln) 0.65-0.82 vs 0.45; CRWD/PANW/NOW with FCF/NI 3-27 match Adam on plain FCF). So no mechanical rule from
  the financials; Adam's treatment is stock-specific. Open: his calculator inputs for BKNG VEEV MELI NVO DSGX EVVTY CNSWF.

### 2026-11-07 — Is something systematically wrong? Diagnostics (42 stocks, Adam's growth fed in, dcf_fcf)
- Engine: reproduces Adam's 7 worked examples within 0.2 % (tests/test_adam_worked_examples.py). Not the maths.
- No global bias: median ours/Adam 1.06 on the TTM FCF base; implied discount rate median 6.5 % vs ours 6.4 %; implied base / our
  base median 0.97. Our beta equals Finviz's for almost every stock (NVO .37/.71, DSGX .22/.65 differ, too little to matter).
  Rate needed to explain the big misses (BKNG 14 %, VEEV 13 %, MELI 30 %) is absurd, so it is not the discount rate.
- Dispersion is stock-specific: ~10 stocks have Adam's IV 1.5-6x BELOW an FCF DCF at his own growth (MELI 5.8, NVO 2.3, ACGL 2.3,
  BKNG 2.0, EVVTY 1.8, VEEV 1.7, DSGX/CNSWF 1.5). No single alternative base explains Adam's IVs: best candidate (CFO TTM) still
  has sd(ln) 0.42, FCF TTM 0.45, NI avg4 0.65, so ±40 % of unexplained scatter against any mechanical base.
- Years 6-10 growth (Stock Oracle's lower long-term rate, e.g. MSFT 19.6→8.9 %) explains some (IDXX/NFLX/NKE/UNH need 0.4-0.8× the
  year 1-5 rate) but not BKNG/VEEV/EVVTY (would need negative growth). We do not have Stock Oracle's long-term growth.
- Conclusion: no bug found; the remaining variation comes from inputs/method choices in Adam's Stock Oracle valuations that are
  not in our files. Needed to close it: Adam's calculator inputs (base cash flow, debt, cash, shares, growth 1-5 and 6-10, rate)
  for the ~10 outliers.

### 2026-11-07 — Fed Adam's own growth (tests/fixtures/adam_growth_reference.tsv): residual gap is base/method, not growth
- Adam's growth into our full model (42 stocks): median ours/Adam 1.04, within ±15 % 21 (17 with our growth). Growth is
  part of it (ASML 1.6 → 1.0, AVGO: single-source Finviz 65 % / 42 % vs Adam 26 / 21 %), not most.
- Growth trend, lowest source vs Adam (40 stocks): mean diff −1.2 pt, median |err| 2.8 pt (same for median/average), corr 0.60,
  slope 0.92; single-source tickers overshoot (+4.3 pt mean), two-source undershoot (−3.5 pt). Sandbox has no IB source.
- Base fit per stock (best of FCF/CFO/NI × TTM/FY/4y-avg): 9 different bases each fit a few stocks within 10 %, no single rule;
  with ~10 candidates a ±10 % hit is partly chance, so the BKNG net-income-average judgement is weaker evidence than it looked.
- Turnaround "4-year average base" REMOVED: with Adam's growth the plain TTM FCF base fits UNH (1.07) and NKE (1.18) while the
  average overshoots (1.47 / 2.32). Turnaround keeps DCF-first with consistency waived.

### 2026-11-07 — BKNG explained: Adam's growth is 14.9 % (owner), so the base differs
- With his growth (14.9 %, ours 15.2 %), reproducing his 188.08 needs a base of ~4.7B (ours: FCF 9.2B). Shares would have to be
  ~1.6B or the discount rate 14 %, so neither is the cause. Candidate bases: FCF FY25 9.09B → 368; FCF − SBC → 349; NI TTM
  7.18B → 289; NI FY25 5.40B → 216; 5y avg FCF → 263; **4y average net income (2022–25) 4.66B → 186**: the only match.
- `config/judgements.json` BKNG: method dni + base_period average (Adam l.2502, l.1568), flagged INFERRED/please verify. Judged
  calibration: ours 175 vs Adam 188 (0.93, slightly conservative with the 7.5 % haircut). Pure formula still 0.95-1.9x on the FCF base.
- Open: why Adam averages NI for BKNG (FY25 NI dipped on one-offs; 2022 was a COVID-recovery year) is not stated anywhere I read.

### 2026-11-07 — Scanner growth = lowest analyst estimate; BKNG gap analysis
- Scanner "Growth" (and the category/style that use it) = the LOWEST usable source estimate
  (`pipeline.displayed_growth`, same filters as the valuation: excluded sources and impossible values dropped), or the
  human's growth override when set. Supersedes `used_growth` from the entry below.
- BKNG vs Adam (ours 352-370 vs his 188.08), engine verified: it reproduces Adam's other worked examples. On our FCF base
  (TTM 9.24B, FY 9.09B, 816M diluted shares, debt 20.1B, cash 15.8B, rate 6.74 % for beta 1.153) Adam's 188 needs a flat
  ~5.5 % growth for 20 years, or net income TTM (7.18B) at ~9.4 %, or a base FCF of ~4.6B at consensus growth. Our doomsday
  case (growth halves after year 5, 2 % tail) is still 266, so his figure is NOT a pessimistic variant of the same inputs.
  No Adam rule explains the gap: FCF is the right base (CFO 9.4B > 1.5x NI so the AMZN rule applies, float share 12-29 % <
  the 50 % test), capex is tiny and steady, shares are post-split consistent (25:1, SEC data split-adjusted). Consensus
  EPS growth is 15-16 % (Finviz 15.9, Zacks 15.2; Yahoo/stockanalysis next-year 18/59 %, the 59 % is a one-off EPS rebound
  after the FY2025 charge and not used). UNVERIFIED which inputs Adam used (his reference file has only IV and levels).

### 2026-11-07 — BKNG scanner oddities: growth 65.8 % and ROE 22,573 %
- Growth: the displayed growth, the category and the style used `est.eps_growth_5y`, the plain AVERAGE of all sources, so one
  outlier source (BKNG: very likely IB's EPSTRENDGR on a small base; UNVERIFIED, no IB data in the sandbox) inflated them
  while the DCF itself used the lowest source (15.2 %). Now `pipeline.used_growth()` = the growth the valuation used.
  Adam's rule for an outlier site: ignore it and use the ones that agree (Master doc l.2437).
- ROE: the data source's ROE series ends at FY2023 with 225.7 (equity ≈ 0 that year); BKNG's equity is now −$10.4B from
  buybacks. `pipeline.displayed_roe()` shows nothing when equity ≤ 0 (Adam: ROE from buyback-driven negative equity is
  "effectively infinite, very good", l.1230); Step 4 already passes such companies via `negative_equity.assess`.

### 2026-11-07 — Calibration after the Adam-rule fixes (sandbox, no IB data, pure formula)
- Before → after: median ours/Adam 0.861 → 0.898; within ±15% 13 → 17 of 43; 0.85–1.02 band 8 → 9; below 0.75 8 → 6;
  above 1.05 14 → 14.
- Per stock: PLTR 0.28 → 0.72 (DCF, profitable), NKE 0.67 → 0.90 and LVMUY 0.57 → 0.68 (turnaround, 4y average base),
  CNSWF 0.79 → 1.03, EVVTY 1.72 → 1.04 and TMO 0.67 → 1.07 (P/S reference / DCF), UNH 1.22 → 1.67 (turnaround average
  base above the trough with 13% consensus growth; the committed UNH judgement pins DCF on TTM FCF, so the judged run is
  unaffected). Turnaround selection takes the first method with a value (preconditions waived), fix in 2a72b7e.

### 2026-11-07 — Valuation rules re-checked against Adam's full Master document
- Read the whole VMI_VERBATIM_MASTER_DOCUMENT.md (3,495 lines); every rule with its line number is summarised in the
  session notes (kept out of the repo). Engine check: Adam's own inputs reproduce his worked examples (MA 655.97, AMZN 206,
  AAPL 256, SGX 17.67, BLK 795) within 0.2% and his beta table rows exactly → `tests/test_adam_worked_examples.py`.
  The gaps vs his IVs therefore come from inputs (growth, base cash flow, method choice), not the maths.
- Changes, each tied to a line of the document:
  - Speculative growth that is already profitable with positive CFO/FCF → DCF, not PSG (P/S growth only "for companies
    without consistent profits and cash flow", l.2264/l.2858). PLTR 0.28 → 0.72 of Adam.
  - Turnarounds (Adam's test l.2898, now `consistency.is_turnaround`, shared with the category) → DCF/DNI on the 3–4 year
    average base (abnormal latest year → "average of the last three or four years", l.2502). Replaces my
    "middle of P/S, DCF, DNI" fallback.
  - Neither CFO nor NI consistent and not a turnaround → fails Step 1; P/S shown for reference ("the only method", l.1510).
  - Working-capital/float rule kept (MELI) but now cited to l.1568 (finance-type cash flow → discounted net income);
    removing it put MELI at 5.9× Adam.
  - BKNG and IDXX moat grade wide → narrow (Adam names both as narrow-moat large growth, l.2852).
  - `deep_cyclical` category only when profits/CFO are actually inconsistent (LIN is "pretty predictable", l.2740).
  - Zacks: a page without the EPS fields raises instead of being cached as "no data" for 3 days.
- Not Adam (owner's call): uncertainty haircut 7.5%, 40% cap on years 1–5 growth. Unexplained by his rules: BKNG (his 188
  implies ~4% growth vs 15% consensus), ASML/AVGO/NVDA (cap). Calibration numbers for this change: see the next entry.

### 2026-11-07 — Moat evaluation page
- New view `static/js/views/moat.js` (route `#/moat/SYMBOL`), opened in its own tab from the "Open Moat evaluation" button in
  Step 3. One place for: Adam's pass/fail tests, the evidence rows (N/A = no numbers from Adam, reviewer judges), the peer
  comparison and annual-report excerpts (loaded automatically), Adam's 5 sources as a checklist + his questions, and the
  verdict form (grade, sources, score /10, note; DB or config/judgements.json). Saves through the existing override keys,
  so Step 3 and the pipeline need no change. The inline loader/peer/filing code moved out of analysis.js.
- Verified in Chromium against the running app (AAPL): page renders, peers + 10-K load, no console errors.

### 2026-11-07 — Review pass on the IB path
- One flow: `service.login_and_sync()` (contract ids → browser login → parallel sync) is used by both the CLI and the app's
  job; the duplicated copy in the CLI is gone. `--no-statements` passes through.
- Robustness: an unexpected exception on one ticker (parser surprise) is recorded as that ticker's failure instead of
  ending a 500-ticker run. IB's 404 MISSING_DATA is reported as `NO_IB_DATA` ("other sources cover it"), not as an error.
- `check` resolves contract ids once for all tickers (was one 15 s TWS wait per ticker when TWS is down).
- Contract-id progress now reaches the caller's `say` (the app's Settings card), not just the console.
- Removed a dead `except PortalError: raise` in `Portal._send`. Tests: 94 pass (new: one bad stock never ends the sync).

### 2026-11-07 — IB sync inside the app; app listens on localhost by default
- `vmi/data/ibportal/job.py`: one background job (S&P 500 → contract ids via the app's IB Gateway connection → browser login
  window → parallel fetch → `ibportal:last_sync`). Settings page card "IB fundamentals" (last sync, fresh/stale, "Sync now",
  live progress); `GET/POST /api/ib/sync`. At app start `job.autosync()` opens the login window only when the IB data is
  older than `ttl_ib_portal` (14 d) or was never synced; turn off with `VMI_IB_PORTAL_AUTOSYNC=0`. Tests never open it
  (conftest `no_autosync`). The window opens on the machine running the app.
- Default `host` is now 127.0.0.1 (was 0.0.0.0, i.e. reachable from the LAN, which now matters because a POST can open a
  window on this PC). `VMI_HOST=0.0.0.0` restores LAN access (ecosystem.config.cjs still sets it for the Linux/PM2 setup).
  Browsers on Windows cannot open http://0.0.0.0:8000: use http://localhost:8000.

### 2026-11-06 — `sync` stalled ~20 min before the browser opened
- Suspect: contract-id lookup via TWS ran 11 batches with a 120 s timeout each against a connected-but-silent IB Gateway.
  Now bounded (20 s per batch, 60 s total, `IBGateway.conids`), `prefetch_conids` never raises and `sync` continues with the
  cached ids (tickers without one are listed and skipped). Every step prints a line first ("Loading the S&P 500 list",
  "Looking up contract ids", "Opening the browser"), so a stall shows where. UNVERIFIED that this was the cause: with a
  full conid cache the lookup is skipped entirely, so the next stall report needs the last printed line.

### 2026-11-06 — First full `sync --sp500` (VERIFIED on a real login)
- 503 tickers, fast mode (copied browser cookies accepted by the portal), 8 workers: 350 s. Result: 503 conids, 496 analyst
  records, 497 statement sets. That is ≈ 10 requests/s, i.e. bound by `ib_portal_max_rps` (10), not by the workers; raising
  it is untested against IBKR's real limit (no 429 was seen at 10/s).
- 6 stocks have no IB data (HTTP 404 `{"type":"MISSING_DATA","message":"No estimates data for isin …"}`): FOX, KKR, L, MPC, NWS, ZTS.
  This is IBKR's side; the other sources (SEC, stockanalysis, Yahoo) cover them as before.
- Next: re-run the calibration (docs/CALIBRATION.md) with the new IB growth source before trusting it.

### 2026-11-06 — Speed + cleanup: parallel `sync`, gateway path removed
- Cost model of `sync --sp500`: ~500 tickers x 7 requests (6 statements + key metrics) + 10 batched data_list calls
  ≈ 3,500 requests, previously one at a time through the browser and capped at 5/s (≥ 12 min, realistically more).
- Fast mode (`browser.login`): after the browser login, the browser's cookies and user agent are copied into an httpx
  client, which is checked with one real request; if it answers, `sync` runs `ib_portal_workers` (8) tickers in
  parallel under one shared, thread-safe rate limit (`ib_portal_max_rps` 10; IBKR documents ~10 req/s per session for
  its Web API, the portal's own limit is unpublished) and retries 429/502/503/504 with backoff (Retry-After honoured).
  If the copied cookies are refused, the browser sends every request serially, as before. Verified locally: the cookie
  copy (browser cookie + UA reach the server via httpx; local HTTP server, Chromium). UNVERIFIED on IBKR: whether the
  portal accepts the copied session (the run prints which mode it used, `check` reports `mode`).
- Removed the Client Portal Gateway path (proven unable to carry fundamentals): gateway fallbacks and base chains,
  self-redirect retry, `probe.py`, `tools/start_cp_gateway.cmd`, `/trsrv` contract lookup (`parse.pick_conid`),
  settings `ib_cp_url/ib_cp_verify/ib_cp_max_rps`, the PORTAL breaker. The app now READS the IB portal cache only
  (`cached_fundamentals/estimates`); before, every uncached analysis tried https://localhost:5000 first.
- CLI: the browser is the only path, so `--browser` is accepted but no longer needed; `sync --workers N`;
  ib_async's per-port "API connection failed" log spam is silenced in the CLI (the error message lists every port).
- `check` trimmed to route status, parsed counts, analyst values, unmapped labels and raw dump (the one-off
  investigation outputs are recorded in the entries below).
- Tests: 90 pass (gateway-only tests removed; new: parallel sync on >1 thread, 429 retry, cross-thread rate limit,
  401 abort, cache-only app reads, browser fallback is serial).

### 2026-11-06 — Contract-id lookup in batches
- First `sync --sp500 --browser` took ~10 min before the login window opened: `_tws_conids` qualified one symbol per round
  trip (~500). Now `IBGateway.conids()` qualifies 50 per call and prints progress. UNVERIFIED on a live Gateway (tests
  have no TWS); ids are cached 180 days, so only the first run pays.

### 2026-11-06 — `sync --browser` fails fast without IB Gateway
- `sync --sp500 --browser` died after the browser login because contract ids need the TWS API (IB Gateway was closed).
  `service.prefetch_conids()` now resolves and caches uncached ids BEFORE the browser opens; if TWS is down the command
  exits with a clear message. Cached ids (180 days) make later runs independent of IB Gateway.

### 2026-11-06 — Real run #3: growth source wired (EPSTRENDGR), MSFT gaps are IBKR's
- MSFT short series (EPS, normalised EPS, shares outstanding, short-term debt, CFO): IBKR's own table has null cells for
  most years in those rows (e.g. EPS only FY2025, CFO FY2023 and FY2025). Source-side gaps, not a parser bug; the SEC series
  fills them in the merge.
- fin_trends (I/B/E/S consensus, FY actual + estimates to +5y): AAPL pretax income FY2025 132.7B → FY2029 194.8B =
  10.1 %/yr (FY2030 184.5B is thinly covered); MSFT FY2026 159.4B → FY2030 314.7B = 18.5 %/yr. `key_metrics.EPSTRENDGR`
  = AAPL 9.85 %, MSFT 17.38 %: same ballpark, so it behaves as a forward consensus growth rate. Its meaning is still
  not documented anywhere I could read, so it is registered as UNVERIFIED-but-cross-checked.
- Implemented: `routes.KEY_METRIC_FIELDS` + `parse.parse_key_metrics`; `service._fetch_analyst` makes one key_metrics call
  per stock and stores EPSTRENDGR as `eps_growth_5y` (the IB source in `est.sources`). It enters the growth blend
  like any source, so with the default "lowest" blend it can lower growth; exclude it per stock with the
  `exclude_sources` override. Run the calibration (docs/CALIBRATION.md) after the first full sync before trusting it.
- Not done: CAGR from fin_trends as a second source (pretax income is not EPS; would double count one forecast).

### 2026-11-06 — Real run #2 (AAPL, MSFT) and what is still open
- Verified: with the new LABELS AAPL parses 29 concepts x 4 annual years (net income, CFO, EPS, SG&A, R&D, ...). MSFT parses
  the same but with short series: eps_diluted 1, eps_diluted_norm 1, shares_outstanding 1, st_debt 1, cfo 2 (cause
  unknown: `check` now prints `short_series_rows`, the raw cells of those rows).
- Verified shapes: `fin_trends` (Refinitiv I/B/E/S consensus) = `{name, search_id, forecast_id, value, source,
  periods:[{title, fiscal_year, fiscal_period_number, search_id, actual, estimate, suprise…}]}`; only Revenue, Net Income
  bf/Tax and Dividend Per Share have estimates (no EPS row). `key_metrics` has `EPSTRENDGR` (AAPL 9.85%, MSFT 17.38%),
  TARGET_PRICE, ANALYST_CONSENSUS; meaning of EPSTRENDGR is UNVERIFIED (not in portal JS). `check` now prints the
  fin_trends digest `[fiscal_year, actual, estimate]` per row and saves the full answers in the raw JSON.
- Symbol → conid needs the TWS API (IB Gateway running); without it only AAPL/MSFT (KNOWN_CONIDS) work in `check`.
- Open: choose the growth source from the digest (candidates: CAGR of consensus pretax income / revenue from
  fin_trends; EPSTRENDGR once its meaning is confirmed). Wire it into `parse_analyst`/`estimates` only then.

### 2026-11-06 — Real AAPL labels mapped; symbol lookup via TWS; growth-field hunt
- Real run (AAPL, MSFT): `/iserver/secdef/search` on the portal site answered `400 {"error":"Bad Request: no bridge"}`
  (needs a trading/brokerage session, which a browser login does not open). The secdef code and its read-only exception
  were REMOVED (unverifiable). Symbol → conid in browser mode now uses the TWS API connection (`IBGateway.conid`, needs
  the live IB Gateway running), cached 180 days. `KNOWN_CONIDS` only feeds `check`.
- Row names from the real income/balance/cash answers added to `parse.LABELS` (net income = "Net Inc. Incl. Ex. Items",
  CFO = "Cash from Op. Act.", plus cost of revenue, SG&A, R&D, pretax income, diluted EPS, DPS, shares outstanding).
  Still unmapped on purpose: "Interest Inc.(Exp.),Net-Non-Op." (net, sign ambiguous), "Total Debt", PP&E rows.
- Growth: `data_list` returned BETA only. `LONG_TERM_GROWTH` is a real IBKR column name (portal i18n
  `col_LONG_TERM_GROWTH`, "Long Term Growth") but not returned for AAPL via data_list. `key_metrics` fields seen:
  ADIVSHR ANALYST_CONSENSUS APR2TANBK APRICE2BK AQUICKRATI AREVPS AROEPCT DIVNQXDT DivYield_CurTTM EPSTRENDGR MKTCAP
  PEEXCLXOR QREV TARGET_PRICE TARGET_TO_PRICE_PCT TICKER. `EPSTRENDGR` is not in the portal JS, so its meaning is
  UNVERIFIED. `check` now prints key_metrics values, key_ratios head and `fin_trends` answers for the estimate rows
  (hasEsimates + search_id) so the growth source is chosen from real data.

### 2026-11-06 — Browser path VERIFIED; conid lookup via secdef search; evidence lists in `check`
- Real run `check AAPL --no-tws --browser`: all 9 fundamentals routes answered via `/tws.proxy` on the portal site;
  20 line items x 4 annual years parsed; `data_list` returned BETA only (1.09), not LONG_TERM_GROWTH. Contract route
  `/portal.proxy/v1/portal/trsrv/stocks` answered 401 (not a portal route).
- Evidence for symbol lookup (portal JS in the 2026-11-05 research dump): `PORTAL_BASE_URL:"/portal.proxy/v1/portal"`,
  `getSearchBySym` → `/iserver/secdef/search?symbol=`. `fundamentals/search/{conid}?query=` is a search INSIDE a
  contract, not symbol → conid. Implemented: `Portal.conids` in direct mode calls secdef search per symbol;
  `parse.pick_secdef_conid` picks the US-listed STK whose symbol matches. `routes.READ_ONLY_EXCEPTIONS` allows only that
  one /iserver route (contract search, not trading). UNVERIFIED on a real login: the exact answer shape (documented
  shape used: conid, symbol, description, sections[].secType).
- Direct mode uses single bases (`DIRECT_*`), no fallback chains.
- `check` now prints `unmapped_rows` (IB row labels not in parse.LABELS), `data_list_values` and `key_metrics_fields`,
  so missing items (net income, CFO, interest, LONG_TERM_GROWTH) are fixed from the real labels, not guessed.
- Ground rule added: research before building (docs/GROUND_RULES.md).

### 2026-11-06 — Browser login replaces the gateway for fundamentals (`--browser`)
- Real run after the correction below: every gateway route 404s or 302s, so the gateway cannot carry fundamentals.
- New `vmi/data/ibportal/browser.py`: `browser_portal()` opens Edge/Chrome (Playwright, `pip install playwright`, no
  download needed), the owner logs in with the PAPER username, and `BrowserHttp` sends the GETs through that browser's
  cookies to https://ndcdyn.interactivebrokers.com (`/tws.proxy/fundamentals/...`). `Portal(http=…)` is the same
  client as before (same parse/cache code), `session()` is skipped because the login wait already proved the routes answer.
- CLI: `python -m vmi.data.ib_fundamentals check AAPL --no-tws --browser`, `sync … --browser`. Results land in the
  14-day cache, so a sync is needed about every two weeks, and the browser is closed afterwards.
- UNVERIFIED on a real login: whether the portal site serves `/tws.proxy/fundamentals/*` to this client, and the
  contract route (`/portal.proxy/v1/portal/trsrv/stocks`, `check` falls back to the AAPL conid if it fails).
- The gateway path stays as is but is known not to work for fundamentals; remove it if the browser path is confirmed.

### 2026-11-06 — Correction: the gateway REDIRECTS unknown paths, it does not proxy them
- Disassembly of GatewayHttpProxy (router setup): only `^/(v1|qa|ci|alpha|local)/(portal|am|api|tws)/…` is proxied
  (`generalHandler`, "api" is mapped to "portal"; "tws" has no registered service). The final `/*` route is
  `handleRedirect`: 302 to `proxyRemoteHost + path`, generated by the gateway itself (hence no Set-Cookie).
  So `/tws.proxy/...` and `/portal.proxy/...` can never be served through the gateway; the earlier belief
  (Log entry below, "forwards every unrecognised path") was wrong. The self-redirect retry cannot help.
- Only `/v1/api/*` and `/v1/portal/*` can carry data, forwarded to `proxyRemoteHost + portalBaseURL`. Both 404'd
  for the session/contract routes on a real run; fundamentals under `/v1/portal` is untested. `FUNDAMENTALS_BASES`
  is now (/tws.proxy, /v1/portal, /v1/api); `/v1/tws` removed.
- If `/v1/portal/fundamentals/...` also fails: the gateway cannot reach the Fundamentals Explorer; the remaining
  routes are a direct client with the portal login cookies (no gateway), or a small patched/own proxy.

### 2026-11-06 — `probe` command (raw gateway answers)
- `python -m vmi.data.ib_fundamentals probe [conid]` (vmi/data/ibportal/probe.py) prints status, key headers, Set-Cookie
  names and the body start for every candidate route, following redirects by hand. Added because the gateway log shows
  its own calls to ndcdyn failing ("Access Denied" on get user, "ssodh failed"), so our 302s need the raw reply to explain.
- `ssodh` = the gateway's Diffie-Hellman handshake that opens a brokerage session after login. It fails for the tws
  profile. We never need it (read-only), but it shows ndcdyn rejects the gateway's own follow-up requests.

### 2026-11-06 — Self-redirect retry, gateway /v1/portal and /v1/tws routes
- Real run: `/portal.proxy/...` and `/tws.proxy/...` answered 302 → the SAME path on ndcdyn.interactivebrokers.com.
  I read this as IBKR setting a cookie and expecting a retry. The gateway passes such redirects through
  (HttpProxy only strips its own host from Location), so `_send` now retries a same-path redirect twice with
  the cookie jar. Error messages also say whether the 302 carried a Set-Cookie.
- The disassembled GatewayHttpProxy routes `^/(v1|qa|ci|alpha|local)/(portal|am|api|tws)/(.*)` to its own services. With
  conf.tws.yaml, `portalBaseURL: "/portal.proxy"`, so `/v1/portal` is now tried for the session and contract
  routes, and `/v1/tws` for the fundamentals routes.
- If this still fails, the next step is to drop the portal path: SEC/stockanalysis/Yahoo already cover the
  statements. The only unique IB field was LONG_TERM_GROWTH.

### 2026-11-06 — Gateway on conf.tws.yaml: Web API routes moved to /portal.proxy
- Real run with the launcher: login succeeded ("authenticated to cp"), but `/v1/api/sso/validate` returned 404.
  The tws profile forwards to the portal website, which doesn't serve `/v1/api`. The gateway's own brokerage init
  also logged "Access Denied / ssodh failed". That's harmless here because we never use brokerage routes.
- `client._routed(group, bases, …)` is now one fallback mechanism for both route groups. It remembers the
  working base per (gateway, group). `routes.API_BASES = ("/v1/api", "/portal.proxy/v1/portal")`.
  `/portal.proxy/v1/portal` is the prefix the portal web app uses for Web API routes. It is unverified on a real
  run, so check `check` output.
- `check()` now continues after a non-401 session error. It uses cached conids and falls back to `KNOWN_CONIDS`
  (AAPL), so the fundamentals routes get probed even when contract lookup fails.
- Fixed the SyntaxWarning (`\c` in the routes.py docstring): it is now a raw string.
- Test: `test_web_api_routes_fall_back_to_portal_proxy_on_the_tws_profile`.

### 2026-11-06 — Gateway launcher script (PowerShell quoting)
- On the owner's PC, typing the java line in PowerShell failed with "Could not find or load main class
  .disableDnsResolver=true": PowerShell splits unquoted `-Dname=value` arguments at the dot.
- Added `tools/start_cp_gateway.cmd [clientportal.gw folder]`. It quotes the `-D` args and runs `--conf conf.tws.yaml`,
  and it works from cmd and PowerShell. README and `routes.GATEWAY_CONFIG_HINT` now point to it.
- Open: confirm on a real run that `/tws.proxy/fundamentals/...` returns data with this profile.

### 2026-11-06 — Why conf.tws.yaml had no effect (and how to start the gateway)
Real run: a 302 redirect to `api.ibkr.com` showed the gateway was still on `conf.yaml` even after
`bin\run.bat root\conf.tws.yaml`. Cause (read from IBKR's scripts): `run.bat` only uses its argument to derive the
folder and never passes the file to Java, whose `--conf` option defaults to `conf.yaml`. Fix for the owner: start Java
directly with `--conf conf.tws.yaml` (command in README and in the error hint). Not yet verified: that the portal
profile then authenticates and serves `/tws.proxy/fundamentals/...`.

### 2026-11-06 — First real IB gateway run: route fix
Owner's run: login and ticker lookup worked (`session ok`, AAPL conid 265598). Every fundamentals request failed:
`/v1/tws/...` gave "Unknown service tws", and `/v1/api/tws.proxy/...` gave 404.
- Cause (from the gateway's own code, build a27ed42): `TwsService` is never registered, so `/v1/tws` can never work.
  The gateway forwards any unrecognised path unchanged, with the login cookies, to `proxyRemoteHost`. The default
  `conf.yaml` points at IB's public Web API (no fundamentals); `conf.tws.yaml` points at the portal website host,
  which serves `/tws.proxy/fundamentals/...`.
- Fix: fundamentals bases are now `/tws.proxy` then `/v1/api`. When every route fails, the error tells the user to
  restart the gateway with `root/conf.tws.yaml`. Non-JSON 200 answers fall back instead of crashing.
- Unverified until the next run: whether login and conid lookup also work under `conf.tws.yaml`.

### 2026-11-06 — IB connections need no configuration
Owner: having to set `VMI_IB_CP_URL` by hand makes no sense, so the app now finds both IB programs itself.
- Client Portal Gateway: `ib_cp_url` defaults to `https://localhost:5000`. If it isn't running or logged in the app
  skips it and rechecks every minute (breaker 60 s, was 30 min). `VMI_IB_CP_URL=` (empty) disables it.
- TWS / IB Gateway: `ib_port` defaults to 0 = try 7496, 7497, 4001, 4002 in turn (`vmi/data/ib.py`
  `candidate_ports`); a configured port is used alone. The port in use is shown in `/api/health`.
- Verified: 90 tests; with no gateway running the check fails fast with a clear message.

### 2026-11-05 — Correction: approved moat items restored (I had removed too much)
The owner clarified that things they explicitly said to leave, or that I proposed and they approved, stay. My criteria
audit wrongly removed three approved moat-proposal items. Restored as evidence (they never change a verdict):
- *Pricing-power test:* margin in 2021–23 vs the three years before (operating margin when gross margin is missing).
  The 2021–23 window is approved; the 2018–20 baseline and 2-point tolerance are labelled interpretation.
- *Review age:* a stored verdict older than 365 days, or with no date, is "review due".
- *Decline alert:* gross/operating/net margin or ROIC falling 2 years in a row (no minimum size). The 1-point minimum
  stays removed.

Also restored the earlier values I had changed unasked: narrow-moat size 0.75 and the 60-position cap (flagged for
the owner to confirm). New provenance kind `approved` in `vmi/rules_sources.py`. 89 tests pass.

**Observation:** with the 2-year rule, 17 of 43 reference stocks show "review due", including V for a 0.1-point
gross-margin dip. That is what the approved rule does; options are 3 years or a minimum size (both are Settings).

### 2026-11-05 — Criteria audit against Adam's text; invented thresholds removed
**Owner instruction:** reread what Adam says and fix the criteria; do not invent.

**What I did:** compared every rule in `vmi/rules.py` with the master document and recorded the basis in
`vmi/rules_sources.py`. Each setting is exactly one of: *Adam states it* (60 of them, with line numbers), *interpretation*
of his words (16: he gives a rule but no number), *owner*, *calibration* (owner-approved fits) or *software*. A test
fails when a rule has no entry, the Settings screen shows the badge beside each setting, and
`docs/CRITERIA_AUDIT.md` is generated from the registry.

**Removed because Adam does not say it (I had invented these):**
- the pricing-power stress window (2018–20 vs 2021–23) and its 2-point tolerance
- the 1-point minimum margin move, the 365-day review age
- margin cut-offs (40% gross, 20% operating, 10% net/FCF), the 3-point stability limit
- the "≥80% supportive signals = wide moat" hint
- "≥4 sources = wide" and "score ≥8 = wide"
- narrow-moat position multiplier 0.75 (now 1.0: he says "smaller positions" with no figure)
- the 60-position cap (now his 30)

**Fixed to his words:**
- *Step 3.* Pass/fail only from what he states:
  - never a no-moat industry
  - no 10-year downtrend
  - the reviewer's verdict: grade wide/narrow, ≥3 of 5 sources, score ≥7/10
  
  Wide vs narrow comes from the reviewer's pricing-power judgement, never inferred. Margins, recurring revenue and
  reinvestment are shown as information, with no thresholds. Unreviewed = provisional result from his two
  shortcuts only.
- *Moat deterioration signal.* His signal is profit margins declining for "at least 2–3 years". It flags gross,
  operating and net margins falling 3 years in a row, with no size filter (he gives none). 3 is an interpretation,
  because Step 1 accepts 1–2 down years. It's editable (Settings → moat). Free-cash-flow margin is not a profit
  margin, so it doesn't trigger it. 5 of 43 reference stocks flag.
- *Turnaround (Category 7).* His one requirement is "the moat must remain intact". Step 1's profit checks are now waived
  whenever a reviewer confirms the moat, with nothing added. My earlier "sales still rising" condition is gone.
- Moat reviews recorded with a score below 7 (BABA 6, NKE 6) now fail Step 3, as Adam says 6/10 is "not strong enough".

**Not touched, flagged for the owner:** the owner-directed growth blends and haircuts (`calibration`) stay as approved;
interpretation numbers (e.g. margin tolerance 15% for "close to the 5-year average", capex spike 1.5×) are now labelled
so they can be changed.

**Fixed on the way:** a circular import in the settings loader (importing `vmi.settings` before `vmi.rules` crashed).

**Verified:** 89 offline tests; 0 unspecified settings; moat flags and verdicts re-run on Adam's 43 stocks.

### 2026-11-05 — Moat evidence expanded (no AI scorer, by decision)
**Why:** the owner approved every proposed helper except the AI moat scorer, which isn't trustworthy enough.

**Added to Step 3** (evidence only; the verdict stays with the reviewer):
- `pricing_power_through_inflation`: margin before (2018–20) vs during (2021–23) the cost-inflation window. It uses
  gross margin and falls back to operating margin when gross profit is missing or too short (e.g. Visa).
  Thresholds are in `MoatRules` / Settings.
- `recurring_revenue` (deferred revenue and contracted backlog vs sales) and `reinvestment_intensity` (R&D,
  SG&A, capex vs sales). New SEC concepts: `rd`, `sga`, `deferred_revenue`, `rpo`.
- Review dates and staleness: saving a moat verdict stamps `moat_reviewed_on`. "Review due" is flagged when the
  verdict is older than 365 days, has no date, or a margin fell 2 years in a row by ≥1 point.
- Peer comparison (`vmi/analysis/moat_peers.py`): S&P 500 sub-industry, or your own list in the `peers`
  override. Size, share, margins, 3-year growth, ranks and a "looks like the leader" hint, from SEC frames.
- Annual-report excerpts (`vmi/data/filings.py`): the 10-K competition passage and customer-concentration
  sentences, verbatim with the filing date. Both network pieces load on demand (button in Step 3) via
  `GET /api/analysis/{symbol}/moat-evidence`, so analysis stays fast.

**Oversight findings:**
- Visa's gross-profit history starts in 2022 → operating-margin fallback.
- A 0.1-point margin wobble was flagged as "falling" → added the 1-point minimum.
- The 42 earlier AI reviews had no dates → backfilled to 2026-11-05.
- A review question still mentioned an AI scorer → reworded.
- Flags that look right: UNH operating margin 8.7% → 4.2%; MSFT gross margin down (AI depreciation); LVMUY, MELI,
  POOL margins down.

**Verified:** 90 offline tests; live SEC data (V peer table, NVDA 10-K excerpts); browser run with no errors.

**Open:** IB ratings (#8) once the gateway works. Many peers lack gross margin in SEC frames (shown as "—").

### 2026-11-05 — More control, an oversight run (AI reviewer), rules fixes found by reviewing
**More per-stock control** (UI card / API / CLI; registry `vmi/overrides.py`):
- `growth_source`: use exactly one source.
- `extra_sources`: your own estimates, e.g. `factset=0.15`, which join the blend.
- `growth_blend`: lowest / second_lowest / median / average / highest (also global in Settings).
- `base_period`: auto / ttm / last_fy / average.
- Code: `GrowthControls` in `vmi/analysis/valuation/growth.py` replaces separate parameters, and
  `steady_base(mode=…)` in `methods.py`.

**Oversight run.** I reviewed every verdict for Adam's 43 stocks, not only the IVs, and acted on what I found.
Each item is either a rule mismatch with the doc (fixed in code) or a per-stock judgement (recorded with a reason):
1. *Step 5 vs Adam's table.* "Passing 2 out of 3 is acceptable" and the ratios don't apply to insurance or
   financial companies. Code required all three: fixed (`DebtRules.min_core_ratios_passed`, insurer/asset-manager
   exemption).
2. *No-moat industry matching used substrings.* "Fire, Marine & Casualty Insurance" and "Security & Commodity
   Exchanges" were flagged, and "gold" would hit Goldman. Fixed: whole-word phrases with plurals.
3. *Turnaround category.* Adam's Category 7 says profits fall temporarily while the moat stays intact. Now Step 1
   passes when the reviewed moat is intact and sales still rise (`_turnaround_exception` in `pipeline.py`); the
   category's ½ size applies. UNH became a buy at ½ size; NKE, POOL and LVMUY still fail (sales falling).
4. *SEC restatements.* GE's history mixed bases (pre/post HealthCare and Vernova spin-offs).
   `sec.restated_years()` now flags years restated by more than 15% within the 10-year window (warning on Step 1,
   `data.warnings`). GE got the judgement step1=pass with the reason.
5. *Moat reviews.* AI verdicts (grade, sources, score, reason) for 42 reference stocks, saved in
   `config/judgements.json` and marked "please verify". MBGL was skipped (company not identified).
6. *Scanner.* Moat reviews alone no longer pin a ticker past the pre-filters (`overrides.pins_in_scanner`).

**Data gaps found (not judgements):** CNSWF has only 4 years of data (no SEC filing; Yahoo only), so Step 1
can't pass yet. ADR names need re-checking on the owner's PC (Yahoo is blocked in the sandbox).

**Moat-evaluation proposals:** the next entry or `docs/MOAT_PROPOSALS.md`.

### 2026-11-05 — Structural calibration, discretionary moat, Settings screen (everything editable in the UI)
**Asked:**
- conservative growth (lowest source) with per-stock overrides
- understand and fix the valuation gaps vs Adam, looking at every company feature, with structural reasons only
- the moat must be the reviewer's call
- every nuance must be editable from the UI, not in code or GitHub

**Done:**
- *Growth.* Rules in `vmi/rules.py` `GrowthRules` (`blend`, `blend_defensive`, `disagreement_ratio`,
  `blend_when_disagree`), logic in `vmi/analysis/valuation/growth.py`:
  - growth stocks: lowest source
  - defensives: median source
  - sources disagree ≥1.5×: median
- *Haircuts.* Base 0; `uncertainty_haircut` = 7.5% for growth stocks and single-source estimates
  (`ValuationContext.haircut`). Evidence: `docs/CALIBRATION.md` (2026-11-05, later).
- *Step-1-fail reference.* The middle of P/S, DCF and DNI (`selector.REFERENCE_ONLY`).
- *Moat (Step 3).* Evidence only:
  - industry, 10-year chart and return
  - gross/operating/net/FCF margins with history, gross-margin stability
  - ROIC/ROE persistence, consistency, scale
  - Adam's five sources and the review questions

  The verdict comes from the overrides `moat_grade` / `moat_sources` / `moat_score`. An unreviewed moat shows a
  labelled data hint, and VMI buy requires a reviewed moat (`moat_reviewed` in the report).
- *Settings screen* (`static/js/views/settings.js`, `vmi/settings.py`, `/api/settings`):
  - every rule, with help taken from the code comments
  - saved to `config/rules_settings.json` (differences only) and applied immediately in place
  - lists every per-stock override with edit and clear
- *Overrides.* The registry (`vmi/overrides.py`) now has the moat review keys; the earlier entry covers the rest.
- *Tools.* `tools/segment_analysis.py` (segments by every feature), `tools/haircut_sweep.py` (sweeps any
  setting through the full model).
- *Judgements* (`config/judgements.json`): removed NVDA, MELI and AMZN (the rule covers them); VEEV → lowest;
  added UNH method dcf_fcf.

**Verified:**
- 79 offline tests.
- Calibration with judgements: median 0.851, 15 within ±15%, 10 in band, 11 >1.05, 7 <0.75.
- UI screenshots of Settings and the NVDA analysis (overrides card and moat review).

**Open:**
- The remaining outliers listed in `docs/CALIBRATION.md`.
- The sandbox lacks Yahoo (market cap, a third growth source), so ADR names and blends should be re-checked on
  the owner's PC.

### 2026-11-05 — Growth = lowest analyst source by default; full judgement-override layer
**Why:** owner directive: be conservative by default (lowest source, not the average), and make every input
easy for a human or an AI to override per stock (interventionist strategy).

**Growth blend:**
- `rules.growth.blend = "lowest"` is the default. The other choices are "average" (Adam's literal rule) and "median".
- It can be changed per ticker with `growth_blend`. Code: `vmi/analysis/valuation/growth.py` (`BLENDS`, `choose_growth`).
- The Step 2 and category growth still use the averaged consensus (`est.eps_growth_5y`). Only the valuation input changed.

**Override registry:**
- `vmi/overrides.py` declares every key once. Validation, `GET /api/overrides/schema`, the UI card and the CLI are
  all generated from it.
- Keys: growth, growth_blend, exclude_sources, growth_6_10, growth_11_20, method, base_cf, discount_rate, beta,
  shares, cash, debt, iv_haircut, iv_override, conservative_override, biz_type, category, moat, step1–step7
  (force pass/fail), buy_levels, allocation_multiplier, scan (pin/exclude).
- Storage: the database (UI/API/CLI) or the committed `config/judgements.json` (`--commit`). Edits merge, and a
  null value removes that key.
- Reports list what was overridden (`overrides_applied`).
- To add a key: one `Field(...)` line in `vmi/overrides.py`, plus the line that applies it (`vmi/analysis/pipeline.py`
  or `ValuationContext` in `vmi/analysis/valuation/methods.py`).

**CLI:**
```bash
python3 -m vmi.overrides set NKE growth_blend=average step1=pass --note "temporary dip" --commit
```

**Files:**
- New: `vmi/overrides.py`, `tests/test_overrides.py`.
- Changed: `vmi/store.py` (merge, clear, `set_judgement`), `vmi/api/app.py`, `vmi/analysis/pipeline.py`,
  `vmi/analysis/valuation/{methods,growth}.py`, `vmi/scanner/funnel.py` (pin/exclude), `static/js/{api.js,views/analysis.js}`,
  `static/css/app.css`, `vmi/rules.py`, `config/judgements.json` (`_doc`).

**Verified:** 73 offline tests.

### 2026-11-05 — UI fix: "Personality" showed `[object Object]`
- `static/js/views/analysis.js`: technicals personality is a map of moving average → bounce count; the card now
  shows the one the stock respects most (e.g. "daily sma50 (14 bounces)"). Found by screenshotting the running app
  (Playwright, sandbox, SEC data, IB disabled). Screenshots are written to `data/ui_preview/` (git-ignored).

### 2026-11-05 — IB fundamentals through the Client Portal Gateway (read-only), replacing the guessed version

**Problem.** The owner wants fundamentals from IBKR. `reqFundamentalData` no longer works in TWS, the earlier
attempt (`vmi/data/ib_portal.py`, same day) used guessed routes, and the owner can't run two sessions on one
username.

**Research (evidence, all checked 2026-11-05):**
1. *TWS API.* The TWS API 10.47 release notes list `reqFundamentalData`, its callbacks and tick type 47 as
   removed ("De-Supported Fundamentals Data Request"):
   https://www.ibkrguides.com/releasenotes/prod-2026.htm. Current builds are Stable 10.50.1f (2026-10-05) and
   Latest 10.51.1e (2026-10-26), per IB's `download2.interactivebrokers.com/installers/{tws,ibgateway}/{stable,latest}-standalone/version.json`.
2. *Where the refusal happens.* The ibx project's gateway investigation found that 10.51 refuses fundamentals
   **locally** with error 10358 unless the login's feature list contains `ALLOW_FNDT_SOMEAPI` ("Nothing is sent
   to the farm"). An older 10.40 still forwarded the request and received ratios on a paper account on
   2026-10-07: https://github.com/deepentropy/ibx/issues/639, /674, /634. So the old README line "IB servers
   refuse older clients" was wrong: the gate is per login and sits in new builds. Running an outdated build to
   get around an entitlement check is fragile and against IB's intent, so it is **not** used.
3. *IB still serves fundamentals.* The Fundamentals Explorer "provides comprehensive, worldwide fundamentals
   data to all IBKR clients, at no cost" (LSEG data): https://www.interactivebrokers.com/en/trading/fundamentals-explorer.php
4. *Exact routes and response shapes.* These were read from IB's own portal JavaScript (public files under
   https://ndcdyn.interactivebrokers.com/portal/: `index.js`, `part.5012.js` financials, `part.2663.js` key
   metrics, `part.9665.js` key ratios, `part.7109.js` data_list). The portal calls `/tws.proxy/fundamentals/…`.
   They are recorded with their shapes in `vmi/data/ibportal/routes.py`. IB's field dictionary includes
   `LONG_TERM_GROWTH` ("Long Term Growth"), the analyst consensus input Adam's DCF needs.
5. *How the gateway reaches them.* IB's Client Portal Gateway (`clientportal.gw.zip`, disassembled with
   `javap`) routes `^/(v1|…)/(portal|am|api|tws)/(.*)`. Its `TwsService` rewrites `/v1/tws/<route>` to
   `/tws.proxy/<route>` (`twsBaseURL`). So the local URL is `https://localhost:5000/v1/tws/fundamentals/…`.
   The `PossibleIBFundamentalFix` note's claims (that TWS has a local REST server, and the `/mofw/` route) are
   wrong.
6. *Sessions.* One brokerage session per username across TWS, Client Portal and Mobile, and a second username
   is the documented fix: https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions.md.
   The gateway itself opens a brokerage session after login (`ClientPortalService`: `iserver/auth/ssodh/init`,
   "iserver init"). Therefore **the gateway must use a different username than TWS.** Paper usernames are
   valid gateway logins: https://interactivebrokers.com/docs/web-api/authentication/paper.md.
7. *Paper/live market data.* IB's FAQ "Market data considerations for the paper trading account"
   (https://www.interactivebrokers.com/lib/cstools/faq/content/1136176599, rendered with Playwright) says:
   - With sharing on, a paper session gets live data alongside the live session only when both run on the
     same device. Otherwise the paper session shows "No Data".
   - The live session always keeps real-time data.

   This is an exchange-licensing rule about market data. Fundamentals are not exchange market data.
   https://www.interactivebrokers.com/docs/tws-api/doc/connectivity/logging-into-multiple-applications.md adds
   that a username used in Client Portal while TWS runs stops TWS auto-reconnecting after the next reset.

**Decision (recommended setup on the owner's PC):**
- TWS (or IB Gateway) on the **live** login, `VMI_IB_PORT=7496` (IB Gateway: 4001), with TWS → Global
  Configuration → API → Settings → **Read-Only API** ticked. The app only reads market data and connects with
  `readonly=True`; its paper trading is simulated locally.
- IBKR **Client Portal Gateway** on the **paper** login, `VMI_IB_CP_URL=https://localhost:5000`. That's a
  different username, so it doesn't compete with TWS, and it only reads fundamentals.
- Fallback if the paper login cannot read fundamentals: one login at a time. Log the gateway in (with any
  login) while TWS is closed, run `sync`, and the cache serves the app for 14 days (`ttl_ib_portal`).

**What was built:**
- `vmi/data/ibportal/` package:
  - `routes.py`: all URLs and fields.
  - `client.py`: HTTP. Refuses any `/iserver` path, rate-limited (`ib_cp_max_rps`), and remembers which
    fundamentals base answers.
  - `parse.py`: pure functions. Exact table schema, with a generic fallback. Estimate columns ("2025E") never
    become history. `harmonize()` snaps units to SEC by a power of 1000 and fills fiscal-year ends.
  - `service.py`: cache-first `fundamentals()` and `estimates()`, bulk `sync()` (analyst fields 50 conids
    per call), and `check()` diagnostics.
- `vmi/data/breaker.py`: shared circuit breaker, replacing ad-hoc dicts.
- `vmi/data/ib_fundamentals.py`: coordinator (TWS XML, then gateway) and the CLI. A per-security 430 no longer
  pauses the TWS path; only 10358/"not allowed"/timeouts do.
- `vmi/data/fundamentals.py`: `MERGED_KEY` and `invalidate()`, which sync calls so merged data picks up IB.
- `vmi/config.py`: `ib_cp_max_rps`, `ttl_ib_portal`; `ib_cp_url` is now the gateway root.
- Tests: `tests/test_ibportal.py`, with a mock gateway. It proves no `/iserver` call is ever made.
  `tests/conftest.py` gives every test an isolated cache. Removed: `vmi/data/ib_portal.py`,
  `tests/test_ib_portal.py`.

**How to use (owner's PC):**
```bash
python3 -m vmi.data.ib_fundamentals check AAPL MSFT    # TWS probe + every gateway route; raw JSON → data/ib_portal_samples/
python3 -m vmi.data.ib_fundamentals sync --sp500       # fill the IB cache (add --no-statements for analyst growth only)
```

**Verified:** offline tests (66 pass). Probing IB's endpoints from the cloud sandbox was blocked, correctly,
so nothing here has seen a real IB response yet.

**Unverified, to be settled by the first `check` run:**
- `/v1/tws/fundamentals/*` answers through the gateway. The code falls back to `/v1/api/tws.proxy`.
- The paper login can read fundamentals.
- Exact `metric_name` strings and number formats. If `parsed_annual` is sparse, extend `LABELS` from the
  saved JSON.
- The `LONG_TERM_GROWTH` units.

### 2026-11-05 — Managed care (SIC 6324) classified as normal companies
- `vmi/analysis/classify.py`: SIC 6324 and text "healthcare plans"/"managed care" map to `normal` (DCF), not
  `insurance`. The master doc files managed care under Healthcare. Test in `tests/test_valuation_rules.py`.
- Effect: UNH is now DCF IV 638 vs Adam 438 (ratio 1.46; it was 1.35 on P/B). The gap is the growth input
  (13–18% rebound consensus vs ~6% implied by Adam). This is a judgement case; details in `docs/CALIBRATION.md`.
  BKNG was re-checked the same way: the data matches filings and the gap is Adam's growth.

### 2026-11-05 — FDIC CET1 holding-company matching
- `vmi/data/fdic.py`:
  - Canonical tokens on both sides (FINL/SVC/BCORP/NY abbreviations, split initials "U S" → "US").
  - Exact holding matches rank above bank-name matches.
  - Single-token keys must match exactly.
  - Fallback to the bank's own name for banks without a holding company (Zions).
- Verified live against api.fdic.gov with the final code: 25 large bank holding companies resolve to their
  main bank (JPM, USB, MTB, BK, FCNCA, ZION, WFC, PNC, EWBC, C, BAC, GS, MS, SCHW, WAL, CFR, KEY, TFC, FITB,
  HBAN, CFG, RF, COF, STT, NTRS). A name search finds no active FDIC bank for Comerica or Webster, so they
  return none rather than a wrong bank. Test in `tests/test_parsing.py`.

### 2026-11-05 — First Client Portal provider (superseded the same day)
- `vmi/data/ib_portal.py` implemented the `PossibleIBFundamentalFix` idea with guessed routes and a
  schema-agnostic parser. It was replaced by the `vmi/data/ibportal/` entry above once the real routes were
  found in IB's code.

### Before 2026-11-05
See `git log`, `docs/CALIBRATION.md` (valuation calibration history) and `docs/GROUND_RULES.md`.
