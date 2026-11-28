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
        p.last_checked = datetime.now(timezone.utc) - timedelta(days=21)
        s.commit()
    days = pd.bdate_range(date.today() - timedelta(days=20), date.today() - timedelta(days=1))   # >= 6 bars any weekday
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


def test_plans_from_watchlist_use_the_stated_supports_as_tranches(pid):
    with store.session() as s:
        w = store.Watchlist(name="W")
        s.add(w)
        s.flush()
        s.add(store.WatchItem(watchlist_id=w.id, symbol="AAA", intrinsic_value=100, iv_source="manual", supports=[110, 95, 80, 70, 60]))
        s.add(store.WatchItem(watchlist_id=w.id, symbol="BBB", intrinsic_value=50, iv_source="auto", supports=[40, 35, 30]))
        s.add(store.WatchItem(watchlist_id=w.id, symbol="CCC", supports=[]))
        s.commit()
        wid = w.id
    res = autotrade.plans_from_watchlist(pid, wid)
    assert sorted(res["created"]) == ["AAA", "BBB", "CCC"]
    plans = {p["symbol"]: p for p in autotrade.get_plans(pid)}
    assert [l["price"] for l in plans["AAA"]["buy_levels"]] == [110, 95, 80, 70, 60]      # the number of tranches follows the stated supports
    assert [round(l["fraction"], 3) for l in plans["AAA"]["buy_levels"]] == [0.2] * 5
    assert len(plans["BBB"]["buy_levels"]) == 3 and plans["CCC"]["buy_levels"] == []
    assert plans["AAA"]["intrinsic_value"] == 100 and plans["BBB"]["intrinsic_value"] is None   # only a typed IV is copied
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


def test_alert_only_plan_staggers_a_gap_too(pid):
    autotrade.update_settings(pid, {"auto_trade": False, "gap_stagger_days": 3})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[95, 90, 85], intrinsic_value=150)
    ev = autotrade.run(pid, quote_fn=quote(84), history_fn=no_history, in_session=lambda: True)
    assert _trades(pid) == []                                            # alert only: nothing is bought
    lv = autotrade.get_plans(pid)[0]["buy_levels"]
    assert [l["status"] for l in lv] == ["alerted", "scheduled", "scheduled"] and lv[2]["fill_after"] > lv[1]["fill_after"]
    assert any(e["event"] == "gap_stagger" for e in ev)


def test_one_click_sizing_follows_the_stated_levels(pid):
    from vmi.paper import engine
    with store.session() as s:
        w = store.Watchlist(name="W2")
        s.add(w)
        s.flush()
        s.add(store.WatchItem(watchlist_id=w.id, symbol="ZZZ", supports=[50, 45, 40, 35, 30, 25]))
        s.commit()
    assert engine.stated_tranches(pid, "ZZZ") == 6                     # six stated supports = six tranches
    assert engine.stated_tranches(pid, "NOPE") is None                 # nothing stated: the fixed rule (4)
    autotrade.upsert_plan(pid, "ZZZ", buy_levels=[50, 45, 40])
    assert engine.stated_tranches(pid, "ZZZ") == 3                     # the portfolio's own plan wins over the watchlist


def test_size_for_takes_an_explicit_price(pid):
    from vmi.paper import engine
    s = engine.size_for(pid, "ZZZ", 1.0, 50.0)
    assert s["price"] == 50.0 and abs(s["shares_next_tranche"] - s["tranche_value"] / 50) < 0.01


def test_run_backdater_executes_missed_levels_once_even_when_alert_only(pid):
    now = datetime.now(timezone.utc)
    day = pd.bdate_range(end=now.date() - timedelta(days=3), periods=1)[0]
    bars = pd.DataFrame({"open": [105.0], "high": [106.0], "low": [89.0], "close": [95.0]}, index=[day])
    autotrade.upsert_plan(pid, "AAA", buy_levels=[100, 50], require_below_iv=False)
    kw = dict(quote_fn=quote(200), history_fn=lambda s: bars, in_session=lambda: True)
    ev = autotrade.run(pid, backdate_days=20, **kw)                    # alert-only portfolio, plan made after the bar
    assert [e["event"] for e in ev] == ["backfill_buy"] and len(_trades(pid)) == 1
    assert autotrade.run(pid, backdate_days=20, **kw) == [] and len(_trades(pid)) == 1       # never twice


