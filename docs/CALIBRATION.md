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

## Haircut-location experiments (2026-11-04, `tools/haircut_experiments.py`)
36 reference tickers valued by DCF/DNI (P/B, P/S, PSG names excluded — haircuts don't apply to them).
Each row = ONE fixed number in ONE place. ratio = ours ÷ Adam.

| Variant | Median | in 0.85–1.05 | ±15% | >1.10 (too high) | <0.75 (too low) | log-IQR (spread) |
|---|---|---|---|---|---|---|
| none (pure Adam rules) | 1.036 | 11 | 15 | 15 | 1 | 0.378 |
| **IV −10% (current)** | 0.932 | 9 | 12 | 10 | 7 | 0.378 |
| IV −15% | 0.880 | 10 | 13 | 7 | 13 | 0.378 |
| growth ×0.90 | 0.932 | 9 | 11 | 10 | 6 | 0.375 |
| growth ×0.85 | 0.887 | 9 | 12 | 8 | 9 | 0.367 |
| growth ×0.80 | 0.845 | 9 | 12 | 7 | 13 | 0.349 |
| growth −2pp | 0.901 | 11 | 15 | 10 | 10 | 0.429 |
| discount rate +1pp | 0.930 | 9 | 12 | 10 | 8 | 0.385 |
| yrs 11–20 at 2% (Adam's own conservative option) | 0.977 | 9 | 13 | 11 | 4 | 0.378 |
| lowest source instead of average (Adam's conservative case) | 0.911 | 7 | 12 | 11 | 8 | 0.406 |

### Conclusions
1. **Where the haircut goes barely matters.** A flat IV cut, a relative growth cut and a discount-rate
   add-on all just shift the median. Spread (log-IQR ≈ 0.38) is unchanged because the errors are
   **per-company**, not systematic.
2. A relative growth cut (×0.85–0.80) shrinks spread a little: it hits high-growth names harder, and
   those are where free consensus is most inflated. An absolute pp cut is worse (it crushes slow growers).
3. **Kept: IV −10%.** It's the simplest knob and lands the median at 0.93 (conservative side), with fewer
   over-valuations than pure Adam rules (10 vs 15). `growth_haircut` exists as an alternative (×0.85 ⇒
   median 0.89, only 8 over-valuations) if more conservatism is wanted. Use one knob or the other, not both.
4. The remaining large misses are data/judgement cases, not formula cases (next section).

## Judgement cases (human-in-the-loop — per-ticker overrides, never formula changes)
| Ticker | Ours/Adam | Why | Action |
|---|---|---|---|
| ASML | 3.3 | Free "EPS next 5Y" 42–52% (cycle peak); ADR, EUR statements | override growth to normalised (~15–18%) |
| BKNG | 2.2 | Adam's IV implies ~4% growth vs consensus ~16% | review: Adam likely uses a different base/share count after the split |
| VEEV | 2.0 | FinViz 12.5% vs Zacks 35% — one source stale | override growth to the credible source |
| ACGL | 1.9 | insurer: DNI with near-zero growth estimate vs Adam's P/B | method override to `pb_bank` |
| AVGO | 1.4 | 65% growth (AI cycle) hits the 40% cap | override growth |
| TMO | (P/S ref.) | consensus growth was temporarily distorted LOW; Adam kept the prior rate (high-quality compounder); CFO dip fails strict consistency | override method `dcf_fcf` + growth ≈ Adam's prior rate |
| LIN, WM, CTAS | 0.58–0.78 | low beta ⇒ lowest rate, but growth sources ~9–11%; Adam uses higher FactSet growth | acceptable (conservative); override if conviction |
| PLTR | 0.28 | speculative ⇒ PSG; Adam uses DCF on forward numbers | method override `dcf_fcf` if desired |

## Update 2026-11-04 (later) — data fixes, Adam normalisation rule, judgement layer

Fixes applied (all Adam-rule or data-hygiene, no fitting):
1. **SEC currency bug** — 20-F filers tag a one-year USD convenience translation beside the real currency; we
   mixed RMB history with a USD year. Now the dominant unit is used. BABA 0.19 → **0.96**.
2. **Adam's cash-flow normalisation rule** (MSFT/AMZN case study): sudden big TTM jump → prior FY; sudden plunge
   → 4y average. "Sudden" is measured against the company's own 3y trend (steady compounders keep TTM, as
   Adam does for MSFT). ASML's TTM FCF 21.2B vs FY 11.1B is the main target (still high, see below).
3. **Negative equity** (doc §3.5/§5.1): ROE "effectively infinite" → pass when profitable, NI rising, FCF rising
   (or growth-capex dip with rising CFO, doc Amazon rule), and buybacks caused it. MCD/AZO/YUM/DPZ/ORLY/HLT/BKNG/
   VRSN pass; LOW/SBUX/PM/MO/ABBV fail on profit consistency (correct per the rule).
4. **Judgement layer** `config/judgements.json` (committed; DB overrides layer on top): TMO (growth 13% + DCF),
   ASML 20%, AVGO 25%, VEEV 18%, ACGL P/B, PLTR DCF. Pure-formula results are always reported separately.

| run | median ours/Adam | within ±15% | > 1.05 | < 0.75 |
|---|---|---|---|---|
| pure formula (iv −10%) | **0.922** | 13/43 | 13 | 10 |
| with judgements | 0.81 | 12/43 | 9 | 12 |

Growth input vs Adam's own "Avg. Growth Rate" (data/growth_vs_adam.json): median diff **+0.8pp**, 18/35 within
±2pp. Feeding Adam's exact growth into our DCF raises ±15% hits from 12 → 18, so ~half the error is growth input,
half is base cash flow / balance sheet. Biggest growth misses: ASML +18.9pp, BABA +17.3pp, AVGO +13.9pp (cyclical
rebound estimates hitting the 40% cap) and NVO −10.5pp (consensus collapsed; Adam kept 14.5%).

Remaining open outliers: BKNG 2.0 (Adam 188 vs our 378 at the same growth — base or share count differs;
under investigation), NKE 1.9 / LVMUY 0.28 / CNSWF 0.79 (P/S mean; Adam uses DCF), VEEV 1.48, UNH 1.35 (classified
as insurer → P/B), POOL/LIN/WM 0.5–0.7 (conservative side — acceptable per policy).

## Update 2026-11-04 (evening) — split adjustment, scanner pins

- **Stock splits** (`vmi/data/splits.py`): XBRL mixed pre/post-split units (BKNG 25:1 → P/E ≈ 1). Self-checking
  per-point adjustment; NVDA/AVGO/BKNG histories now consistent. BKNG 2.01 → 1.85 (remaining gap: base FCF).
- Latest run: **pure formula median 0.922, 14/43 within ±15%, 8 in the 0.85–1.02 target band**; with judgements
  median 0.81, 14/43 within ±15%, 9 in band, only 8 above 1.05.
- Scanner: tickers with a judgement override bypass the cheap pre-filters and get a full deep report (TMO).
