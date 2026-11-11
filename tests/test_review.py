"""Review + what-if engine on a synthetic price path (no network)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from vmi.paper import engine, ledger, review


def path(symbol):
    days = pd.bdate_range(date.today() - timedelta(days=600), date.today())
    px = pd.Series([100 + 100 * i / (len(days) - 1) for i in range(len(days))], index=days)   # 100 → 200 straight
    return pd.DataFrame({"open": px, "high": px * 1.01, "low": px * 0.99, "close": px})


def iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat() + "T15:00:00+00:00"


@pytest.fixture
def pid(temp_db):
    pid = engine.create_portfolio("R", "growth", cash=100_000)["id"]
    df = path("AAA")

    def px(days_ago):
        return float(df["close"].loc[:pd.Timestamp(date.today() - timedelta(days=days_ago))].iloc[-1])

    ctx = {"analysis": {"intrinsic_value": 120.0, "metrics": {"margin_of_safety": 0.1}, "category": "growth",
                        "moat": "wide"}}
    ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 10, "price": px(590), "ts": iso(590),
                           "context": ctx, "tags": "core"}, reason="test")
    ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 10, "price": px(560), "ts": iso(560),
                           "context": ctx}, reason="test")
    ledger.add_trade(pid, {"symbol": "AAA", "side": "SELL", "qty": 15, "price": px(400), "ts": iso(400)}, reason="test")
    return pid


def test_fifo_lots_split_partial_exit(pid):
    ls = review.lots(pid)
    closed = [l for l in ls if l.closed]
    assert [l.qty for l in closed] == [10, 5] and [l.qty for l in ls if not l.closed] == [5]
    assert closed[0].entry["intrinsic_value"] == 120 and closed[0].entry["tags"] == ["core"]


def test_summary_flags_selling_too_early(pid):
    s = review.summary(pid, history_fn=path)
    assert s["stocks"]["closed"] == 2 and s["stocks"]["win_rate"] == 1.0
    assert s["flags"]["sold_too_early"]
    assert s["breakdowns"]["moat"]["wide"]["lots"] == 3


def test_hold_instead_beats_selling_in_an_uptrend(pid):
    r = review.what_if(pid, "hold_instead", history_fn=path)
    assert r["difference"] > 0


def test_exit_over_iv_and_tranches(pid):
    one = review.what_if(pid, "exit_over_iv", history_fn=path, pct=0.5)
    assert all(abs(x["alt_exit_price"] - 180) < 1 for x in one["lots"])          # first close >= 120 × 1.5
    tr = review.what_if(pid, "exit_tranches", history_fn=path, levels=[[0.5, 0.5], [0.6, 0.5]])
    assert tr["alternative_pnl"] > one["alternative_pnl"]                          # second half sold higher (192)


def test_entry_covered_calls_benchmark_and_curve(pid):
    e = review.what_if(pid, "entry_all_at_once", history_fn=path)
    assert e["lots"][0]["tranches"] == 3                    # FIFO lots per symbol (10, 5 closed + 5 open)
    cc = review.what_if(pid, "covered_calls", history_fn=path, otm=0.05, dte=30, iv=0.25)
    assert cc["lots"] and all(r["cycles"] for r in cc["lots"])
    b = review.what_if(pid, "benchmark", history_fn=path, symbol="SPY")
    assert b["difference"] == pytest.approx(0, abs=1e-6)      # same path as the stock
    curve = review.equity_curve(pid, history_fn=path)
    assert curve["points"] and curve["source"].startswith("ledger replay")


def test_unknown_what_if(pid):
    with pytest.raises(ValueError):
        review.what_if(pid, "nope")
