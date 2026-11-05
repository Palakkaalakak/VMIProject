# VMI Toolkit — Adam Khoo's Value Momentum Investing, all in one

A local investing workstation built from the VMI Master Document (`docs/VMI_MASTER_DOCUMENT.pdf`):
7-step stock analysis with auto-selected valuation methods, a full-US-market superscanner, watchlists with
intrinsic values, buy levels and alerts, multi-portfolio **paper trading** (stocks plus covered calls and
cash-secured puts), and an options chain.

> **Paper trading only.** No order is ever sent to IBKR. IB is used for market data only.

## Run it

```bash
bash tools/setup_env.sh        # idempotent: installs deps, starts autocommit watchdog + PM2 server
open http://localhost:8000     # web UI   ·   http://localhost:8000/docs  → interactive API docs
python3 -m pytest -q tests     # offline test suite (no network)
```

Run the server on the same machine as **TWS or IB Gateway** with the API enabled (default port 7497, client id
17). Cloud hosting such as Cloudflare can't open a TCP connection to TWS, which is why this is a local FastAPI
server rather than a Workers app. Without IB the app still works, falling back to Yahoo for quotes and options.

Settings come from environment variables or `.env` with the `VMI_` prefix (see `vmi/config.py`): `VMI_IB_HOST`,
`VMI_IB_PORT`, `VMI_IB_CLIENT_ID`, `VMI_IB_CP_URL`, `VMI_SEC_USER_AGENT`, `VMI_PORT`, …

## Features (status)

| Area | Status | Where |
|---|---|---|
| 7-step analysis (track record, growth, moat, profitability, debt, price, entry) | ✅ | `vmi/analysis/steps.py`, `pipeline.py` |
| Valuation auto-selection: DCF FCF / normalised capex / CFO, DNI, P/B (banks, distressed), P/NAV, P/S, PSG | ✅ | `vmi/analysis/valuation/` |
| Adam's cash-flow normalisation (TTM jump → prior FY, plunge → average) | ✅ | `methods.steady_base` |
| Split-adjusted per-share history · single reporting currency for 20-F filers | ✅ | `data/splits.py`, `data/sec.py` |
| Negative equity from buybacks (MCD, AZO, YUM…) — doc §3.5 / §5.1 | ✅ | `vmi/analysis/negative_equity.py` |
| Technicals: trend states, MAs, swing levels, 10-year uptrend, tranche buy levels | ✅ | `vmi/analysis/technicals.py` |
| Superscanner (cheap/broad filters first → deep 7-step; judged tickers pinned) | ✅ (list run verified; full-market run pending) | `vmi/scanner/funnel.py` |
| Paper trading: mid + flat slippage, illiquid debuff, tranches, multi-portfolio, CSP/CC, assignment | ✅ | `vmi/paper/` |
| Watchlists: import (Adam pipe / CSV / TradingView), auto-fill IV + levels, 60s alerts | ✅ | `vmi/watchlist/service.py` |
| Options chain (IB → Yahoo, rows never disappear), VMI CSP/CC suggestions | ✅ | `vmi/options/chain.py` |
| Web UI (analysis, scanner, watchlists, portfolios, options, alerts) | ✅ | `static/` |
| Human judgement overrides (TMO, ASML, AVGO, VEEV, ACGL, PLTR) | ✅ | `config/judgements.json` |

**Not done yet:** full-market scanner run benchmark; remaining calibration outliers (BKNG base FCF, NKE/LVMUY on P/S,
UNH classification); bank CET1 name matching for a few banks; companies with a short history.

## Data sources (fundamentals)

IB removed fundamentals: `reqFundamentalData` returns server-side error 10358 since about April 2026, and TWS API
10.47 deleted the call. **An older TWS/API version does not help**, because the block is on IB's servers. The app
still tries IB first behind a 6-hour circuit breaker (TWS XML, then the **Client Portal Gateway**), then falls back:

