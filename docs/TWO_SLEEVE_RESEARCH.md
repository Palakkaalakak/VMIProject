# Two-sleeve withdrawal system: research results (2026-11-07)

Code: `vmi/research/` (data, strategies, simulator), `tools/two_sleeve_study.py`, `two_sleeve_reserve_sweep.py`,
`two_sleeve_report.py`, `scanner_baskets.py`. Data: `data/research/monthly.csv` (Ken French factors, Shiller CPI and
10y Treasury returns, 1926-07 to 2023-09; everything converted to REAL returns). Big outputs are regenerable and git-ignored.

## 1. What the targets demand (30-year horizon assumed; you did not give one)
Constant real return the whole portfolio must earn so that, after the real-constant withdrawals, capital grows at the target:

| Config | Withdrawal | Real CAGR target | Required real return |
|---|---|---|---|
| Growth | 4% | 5% | **7.3%** |
| Balanced | 5.5% | 3% | **7.0%** |
| Withdrawal Max | 7.5% | 1% | **7.8%** |

US stocks earned 6.2% real (1963-2023, 6.8% since 1926); a reserve in cash/bonds earns 0.3-1.8% real. So the growth sleeve
must beat the market by roughly 2-4 points a year, net of costs, and it does so with ordinary sequence risk.
100% market, no reserve, bootstrap of 1963-2023: P(meets target) 33% / 35% / 28%; P(depletion) 11% / 29% / 57%.

## 2. How candidates were tested
The VMI steps cannot be back-tested point in time (no historical fundamentals), so stock selection was NOT back-tested.
Instead the growth sleeve is modelled by what the screen is meant to deliver, using published, look-ahead-free series:
quality (profitability + investment factors) ~ steps 1/4/5; momentum ~ step 7 and the 10y-uptrend filter; trend (price vs
10-month average, switch to cash) ~ Adam's moving-average rule applied to the sleeve; low beta ~ defensive large caps.
Factor premia shrink after publication, so "decayed" results keep only half of each strategy's historical excess return
(0.5% a year implementation cost included). 2,000 block-bootstrap 30-year paths (5-year blocks) and the 31 historical
30-year windows were both used. Rules of the reserve: see `vmi/research/two_sleeve.py` docstring.

## 3. Findings
1. **The reserve sleeve does not improve the numbers.** Over 24 strategy/config pairs and a sweep of size (1-5 years),
   composition (cash / bonds / mix), trigger (10-35% sleeve drawdown) and refill speed, it cut depletion risk by more than
   0.5 point in only 3 cases (all 100%-equity market sleeves), and it lowered P(target) by 1-10 points because reserve assets
   earn about 6 points less than equities. Even on the worst quarter of starting sequences it helped only the plain market
   sleeve slightly (depletion 42% to 35% with 5 years of bonds) and hurt the quality sleeves. This matches published bucket-strategy
   work: a reserve is a behavioural and liquidity tool, not a return source. Keep it small (1-2 years of withdrawals).
2. **The lever is the growth sleeve's return and drawdown, not the reserve.** Decayed results (no reserve):

| Sleeve | Real CAGR | Vol | Worst drawdown | P(target) G / B / M | Depletion G / B / M |
|---|---|---|---|---|---|
| Market | 6.2% | 15.6% | 56% | .33 / .35 / .28 | .11 / .29 / .57 |
| Trend (market, to cash below 10m avg) | 5.6% | 11.5% | 27% | .23 (balanced) | .23 (balanced) |
| Low beta + trend | 5.6% | 9.8% | 25% | .27 / .31 / .20 | .01 / .17 / .61 |
| Quality + momentum | 9.6% | 15.1% | 43% | .73 / .73 / .62 | .01 / .08 / .27 |
| Quality + momentum + trend | 8.4% | 12.3% | 29% | .66 / .69 / .51 | .00 / .03 / .29 |

   Plain defensiveness (trend, low beta) loses too much return to meet any target: that is the "excessive defensiveness"
   case. Quality + momentum + trend gives up about 7 points of P(target) versus quality + momentum but halves the drawdown.
3. **Results depend on how much factor premium survives.** Quality + momentum + trend, P(target) Growth/Balanced:
   keep 0% of the historical excess: .38/.41; 25%: .52/.55; 50%: .66/.69; 100%: .89/.90. A constant excess return over
   the market (no change in volatility) needed for about 70% success: **+3 points** for Growth and Balanced; for Withdrawal Max,
   +4 points still leaves 21% depletion risk.
