# Task for the local session: scanner watchlists for the three withdrawal configurations

**Deliverable:** use the VMI scanner (with IB fundamentals synced, via the app or `funnel.run`) to build ONE stock watchlist
per configuration, saved as app watchlists (`Growth`, `Balanced`, `Withdrawal Max`). Selection by scanner output only:
no forecasting of whether the targets are reachable and no return/withdrawal modelling is wanted from this session.

The system (owner's brief): two sleeves. Growth Sleeve = individually selected equities (what this task builds).
Reserve Sleeve = defensive liquid assets funding withdrawals in bad periods (out of scope here). Start from Adam Khoo's VMI
but modify/supplement the screening criteria where that suits the goal: the Growth Sleeve should achieve the needed return
with the lowest practical volatility, drawdown and recovery time.

| Config | Initial withdrawal (inflation-linked) | Target real CAGR after withdrawals | Emphasis |
|---|---|---|---|
| Growth | 4% | 5% | capital appreciation, still consistent income |
| Balanced | 5.5% | 3% | more income, still real growth |
| Withdrawal Max | 7.5% | 1% | dependable income, capital resilience first |

Each step down prioritises income consistency and resilience over growth, without needless defensiveness.

## How to work
1. Sync IB fundamentals (Settings page or `python -m vmi.data.ib_fundamentals sync --sp500`), run the Superscanner, review moats
   (Moat evaluation page) for the steps 1-5 names (94 of 110 were unreviewed on the cloud run).
2. Use the scanner's filter panel (steps pass/fail, beta, trend, growth, ROE, margins, MOS, moat, IV-confidence flag) to
   build each list. Judge candidates on total-portfolio traits: drawdown, volatility, return consistency, recovery time,
   concentration by sector, correlation between holdings.
3. Hypotheses from the cloud run, to test and not to assume: steps 1-5 alone is no less volatile than the index; adding beta < 1
   or a daily uptrend lowered risk (downside capture 0.59 vs 0.83) in the last 10 years; growth >= 15% names added drawdown
   (beta 1.27, max drawdown 32%). Growth config can lean to growth/quality/momentum; Balanced and Withdrawal Max to lower beta,
   consistent earnings, dividends/buybacks, strong balance sheets. Adam's rules stay the base: no inventing criteria without
   saying so in Log.md.
4. For each list record: criteria used, number of names, sector mix, basket volatility/beta/drawdown vs SPY
   (`tools/scanner_baskets.py` shows how), and the stocks' IV, MOS and support levels. Log everything in Log.md.

## Moat re-review of the chosen companies (owner, 2026-11-07: required)
The scanner's step 3 is only a provisional shortcut. Every company that makes a watchlist must have its moat re-reviewed
by hand, with information from beyond the scanner (company filings and investor materials, competitor comparison, market
share and pricing-power evidence, news), following Adam's method in the master document (Step 3, l.2146-2212, l.2440-2464):
- Five moat sources: brand monopoly, switching costs, network effect, barriers to entry (patents/regulation), economies of
  scale. At least 3 of 5 to invest; score each with evidence, not assertion.
- Wide (about 20 years, no or insignificant competitors, can raise prices) vs narrow (about 10 years, several significant
  competitors, limited pricing power) vs none (many competitors, commodity, price decides: never invest).
- "Be the customer", compare against the closest competitors (they should be weaker; top dog only), check customer
  concentration, pricing power and margin trend; the 10-year chart is only a supporting shortcut.
- Where available, the Moat evaluation page (peers, annual-report competition passage, customer concentration) is the
  starting point, not the end.
Record the verdict on the Moat evaluation page (grade, sources, score, why) so it is saved as an override, with the evidence
and links in the "why" note. Drop any name that fails (no moat) from the watchlist. Mark as INFERRED anything that rests on
judgement rather than a source.

## Size note (owner, 2026-11-07: no action needed)
Adam's "< 1% pass steps 1-5" is reached only after the discretionary moat review. The scanner does not decide the moat
(step 3 is a provisional shortcut), so a large steps 1-5 count before moat review (110 of 231 on the cloud S&P 500 scan) is
expected and is not a bug. Do not tighten rules for this. Adam's portfolio size guidance (about 8-30 stocks, at most ~60) is
useful context when choosing how long each watchlist should be.

Background (not required reading, not part of the app): `docs/TWO_SLEEVE_RESEARCH.md` is a modelling side-study from the cloud
session that went beyond this brief; treat its conclusions as unverified context only.