def test_premarket_view_needs_ib_and_revalues(pid, monkeypatch):
    from vmi.data import ib
    engine.trade_stock(pid, "AAA", "BUY", qty=10, quote=quote(100)("AAA"))

    class GW:
        connected = False

        def quote(self, s, wait=2.0):
            return Quote(s, last=110, bid=None, ask=None, close=100, source="ib")

        def after_hours(self, s):
            return self.ah

    gw = GW()
    monkeypatch.setattr(ib, "gateway", lambda: gw)
    monkeypatch.setattr(engine, "_mark", lambda pos, quotes=True: 100.0)
    with pytest.raises(engine.TradeError):
        engine.premarket_view(pid)
    gw.connected = True
    gw.ah = (110.0, "2026-11-25")                                     # the quote's undated `last` must not count
    v = engine.premarket_view(pid)
    assert v["change"] == pytest.approx(100) and v["positions"][0]["move"] == pytest.approx(0.10) and v["missing"] == []
    assert v["positions"][0]["source"] == "previous after-hours 2026-11-25"
    gw.ah = None
    v = engine.premarket_view(pid)
    assert v["missing"] == ["AAA"] and v["change"] == pytest.approx(0)


def test_premarket_price_and_previous_after_hours():
    from types import SimpleNamespace as NS
    from vmi.data.ib import last_after_hours
    from vmi.data.market_hours import ET
    from vmi.paper import engine
    at = lambda d, h, m=0: datetime(2026, 11, d, h, m, tzinfo=ET)
    now = at(24, 8)                                                   # Tuesday pre-market
    q = lambda ts: Quote("AAA", last=110, last_ts=ts.timestamp(), source="ib")
    assert engine.premarket_price(q(at(24, 7)), now) == 110
    assert engine.premarket_price(q(at(23, 15, 59)), now) is None and engine.premarket_price(q(at(23, 19)), now) is None
    assert engine.premarket_price(q(at(24, 7)), at(24, 11)) is None   # regular session
    bars = [NS(date=at(20, 19), close=1), NS(date=at(23, 15, 55), close=2), NS(date=at(23, 19, 55), close=3), NS(date=at(24, 7), close=4)]
    assert last_after_hours(bars, now) == (3.0, "2026-11-23")
    assert last_after_hours(bars[:2], now) is None                    # no after-hours trade: never the regular close


def _day_bars(rows):
    """rows: [(open, low)] for consecutive business days ending a few days ago."""
    days = pd.bdate_range(end=date.today() - timedelta(days=3), periods=len(rows))
    return pd.DataFrame([{"open": o, "high": o + 1, "low": lo, "close": o} for o, lo in rows], index=days)


def _watchlist(items):
    with store.session() as s:
        w = store.Watchlist(name="W")
        s.add(w)
        s.flush()
        for sym, sup in items.items():
            s.add(store.WatchItem(watchlist_id=w.id, symbol=sym, supports=sup))
        s.commit()
        return w.id


def test_backdater_one_timeline_in_order_of_hits_with_limited_cash(pid):
    autotrade.update_settings(pid, {"sizing_mode": "manual", "manual_allocation": 40_000})    # cash: 2.5 positions
    for sym in ("AAA", "BBB", "CCC", "DDD"):
        autotrade.upsert_plan(pid, sym, buy_levels=[100], require_below_iv=False)
    hist = {"AAA": _day_bars([(110, 105), (110, 105), (110, 99)]),     # last day, 9% drop to the level
            "BBB": _day_bars([(110, 105), (110, 99), (110, 105)]),     # first to be hit
            "CCC": _day_bars([(110, 105), (110, 105), (99, 98)]),      # last day, gap at the open
            "DDD": _day_bars([(110, 105), (110, 105), (101, 99)])}     # last day, 1% drop
    r = autotrade.backdate(pid, 30, history_fn=hist.get)
    assert [e["symbol"] for e in r["events"]] == ["BBB", "CCC"]
    assert "no cash" in r["reasons"]["DDD"][0] and "no cash" in r["reasons"]["AAA"][0]
    assert all(p["buy_levels"][0]["status"] == "pending" for p in autotrade.get_plans(pid) if p["symbol"] in ("AAA", "DDD"))
    with store.session() as s:                                          # a later run with more cash still fills them
        s.get(store.Portfolio, pid).starting_cash = 500_000
        s.commit()
    r = autotrade.backdate(pid, 30, history_fn=hist.get)
    assert [e["symbol"] for e in r["events"]] == ["DDD", "AAA"]


