"""Paper-trading fills, sizing and market session logic."""
from datetime import datetime

import pytest

from vmi.data import market_hours
from vmi.data.models import Quote
from vmi.paper.fills import option_fill, stock_fill
from vmi.paper.sizing import option_contracts_for_csp, plan


def test_yahoo_book_is_never_trusted():
    f = stock_fill("BUY", Quote("MSFT", last=516, bid=505, ask=525, avg_volume=2e7, source="yahoo"))
    assert f.liquidity == "no_quote" and f.mid == 516
    assert f.price == pytest.approx(516 * 1.0005)                   # mid + 5 bps


def test_ib_regular_session_uses_book():
    f = stock_fill("SELL", Quote("AAPL", last=348, bid=347.98, ask=348.02, avg_volume=5e7, source="ib"))
    assert f.liquidity == "liquid" and f.basis == "book" and f.price < f.mid


def test_ib_wide_spread_is_illiquid_with_debuff():
    f = stock_fill("BUY", Quote("X", last=10, bid=9.8, ask=10.2, avg_volume=1e6, source="ib"))
    assert f.liquidity == "illiquid"
    assert f.price == pytest.approx(10 + 10 * 0.0005 + 0.5 * 0.4 / 2)


def test_ib_extended_session_ignores_book():
    q = Quote("X", last=100, bid=95, ask=105, avg_volume=1e6, source="ib", session=market_hours.EXTENDED)
    assert stock_fill("BUY", q).liquidity == "no_quote"


def test_thin_volume_is_illiquid():
    assert stock_fill("BUY", Quote("TINY", last=10, avg_volume=5e4, source="yahoo")).liquidity == "illiquid"


def test_no_price_raises():
    with pytest.raises(ValueError):
        stock_fill("BUY", Quote("NONE"))


def test_option_fill_slippage():
    f = option_fill("SELL", 2.45, 2.55, None)
    assert f.mid == pytest.approx(2.50) and f.price == pytest.approx(2.49)


def test_sizing_equal_weight_tranches():
    p = plan(100_000, 100, target_positions=20)
    assert p.full_allocation == 5000 and p.tranche_value == 1250 and p.shares_next_tranche == 12


def test_sizing_speculative_half_and_full_stop():
    assert plan(100_000, 100, target_positions=20, multiplier=0.5).full_allocation == 2500
    full = plan(100_000, 100, target_positions=20, current_value=5000)
    assert full.remaining_value == 0 and "full allocation" in full.warning


def test_csp_contracts():
    assert option_contracts_for_csp(100_000, 330) == 3


@pytest.mark.parametrize("ts,expected", [
    ("2026-11-04 10:00", market_hours.REGULAR), ("2026-11-04 17:00", market_hours.EXTENDED),
    ("2026-11-04 22:00", market_hours.CLOSED), ("2026-11-07 12:00", market_hours.CLOSED),   # Saturday
])
def test_market_session(ts, expected):
    assert market_hours.session_now(datetime.fromisoformat(ts).replace(tzinfo=market_hours.ET)) == expected
