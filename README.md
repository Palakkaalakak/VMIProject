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
17; see "IB setup" below for the recommended live-login + Read-Only API setup). Cloud hosting such as Cloudflare can't open a TCP connection to TWS, which is why this is a local FastAPI
server rather than a Workers app. Without IB the app still works, falling back to Yahoo for quotes and options.

Settings come from environment variables or `.env` with the `VMI_` prefix (see `vmi/config.py`): `VMI_IB_HOST`,
`VMI_IB_PORT`, `VMI_IB_CLIENT_ID`, `VMI_IB_PORTAL_WORKERS`, `VMI_SEC_USER_AGENT`, `VMI_PORT`, …

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
| IB fundamentals via a browser login on the portal site (Fundamentals Explorer backend), parallel bulk `sync` | ✅ verified live: full S&P 500 `sync` in ~6 min (497/503) | `vmi/data/ibportal/`, `vmi/data/ib_fundamentals.py` |
| Settings screen: every rule editable in the UI (no code), saved to `config/rules_settings.json` | ✅ | `vmi/settings.py`, `static/js/views/settings.js` |
| Moat = reviewer's verdict; the app gathers the evidence + Adam's 5-source checklist; VMI buy needs a reviewed moat | ✅ | `vmi/analysis/steps.py` |
| Judgement overrides for every input (growth, blend, sources, method, beta, shares, cash/debt, haircut, IV, steps, buy levels, sizing, scanner pin/exclude): UI card, API, CLI | ✅ | `vmi/overrides.py`, `config/judgements.json` |

**Not done yet:** the calibration re-run with the new IB data; full-market
scanner run benchmark; judgement-only calibration cases (BKNG and UNH growth input, NKE/LVMUY on P/S), see
`docs/CALIBRATION.md`; companies with a short history. Progress and reasoning for every change: `Log.md`.

## Data sources (fundamentals)

TWS API 10.47 removed `reqFundamentalData`, and current TWS builds refuse it locally (error 10358) unless your login
has IB's fundamentals-for-API permission. IB still serves the same LSEG data, free, through its Fundamentals Explorer.
The app tries IB first (`vmi/data/ib_fundamentals.py`, each path behind a circuit breaker), then falls back:

0. **IB**:
   - **TWS XML**, which works automatically wherever IB still allows it.
   - **IB's portal site** (`vmi/data/ibportal/`): financial statements plus analyst growth from the Fundamentals
     Explorer backend, read after a browser login. Routes taken from IB's own portal code (`Log.md`). Read-only,
     cached for 14 days, filled by a parallel bulk `sync`; the app only reads the cache.

1. **SEC EDGAR XBRL**: official statements for every US filer. Companyfacts serve deep analysis; frames serve cheap cross-market scans.
2. **stockanalysis.com**: gap fill, ratio histories, newer fiscal years.
3. **Yahoo**: last resort for core items.
4. **FinViz / Zacks / Yahoo / stockanalysis**: consensus growth (plain average, Adam's rule).
5. **FDIC BankFind**: bank CET1.
6. **NASDAQ screener / Wikipedia / GitHub**: universe lists.

Coverage audit: `python3 -m vmi.data.coverage` writes `data/coverage_sp500.json`.

### IB setup (reasoning, evidence and the dead ends are in `Log.md`, 2026-11-05 and 2026-11-06)

Two separate things, using two usernames:

1. **Live quotes: IB Gateway (or TWS) on your live login**, API port 7496 / 4001, with Read-Only API ticked. The app finds
   the port itself (tries 7496, 7497, 4001, 4002; set `VMI_IB_PORT` only to force one). It only reads market data; its
   paper trading is simulated locally. It also resolves ticker → IB contract id (cached 180 days).
2. **Fundamentals + analyst growth: a browser login on your PAPER username** (no gateway, no Java). IBKR's Client Portal
   Gateway cannot carry these routes (it redirects them; verified 2026-11-06), so the app drives your installed Edge/Chrome:
   ```bash
   pip install playwright
   ```
   ```bash
   python3 -m vmi.data.ib_fundamentals check AAPL MSFT --no-tws
   ```
   ```bash
   python3 -m vmi.data.ib_fundamentals sync --sp500
   ```
   Start IB Gateway first (step 1): `sync` resolves contract ids before opening the browser. After the login it copies the
   browser's cookies into a fast HTTP client (8 tickers in parallel); if the portal refuses that, the browser does the work. Log in with the paper username in
   the window that opens; the command continues by itself. Results are cached 14 days, so repeat about every two weeks.
   `check` saves raw JSON to `data/ib_portal_samples/`. `/api/health` shows the TWS path state.


## Ledger, journal, option book, automation (paper portfolios)
- **Ledger** (`#/ledger/ID`, `vmi/paper/ledger.py`): the trade list is the source of truth; cash and positions are a replay of it.
  An order added or edited by hand is a genuine order, exactly as if executed that way at that date and time (not a what-if);
  every change needs a reason and is kept in the audit trail (before/after rows). Drift check + rebuild, JSON export of everything.
- **Journal**: each trade stores what was known (trimmed VMI analysis, portfolio state, quote, plan level, tags, thesis); daily
  marks per portfolio/position/plan (`vmi/paper/journal.py`).
- **Review** (`#/review/ID`, `vmi/paper/review.py`): FIFO lots with path stats and what happened after the sale, behaviour flags,
  breakdowns and what-ifs (keep, sell at X over IV, tranche exits, stop/target, hold N days, all-at-once entry, covered calls, benchmark).
- **Option book** (`#/optionbook/ID`, `vmi/options/payoff.py`, `book.py`): payoff curves, breakevens, greeks and price x IV x date
  grids, saved after every option trade and daily, recomputable with no IBKR connection.
- **Plans** (`#/plans/ID`, `vmi/paper/autotrade.py`): tranche levels per stock, sizing by watchlist size (default) / target count /
  manual $, auto-fill or alert-only per portfolio, regular hours only, offline backfill from daily bars (dated that day).
- Design and backend entry points: `docs/LEDGER_AUTOMATION_PLAN.md`.

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
    ib_fundamentals.py  IB coordinator: TWS XML → Client Portal Gateway; CLI `check` / `sync`
    ibportal/         portal client: routes.py (all URLs) · browser.py (login) · client.py (read-only HTTP) · parse.py · service.py (cache, sync)
    breaker.py        circuit breakers for optional sources (state shown by /api/health)
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
- **Override anything for one stock:** `python3 -m vmi.overrides schema` lists every key; `set TICKER key=value --note "why" [--commit]` applies it (the UI's Judgement overrides card does the same). New key: one line in `vmi/overrides.py` plus the line that applies it.
- **Change a threshold:** Settings screen in the UI (or `PUT /api/settings`); the defaults live in `vmi/rules.py`. For experiments: `RULES.with_overrides(...)` or `tools/haircut_sweep.py <section.key> <levels…>`.
- **IB changed a route or field:** edit `vmi/data/ibportal/routes.py`. To map another IB row label, add it to `LABELS` in `vmi/data/ibportal/parse.py`.

## Ground rules for contributors

See `docs/GROUND_RULES.md`. In short:

- Commit constantly (the watchdog runs every 30s).
- Log every change in `Log.md`: what, why, files, verification, open items.
- Never stop to wait.
- Research first.
- No patch-over-patch: restructure instead.

## Deployment

A local server (FastAPI + PM2, port 8000) running next to TWS. Not deployable to Cloudflare, because TWS needs a
local TCP connection.

Repo: https://github.com/Palakkaalakak/VMIProject (branch `main`). Last updated: 2026-11-04.