4. **Withdrawal Max (7.5% with +1% real growth) is not achievable dependably.** Best tested: quality + momentum, P(target)
   .62 but depletion .27-.30; quality + momentum + trend .51 / .29. Maximum initial withdrawal for 80% chance of meeting
   each growth target, 30 years, decayed quality + momentum + trend: 5% growth target 2.5%; 3% target 4.5%; 1% target 5.5%; 0% 6.0%.
   Shorter horizon helps: 20 years, depletion .10 for quality + momentum + trend.
5. Historical windows are kinder (in-sample factor premia): quality + momentum + trend met all targets with 0 depletion in
   the 31 windows for Growth/Balanced (worst start 1964), and 2 of 31 depleted for Withdrawal Max. Plain market: 9 of 31
   depleted at 5.5% and 11 of 31 at 7.5% (1963 and 1968 starts).

## 4. Suggested configurations (all one system: scanner-selected growth sleeve + small reserve)
Selection rule: highest P(target) among plans with acceptable depletion risk (3% / 5% / 10%), then lowest drawdown and
shortest time under water within a tolerance of 3 / 5 / 8 points of P(target), so defensiveness grows with the withdrawal.

| | Growth | Balanced | Withdrawal Max |
|---|---|---|---|
| Growth-sleeve style | quality + momentum, fully invested | quality + momentum with trend exit to cash | same as Balanced |
| Scanner screen (see section 5) | steps 1-5, below IV, daily uptrend, ROE >= 20%, growth >= 10% | steps 1-5, below IV, beta < 1, uptrend, net margin >= 15% | same as Balanced, plus no new buys in a downtrend |
| Reserve | 2 years of withdrawals (8% of capital), bonds/cash, used after a 15% sleeve drawdown, refilled from gains at the high | 1 year (5.5%), same rules (optional: costs 2 points of P(target)) | 1 year (7.5%) |
| Modelled P(target) / depletion | .72 / 1% | .69 / 3% | .58 / 30% (fails) |
| Real CAGR p10 / p50 / p90 | 1.6% / 7.2% / 12.0% | -0.8% / 5.0% / 9.5% | 3.0% median, 10th percentile depleted |
| Drawdown (median / 90th pct) | 40% / 48% | 26% / 30% | 39% / 47% |
| Time under water, 90th pct | 17 years | 23 years | 30 years |

Withdrawal Max should not be sold to yourself as dependable: 7.5% with positive real growth needs about 4 points of net
excess return. Options: accept guardrails (cut the real withdrawal after a bad year; not simulated yet), a 20-year horizon,
or about 5.5% initial withdrawal.

## 5. VMI scanner run (S&P 500, 2026-11-07)
Funnel: 503 listings -> 341 consistent track record -> 249 ROE >= 12% -> 228 in a 10-year uptrend -> 231 deep-analysed
(pinned judgements added). 110 pass steps 1-5; 108 trade below IV; only 4 pass the full buy signal because 94 of the 110 have an
unreviewed moat. Equal-weight, monthly, last 10 years (returns are look-ahead biased, because the screen uses today's data and a
10-year uptrend; only the risk columns are usable):

| Screen | n | Vol | Beta | Max drawdown | Downside capture | Worst 12m |
|---|---|---|---|---|---|---|
| S&P 500 (SPY) | | 15.4% | 1.00 | 24% | 1.00 | |
| Steps 1-5 | 110 | 16.7% | 1.03 | 22% | 0.83 | -13% |
| + beta < 1 | 56 | 14.6% | 0.75 | 20% | 0.59 | -6% |
| + daily uptrend | 25 | 14.4% | 0.78 | 18% | 0.59 | -3% |
| + defensive (< 15% growth) | 74 | 16.2% | 0.92 | 21% | 0.78 | -8% |
| + growth >= 15% | 36 | 21.5% | 1.27 | 32% | 0.93 | -27% |
| + wide moat | 14 | 18.1% | 1.08 | 31% | 0.94 | -22% |
| + ROE >= 25% | 65 | 18.1% | 1.11 | 27% | 0.90 | -19% |

Reading: steps 1-5 alone do not lower risk versus the index; beta < 1 and the uptrend condition do (downside capture 0.59).
High-growth names add drawdown. Valuation multiples (IV, MOS, PEG) cannot be tested historically without point-in-time
fundamentals: they were used only as entry filters, not as return predictors.

## 6. What this does not prove
- Stock selection by the scanner was not back-tested; factor series stand in for it. Real alpha could be lower (or higher).
- Factor tilts are gross long-short premia; a long-only stock portfolio captures less. Decay of 50% is a judgement.
- Sample 1963-2023 (60 years, about 2 independent 30-year periods); bootstrap resamples it, it does not add history.
- IB data was not used (the cloud session cannot reach your IB sign-in). Next: run the scanner on IB fundamentals locally or
  via a shared-folder session, review the moats of the 110 names, and re-run section 5.
