"""Series statistics used throughout the VMI checks ("consistently increasing", CAGR, margins…)."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Sequence


@dataclass
class TrendStats:
    n: int
    first: float | None
    last: float | None
    cagr: float | None
    declines: int
    r2: float | None
    slope_positive: bool
    consistent: bool
    reason: str = ""

    def to_dict(self):
        return asdict(self)


def cagr(first: float, last: float, years: float) -> float | None:
    if years <= 0 or first is None or last is None or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _linfit(ys: Sequence[float]) -> tuple[float, float]:
    """Return (slope, r2) of a least squares line through ys vs index."""
    n = len(ys)
    xs = range(n)
    mx = (n - 1) / 2
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx if sxx else 0.0
    r2 = (sxy * sxy) / (sxx * syy) if sxx and syy else 0.0
    return slope, r2


def trend(values: Sequence[float], max_down_years: int = 2, min_years: int = 5,
          min_r2: float = 0.0, require_positive_last: bool = True) -> TrendStats:
    """VMI "consistently increasing": general uptrend over the window; 1–2 down years tolerated.

    Rules (Lesson 5 §4.3 / Step 1): last > first, positive regression slope, number of YoY declines
    ≤ max_down_years (scaled up for windows longer than 6 points), latest value positive.
    """
    vals = [float(v) for v in values if v is not None and not math.isnan(v)]
    n = len(vals)
    if n < 2:
        return TrendStats(n, None, None, None, 0, None, False, False, "insufficient history")
    first, last = vals[0], vals[-1]
    declines = sum(1 for a, b in zip(vals, vals[1:]) if b < a)
    use_log = all(v > 0 for v in vals)
    ys = [math.log(v) for v in vals] if use_log else vals
    slope, r2 = _linfit(ys)
    g = cagr(first, last, n - 1)
    allowed = max_down_years if n <= 6 else max_down_years + (n - 6) // 3
    reasons = []
    if n < min_years:
        reasons.append(f"only {n} years of data (<{min_years})")
    if last <= first:
        reasons.append("latest ≤ first (no uptrend)")
    if slope <= 0:
        reasons.append("negative trend slope")
    if declines > allowed:
        reasons.append(f"{declines} down years (>{allowed})")
    if require_positive_last and last <= 0:
        reasons.append("latest value not positive")
    if min_r2 and r2 < min_r2:
        reasons.append(f"choppy (r²={r2:.2f})")
    ok = not reasons
    return TrendStats(n, first, last, g, declines, round(r2, 3), slope > 0, ok, "; ".join(reasons) or "consistent uptrend")


def ratio_series(num: Sequence[float], den: Sequence[float]) -> list[float]:
    return [a / b for a, b in zip(num, den) if b not in (0, None) and a is not None]


def aligned(a: dict[str, float], b: dict[str, float]) -> tuple[list[float], list[float]]:
    keys = sorted(set(a) & set(b))
    return [a[k] for k in keys], [b[k] for k in keys]


def falling_streak(values: Sequence[float]) -> int:
    """Length of the current consecutive-decline streak ending at the latest value."""
    streak = 0
    for a, b in zip(reversed(values[:-1]), reversed(values[1:])):
        if b < a:
            streak += 1
        else:
            break
    return streak


def mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def stdev(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
