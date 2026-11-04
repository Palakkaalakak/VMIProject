"""Diagnostics: dump every valuation input for tickers and compare to Adam's reference IV.

    PYTHONPATH=. python tools/diag_valuation.py BKNG UNH VEEV
"""
from __future__ import annotations

import sys

from vmi.analysis.calibrate import load_reference
from vmi.analysis.valuation.core import discounted_value, growth_path
from vmi.analysis.valuation.methods import ValuationContext, capex_is_lumpy, normalised_fcf
from vmi.data import market
from vmi.data.estimates import get_estimates
from vmi.data.fundamentals import resolve


def solve(fn, target, lo, hi, increasing=True):
    for _ in range(60):
        mid = (lo + hi) / 2
        if (fn(mid) < target) == increasing:
            lo = mid
        else:
            hi = mid
    return mid


def main(symbols: list[str]) -> None:
    ref = load_reference()
    for s in symbols:
        f = resolve(s)
        e = get_estimates(s)
        px = market.last_price(s) or 0
        ctx = ValuationContext(f, e, px, None)
        y = e.extra.get("yahoo", {})
        mc, yso = y.get("market_cap"), y.get("shares_outstanding")
        lumpy = capex_is_lumpy(f)
        base = normalised_fcf(f) if lumpy else f.last("fcf")
        adam = (ref.get(s) or {}).get("iv")
        g = e.eps_growth_5y
        iv = discounted_value(base, growth_path(g), ctx.rate, ctx.debt, ctx.cash, ctx.shares) if base and g else None
        print(f"{s:5s} px={px:.2f} adam={adam} ourIV={iv and round(iv, 1)} ratio={iv and adam and round(iv / adam, 2)}")
        print(f"   shares ctx={ctx.shares / 1e6:.1f}M dei={f.latest.get('shares_outstanding', 0) / 1e6:.1f}M "
              f"yahoo={(yso or 0) / 1e6:.1f}M mcap/px={(mc or 0) / max(px, 1e-9) / 1e6:.1f}M "
              f"q={[(p.end, round(p.value / 1e6, 1)) for p in f.quarterly.get('shares_diluted', [])[-2:]]}")
        print(f"   biz={f.meta.get('biz')} lumpy={lumpy} base={base and base / 1e9:.2f}B fcf={f.last('fcf') / 1e9:.2f}B "
              f"cfo={f.last('cfo') / 1e9:.2f}B ni={f.last('net_income') / 1e9:.2f}B debt={ctx.debt / 1e9:.1f}B "
              f"cash={ctx.cash / 1e9:.1f}B beta={e.beta} rate={ctx.rate}")
        print(f"   growth sources={ {k: v['eps_growth_5y'] for k, v in e.sources.items()} } blend={g}")
        print(f"   cfo hist={[round(v / 1e9, 2) for v in f.series('cfo')[-6:]]} capex={[round(v / 1e9, 2) for v in f.series('capex')[-6:]]} "
              f"prov cfo={f.provenance.get('cfo')} ttm={f.provenance.get('ttm:cfo')}")
        if base and base > 0 and adam:
            ig = solve(lambda x: discounted_value(base, growth_path(x), ctx.rate, ctx.debt, ctx.cash, ctx.shares), adam, -0.3, 0.8)
            print(f"   growth implied by Adam's IV (same base/rate): {ig:.3f}")


if __name__ == "__main__":
    main([a.upper() for a in sys.argv[1:]])
