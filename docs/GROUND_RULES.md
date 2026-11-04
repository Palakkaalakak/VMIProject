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
