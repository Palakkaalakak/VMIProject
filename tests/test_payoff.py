"""Option payoff maths and the offline snapshot book."""
import math

import pytest

from vmi.options import payoff


def test_put_call_parity_and_iv_round_trip():
    s, k, t, iv, r = 100, 95, 0.5, 0.25, 0.04
    c, p = payoff.bs_price(s, k, t, iv, "C", r), payoff.bs_price(s, k, t, iv, "P", r)
    assert c - p == pytest.approx(s - k * math.exp(-r * t), abs=1e-6)
    assert payoff.implied_vol(p, s, k, t, "P", r) == pytest.approx(iv, abs=1e-4)
    assert payoff.bs_price(80, 95, 0, iv, "P") == 15            # expired = intrinsic


def test_short_put_profile_at_expiry():
    legs = [{"type": "OPT", "right": "P", "strike": 100, "expiry": "20270115", "qty": -1, "entry": 3.0, "iv": 0.3}]
    pr = payoff.profile(legs, 105, as_of="2026-11-11")
    assert pr["breakevens"] == [pytest.approx(97, abs=0.3)]
    assert pr["max_profit_in_range"] == pytest.approx(300)
    assert pr["unbounded_downside_risk"]
    g = pr["scenarios"]["grids"]["expiry"]
    moves = pr["scenarios"]["moves"]
    assert g[moves.index(0.0)][3] == pytest.approx(300)          # +5% spot at expiry: full premium kept
    assert g[0][3] < g[-1][3]                                   # crash hurts a short put
    today = pr["scenarios"]["grids"]["+0d"]
    assert today[moves.index(0.0)][0] > today[moves.index(0.0)][-1]   # IV up = short put loses


def test_covered_call_caps_upside():
    legs = [{"type": "STK", "qty": 100, "entry": 100},
            {"type": "OPT", "right": "C", "strike": 110, "expiry": "20270115", "qty": -1, "entry": 2.0, "iv": 0.3}]
    pr = payoff.profile(legs, 100, as_of="2026-11-11")
    assert pr["max_profit_in_range"] == pytest.approx(1200)
    assert not pr["unbounded_upside"]


def test_snapshot_recompute_is_offline(temp_db, monkeypatch):
    from vmi.options import book, chain

    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(chain, "option_quote", boom)
    sid = book.snapshot_legs("AAA", [{"right": "P", "strike": 100, "expiry": "20270115", "qty": -1, "entry": 3.0}],
                             spot=105, as_of="2026-11-11")
    base = book.get(sid)["result"]["pnl_now"]
    worse = book.recompute(sid, spot=90, iv_shift=0.1)["result"]["pnl_now"]
    assert worse < base
    assert book.list_snapshots(symbol="AAA")[0]["id"] == sid


def test_portfolio_snapshot_from_positions(temp_db, monkeypatch):
    from vmi.data import market
    from vmi.data.models import OptionQuote
    from vmi.options import book, chain
    from vmi.paper import engine

    monkeypatch.setattr(chain, "option_quote", lambda s, e, k, r: OptionQuote(s, e, k, r, bid=1.9, ask=2.1, iv=0.28))
    monkeypatch.setattr(market, "last_price", lambda s: 100.0)
    pid = engine.create_portfolio("P", "growth", cash=50_000)["id"]
    res = engine.trade_option(pid, "AAA", "20991219", 90, "P", "SELL", 2)
    assert res.get("snapshot_id")
    snap = book.get(res["snapshot_id"])
    leg = snap["inputs"]["legs"][0]
    assert leg["qty"] == -2 and leg["iv"] == 0.28 and snap["reason"] == "trade"
