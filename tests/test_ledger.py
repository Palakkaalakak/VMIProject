"""Ledger: replay == live engine, admin back-dated edits, audit, expiry rows, legacy migration."""
from datetime import datetime, timedelta, timezone

import pytest

from vmi import store
from vmi.data.models import OptionQuote, Quote
from vmi.paper import engine, ledger


def q(px):
    return Quote("X", last=px, avg_volume=1e7, source="yahoo")


@pytest.fixture
def pid(temp_db):
    return engine.create_portfolio("T", "growth", cash=10_000)["id"]


@pytest.fixture
def fake_options(monkeypatch):
    from vmi.data import market
    from vmi.options import chain

    monkeypatch.setattr(chain, "option_quote", lambda s, e, k, r: OptionQuote(s, e, k, r, bid=1.9, ask=2.1, iv=0.3))
    monkeypatch.setattr(market, "last_price", lambda s: 95.0)


def test_replay_matches_live_engine(pid, fake_options):
    engine.trade_stock(pid, "AAA", "BUY", 10, quote=q(100))
    engine.trade_stock(pid, "AAA", "BUY", 5, quote=q(90))
    engine.trade_stock(pid, "AAA", "SELL", 8, quote=q(120), fees=1.5)
    engine.trade_option(pid, "AAA", "20991219", 80, "P", "SELL", 1)
    engine.trade_option(pid, "AAA", "20991219", 80, "P", "BUY", 1)
    v = ledger.verify(pid)
    assert v["ok"], v


def test_backdated_buy_changes_cost_and_cash_and_is_audited(pid):
    engine.trade_stock(pid, "AAA", "BUY", 10, quote=q(100))
    ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 10, "price": 50, "ts": ts, "fees": 2},
                           reason="missed fill")
    assert res["state"]["ok"]
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        pos = [x for x in p.positions if x.key == "AAA"][0]
        assert pos.qty == 20 and pos.avg_cost == pytest.approx((10 * 50 + 10 * 100.05) / 20)
        assert p.cash == pytest.approx(10_000 - 500 - 2 - 10 * 100.05)
    acts = [a["action"] for a in ledger.audit(pid)]
    assert "add" in acts and "rebuild" in acts


def test_sell_before_the_shares_existed_is_rejected(pid):
    engine.trade_stock(pid, "AAA", "BUY", 10, quote=q(100))
    early = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with pytest.raises(ledger.LedgerError, match="only 0"):
        ledger.add_trade(pid, {"symbol": "AAA", "side": "SELL", "qty": 5, "price": 100, "ts": early}, reason="x")


def test_update_and_delete_rebuild_and_keep_before_after(pid):
    t = engine.trade_stock(pid, "AAA", "BUY", 10, quote=q(100))["trade"]
    ledger.update_trade(t["id"], {"price": 80}, reason="wrong fill")
    with store.session() as s:
        assert s.get(store.Portfolio, pid).cash == pytest.approx(10_000 - 800)
        assert s.get(store.Trade, t["id"]).edited
    ledger.delete_trade(t["id"], reason="never happened")
    with store.session() as s:
        p = s.get(store.Portfolio, pid)
        assert p.cash == pytest.approx(10_000) and not p.positions
    log = ledger.audit(pid)
    upd = next(a for a in log if a["action"] == "update")
    assert upd["before"]["price"] == pytest.approx(100.05) and upd["after"]["price"] == 80


def test_reason_is_required(pid):
    with pytest.raises(ledger.LedgerError):
        ledger.add_trade(pid, {"symbol": "AAA", "side": "BUY", "qty": 1, "price": 1}, reason=" ")


def test_expired_option_leaves_a_closing_row(pid, monkeypatch):
    from vmi.data import market
    from vmi.options import chain

    monkeypatch.setattr(chain, "option_quote", lambda s, e, k, r: OptionQuote(s, e, k, r, bid=1.9, ask=2.1))
    monkeypatch.setattr(market, "last_price", lambda s: 120.0)
    engine.trade_option(pid, "AAA", "20200117", 100, "P", "SELL", 1)   # already expired, OTM at 120
    engine.settle_expired(pid)
    kinds = [t["kind"] for t in engine.trades(pid)]
    assert "expiry" in kinds
    assert ledger.verify(pid)["ok"]


def test_running_ledger_view(pid):
    engine.trade_stock(pid, "AAA", "BUY", 10, quote=q(100))
    engine.trade_stock(pid, "AAA", "SELL", 4, quote=q(110))
    rows = ledger.ledger(pid)
    assert [r["position_after"] for r in rows] == [10, 6]


def test_legacy_database_gets_new_columns(tmp_path, monkeypatch):
    import sqlite3

    from vmi import config

    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("create table trades (id integer primary key, portfolio_id int, ts text, key text, symbol text, "
              "sec_type text, side text, qty float, price float, mid float, slippage float, liquidity text, "
              "multiplier int, note text)")
    c.execute("insert into trades values (1,1,'2026-01-01 00:00:00','A','A','STK','BUY',1,1,1,0,'liquid',1,'')")
    c.commit()
    c.close()
    monkeypatch.setattr(config.Settings, "database_url", property(lambda self: f"sqlite:///{db}"))
    monkeypatch.setattr(store, "_engine", None)
    monkeypatch.setattr(store, "_Session", None)
    with store.session() as s:
        t = s.get(store.Trade, 1)
        assert t.kind == "fill" and t.source == "paper" and t.fees == 0 and t.context == {}
