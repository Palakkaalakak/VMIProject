# Plan: trade ledger, deep journal & what-ifs, option payoff book, UIP automation

## Context
Owner wants the paper-trading side to become a premium UIP workstation:
1. **Admin ledger editing** – add/change/delete past orders (symbol, side, qty, fill, date+time, fees…) when something was wrong or missed.
2. **Deep tracking** – record as much data as possible about every order and every day, so future sessions (or the owner by hand) can study the strategy and simulate alternatives we cannot foresee now (sold calls vs not, sell at +50%/+100% over IV, all-at-once vs tranches, keep vs sell…).
3. **Option payoff book** – save option profit graphs + scenario grids (price ±X, IV ±Y, days forward) with their inputs so positions can be analysed when IBKR/quotes are unavailable.
4. **Automation** – tranche levels per stock, auto-fill paper orders when a level is hit (or alert only), alerts, automatic position sizing (by target count, by watchlist size, or manual override).

Constraints: paper only, never send orders to IBKR; clean, easy-to-edit code; log everything in Log.md; don't invent VMI criteria (automation only executes the owner's levels/rules).

## Current state (uncommitted, from before "plan first")
- `vmi/store.py`: committed – Trade journal columns (kind, source, fees, tags, thesis, context, edited), `TradeAudit`, `OptionSnapshot`, auto column migration. Uncommitted – `Portfolio.settings` JSON, `TranchePlan`, `DailyMark` tables.
- `vmi/paper/ledger.py`: written, untested (pure `step`/`replay`, `verify`, `rebuild`, admin add/update/delete with dry-run validation + audit, running `ledger()` view).

## Design

### 1. Ledger = source of truth (`vmi/paper/ledger.py`, `vmi/paper/engine.py`)
- `engine._apply` uses `ledger.step` (one accounting rule for live fills and replays); fees reduce cash.
- `settle_expired` writes explicit closing trades (`kind="expiry"` at 0, `kind="assignment"` stock trade) so a replay reproduces expiries exactly.
- Admin ops require a reason, dry-run the full replay (no overselling at that point in time; optional allow-negative-cash), then apply, rebuild and write `TradeAudit` (full before/after row). `verify(pid)` = drift check; `ledger(pid)` = each trade with position/cash after it.
- Tests: replay == incremental engine for a mixed stock/option history; back-dated buy changes avg cost/cash; oversell rejected; delete/update audited; legacy DB migrates.

### 2. Journal data capture (`vmi/paper/context.py`, `vmi/paper/journal.py`)
- **On every trade** (`Trade.context`, best effort, never blocks the fill): full analysis snapshot – price, IV + conservative IV + every method's value, growth path, discount rate, MOS, each step pass/fail with key values, category, moat grade/reviewed, buy levels/supports, daily/weekly trend, iv_confidence; portfolio state before/after (equity, cash, weight, position count, sizing plan used); tranche plan + level that triggered it; order origin (manual/auto/admin); thesis & tags; for options also spot, strike/DTE, bid/ask/mid, chain IV, greeks, and a payoff snapshot id.
- **Daily marks** (`DailyMark`, once per day from the existing `_watch_loop` in `vmi/api/app.py`): per portfolio equity/cash/invested; per held or planned symbol price, value, weight, IV, MOS, trend state, ATM option implied vol when a chain is cached. This builds the time series future what-ifs need (incl. option what-ifs).
- Raw export: `GET /api/portfolios/{pid}/export` → one JSON (trades with context, audit, marks, plans, snapshots) for manual analysis.

### 3. Review & what-ifs (`vmi/paper/review.py`)
- FIFO lots (stock + option) from the ledger; per lot: hold days, return, P&L, MFE/MAE, give-back from peak, entry MOS/IV/steps, exit vs IV, price +30/90/180/365 days after exit and today ("if kept").
- Stats: win rate, avg win/loss, profit factor, expectancy, hold time, slippage/fees, cash drag, breakdowns by tag/category/moat/MOS bucket/method/auto vs manual; behaviour flags (sold too early, bought above IV, skipped plan levels, over-allocation).
- What-if engine on daily price paths (`market.history`), each returning actual vs alternative per lot + total:
  `hold_instead`, `exit_over_iv(pct)` (e.g. 0.5, 1.0), `exit_tranches([(pct, fraction)…])`, `entry_all_at_once` vs actual tranches (first-level price / lowest level), `stop_loss`/`take_profit`, `covered_calls(otm_pct, dte)` (Black-Scholes with recorded IV from marks/context, else 30-day realised vol – labelled approximate), `benchmark` (same cash flows into SPY).
- Equity curve from marks (fallback: replay + daily closes) with drawdown.

### 4. Option payoff book (`vmi/options/payoff.py`, `vmi/options/book.py`)
- Pure: Black-Scholes price (reuse `vmi/options/chain.py::bs_greeks`, `_ncdf`, `RISK_FREE`), implied-vol solver, legs (options + stock), P&L curve at expiry and at any date, breakevens, max profit/loss, net greeks, scenario grid (spot moves × IV shifts × days forward).
- Snapshots: build legs from a portfolio's open positions for a symbol (or manual legs), IV per leg from quote → else solved from entry price; save inputs + results to `OptionSnapshot` on every option trade, on demand, and daily. `recompute(id, spot, iv_shift, days_forward, as_of)` works from saved inputs only (offline).