def test_backdater_creates_plans_and_fills_each_support_when_first_hit(pid):
    autotrade.update_settings(pid, {"watchlist_id": _watchlist({"AAA": [95, 90, 85], "BBB": []}), "gap_stagger_days": 3})
    bars = _day_bars([(100, 99), (88, 87), (86, 84)])
    r = autotrade.backdate(pid, 30, history_fn=lambda s: bars)
    assert sorted(r["plans_created"]) == ["AAA", "BBB"] and r["plans_checked"] == 2 and r["buys"] == 3
    assert [(e["level"], e["px"], e["day"]) for e in r["events"]] == [
        (95, 88, str(bars.index[1].date())), (90, 88, str(bars.index[1].date())), (85, 85, str(bars.index[2].date()))]
    assert "no levels" in r["reasons"]["BBB"][0] and r["filled_at_window_open"] == 0
    assert autotrade.backdate(pid, 30, history_fn=lambda s: bars)["buys"] == 0 and len(_trades(pid)) == 3
    autotrade.delete_plan(pid, "AAA")                                   # recreated plan: ledger buys count, no double buy
    assert autotrade.backdate(pid, 30, history_fn=lambda s: bars)["buys"] == 0 and len(_trades(pid)) == 3


def test_backdater_keeps_user_levels_and_warns_without_plans(pid):
    r = autotrade.backdate(pid, 30, history_fn=no_history)
    assert r["plans_checked"] == 0 and any("no active plans" in w for w in r["warnings"])
    wid = _watchlist({"AAA": [95]})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[70])
    autotrade.update_settings(pid, {"watchlist_id": wid})
    r = autotrade.backdate(pid, 30, history_fn=no_history)
    assert autotrade.get_plans(pid)[0]["buy_levels"][0]["price"] == 70 and "no price history" in r["reasons"]["AAA"][0]
    for bad in (0, 999):
        with pytest.raises(autotrade.PlanError):
            autotrade.plans_from_watchlist(pid, bad)


def test_backdater_fetches_histories_in_parallel_and_isolates_provider_errors(pid):
    from threading import Barrier

    autotrade.upsert_plan(pid, "AAA", buy_levels=[100])
    autotrade.upsert_plan(pid, "BBB", buy_levels=[100])
    autotrade.upsert_plan(pid, "CCC", buy_levels=[{"price": 100, "status": "skipped"}])
    barrier = Barrier(2, timeout=5)
    bars = _day_bars([(99, 98)])
    calls = []

    def history(sym):
        calls.append(sym)
        barrier.wait()
        if sym == "AAA":
            raise RuntimeError("provider unavailable")
        return bars

    r = autotrade.backdate(pid, 30, history_fn=history)
    assert sorted(calls) == ["AAA", "BBB"]
    assert [e["symbol"] for e in r["events"]] == ["BBB"]
    assert r["reasons"]["AAA"] == ["price history failed: provider unavailable", "no price history for the period"]
    assert r["plans_checked"] == 3
    assert ledger.verify(pid)["ok"]


def test_backdater_retries_after_sell_and_uses_updated_holdings(pid):
    bars = _day_bars([(90, 88), (110, 89)])
    initial = datetime.combine(bars.index[0].date() - timedelta(days=3), datetime.min.time(), timezone.utc)
    ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 700, "price": 100, "ts": initial}, reason="seed")
    autotrade.upsert_plan(pid, "AAA", sell_levels=[{"price": 100, "fraction": 0.5}, {"price": 105, "fraction": 0.5}])
    autotrade.upsert_plan(pid, "BBB", buy_levels=[100], allocation=50_000)

    r = autotrade.backdate(pid, 30, history_fn=lambda sym: bars)
    assert [e["event"] for e in r["events"]] == ["backfill_sell", "backfill_sell", "backfill_buy"]
    assert all(e["day"] == str(bars.index[1].date()) for e in r["events"])
    assert sorted(t["qty"] for t in _trades(pid) if t["side"] == "SELL") == [175, 350]
    assert "no cash" in r["reasons"]["BBB"][0]
    assert ledger.verify(pid)["ok"]
