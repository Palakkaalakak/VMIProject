# Full test plan — VMI Toolkit at http://localhost:8000 (owner's PC, real data)

For a Claude session testing the running app in the built-in browser. The owner started the app; do not start, stop or
restart it unless a step says so. Work top to bottom, record every result, fix nothing silently.

## Ground rules
- **Paper only. IB is read-only:** never place orders, never call `/iserver` trading routes, never submit a paper trade unless a step
  asks for one (then use a throwaway paper portfolio named `TEST`, and delete it at the end).
- **Leave the owner's state as you found it:** note every Setting you change and change it back; do not clear judgement overrides,
  watchlists or portfolios; save any moat verdict ONLY on a ticker whose current verdict you wrote down first, then restore it.
- **Evidence for every result:** a screenshot or the exact text shown. A result without evidence is "UNVERIFIED".
- **Bug report format** (one per issue, numbered): page · steps · expected · actual · screenshot · console errors (open DevTools
  console and keep it open the whole time; any red error is a bug, even if the page looks fine) · severity (blocker / wrong number /
  cosmetic).
- Before starting: write down `git log -1 --format="%h %s"` from the app folder (or the version in `/api/health`). Expected: commit
  `2d8099d` or later ("Update VMI.bat: stash local changes…"). If older, stop and tell the owner to update first.

## 0. Health and data sources (5 min)
1. Open `http://localhost:8000/api/health`. Record `version` and `ib.connected`.
2. Header badge on any page: "IB live" or "IB offline (Yahoo fallback)". It must match `ib.connected`.
3. Settings → "IB fundamentals" card: record last sync date and fresh/stale.
4. Settings → "AI helper" card: record the status text exactly.

## 1. Readable names with (?) help
1. Settings → open every rule group. Each row shows a readable title (e.g. "REIT maximum price / NAV"), a (?) that shows help on
   hover, a source badge (Adam / interpretation / owner / software…), and the technical key in small grey text.
   Bug if: any title contains `_`, any (?) is empty, a group header shows a raw name like `valuation`.
2. Find "Discount rate method" (`valuation.discount_mode`) = **fixed** and "Fixed discount rate" = **0.1**.
3. Scanner → filter picker set to "Every filter and rule" → type `reit`. Options must read as titles ("REIT maximum price / NAV · Valuation"),
   and picking one adds a row titled the same with a (?) tooltip.

## 2. Analysis page (use MSFT, then RDDT, then a bank e.g. JPM)
1. `#/analysis/MSFT`. Record: price, IV, margin of safety, conservative value, 5 verdict badges, the valuation line "rate 10.0%".
   Expected: the discount rate shown is 10.0% for every stock (fixed mode).
2. Header text ends with "ROE, ROIC and margins judged on the **latest fiscal year**" (normalise off).
3. Tick **normalised (this stock)** → page reloads; header says "normalise: ON (3y)" and "judged on the **3-year average**"; Steps 1, 4,
   5 carry "(NORMALISED)". Untick → back to latest fiscal year. Reload the page: the tick state is remembered for that ticker only
   (open AAPL: it must be unticked).
4. Tick **10-year record only** → header shows "10-YEAR ONLY"; Step 1 checks now need 10 years (a young company like RDDT must fail
   Step 1 with "only N years of data (<10)").
5. Confirm Settings were NOT changed by these ticks (Settings → Normalise is still off, Minimum years still 5).
6. Technicals card → open **Chart** (see section 5 for the chart checks).

## 3. Scanner
### 3a. Presets, size and runner-ups
1. Choose each preset in turn; the note under it must end with "Size: market cap ≥ $X B, price ≥ $Y (applies to every universe)".
   Record X for each. Expected ≥ $10B for every "Adam:" preset except speculative ($1B) and Finviz ($2B).
2. Run **Adam: ULTRA excellent**, universe **Custom list**: `MSFT, AAPL, COST, FAST, V, AZO, ODFL, WST, LLY, RDDT, NVDA, GOOGL`,
   tick **Show runner-ups**. Record the stage funnel (in / out / seconds per stage) and the total time.
   Expected: completes; probably 0 full passes (ultra is extremely strict); runner-ups listed with a "runner-up" badge and "missed …" text;
   "Why dropped?" lists a reason for every dropped ticker (WST: net margin fell N years; ODFL: down years…).
3. Untick "show runner-ups" in the results bar → runner-ups disappear; count text updates.
4. Run the same scan again immediately (cache on). Expected: much faster deep stage; status line shows "(N from cache)".
   Then tick "Ignore cached analyses" and run: slower again.
5. **Size floor for lists:** Custom list with a small cap (e.g. `SMCI`? check its cap first, or any < $10B name) under an Adam preset:
   it must be dropped with "Size: market cap $… < $10B".
6. Run **Adam: great business (steps 1-5)** on **S&P 500**. Record total time and number of results. Note: no-moat industries
   (airlines, oil & gas, autos…) must be dropped early with "Industry: no moat (…)".