### 5. Automation (`vmi/paper/autotrade.py`, `vmi/paper/sizing.py`)
- Portfolio settings: `sizing_mode` target | watchlist (equity ÷ number of stocks in the linked watchlist) | manual ($ per stock), `tranches`, `auto_trade`, `market_hours_only`, per-stock allocation override on the plan.
- `TranchePlan` per stock: buy levels (price + fraction), optional sell levels (fixed price or % over IV + fraction), require-below-IV, multiplier, auto on/off override, history log.
- `plans_from_watchlist(pid, wid)`: one plan per watchlist item, levels = its supports below IV, sizing from the mode.
- `run_plans()` in `_watch_loop`: price ≤ level (within tolerance) & conditions met → auto paper fill via `engine.trade_stock` with plan context, or alert only; sell levels likewise; never over full allocation, never more cash than free cash; each level fires once; alerts for fills, skips (why), allocation reached, price > X% over IV.

- **Owner answers (2026-11-11):**
  - Auto vs alert-only is the owner's choice per portfolio (asked when a portfolio is created, switchable; plans can override). Default off until chosen.
  - Regular US hours only.
  - Default sizing = linked watchlist size (equity ÷ number of stocks in the watchlist the portfolio is built from); target count or manual $ as overrides, per portfolio and per stock.
  - **Backfill while the app/IBKR was offline:** on each run, for every active level, look at daily bars since the plan's last check. If a regular-session low reached the level (and the conditions held: below IV, allocation and cash left), record the fill as if it had happened then: dated that day, at the level (or the open if it gapped below), plus the normal slippage, `source="auto-backfill"`. It is inserted through the ledger (back-dated insert + rebuild + audit), so later cash and positions stay correct. Daily bars only, so intraday order is unknown; this is noted on the trade. The same applies to sell levels (day's high).

### 6. API + UI
- API (`vmi/api/app.py`): ledger (list, add, update, delete, verify, rebuild, audit), review (summary, lots, what-if params, equity curve, export), option book (profile from legs, snapshot create/list/get/recompute/delete), plans (CRUD, from-watchlist, run now), portfolio settings.
- UI (new views, route + nav entry each): `ledger.js` (table + add/edit modal, verify/rebuild, audit), `review.js` (KPIs, lot table, what-if form/results, equity curve SVG), `optionbook.js` (payoff SVG chart, scenario heat table, recompute controls), `plans.js` (levels editor, auto toggle, sizing settings). Portfolio page links to them; options page gets "Save payoff snapshot".

## Phases & model
| Phase | Work | Model |
|---|---|---|
| 1 | Ledger + engine refactor + tests | Opus 5.5 high |
| 2 | Context capture, daily marks, export | Opus 5.5 high |
| 3 | Review/what-if engine + tests | Opus 5.5 high |
| 4 | Payoff math + snapshots + tests | Opus 5.5 high |
| 5 | Automation + sizing + tests | Opus 5.5 high |
| 6 | API routes | Sonnet 5.5 medium |
| 7 | UI views, docs (README section), Log.md | Sonnet 5.5 medium |
I will say "switch to Sonnet medium now" after phase 5 is committed. Commit + push after each phase.

## Verification
- `python3 -m pytest -q tests` (new: `tests/test_ledger.py`, `test_review.py`, `test_payoff.py`, `test_autotrade.py`; existing `test_paper.py` must stay green).
- Scripted end-to-end on a temp DB: create portfolio → buys/sells/options → admin back-dated add + edit + delete → `verify` ok; review/what-ifs return numbers; payoff snapshot recompute without network; plan with levels auto-fills when a fake price crosses; backfill test with synthetic history (level touched 5 days ago → back-dated fill at level, cash/position correct after rebuild; gap-down fills at open; level fires once).
- Launch app (`python -m vmi.api`), drive the new pages with Playwright, screenshot each.

## Status (2026-11-11)
Phases 1-5 done and tested (`tests/test_ledger.py`, `test_payoff.py`, `test_review.py`, `test_autotrade.py`; full suite 137
passing). Background loop (`vmi/api/app.py::_watch_loop`) runs tranche plans, daily marks and daily option snapshots.

Backend entry points for phases 6-7 (API routes + UI), all plain functions returning JSON-able dicts:
- `vmi/paper/ledger.py`: `ledger(pid)`, `add_trade(pid, data, reason, allow_negative_cash)`, `update_trade(id, changes, reason)`,
  `delete_trade(id, reason)`, `verify(pid)`, `rebuild(pid, reason)`, `audit(pid)`. Errors: `LedgerError` (400).
- `vmi/paper/journal.py`: `record(pid)`, `marks(pid, key, since)`, `export(pid)`.
- `vmi/paper/review.py`: `summary(pid)` (lots, stats, flags, breakdowns), `what_if(pid, name, **params)` with names in
  `WHAT_IFS`, `equity_curve(pid)`.
- `vmi/options/book.py`: `snapshot_portfolio(pid, symbol, ...)`, `snapshot_legs(symbol, legs, spot, ...)`, `get(id)`,
  `list_snapshots(pid, symbol)`, `recompute(id, spot, iv_shift, as_of)`, `delete(id)`; pure maths in `vmi/options/payoff.py`.
- `vmi/paper/autotrade.py`: `settings(pid)`, `update_settings(pid, changes)` (keys in `DEFAULTS`), `upsert_plan(pid, symbol,
  **fields)`, `get_plans(pid)`, `delete_plan(pid, symbol)`, `plans_from_watchlist(pid, wid)`, `run(pid)`,
  `full_allocation(pid, equity)`. Errors: `PlanError` (400).
- Order endpoints should accept the new optional `fees`, `tags`, `thesis` (pass as `journal={"tags":…, "thesis":…}`).
- Portfolio creation UI must ask the owner: auto-trade on/off and the watchlist to size from.


## Status update
Phases 6-7 done (API routes, `ledger.js`, `review.js`, `optionbook.js`, `plans.js`, `charts.js`, portfolio links, options-page hook). 143 tests passing. Browser-checked.