0. **IB Client Portal Gateway** (`vmi/data/ib_portal.py`): the Fundamentals Explorer backend
   (`/tws.proxy/fundamentals/financials/{conid}`, `/fundamentals/landing/{conid}`). TWS has no REST server, so run
   IBKR's separate gateway (`clientportal.gw` or IBeam), log in at https://localhost:5000, and set
   `VMI_IB_CP_URL=https://localhost:5000`. The routes are undocumented, so check them once with
   `python3 -m vmi.data.ib_portal AAPL`: it prints session/conid status and saves the raw JSON to
   `data/ib_portal_samples/`. Units and fiscal-year ends are checked against SEC. `/api/health` shows breaker state.

1. **SEC EDGAR XBRL**: official statements for every US filer. Companyfacts serve deep analysis; frames serve cheap cross-market scans.
2. **stockanalysis.com**: gap fill, ratio histories, newer fiscal years.
3. **Yahoo**: last resort for core items.
4. **FinViz / Zacks / Yahoo / stockanalysis**: consensus growth (plain average, Adam's rule).
5. **FDIC BankFind**: bank CET1.
6. **NASDAQ screener / Wikipedia / GitHub**: universe lists.

Coverage audit: `python3 -m vmi.data.coverage` writes `data/coverage_sp500.json`.

## Calibration vs Adam

`python3 -m vmi.analysis.calibrate [--judged]` compares our IVs with Adam's (`tests/fixtures/adam_reference.txt`).
Policy (from `docs/CALIBRATION.md`):

- Stay near Adam's numbers, and err conservative.
- Only flat, fixed adjustments are allowed (currently IV −10%); no fitted transforms.
- Distorted cases go in per-ticker judgements, never into the general formula.

`tools/growth_vs_adam.py` isolates growth-input error from model error.

## Architecture (how to change things)

```
vmi/
  rules.py            every VMI threshold as frozen dataclasses — change a rule HERE, nowhere else
  config.py           environment settings
  data/               providers → provider-agnostic models (models.py). Analysis never imports a provider.
    fundamentals.py   resolve(ticker): IB → SEC → stockanalysis → Yahoo merge + TTM reconciliation
    market.py, ib.py  quotes / history / options (IB first, Yahoo fallback); market_hours.py = session logic
  analysis/
    consistency.py    single definition of "consistently increasing" (Step 1 AND valuation use it)
    negative_equity.py, steps.py, technicals.py, classify.py, pipeline.py
    valuation/        core.py (DCF math) · growth.py · methods.py (REGISTRY of methods) · selector.py
  paper/              fills.py (fill model) · sizing.py · engine.py (portfolios, orders, expiry)
  options/ scanner/ watchlist/
  store.py            SQLite (SQLAlchemy); judgement overrides merged from config/judgements.json
  api/                FastAPI app; jsonsafe.py makes every response JSON-safe (numpy/NaN)
static/               no-build ES-module UI: api.js (only HTTP client) · ui.js (helpers, sortable table)
  js/views/*.js       one module per screen exporting render(root, params) [+ destroy()]
tests/                offline pytest (golden examples from the doc)
tools/                autocommit watchdog, save.sh, setup_env.sh, diagnostics, experiments
```

Recipes:

- **New valuation method:** write `fn(ctx) -> ValuationResult` in `methods.py`, add it to `REGISTRY`, then list it in `selector.candidate_methods`.
- **New data provider:** return a `Fundamentals` / `Estimates` from `vmi/data/<provider>.py`, then merge it in `fundamentals.resolve` or `estimates.SOURCES`.
- **New UI screen:** create `static/js/views/<name>.js`, then add one entry to `ROUTES` in `app.js` and one nav link in `index.html`.
- **Change a threshold:** edit `vmi/rules.py`, or override it per run with `RULES.with_overrides(...)`.

## Ground rules for contributors

See `docs/GROUND_RULES.md`. In short:

- Commit constantly (the watchdog runs every 30s).
- Never stop to wait.
- Research first.
- No patch-over-patch: restructure instead.

## Deployment

A local server (FastAPI + PM2, port 8000) running next to TWS. Not deployable to Cloudflare, because TWS needs a
local TCP connection.

Repo: https://github.com/Palakkaalakak/VMIProject (branch `main`). Last updated: 2026-11-04.
