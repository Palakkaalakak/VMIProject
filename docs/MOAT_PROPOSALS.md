# Proposals: better evidence for the (discretionary) moat review

The moat verdict stays with the reviewer, a person or an AI. These additions would give the reviewer more and
better evidence, ranked by value for effort. Each one maps to something Adam explicitly checks (master doc,
Step 3 and Pillar 5).

| # | Addition | What the reviewer gets | Adam's basis | Data source | Effort |
|---|---|---|---|---|---|
| 1 | **Peer comparison ("top dog?")** | Auto peer set (same SIC/industry); side-by-side margins, ROIC, growth, size, share of the peer group's revenue; rank | "Closest competitors must be weaker… invest in the top dog; if no clear leader, forget it" | SEC frames (all US filers, free), already used by the scanner | Medium |
| 2 | **AI moat scorer** | Each of the 5 sources scored /10 with a written reason, plus an overall score; pre-fills the review card for confirmation | Adam uses StockOracle's AI moat score (7–9 = confidence, 6 = not enough) | Claude API over the 10-K "Business" and "Risk factors" sections plus our evidence; cached per filing | Medium |
| 3 | **Pricing-power test from history** | Did gross margin hold through the 2021–23 cost inflation? Price/mix vs volume where disclosed | "Can it raise prices every year without losing share?" | SEC gross profit/revenue by year (have); CPI | Small |
| 4 | **Switching-cost proxies** | Deferred revenue ÷ revenue trend (recurring/prepaid business); remaining performance obligations | Switching costs "normally subscription-based" | SEC tags (ContractWithCustomerLiability, RevenueRemainingPerformanceObligation) | Small |
| 5 | **10-K text excerpts** | The "Competition" paragraph, customer-concentration sentences ("one customer accounted for X%"), named competitors | Competitors, weak suppliers/customers (Pillars 3–5) | SEC EDGAR full-text / filing HTML | Medium |
| 6 | **Reinvestment and scale intensity** | R&D and SG&A as % of sales vs peers; capex vs peers | Economies of scale: "out-spend on R&D", spread fixed costs | SEC tags | Small |
| 7 | **Moat staleness alerts** | Review date per ticker; alert "moat check due" when margins/ROIC fall for 2 years or after 12 months | Moats erode (Intel example); turnaround rule needs the moat intact | Our own data + review timestamps | Small |
| 8 | **Third-party views** | Analyst/peer ratings where licensed (e.g. IB Fundamentals Explorer ratings widget) | Adam cross-checks Oracle/Community/AI moat views | IB gateway (once live) | Small, after IB check |

Recommended order: 3, 4, 7 (small, pure data, immediately useful) → 1 (biggest evidence gap) → 2 (best
reviewer productivity; needs an API key and a cost decision) → 5, 6, 8.
