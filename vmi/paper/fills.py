"""Paper-trading fill model (owner spec): instant fill at mid + flat realistic slippage; if illiquid,
fill at mid shifted toward the touch ("mid debuff"). Nothing else (no commissions, no partial fills).

Research basis for defaults (vmi.rules.ExecutionRules):
  * US equities: typical retail slippage 5–20 bps per trade; liquid large caps at the low end → 5 bps.
  * Options: retail fills usually land between mid and the touch; $0.01/share flat ($1/contract).
  * Illiquid: stock spread > 0.5% of mid or avg volume < 200k sh; option spread > 10% of mid →
    fill at mid ± 50% of the half-spread (buyer pays more, seller receives less), plus the flat slippage.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from vmi.data import market_hours
from vmi.data.models import Quote
from vmi.rules import RULES, ExecutionRules


@dataclass
class Fill:
    price: float          # per share (per option share for options)
    mid: float
    slippage_per_share: float
    liquidity: str        # liquid | illiquid | no_quote
    spread_pct: float | None
    basis: str = "book"   # what the mid was taken from: book | last | last (extended session) …

    def to_dict(self):
        return asdict(self)


def _mid(bid: float | None, ask: float | None, last: float | None) -> tuple[float | None, float | None]:
    if bid and ask and bid > 0 and ask >= bid:
        return (bid + ask) / 2, (ask - bid)
    return (last, None) if last else (None, None)


def stock_fill(side: str, quote: Quote, rules: ExecutionRules = RULES.execution) -> Fill:
    """Fill a stock order against a quote.

    The bid/ask is only used when `quote.book_trusted` (real-time NBBO source, regular session). Otherwise —
    Yahoo quotes, pre/after-hours, closed market — the reference is the last trade, the spread is the synthetic
    `no_quote_spread_pct`, and liquidity is judged on average volume alone (no false "illiquid" megacaps).
    """
    book_ok = quote.book_trusted
    if book_ok:
        mid, spread, basis = (quote.bid + quote.ask) / 2, quote.ask - quote.bid, "book"
    else:
        mid = quote.last or quote.close
        spread = mid * rules.no_quote_spread_pct if mid else None
        basis = f"last ({quote.source or 'unknown'}, {quote.session} session)"
    if not mid:
        raise ValueError("no price available")
    spread_pct = spread / mid
    thin_volume = quote.avg_volume is not None and quote.avg_volume < rules.illiquid_min_volume
    wide_book = book_ok and spread_pct > rules.illiquid_spread_pct
    illiquid = thin_volume or wide_book
    debuff = rules.illiquid_debuff_frac * spread / 2 if illiquid else 0.0
    slip = mid * rules.stock_slippage_bps / 10_000
    sign = 1 if side.upper() == "BUY" else -1
    liquidity = "illiquid" if illiquid else "liquid" if book_ok else "no_quote"
    return Fill(round(mid + sign * (slip + debuff), 4), mid, round(slip + debuff, 6), liquidity,
                round(spread_pct, 6), basis)


def option_fill(side: str, bid: float | None, ask: float | None, last: float | None,
                rules: ExecutionRules = RULES.execution) -> Fill:
    mid, spread = _mid(bid, ask, last)
    if mid is None:
        raise ValueError("no option price available")
    sign = 1 if side.upper() == "BUY" else -1
    liquidity, debuff = "liquid", 0.0
    spread_pct = (spread / mid) if spread and mid else None
    if spread is None:
        liquidity = "no_quote"
    elif spread_pct is not None and spread_pct > rules.illiquid_option_spread_pct:
        liquidity = "illiquid"
        debuff = rules.illiquid_debuff_frac * spread / 2
    slip = rules.option_slippage_per_share
    price = max(0.01, mid + sign * (slip + debuff))
    return Fill(round(price, 4), mid, round(slip + debuff, 6), liquidity,
                round(spread_pct, 6) if spread_pct is not None else None)
