# Intrinsic-value calibration vs Adam's published numbers

Reference: `tests/fixtures/adam_reference.txt` (owner-supplied, 2026-11-04). Run:

    PYTHONPATH=. python -m vmi.analysis.calibrate          # writes data/calibration.json

## Policy (owner directive)
- The valuation engine implements Adam's method only: average of available analyst 5y EPS growth
  estimates for years 1–5, same rate capped at 15% for years 6–10, 4% for years 11–20, 20-year horizon,
  beta-table discount rate, cash − debt, diluted shares. Capex normalisation / CFO / DNI / P/B / P/NAV /
  P/S / PSG chosen per company type exactly as in Lesson 5.
- NO fitted transforms of growth or cash flow. The only calibration knob is ONE flat haircut on
  discounted-stream valuations: `rules.valuation.iv_haircut`.
- `calibrate.py` reports `suggested_flat_haircut` = smallest 5%-step cut that brings the median
  ours/Adam ratio of DCF/DNI results to ≤ 0.95 (conservative side).

## Current setting: iv_haircut = 0.10
Calibration run on 43 reference tickers (before haircut): median ratio 1.036, suggested haircut 10%.
Reason: we lack FactSet; the free consensus (FinViz/Zacks/Yahoo) runs higher on average.

## Known outliers (left as-is, NOT fitted; use per-ticker overrides after reading the news)
| Ticker | Cause |
|---|---|
| ASML, AVGO | free sources show 40–65% "EPS next 5Y" (stale/hyper-cycle); hits the 40% sanity cap |
| VEEV | sources disagree (FinViz 12.5% vs Zacks 35%) — average is high |
| BKNG | post-split; Adam's IV implies ~4% growth vs consensus ~16% |
| ACGL, UNH | insurers: NI-based / P/B values diverge from Adam's choice |
| NKE, TMO, LVMUY, CNSWF, EVVTY | fail Step 1 consistency → mean P/S "reference only" value |
| PLTR | speculative (PSG) — Adam uses a DCF on forward numbers |

Per-ticker overrides (growth, method, business type, IV) are stored in the DB and applied by
`analyse_ticker(..., overrides=...)` — this is the human-in-the-loop path the owner asked for
(e.g. forcing normalised capex for a hyperscaler, or a lower growth for a cyclical peak).
