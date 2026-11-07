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

Background (not required reading, not part of the app): `docs/TWO_SLEEVE_RESEARCH.md` is a modelling side-study from the cloud
session that went beyond this brief; treat its conclusions as unverified context only.
