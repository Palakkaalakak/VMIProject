"""Risk profile of candidate VMI-scanner screens (equal-weight baskets, monthly, last 10 years).
Baskets are chosen with TODAY's fundamentals, so their RETURNS are look-ahead biased and are shown only for scale; the
risk columns (vol, beta, drawdown, downside capture) are what feeds the sleeve design.
PYTHONPATH=. python tools/scanner_baskets.py   (needs data/research/scan_sp500.json from a scanner run)"""
import json

import numpy as np
import pandas as pd
import yfinance as yf

rows = json.load(open("data/research/scan_sp500.json"))
R = pd.DataFrame(rows)
print(len(R), "scanner survivors (deep-analysed)")
great = R["great_business"] == True  # noqa: E712
BASKETS = {
    "all survivors": R.index == R.index,
    "great (steps 1-5)": great,
    "great + below IV": great & (R["undervalued"] == True),  # noqa: E712
    "great + beta<1": great & (R["beta"].fillna(9) < 1.0),
    "great + wide moat": great & (R["moat"] == "wide"),
    "great + defensive (<15% growth)": great & (R["style"] == "defensive"),
    "great + growth>=15%": great & (R["style"] == "growth"),
    "great + ROE>=25%": great & (R["roe"].fillna(0) >= 0.25),
    "great + daily uptrend": great & (R["trend"] == "uptrend"),
    "great + steps 1-5 + net margin>=20%": great & (R["net_margin"].fillna(0) >= 0.20),
}
syms = sorted({s for m in BASKETS.values() for s in R.loc[m, "symbol"]})
px = yf.download(syms + ["SPY"], period="10y", interval="1mo", auto_adjust=True, progress=False)["Close"]
ret = px.pct_change().dropna(how="all")
spy = ret["SPY"]
down = spy < 0
print(f"{'basket':38}{'n':>4}{'CAGR*':>7}{'vol':>6}{'beta':>6}{'MDD':>6}{'down-capt':>10}{'worst yr':>9}")
for name, mask in BASKETS.items():
    s = [x for x in R.loc[mask, "symbol"] if x in ret]
    if len(s) < 3:
        print(f"{name:38}{len(s):>4}  too few")
        continue
    b = ret[s].mean(axis=1)
    idx = (1 + b).cumprod()
    mdd = (1 - idx / idx.cummax()).max()
    beta = np.cov(b, spy.reindex(b.index))[0, 1] / spy.var()
    dcap = b[down.reindex(b.index)].mean() / spy[down].mean()
    yr = (1 + b).rolling(12).apply(np.prod, raw=True).min() - 1
    print(f"{name:38}{len(s):>4}{(idx.iloc[-1] ** (12 / len(b)) - 1):>7.1%}{b.std() * 12 ** .5:>6.1%}{beta:>6.2f}{mdd:>6.0%}{dcap:>10.2f}{yr:>9.0%}")
i = (1 + spy).cumprod()
print(f"{'SPY':38}{'':>4}{(i.iloc[-1] ** (12 / len(spy)) - 1):>7.1%}{spy.std() * 12 ** .5:>6.1%}{1:>6.2f}{(1 - i / i.cummax()).max():>6.0%}{1:>10.2f}")
