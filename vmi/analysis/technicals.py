"""Technical analysis per Lesson 6 + Step 7: trend state, MA "personality", support levels,
parabolic moves, catching-bottom signals and 3–4 tranche buy levels.

Everything is computed from closed candles only ("never analyse an unclosed candle").
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from vmi.rules import RULES, TechnicalRules


# ------------------------------------------------------------------------------------ resampling
def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """'W' weekly / 'ME' monthly candles from daily OHLCV. Drops the still-forming last candle."""
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule).agg(agg).dropna(subset=["close"])
    if len(out) > 1:
        last_daily = df.index[-1]
        period_end = out.index[-1]
        if last_daily < period_end:  # current week/month not finished
            out = out.iloc[:-1]
    return out


def add_mas(df: pd.DataFrame, rules: TechnicalRules = RULES.technical) -> pd.DataFrame:
    df = df.copy()
    for p in rules.sma_periods:
        df[f"sma{p}"] = df["close"].rolling(p).mean()
    for p in rules.ema_periods:
        df[f"ema{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


def _slope(series: pd.Series, lookback: int) -> float | None:
    s = series.dropna()
    if len(s) <= lookback:
        return None
    prev = s.iloc[-lookback - 1]
    return float((s.iloc[-1] - prev) / prev) if prev else None


# ------------------------------------------------------------------------------------ swings & S/R
def swing_points(df: pd.DataFrame, window: int) -> tuple[list[tuple[pd.Timestamp, float]], list[tuple[pd.Timestamp, float]]]:
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(window, len(df) - window):
        if h[i] == max(h[i - window:i + window + 1]):
            highs.append((df.index[i], float(h[i])))
        if l[i] == min(l[i - window:i + window + 1]):
            lows.append((df.index[i], float(l[i])))
    return highs, lows


@dataclass
class Level:
    price: float
    kind: str            # "support" | "resistance" | "ma"
    source: str          # e.g. "daily swing lows", "weekly sma50", "polarity (old resistance)"
    touches: int = 0
    confirmed: bool = False
    timeframe: str = "daily"

    def to_dict(self):
        return asdict(self)


def cluster_levels(points: list[float], tol: float) -> list[tuple[float, int]]:
    """Group prices within `tol` (relative) → (mean price, touches). Line of best fit = most touches."""
    clusters: list[list[float]] = []
    for p in sorted(points):
        if clusters and abs(p - np.mean(clusters[-1])) / np.mean(clusters[-1]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [(float(np.mean(c)), len(c)) for c in clusters]


def horizontal_levels(df: pd.DataFrame, timeframe: str, rules: TechnicalRules = RULES.technical) -> list[Level]:
    if len(df) < rules.swing_window * 3:
        return []
    highs, lows = swing_points(df, rules.swing_window)
    price = float(df["close"].iloc[-1])
    levels: list[Level] = []
    for p, n in cluster_levels([x for _, x in lows], rules.support_tolerance):
        if n >= rules.min_touches_potential:
            levels.append(Level(p, "support" if p < price else "resistance", f"{timeframe} swing lows", n,
                                n >= rules.min_touches_confirmed, timeframe))
    for p, n in cluster_levels([x for _, x in highs], rules.support_tolerance):
        if n >= rules.min_touches_potential:
            # Polarity rule: broken resistance (now below price) becomes support
            kind = "support" if p < price else "resistance"
            src = f"{timeframe} swing highs" + (" (polarity: old resistance)" if kind == "support" else "")
            levels.append(Level(p, kind, src, n, n >= rules.min_touches_confirmed, timeframe))
    # single significant swing highs below price are also candidate supports (Step 7 examples)
    return levels


def ma_bounces(df: pd.DataFrame, col: str, tol: float = 0.015, lookback: int = 750) -> int:
    """How many times price dipped into an MA (low within tol) and closed back above it — the
    stock's MA 'personality' (Lesson 6 §6.7)."""
    d = df.dropna(subset=[col]).iloc[-lookback:]
    if d.empty:
        return 0
    touches = (d["low"] <= d[col] * (1 + tol)) & (d["close"] >= d[col])
    above_before = d["close"].shift(5) > d[col].shift(5) * (1 + tol)
    events = touches & above_before
    # de-duplicate events within 10 bars
    count, last = 0, -999
    for i, flag in enumerate(events.values):
        if flag and i - last > 10:
            count += 1
            last = i
    return count


