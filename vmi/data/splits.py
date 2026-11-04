"""Stock-split adjustment of per-share history (single place; applied in fundamentals.resolve).

Why: XBRL keeps the as-filed values of periods before a split until a later filing restates them, so the
annual series can mix pre- and post-split units (BKNG 25:1 on 2026-04-06: 32.6M "shares" and $165 EPS vs a
~$160 price → P/E ≈ 1). Some periods may already be restated, so blind adjustment would double-count.

Approach (self-checking, per point):
  * shares: a point dated before a split is multiplied by the cumulative factor k only if that moves it
    closer (log distance) to the post-split share count reference.
  * per-share (eps_diluted, dps): divided by k only if the adjusted shares say this period was unadjusted
    (i.e. the shares point itself needed adjustment), or — when shares are missing — if eps/k × shares_ref
    is closer to net income than eps × shares_ref.
"""
from __future__ import annotations

import logging
import math
from datetime import date

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

log = logging.getLogger(__name__)

SHARE_SERIES = ("shares_diluted", "shares_outstanding")
PER_SHARE_SERIES = ("eps_diluted", "dps")


def history(ticker: str) -> list[tuple[str, float]]:
    """[(ISO date, ratio)] e.g. [("2026-04-06", 25.0)] — ratio > 1 is a forward split. Cached daily."""
    def fetch():
        import yfinance as yf
        s = yf.Ticker(ticker.replace(".", "-")).splits
        return [(d.date().isoformat(), float(r)) for d, r in s.items() if r and r > 0 and r != 1]
    try:
        return get_cache().get_or_set(f"splits:{ticker.upper()}", get_settings().ttl_universe, fetch) or []
    except Exception as exc:          # splits are an enhancement; never block fundamentals
        log.info("split history unavailable for %s: %s", ticker, exc)
        return []


def factor_after(end: str, splits: list[tuple[str, float]]) -> float:
    """Cumulative split factor for splits strictly after period end `end`."""
    k = 1.0
    for d, r in splits:
        if d > end:
            k *= r
    return k


def _closer(a: float, b: float, ref: float) -> bool:
    """True if a is closer than b to ref in log space (all positive)."""
    return abs(math.log(a / ref)) < abs(math.log(b / ref))


def adjust(f: Fundamentals, splits: list[tuple[str, float]]) -> list[str]:
    """Adjust f in place. Returns a list of human-readable notes (empty if nothing changed)."""
    recent = [(d, r) for d, r in splits if d >= f"{date.today().year - 12}-01-01"]
    if not recent:
        return []
    ref = f.latest.get("shares_outstanding")
    notes: list[str] = []
    adjusted_periods: set[str] = set()
    for c in SHARE_SERIES:
        pts = f.annual.get(c, [])
        r = ref or (pts[-1].value if pts else None)
        if not r or r <= 0:
            continue
        new = []
        for p in pts:
            k = factor_after(p.end, recent)
            if k != 1 and p.value > 0 and _closer(p.value * k, p.value, r):
                new.append(Point(p.end, p.value * k, p.fy))
                adjusted_periods.add(p.end)
            else:
                new.append(p)
        f.annual[c] = new
    ni = {p.end: p.value for p in f.annual.get("net_income", [])}
    sh = {p.end: p.value for p in f.annual.get("shares_diluted", [])}
    for c in PER_SHARE_SERIES:
        new = []
        for p in f.annual.get(c, []):
            k = factor_after(p.end, recent)
            if k == 1 or p.value == 0:
                new.append(p)
                continue
            if p.end in adjusted_periods:
                fix = True
            elif c == "eps_diluted" and ni.get(p.end) and sh.get(p.end) and ni[p.end] > 0 and p.value > 0:
                fix = _closer(p.value / k * sh[p.end], p.value * sh[p.end], ni[p.end])
            else:
                fix = False
            new.append(Point(p.end, p.value / k, p.fy) if fix else p)
        f.annual[c] = new
    if adjusted_periods:
        notes.append(f"split-adjusted {len(adjusted_periods)} period(s) for splits "
                     + ", ".join(f"{r:g}:1 on {d}" for d, r in recent))
    if adjusted_periods:
        # quarterly per-share/share series can carry the same mixed units; drop them so nothing reads stale
        # units (valuation falls back to the adjusted annual series / price-implied share count)
        for c in (*SHARE_SERIES, *PER_SHARE_SERIES):
            if any(factor_after(p.end, recent) != 1 for p in f.quarterly.get(c, [])):
                f.quarterly.pop(c, None)
    return notes
