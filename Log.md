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