### 3b. Results consistency with the Analysis page (most important)
For 3 result rows (include one with a "loss yr" note under ROE if any):
- Compare scanner row vs `#/analysis/<ticker>` for: price, IV, MOS, growth, ROE, ROIC, net margin, steps passed.
  Expected: identical numbers. ROE/ROIC/net margin carry "(FY)" or "(avg)" in the row; the analysis header names the same basis.
  If the scan ran with normalise on, the row shows "latest FY x%" under ROE/ROIC.
  Allowed differences ONLY: price-dependent values when the row is from cache (up to 8 h old) — note the age.
  Any other mismatch = bug "wrong number".

### 3c. Filters
1. Filters panel → **Conditions** (top) → + Add condition → ROE % **between** 15 and 30 → row count changes and every shown row has
   ROE in [15%, 30%]. Test each operator once: above, at least, below, at most, equals (e.g. Steps passed equals 5), between with the
   numbers reversed (30 and 15 must behave the same).
2. Picker → "Condition on any column (above, below, between, equals…)" opens the panel with a new condition row.
3. Reload the page: filters and conditions are restored. Reset clears them.

### 3d. Saved scans
1. "Save this scan…" → name it `TEST scan` → it appears in the saved list with result and runner-up counts.
2. Run a different scan, then select `TEST scan` → Open → the old rows come back and the count says "scan #N" of the saved run.
3. Remove it with ✕ (only removes it from the list).

## 4. Moat page (`#/moat/MSFT`, then a weak business e.g. `#/moat/DAL` or `#/moat/F`)
1. **At first sight** card: a leaning badge (wide-looking / narrow-looking / weak / unclear), one paragraph, and a signal table where
   each row says `adam` or `inferred`. Expected: MSFT not "weak"; DAL/F "weak" (no-moat industry or low margins).
2. **Your verdict** form: sources show "1a. Brand" and "1b. Pricing power (instead of brand)" plus 2–5, and the note that ticking both
   counts once. Record MSFT's current verdict, grade, score and sources BEFORE touching anything.
3. **Guided evaluation** button → 7 questions in order (brand or pricing power, switching costs, network effect, barriers, scale,
   competitors, how long it lasts). Each shows Adam's text, search links (open one: it must search for the company), and for 1, 6, 7
   "What the app already knows". Back/Next keep your answers. Final screen: sources count, suggested verdict, score, comment.
   Save it on MSFT, check the Step 3 line updates, then **restore** the original verdict via the normal form.
4. Pricing-power rule: in the verdict form tick brand + pricing power + scale only (2 slots) with grade wide, score 8 → Step 3 must NOT
   pass (needs 3 sources). Then restore.
5. **AI second opinion** card: visible only if the Settings AI card says ready (or Ollama is running). If visible, press it once and
   record time taken and the answer (label "minor help"). If not visible, record "hidden, AI not installed" (correct behaviour).

## 5. Chart (moat page under "Your verdict", and Analysis → Technicals → Chart)
1. Loads with source label ("IB (live)" for Daily when IB is connected, else "Yahoo") and bar count.
2. Defaults on Daily: SMA 50 blue, 100 orange, 150 green, 200 red ticked; EMA 20/40 unticked; **Bollinger (SMA 20, 2σ) ticked**;
   **Stochastic (5,3,3) ticked**; Volume ticked; the note "Adam: … 20 and 40 EMAs are meant for weekly and monthly charts only (they
   are allowed here on every timeframe)".
3. Hover candles: the readout shows O/H/L/C, % change and volume for the hovered bar; the stochastic readout shows %K, %D and
   overbought (≥80) / oversold (≤20) / neutral. Cross-check one bar's O/H/L/C against another source (e.g. Yahoo Finance page).
4. Stochastic pane: two lines (%K blue, %D orange), dashed 80 and 20 lines, scrolls/zooms in step with the price chart.
5. Timeframes 5m, 15m, 1h, Daily, Weekly, Monthly each load. Weekly/Monthly: EMA 20/40 tick themselves on. Tick EMA 20 on Daily: it draws.
6. Ranges 3M/6M/1Y/5Y/All change the visible window.
7. Drawing: Horizontal line (one click) and Trend line (two clicks) draw; reload the page → drawings for that ticker+timeframe come back;
   Clear drawings removes them.

## 6. Settings — AI helper (only if the owner agrees to a ~10 GB download)
1. Press "Download the built-in AI". Record progress text over time and any error verbatim (GitHub or Hugging Face blocked, disk full…).
2. When "ready": open a moat page → Ask the local AI → record time to answer, whether the GPU was used (Task Manager → GPU), the answer.
3. Wait 10+ minutes idle: the `llama-server` process should exit by itself.
If the owner declines the download: record "not tested".

## 7. Regression sweep (quick, every page)
Visit Analysis, Superscanner, Watchlists, Paper portfolios, Options, Plans, Ledger, Review, Option book, Alerts, Settings.
For each: page renders, no red console errors, no "undefined"/"NaN"/"[object Object]" text, buttons that only read data work.
Watchlists: review queue and stats load. Ledger/Review: open an existing portfolio read-only.

## 8. Report back
One message to the owner:
1. Version tested, IB live or not.
2. Pass / fail table per section (0–7).
3. Numbered bug list (format above), blockers first.
4. Timings: ultra list scan, repeat scan with cache, S&P 500 great-business scan.
5. Confirmation that every Setting, verdict and override changed during testing was restored (list them), and the `TEST` items deleted.