# ------------------------------------------------------------------------------------ trend
@dataclass
class TrendState:
    state: str                    # uptrend | downtrend | consolidation | unknown
    price: float
    mas: dict[str, float | None]
    slopes: dict[str, float | None]
    stacked_up: bool
    stacked_down: bool
    higher_highs_lows: bool
    lower_highs_lows: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def trend_state(df: pd.DataFrame, rules: TechnicalRules = RULES.technical) -> TrendState:
    if df.empty:
        return TrendState("unknown", 0.0, {}, {}, False, False, False, False, ["no data"])
    d = add_mas(df, rules)
    last = d.iloc[-1]
    price = float(last["close"])
    mas = {k: (float(last[k]) if pd.notna(last[k]) else None) for k in d.columns if k.startswith(("sma", "ema"))}
    slopes = {k: _slope(d[k], rules.trend_slope_lookback) for k in mas}
    s50, s100, s150, s200 = (mas.get(f"sma{p}") for p in (50, 100, 150, 200))
    if s200 is None and mas.get("ema20") is not None and mas.get("ema40") is not None and len(d) >= 60:
        # Higher timeframes (monthly) rarely have 200 bars: use the 20/40 EMA pair (Lesson 6 §6.4)
        fast, slow = mas["ema20"], mas["ema40"]
        fs, ss = slopes.get("ema20") or 0, slopes.get("ema40") or 0
        st = ("uptrend" if fast > slow and fs > 0 and ss > 0 and price > slow else
              "downtrend" if fast < slow and fs < 0 and price < slow else "consolidation")
        return TrendState(st, price, mas, slopes, fast > slow, fast < slow, False, False,
                          ["trend from 20/40 EMA (insufficient bars for 200 SMA)"])
    stacked_up = all(v is not None for v in (s50, s100, s150, s200)) and s50 > s100 > s150 > s200
    stacked_down = all(v is not None for v in (s50, s150, s200)) and s200 > s150 > s50
    highs, lows = swing_points(d.iloc[-260:], rules.swing_window)
    hh = len(highs) >= 2 and highs[-1][1] > highs[-2][1]
    hl = len(lows) >= 2 and lows[-1][1] > lows[-2][1]
    lh = len(highs) >= 2 and highs[-1][1] < highs[-2][1]
    ll = len(lows) >= 2 and lows[-1][1] < lows[-2][1]
    up_slopes = all((slopes.get(f"sma{p}") or 0) > 0 for p in (50, 150, 200))
    down_slopes = all((slopes.get(f"sma{p}") or 0) < 0 for p in (50, 150))
    notes = []
    if s50 and s150 and s200 and s50 > s150 and up_slopes and price > s200:
        state = "uptrend"
    elif s50 and s150 and s200 and s50 < s150 and down_slopes and price < s200:
        state = "downtrend"
    elif s50 is None or s200 is None:
        state = "unknown"
        notes.append("not enough history for 200 SMA")
    else:
        state = "consolidation"
    if state == "downtrend" and s50 and price > s50 and abs(slopes.get("sma50") or 0) < 0.01 and hh and hl:
        notes.append("pre-emptive reversal: higher highs/lows + price above flattening 50 SMA")
    return TrendState(state, price, mas, slopes, stacked_up, stacked_down, hh and hl, lh and ll, notes)


# ------------------------------------------------------------------------------------ patterns
def parabolic_up(df: pd.DataFrame, rules: TechnicalRules = RULES.technical) -> bool:
    d = add_mas(df, rules)
    s50 = d["sma50"].iloc[-1]
    if pd.isna(s50):
        return False
    return float(d["close"].iloc[-1]) > s50 * (1 + rules.parabolic_dist_from_50)


def parabolic_drop(df: pd.DataFrame, rules: TechnicalRules = RULES.technical, bars: int = 10) -> dict[str, Any]:
    """'90-degree drop' with longer-than-usual red candles (capitulation)."""
    if len(df) < 60:
        return {"active": False}
    recent = df.iloc[-bars:]
    peak = float(recent["high"].max())
    last = float(df["close"].iloc[-1])
    drop = (peak - last) / peak if peak else 0
    body = (df["open"] - df["close"]).clip(lower=0)
    typical = float(body.iloc[-60:-bars].mean() or 0)
    big_red = int((body.iloc[-bars:] > 1.8 * typical).sum()) if typical else 0
    last_c = df.iloc[-1]
    rng = float(last_c["high"] - last_c["low"]) or 1e-9
    lower_tail = float(min(last_c["open"], last_c["close"]) - last_c["low"])
    bullish_pin = lower_tail / rng >= 0.6
    big_green = float(last_c["close"] - last_c["open"]) > 1.5 * typical if typical else False
    return {"active": drop >= rules.parabolic_drop_pct and big_red >= 2, "drop_pct": round(drop, 4),
            "big_red_candles": big_red, "confirmation": bool(bullish_pin or big_green),
            "bullish_pin_bar": bool(bullish_pin)}


