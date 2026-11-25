"""Entry-timing tracker: touches, the 2-day asking rule, no answer = waiting, entry types, and the comparison maths."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from vmi import store
from vmi.paper import entry_timing as et


def _bars(start, closes, lows=None, highs=None):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"open": closes, "high": highs or [c * 1.01 for c in closes], "low": lows or [c * 0.99 for c in closes], "close": closes}, index=idx)


def test_one_open_touch_per_level_and_unanswered_means_waiting(temp_db):
    assert et.record_touch("AAA", 100, 99.5, "watchlist")["status"] == "open"
    assert et.record_touch("AAA", 100.2, 99.9, "plan") is None            # same level (within 0.5%): not a second touch
    assert et.record_touch("AAA", 90, 89.5, "plan") is not None            # another level is its own touch
    o = et.open_touches()
    assert len(o) == 2 and all(t["effective_waiting"] and t["assumed"] for t in o)


def test_prompts_are_shown_once_per_two_days(temp_db):
    et.record_touch("AAA", 100, 99.5)
    assert len(et.prompts()) == 1                                          # shown now
    assert et.prompts() == []                                              # not again straight away
    with store.session() as s:                                             # two days later it is due again
        t = s.query(store.SupportTouch).one()
        t.last_asked_at = datetime.now(timezone.utc) - timedelta(days=2, minutes=1)
        s.commit()
    assert len(et.prompts()) == 1
    tid = et.open_touches()[0]["id"]
    et.answer(tid, False)                                                  # "not waiting": never asked again
    with store.session() as s:
        s.query(store.SupportTouch).one().last_asked_at = datetime.now(timezone.utc) - timedelta(days=9)
        s.commit()
    assert et.prompts() == []


def test_a_buy_links_to_the_open_touch_with_its_type(temp_db):
    et.record_touch("AAA", 100, 99.5)
    t = et.link_entry("AAA", 7, 101.0, "confirmed")
    assert t["status"] == "entered" and t["entry_type"] == "confirmed" and t["trade_id"] == 7 and t["touch_price"] == 99.5
    assert et.open_touches() == []
    t2 = et.link_entry("BBB", 8, 50.0, "special")                          # a buy with no earlier touch still counts, by type
    assert t2["source"] == "manual" and t2["entry_type"] == "special"
    with pytest.raises(ValueError):
        et.link_entry("CCC", 9, 10.0, "whenever")


def test_price_leaving_the_zone_lapses_the_touch(temp_db):
    et.record_touch("AAA", 100, 99.5)
    et.on_price("AAA", 101)                                                # still near: stays open
    assert len(et.open_touches()) == 1
    et.on_price("AAA", 130)
    assert et.open_touches() == []
    with store.session() as s:
        assert s.query(store.SupportTouch).one().status == "lapsed"


def test_stats_compare_entry_types_and_flag_breakdowns(temp_db):
    day0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
    closes = [100.0] * 5 + [92.0] * 30 + [96.0] * 40                      # touch, then a breakdown below 95, then a recovery
    bars = _bars("2026-01-05", closes, lows=[c * 0.995 for c in closes])
    with store.session() as s:
        s.add(store.SupportTouch(symbol="AAA", level=100, touch_price=100, touched_at=day0, status="entered", entry_type="on_touch",
                                 entry_price=100.0, entered_at=day0))
        s.add(store.SupportTouch(symbol="AAA", level=100, touch_price=100, touched_at=day0, status="entered", entry_type="confirmed",
                                 entry_price=103.0, entered_at=day0))
        s.add(store.SupportTouch(symbol="AAA", level=100, touch_price=100, touched_at=day0, status="lapsed"))
        s.commit()
    r = et.stats(history_fn=lambda sym: bars)
    g = r["groups"]
    assert g["on_touch"]["n"] == 1 and g["confirmed"]["n"] == 1 and g["waited_no_entry"]["n"] == 1
    assert g["confirmed"]["avg_cost_vs_touch"] == pytest.approx(0.03)      # waiting cost 3% more than the touch price
    assert g["on_touch"]["breakdown_rate"] == 1.0                          # price fell more than 5% below the level within 20 bars
    assert "Not enough data" in r["verdict"]                               # 3 finished touches < 10


def test_auto_plan_fill_is_an_on_touch_entry(temp_db, monkeypatch):
    from vmi.data import market
    from vmi.data.models import Quote
    from vmi.paper import autotrade, engine
    monkeypatch.setattr(market, "last_price", lambda s: 100.0)
    pid = engine.create_portfolio("A", "growth", cash=100_000, target_positions=10)["id"]
    autotrade.update_settings(pid, {"auto_trade": True})
    autotrade.upsert_plan(pid, "AAA", buy_levels=[95], intrinsic_value=150)
    autotrade.run(pid, quote_fn=lambda s: Quote(s, last=94.0, avg_volume=1e7, source="yahoo"), history_fn=lambda s: pd.DataFrame(), in_session=lambda: True)
    with store.session() as s:
        t = s.query(store.SupportTouch).one()
        assert t.status == "entered" and t.entry_type == "on_touch" and t.trade_id
    tr = engine.trades(pid)[0]
    assert tr["context"]["entry_type"] == "on_touch" and "entry:on_touch" in tr["tags"]


def test_api_flow(temp_db):
    from fastapi.testclient import TestClient
    from vmi.api import app as appmod
    c = TestClient(appmod.app)
    et.record_touch("AAA", 100, 99.5)
    p = c.get("/api/touches/prompts").json()
    assert len(p) == 1 and c.get("/api/touches/prompts").json() == []
    assert c.post(f"/api/touches/{p[0]['id']}/answer", json={"waiting": True}).json()["waiting"] is True
    assert c.post("/api/touches/9999/answer", json={"waiting": True}).status_code == 404
    assert "groups" in c.get("/api/touches/stats").json()
