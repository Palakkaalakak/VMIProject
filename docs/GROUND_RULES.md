# Project Ground Rules (from the owner — non-negotiable)

1. **Constantly commit everything to GitHub.** An autocommit watchdog (`tools/autocommit.sh`, every ~40s)
   must always be running. The environment can randomly wipe uncommitted work.
2. **Never stop to ask questions or to begin.** Only stop if absolutely, critically necessary AND everything
   implementable without stopping is done. If something external breaks (e.g. GitHub disconnects), stay
   active (background retry) and resume automatically.
3. **Research, always.** Best practices, API details, data sources — for highest quality and fastest code.
4. **No patch-over-patch bloat.** Restructure when needed; keep the code extremely modular and easy to iterate.

## Data completeness requirement (added 2026-11-04)
- Get ALL data from the IB API where possible, as efficiently as possible.
- Where IB cannot provide it, use other sites/APIs/scraping.
- "Handling errors" or "omitting items without data" is **NOT an acceptable excuse**. Up-to-date fundamental
  data for everything the VMI checks need MUST be found for **every S&P 500 company**.
- Note: IBKR removed `reqFundamentalData` in TWS API 10.47 (2026). IB is therefore used for quotes, history,
  option chains and scanners; fundamentals come from SEC EDGAR XBRL (official, nightly) with FinViz / Zacks /
  Yahoo / stockanalysis-style fallbacks, and a coverage audit (`vmi coverage`) that proves completeness.

## Product scope (summary)
- Paper trading only (never send orders to IBKR): fill at mid + flat realistic slippage; illiquid ⇒ mid debuff.
  Multiple portfolios (growth / defensive / balanced …), default cash $100k.
- Buy/sell any stock with VMI helpers (auto sizing, tranches).
- Tracked watchlists with IV + supports and in-app notifications; import watchlists.
- Superscanner over the whole US market, cheapest/broadest filters first; all valuation methods auto-selected per
  company type with contingencies (normalised capex, CFO, DNI, P/B, P/NAV, P/S, PSG); sortable by growth, ROE, etc.
- Option chain (CC / CSP) loading in < ~40s, reliable, not disappearing.
- Any other tool that helps given Adam's method.

## IB fundamentals directive (added 2026-11-04, later message)
- "Try to figure out a way to get fundamentals from IB still. Research deeply."
- Research result: TWS API 10.47 (May 2026) removed reqFundamentalData + tick 47/258; servers answer
  older clients with error 10358 since ~Apr 2026. Client Portal fundamental tags deprecated Jan 2026.
  The app still TRIES IB first (vmi/data/ib_fundamentals.py, circuit breaker) — Refinitiv XML incl.
  ProjLTGrowthRate is used automatically whenever IB answers — then SEC → stockanalysis → Yahoo → FDIC.
- Calibrate intrinsic values against Adam's reference numbers (tests/fixtures/adam_reference.txt). Ours need not
  match exactly (Adam uses FactSet growth), but should be close and CONSERVATIVE: being somewhat below Adam's IV
  is better than being above it.

## Operational rule learned (2026-11-04)
- The environment wipe also deletes files written minutes before it hits. Watchdog interval is 30s and
  `tools/save.sh "<msg>"` is run immediately after every significant write. Diagnostics live in `tools/`
  (never /tmp). Never use `pkill -f <pattern>` where the pattern appears in the same command line.

## Calibration directive (added 2026-11-04)
- Do NOT force valuations to match Adam with non-Adam-approved transforms (no fitted formulas on growth,
  cash flow, etc.). Only simple FIXED conservatism adjustments are allowed (e.g. a flat −10% on IV) when we
  consistently overestimate. Nothing complicated or overfitted. → implemented as `rules.valuation.iv_haircut`.