def double_bottom(df: pd.DataFrame, rules: TechnicalRules = RULES.technical, lookback: int = 80) -> dict[str, Any]:
    """Lesson 6 §10.4: 2nd low undercuts 1st swing low, then a bullish close back above it within 3 bars."""
    d = df.iloc[-lookback:]
    if len(d) < 20:
        return {"active": False}
    _, lows = swing_points(d.iloc[:-3], 3)
    if not lows:
        return {"active": False}
    first_date, first_low = lows[-1]
    after = d.loc[d.index > first_date]
    if after.empty:
        return {"active": False}
    broke = after[after["low"] < first_low]
    if broke.empty:
        return {"active": False}
    bidx = d.index.get_loc(broke.index[0])
    window = d.iloc[bidx: bidx + rules.double_bottom_reclaim_bars + 1]
    reclaim = window[(window["close"] > first_low) & (window["close"] > window["open"])]
    recent = len(d) - bidx <= 15
    return {"active": bool(not reclaim.empty and recent), "first_low": first_low,
            "undercut_low": float(broke["low"].min()),
            "reclaim_date": str(reclaim.index[0].date()) if not reclaim.empty else None}


# ------------------------------------------------------------------------------------ main entry
@dataclass
class TechnicalReport:
    price: float
    daily: TrendState
    weekly: TrendState
    monthly: TrendState
    ten_year_uptrend: bool | None
    ten_year_return: float | None
    personality: dict[str, int]
    preferred_ma: str | None
    levels: list[Level]
    buy_levels: list[dict]
    scenario: str
    signals: dict[str, Any]
    entry_ok: bool
    entry_reason: str

    def to_dict(self):
        d = asdict(self)
        return d


def analyse(df: pd.DataFrame, intrinsic_value: float | None = None,
            rules: TechnicalRules = RULES.technical) -> TechnicalReport:
    df = df.dropna(subset=["close"])
    price = float(df["close"].iloc[-1]) if not df.empty else 0.0
    weekly, monthly = resample(df, "W-FRI"), resample(df, "ME")
    td, tw, tm = trend_state(df, rules), trend_state(weekly, rules), trend_state(monthly, rules)

    # 10-year monthly filter (Lesson 6 §3.3): one clear long-term uptrend
    ten_up, ten_ret = None, None
    if len(monthly) >= 60:
        m = monthly["close"]
        ten_ret = float(m.iloc[-1] / m.iloc[0] - 1)
        logp = np.log(m.values)
        slope = np.polyfit(np.arange(len(logp)), logp, 1)[0]
        ten_up = bool(slope > 0 and ten_ret > 0.5)

    # MA personality on each timeframe (daily → SMAs only; weekly/monthly → EMAs too)
    dd, wd, md = add_mas(df, rules), add_mas(weekly, rules), add_mas(monthly, rules)
    personality: dict[str, int] = {}
    for p in rules.sma_periods:
        personality[f"daily sma{p}"] = ma_bounces(dd, f"sma{p}")
        personality[f"weekly sma{p}"] = ma_bounces(wd, f"sma{p}", lookback=260)
    for p in rules.ema_periods:
        personality[f"weekly ema{p}"] = ma_bounces(wd, f"ema{p}", lookback=260)
        personality[f"monthly ema{p}"] = ma_bounces(md, f"ema{p}", lookback=120)
    personality["monthly sma50"] = ma_bounces(md, "sma50", lookback=120)
    preferred = max(personality, key=personality.get) if any(personality.values()) else None

    # Support levels: MAs below price + horizontal S/R on daily & weekly (+ monthly)
    levels: list[Level] = []
    for tf, frame, cols in (("daily", dd, [f"sma{p}" for p in rules.sma_periods]),
                            ("weekly", wd, [f"sma{p}" for p in rules.sma_periods] + [f"ema{p}" for p in rules.ema_periods]),
                            ("monthly", md, [f"ema{p}" for p in rules.ema_periods] + ["sma50"])):
        if frame.empty:
            continue
        for c in cols:
            v = frame[c].iloc[-1] if c in frame else np.nan
            if pd.notna(v) and v < price:
                levels.append(Level(float(v), "ma", f"{tf} {c}", personality.get(f"{tf} {c}", 0),
                                    personality.get(f"{tf} {c}", 0) >= 2, tf))
    levels += horizontal_levels(df.iloc[-260:], "daily", rules)
    levels += horizontal_levels(weekly.iloc[-260:], "weekly", rules)
    levels += horizontal_levels(monthly.iloc[-120:], "monthly", rules)

    supports = [l for l in levels if l.price < price * (1 + rules.near_level_pct) and l.kind in ("support", "ma")]
    buy_levels = pick_buy_levels(supports, price, intrinsic_value, td.state, rules)

    pdrop = parabolic_drop(df, rules)
    dbl = double_bottom(df, rules)
    para_up = parabolic_up(df, rules)
    near = [b for b in buy_levels if abs(price - b["price"]) / b["price"] <= rules.near_level_pct]
    hi_tf_support = any(b["timeframe"] in ("weekly", "monthly") for b in near)

    # Step 7 scenario & entry decision
    scenario, ok, reason = "", False, ""
    if para_up:
        scenario, ok, reason = "parabolic", False, "Parabolic move — worst time to buy (good time for covered calls)"
    elif td.state == "uptrend":
        scenario = "A: dip on uptrend"
        ok = bool(near)
        reason = "Wave-down into support/MA" if ok else "Uptrend — wait for wave down into a support/MA"
    elif td.state == "consolidation":
        scenario = "B: consolidation support"
        horiz = [b for b in near if "swing" in b["source"]]
        ok = bool(horiz)
        reason = "At channel support" if ok else "Consolidation — buy only near drawn horizontal support (MAs ignored)"
    elif td.state == "downtrend":
        scenario = "C: downtrend"
        if dbl.get("active"):
            ok, reason = True, "Double bottom completed (bear trap) — buy trigger"
        elif pdrop.get("active") and hi_tf_support:
            ok, reason = True, "Parabolic drop into higher-timeframe support (potential bottom)"
            if not pdrop.get("confirmation"):
                reason += " — conservative: wait for bullish pin bar / big green candle"
        elif any("pre-emptive" in n for n in td.notes):
            ok, reason = True, "Pre-emptive reversal entry (higher highs/lows above flattening 50 SMA)"
        else:
            reason = "Downtrend — wait for bottom signal or uptrend confirmation; never buy after a wave up"
    else:
        scenario, reason = "unknown", "insufficient price history"
    return TechnicalReport(price, td, tw, tm, ten_up, ten_ret, personality, preferred, levels, buy_levels,
                           scenario, {"parabolic_up": para_up, "parabolic_drop": pdrop, "double_bottom": dbl,
                                      "near_buy_level": bool(near)}, ok, reason)


