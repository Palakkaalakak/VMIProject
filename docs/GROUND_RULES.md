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

## Human-in-the-loop directive (2026-11-04)
- The owner expects me (the AI) to USE the tool and apply judgment where data is distorted, e.g. TMO: consensus
  growth was temporarily distorted very low while Adam kept the previous growth rate (high-quality compounder).
  Such cases are handled with per-ticker overrides (growth / method / biz type / IV + note) stored in the DB —
  never by changing the general formula.
- Haircut experiments requested: compare flat haircuts applied to (1) IV directly, (2) growth rate before the
  IV calculation, etc. Keep each variant a single fixed number.

## Rule reinforcement (2026-11-04, owner was explicit)
- NEVER STOP. After a status report, continue working in the same turn. Do not end a turn waiting for input.
- If the autocommit watchdog is not running, START IT IMMEDIATELY (do not report and wait):
  `setsid -f bash tools/autocommit.sh /home/user/webapp 30 > /home/user/autocommit.out 2>&1 < /dev/null`
  Check at the start of every turn: `ps aux | grep "[a]utocommit.sh"`.
- Negative equity (doc §3.5 / ROE §5.1): fine — even good — when profitable, NI rising, FCF rising, and the cause is
  a large treasury-stock balance (buybacks). ROE is then "effectively infinite" → pass. Implemented in step 4.

## Q: "Can we download an older IB API version for fundamental data?" (answered 2026-11-04)
- No. Error 10358 "Fundamentals data is not allowed" is returned by IB's SERVERS, not by the client library.
  Users on ibapi 10.46.1 + ib_async 2.1.0 (versions that still contain reqFundamentalData) started getting 10358 on
  ~22 Apr 2026 with no code change (r/IBKR_Official thread). 10.47 then removed the method entirely. An older TWS /
  API download therefore still hits the same server-side block. The code keeps trying IB first behind a 6h circuit
  breaker (vmi/data/ib_fundamentals.py), so if IB ever re-enables it, it is used automatically.

## Client Portal fundamentals (2026-11-05)
- Superseded by the `vmi/data/ibportal/` package, built from IB's own portal and gateway code. Full research, sources
  and the setup decision are in `Log.md` (2026-11-05). Correction to the research note above: current TWS builds refuse
  `reqFundamentalData` locally (error 10358, gated by the login's permission). The refusal does not come from IB's
  servers for every client.

## Change log rule (owner, 2026-11-05)
- Every change is logged in `Log.md` (what, why, files, verification, open items) so future AIs and coders can
  continue without guesswork. Code must stay clean and modular: one job per module, one place per setting.
