"""Tranche plans: sizing modes, live auto-fill vs alert-only, backfill of levels hit while offline."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from vmi import store
from vmi.data.models import Quote
from vmi.paper import autotrade, engine, ledger


def quote(px):
    return lambda sym: Quote(sym, last=px, avg_volume=1e7, source="yahoo")


def no_history(sym):
    return pd.DataFrame()


@pytest.fixture
def pid(temp_db, monkeypatch):
    from vmi.data import market
    monkeypatch.setattr(market, "last_price", lambda s: 100.0)
    return engine.create_portfolio("A", "growth", cash=100_000, target_positions=10)["id"]


def _trades(pid):
    return engine.trades(pid)


def test_sizing_modes(pid, temp_db):
    with store.session() as s:
        w = store.Watchlist(name="Growth")
        s.add(w)
        s.flush()
        for sym in ("A", "B", "C", "D"):
            s.add(store.WatchItem(watchlist_id=w.id, symbol=sym, supports=[]))
        s.commit()
        wid = w.id
    assert autotrade.full_allocation(pid, 100_000)["full"] == pytest.approx(10_000)        # target: 10 positions
    autotrade.update_settings(pid, {"watchlist_id": wid})
    assert autotrade.full_allocation(pid, 100_000)["full"] == pytest.approx(25_000)        # default: watchlist size
    autotrade.update_settings(pid, {"sizing_mode": "manual", "manual_allocation": 5_000})
    assert autotrade.full_allocation(pid, 100_000)["full"] == pytest.approx(5_000)
    plan = autotrade.upsert_plan(pid, "AAA", buy_levels=[90], allocation=8_000, multiplier=0.5)
    with store.session() as s:
        assert autotrade.full_allocation(pid, 1, s.get(store.TranchePlan, plan["id"]))["full"] == 4_000


def test_alert_only_by_default(pid):
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95}, {"price": 85}], intrinsic_value=120)
    ev = autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: True)
    assert [e["event"] for e in ev] == ["level_alert"] and not _trades(pid)
    assert autotrade.get_plans(pid)[0]["buy_levels"][0]["status"] == "alerted"


def test_auto_fill_respects_iv_hours_and_allocation(pid):
    autotrade.update_settings(pid, {"auto_trade": True})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.5}, {"price": 85, "fraction": 0.5}],
                          intrinsic_value=120)
    ev = autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: False)
    assert not _trades(pid) and ev[0]["why"] == "outside regular hours"
    ev = autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: True)
    t = _trades(pid)
    assert len(t) == 1 and t[0]["source"] == "auto"
    assert t[0]["qty"] * t[0]["price"] == pytest.approx(5_000, rel=1e-3)                    # half of 10k
    assert t[0]["context"]["plan"]["allocation"]["full"] == pytest.approx(10_000)
    autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: True)  # fires once
    assert len(_trades(pid)) == 1


def test_not_below_iv_is_not_bought(pid):
    autotrade.update_settings(pid, {"auto_trade": True})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[95], intrinsic_value=90)
    autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: True)
    assert not _trades(pid)


def test_backfill_while_offline_and_gap_down(pid):
    autotrade.update_settings(pid, {"auto_trade": True})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.5}, {"price": 85, "fraction": 0.5}],
                          intrinsic_value=120)
    from sqlalchemy import select                    # last check 10 days ago
    with store.session() as s:
        p = s.scalar(select(store.TranchePlan))
        p.last_checked = datetime.now(timezone.utc) - timedelta(days=10)
        s.commit()
    days = pd.bdate_range(date.today() - timedelta(days=9), date.today() - timedelta(days=1))
    bars = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=days)
    bars.iloc[2, :] = [97.0, 98.0, 94.0, 96.0]       # touches 95 intraday → fill at 95
    bars.iloc[5, :] = [82.0, 84.0, 80.0, 83.0]       # gaps below 85 → fill at the open 82
    ev = autotrade.run(pid, quote_fn=quote(100), history_fn=lambda s: bars, in_session=lambda: True)
    t = sorted(_trades(pid), key=lambda r: r["ts"])
    assert [e["event"] for e in ev] == ["backfill_buy", "backfill_buy"]
    assert [round(r["mid"], 2) for r in t] == [95.0, 82.0] and all(r["source"] == "auto-backfill" for r in t)
    assert t[0]["ts"][:10] == str(days[2].date()) and "gapped" in t[1]["note"]
    assert ledger.verify(pid)["ok"]
    assert autotrade.get_plans(pid)[0]["status"] == "done"


def test_sell_level_over_iv(pid):
    autotrade.update_settings(pid, {"auto_trade": True})
    engine.trade_stock(pid, "AAA", "BUY", 30, quote=Quote("AAA", last=100, avg_volume=1e7, source="yahoo"))
    autotrade.upsert_plan(pid, "AAA", buy_levels=[], sell_levels=[{"over_iv": 0.5, "fraction": 1 / 3}],
                          intrinsic_value=100)
    autotrade.run(pid, quote_fn=quote(151), history_fn=no_history, in_session=lambda: True)
    sells = [t for t in _trades(pid) if t["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["qty"] == pytest.approx(10)


def test_plans_from_watchlist(pid):
    with store.session() as s:
        w = store.Watchlist(name="W")
        s.add(w)
        s.flush()
        s.add(store.WatchItem(watchlist_id=w.id, symbol="AAA", intrinsic_value=100, supports=[110, 95, 80]))
        s.add(store.WatchItem(watchlist_id=w.id, symbol="BBB", intrinsic_value=50, supports=[]))
        s.commit()
        wid = w.id
    res = autotrade.plans_from_watchlist(pid, wid)
    assert res["created"] == ["AAA"] and "BBB" in res["skipped"]
    plan = autotrade.get_plans(pid)[0]
    assert [l["price"] for l in plan["buy_levels"]] == [95, 80] and plan["buy_levels"][0]["fraction"] == 0.5
    assert res["settings"]["sizing_mode"] == "watchlist"


def test_hand_entered_order_at_a_level_fills_it_so_automation_does_not_double_buy(pid):
    autotrade.update_settings(pid, {"auto_trade": True})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.5}, {"price": 85, "fraction": 0.5}],
                          intrinsic_value=120)
    res = ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 20, "price": 94.0,
                                 "ts": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}, reason="done by hand")
    assert res["plan_level"] == "AAA level 95"
    lv = autotrade.get_plans(pid)[0]["buy_levels"]
    assert lv[0]["status"] == "filled" and lv[0]["trade_id"] == res["trade_id"] and lv[1]["status"] == "pending"
    autotrade.run(pid, quote_fn=quote(94), history_fn=no_history, in_session=lambda: True)
    assert len(_trades(pid)) == 1                                   # level 95 not bought again


def _bars(days_back, rows):
    days = pd.bdate_range(date.today() - timedelta(days=days_back), date.today() - timedelta(days=1))
    b = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}, index=days)
    for i, vals in rows.items():
        b.iloc[i, :] = vals
    return b


def test_gap_through_three_tranches_fills_one_then_staggers_the_rest(pid):
    from sqlalchemy import select
    autotrade.update_settings(pid, {"auto_trade": True, "gap_stagger_days": 2})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.4}, {"price": 90, "fraction": 0.3},
                                                  {"price": 85, "fraction": 0.3}], intrinsic_value=150)
    with store.session() as s:
        p = s.scalar(select(store.TranchePlan))
        p.last_checked = datetime.now(timezone.utc) - timedelta(days=20)
        s.commit()
    bars = _bars(19, {})
    n = len(bars)
    bars.iloc[3, :] = [84.0, 85.0, 83.0, 84.0]          # gaps below all three levels
    for i in range(4, n):                                # and stays there
        bars.iloc[i, :] = [84.0, 85.0, 83.0, 84.0]
    ev = autotrade.run(pid, quote_fn=quote(84), history_fn=lambda s: bars, in_session=lambda: True)
    t = sorted(_trades(pid), key=lambda r: r["ts"])
    gap_day = bars.index[3].date()
    assert [e["event"] for e in ev].count("gap_stagger") == 1
    assert len(t) == 3
    d = [r["ts"][:10] for r in t]
    assert d[0] == str(gap_day)                                          # tranche 1 on the gap day
    import numpy as np
    assert d[1] == str(np.busday_offset(str(gap_day), 2)) and d[2] == str(np.busday_offset(str(gap_day), 4))
    assert [r["context"]["plan"]["level"] for r in t] == [0, 1, 2]
    assert ledger.verify(pid)["ok"]


def test_gap_stagger_waits_when_price_rebounds_and_can_be_switched_off(pid):
    from sqlalchemy import select
    autotrade.update_settings(pid, {"auto_trade": True, "gap_stagger_days": 2})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.5}, {"price": 90, "fraction": 0.5}],
                          intrinsic_value=150)
    with store.session() as s:
        s.scalar(select(store.TranchePlan)).last_checked = datetime.now(timezone.utc) - timedelta(days=12)
        s.commit()
    bars = _bars(11, {})
    bars.iloc[1, :] = [88.0, 89.0, 87.0, 88.0]          # gap through both levels, then straight back to 100
    autotrade.run(pid, quote_fn=quote(100), history_fn=lambda s: bars, in_session=lambda: True)
    assert len(_trades(pid)) == 1                                       # second tranche released but price is above 90
    lv = autotrade.get_plans(pid)[0]["buy_levels"]
    assert lv[1]["status"] == "pending"
    # switched off: both fill on the gap day
    engine.reset_portfolio(pid)
    autotrade.delete_plan(pid, "AAA")
    autotrade.update_settings(pid, {"gap_stagger_days": 0})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[{"price": 95, "fraction": 0.5}, {"price": 90, "fraction": 0.5}], intrinsic_value=150)
    with store.session() as s:
        s.scalar(select(store.TranchePlan)).last_checked = datetime.now(timezone.utc) - timedelta(days=12)
        s.commit()
    autotrade.run(pid, quote_fn=quote(100), history_fn=lambda s: bars, in_session=lambda: True)
    assert len(_trades(pid)) == 2


def test_live_gap_fills_one_now_and_schedules_the_rest(pid):
    autotrade.update_settings(pid, {"auto_trade": True, "gap_stagger_days": 3})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[95, 90, 85], intrinsic_value=150)
    ev = autotrade.run(pid, quote_fn=quote(84), history_fn=no_history, in_session=lambda: True)
    assert len(_trades(pid)) == 1
    lv = autotrade.get_plans(pid)[0]["buy_levels"]
    assert [l["status"] for l in lv] == ["filled", "scheduled", "scheduled"] and lv[2]["fill_after"] > lv[1]["fill_after"]
    assert any(e["event"] == "gap_stagger" for e in ev)
