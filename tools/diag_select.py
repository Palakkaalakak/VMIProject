"""Why did the selector pick what it picked?  PYTHONPATH=. python tools/diag_select.py HCA MELI V"""
from __future__ import annotations

import sys

from vmi.analysis.classify import classify
from vmi.analysis.consistency import history_with_ttm, series_trend
from vmi.analysis.valuation.methods import ValuationContext, capex_is_lumpy
from vmi.analysis.valuation.selector import candidate_methods, value_company, working_capital_share
from vmi.data import market
from vmi.data.estimates import get_estimates
from vmi.data.fundamentals import resolve

for s in [a.upper() for a in sys.argv[1:]]:
    f = resolve(s)
    e = get_estimates(s)
    px = market.last_price(s) or 0
    h = market.history(s, "10y")
    biz = classify(f.sic, f.sic_description, e.sector, e.industry)
    ctx = ValuationContext(f, e, px, h)
    print(f"== {s} biz={biz.value} px={px:.2f}")
    for c in ("revenue", "cfo", "net_income"):
        t = series_trend(f, c)
        print(f"   {c:10s} ok={t.consistent} {t.reason} vals={[round(v / 1e9, 2) for v in history_with_ttm(f, c)]}")
    print(f"   wc_share={working_capital_share(f)} lumpy={capex_is_lumpy(f)} growth={ctx.growth_choice.to_dict()}")
    order, why = candidate_methods(ctx, biz)
    print(f"   order={order} | {why}")
    rep = value_company(ctx, biz)
    for k, r in rep.methods.items():
        print(f"     {k:15s} applicable={r.applicable} iv={r.intrinsic_value and round(r.intrinsic_value, 1)} {r.reasons[:2]}")
    print(f"   -> selected={rep.selected} iv={rep.intrinsic_value}")