def pick_buy_levels(supports: list[Level], price: float, iv: float | None, state: str,
                    rules: TechnicalRules = RULES.technical) -> list[dict]:
    """3–4 distinct buy levels at/below price, below intrinsic value, preferring confirmed levels and
    the stock's preferred MAs. In consolidation, MAs are excluded (they are useless sideways)."""
    cands = [l for l in supports if l.price > 0]
    if state == "consolidation":
        cands = [l for l in cands if l.kind != "ma"] or cands
    if iv:
        cands = [l for l in cands if l.price <= iv] or []
    # Score: confirmation, touches, higher timeframe weight
    tf_w = {"daily": 1.0, "weekly": 1.3, "monthly": 1.6}

    def score(l: Level) -> float:
        return (l.touches + (2 if l.confirmed else 0)) * tf_w.get(l.timeframe, 1.0)

    cands.sort(key=lambda l: -l.price)
    chosen: list[Level] = []
    for l in sorted(cands, key=score, reverse=True):
        if all(abs(l.price - c.price) / c.price > 0.03 for c in chosen):
            chosen.append(l)
        if len(chosen) >= rules.n_buy_levels:
            break
    chosen.sort(key=lambda l: -l.price)
    n = len(chosen)
    return [{"tranche": i + 1, "price": round(l.price, 2), "source": l.source, "timeframe": l.timeframe,
             "touches": l.touches, "confirmed": l.confirmed, "fraction": round(1 / n, 4) if n else 0}
            for i, l in enumerate(chosen)]


# ------------------------------------------------------------------------------------ fast screen
def quick_screen(df: pd.DataFrame) -> dict[str, Any]:
    """Vectorised cheap metrics for the scanner's technical pass (no swing detection)."""
    if df is None or len(df) < 30:
        return {"ok": False}
    c = df["close"]
    price = float(c.iloc[-1])
    s200 = c.rolling(200).mean()
    s50 = c.rolling(50).mean()
    s150 = c.rolling(150).mean()
    out = {"ok": True, "price": price,
           "above_200": bool(pd.notna(s200.iloc[-1]) and price > s200.iloc[-1]),
           "sma200_slope": _slope(s200, 20), "sma50": float(s50.iloc[-1]) if pd.notna(s50.iloc[-1]) else None,
           "sma150": float(s150.iloc[-1]) if pd.notna(s150.iloc[-1]) else None,
           "sma200": float(s200.iloc[-1]) if pd.notna(s200.iloc[-1]) else None,
           "dist_50": float(price / s50.iloc[-1] - 1) if pd.notna(s50.iloc[-1]) else None,
           "ret_1y": float(price / c.iloc[-252] - 1) if len(c) > 252 else None,
           "drawdown_52w": float(price / df["high"].iloc[-252:].max() - 1),
           "avg_dollar_volume": float((c * df["volume"]).iloc[-50:].mean())}
    return out
