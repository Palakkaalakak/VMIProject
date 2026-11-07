"""Growth-sleeve candidates as REAL monthly return series. Only point-in-time information is used (price trend,
published factor returns), so no look-ahead. Tilts are gross factor exposures minus an assumed implementation cost.

What these stand for in the VMI scanner (a stock screen cannot be back-tested point-in-time with the data we have):
  quality  ← VMI steps 1/4/5 (profitability, consistent growth, low debt)      momentum ← step 7 / 10y-uptrend filter
  trend    ← Adam's 50/150-day MA rule, applied monthly to the whole sleeve     lowbeta  ← defensive large caps
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vmi.research import data

TILT_COST = 0.005 / 12        # 0.5%/yr for factor tilts (turnover, shorting-free capture haircut)
SWITCH_COST = 0.001           # 0.1% per trend switch


def trend_signal(nominal: pd.Series, months: int = 10) -> pd.Series:
    """True for month t+1 when the total-return index at the end of month t is above its `months`-month average."""
    idx = (1 + nominal).cumprod()
    return (idx > idx.rolling(months).mean()).shift(1).fillna(False).astype(bool)


def with_trend(nominal: pd.Series, rf: pd.Series, signal: pd.Series) -> pd.Series:
    out = nominal.where(signal, rf)
    switches = signal.astype(int).diff().abs().fillna(0)
    return out - switches * SWITCH_COST


def strategies(df: pd.DataFrame, factors: bool = True) -> pd.DataFrame:
    """Nominal strategy returns → real. factors=False keeps only market/trend (usable from 1926)."""
    sig = trend_signal(df["mkt"])
    nom = {"market": df["mkt"], "trend": with_trend(df["mkt"], df["rf"], sig)}
    if factors:
        quality = df["mkt"] + 0.5 * df["rmw"] + 0.5 * df["cma"] - TILT_COST
        mom = df["mkt"] + 0.5 * df["mom"] - TILT_COST
        qm = df["mkt"] + 0.5 * (df["rmw"] + df["cma"] + df["mom"]) - 1.5 * TILT_COST
        nom.update({"quality": quality, "momentum": mom, "quality_momentum": qm,
                    "quality_momentum_trend": with_trend(qm, df["rf"], sig),
                    "lowbeta": df["beta_lo"], "lowbeta_trend": with_trend(df["beta_lo"], df["rf"], trend_signal(df["beta_lo"]))})
    out = pd.DataFrame({k: data.real(v, df["infl"]) for k, v in nom.items()})
    return out


def decay(real: pd.DataFrame, keep: float = 0.5) -> pd.DataFrame:
    """Out-of-sample decay: where a strategy beat the market on average, keep only `keep` of that average excess
    (a constant monthly drag; volatility and timing stay as they were). Published factor premia shrink after discovery."""
    out = real.copy()
    for c in real.columns:
        if c == "market":
            continue
        excess = (real[c] - real["market"]).mean()
        if excess > 0:
            out[c] = real[c] - (1 - keep) * excess
    return out
