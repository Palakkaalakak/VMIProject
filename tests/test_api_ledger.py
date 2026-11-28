"""HTTP layer for ledger admin, review, plans and the option book (temp DB, no network)."""
import pytest
from fastapi.testclient import TestClient

from vmi.data.models import Quote


@pytest.fixture
def client(temp_db, monkeypatch):
    from vmi.api import app as appmod
    from vmi.paper import engine

    monkeypatch.setattr(engine, "_stock_quote", lambda s: Quote(s, last=100, avg_volume=1e7, source="yahoo"))
    monkeypatch.setattr(appmod.gateway(), "start", lambda: None, raising=False)
    return TestClient(appmod.app)          # no `with`: lifespan (IB, autosync, loops) is not started


def _pf(c, **kw):
    return c.post("/api/portfolios", json={"name": "T", "cash": 10_000, **kw}).json()["id"]


def test_create_asks_auto_trade_and_sets_sizing(client):
    pid = _pf(client, auto_trade=True)
    s = client.get(f"/api/portfolios/{pid}/settings").json()
    assert s["auto_trade"] is True and s["sizing_mode"] == "target"       # no watchlist linked yet


def test_admin_add_edit_delete_over_http(client):
    pid = _pf(client)
    r = client.post(f"/api/portfolios/{pid}/orders/stock", json={"symbol": "AAA", "side": "BUY", "qty": 10,
                                                               "tags": ["core"], "thesis": "wide moat"})
    assert r.status_code == 200
    add = client.post(f"/api/portfolios/{pid}/ledger", json={
        "symbol": "AAA", "side": "BUY", "qty": 5, "price": 50, "ts": "2026-01-02T15:30:00-05:00", "fees": 1,
        "reason": "missed fill"})
    assert add.status_code == 200 and add.json()["state"]["ok"]
    rows = client.get(f"/api/portfolios/{pid}/ledger").json()
    assert [x["qty"] for x in rows] == [5, 10] and rows[0]["position_after"] == 5 and rows[1]["position_after"] == 15
    assert rows[1]["tags"] == "core" and rows[1]["thesis"] == "wide moat"
    tid = rows[0]["id"]
    assert client.put(f"/api/ledger/{tid}", json={"changes": {"price": 60}, "reason": "typo"}).status_code == 200
    assert client.post(f"/api/ledger/{tid}/delete", json={"reason": "wrong"}).status_code == 200
    assert client.get(f"/api/portfolios/{pid}/verify").json()["ok"]
    assert {a["action"] for a in client.get(f"/api/portfolios/{pid}/audit").json()} >= {"add", "update", "delete"}


def test_history_replays_admin_changes_in_charts_snapshots_and_exports(client, monkeypatch):
    import csv
    from io import StringIO

    import pandas as pd

    from vmi import store
    from vmi.data import market
    from vmi.paper import journal

    pid = _pf(client)
    base = f"/api/portfolios/{pid}"
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    bars = pd.DataFrame({"close": [50, 75, 80]}, index=pd.to_datetime(dates))
    monkeypatch.setattr(market, "history", lambda *a: bars)
    with store.session() as s:
        for day in dates:  # Old account totals cannot become authoritative after a correction.
            s.add(store.DailyMark(portfolio_id=pid, key=journal.PORTFOLIO_KEY, day=day, value=10_000))
        s.commit()
    added = client.post(base + "/ledger", json={"symbol": "AAA", "side": "BUY", "qty": 10, "price": 40,
                                                 "ts": "2026-01-06T19:30:00-05:00", "fees": 2, "reason": "missed fill"})
    assert added.status_code == 200
    tid = added.json()["trade_id"]
    opts = {"start": dates[0], "end": dates[-1]}
    before = client.get(base + "/history/as-of", params={"at": "2026-01-06T19:29:59"}).json()
    after = client.get(base + "/history/as-of", params={"at": "2026-01-07T00:30:00Z"}).json()
    assert before["positions"] == [] and before["cash"] == 10_000
    assert after["day"] == dates[1] and after["cash"] == 9_598 and after["positions"][0]["price"] == 75
    curve = client.get(base + "/history", params=opts).json()["points"]
    assert [p["equity"] for p in curve] == [10_000, 10_348, 10_398]
    review_curve = client.get(base + "/equity-curve").json()["points"]
    assert next(p for p in review_curve if p["day"] == dates[1])["equity"] == 10_348
    r = client.get(base + "/history/csv", params=opts)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert [float(row["equity"]) for row in csv.DictReader(StringIO(r.text))] == [10_000, 10_348, 10_398]
    ex = client.get(base + "/export", params={**opts, "history": "true", "as_of": dates[1]}).json()
    assert ex["history"]["points"][1]["positions"][0]["qty"] == 10 and ex["as_of"]["cash"] == 9_598
    assert ex["daily_marks"][0]["value"] == 10_000  # archive stays as captured
    assert next(a for a in ex["audit"] if a["action"] == "add")["ts"][:10] != dates[1]
    assert client.put(f"/api/ledger/{tid}", json={"changes": {"ts": "2026-01-07T11:30:00-05:00"}, "reason": "date"}).status_code == 200
    assert client.get(base + "/history/as-of", params={"at": dates[1]}).json()["positions"] == []
    intraday = client.get(base + "/history/as-of", params={"at": "2026-01-07T12:00"}).json()
    assert intraday["positions"][0]["price"] == 75  # don't use today's future closing price
    assert client.post(f"/api/ledger/{tid}/delete", json={"reason": "cancelled"}).status_code == 200
    assert all(p["equity"] == 10_000 for p in client.get(base + "/history", params=opts).json()["points"])
    assert client.get(base + "/history/as-of", params={"at": "2099-01-01"}).status_code == 400


def test_oversell_and_missing_reason_are_400(client):
    pid = _pf(client)
    bad = client.post(f"/api/portfolios/{pid}/ledger", json={"symbol": "AAA", "side": "SELL", "qty": 5, "price": 50,
                                                            "reason": "x"})
    assert bad.status_code == 400 and "held" in bad.json()["detail"]
    assert client.post(f"/api/portfolios/{pid}/ledger", json={"symbol": "AAA", "side": "BUY", "qty": 1, "price": 1,
                                                            "reason": " "}).status_code == 400


def test_plans_settings_and_run(client):
    pid = _pf(client)
    assert client.put(f"/api/portfolios/{pid}/plans", json={
        "symbol": "AAA", "buy_levels": [{"price": 95, "fraction": 0.5}, {"price": 85}], "intrinsic_value": 120}).status_code == 200
    data = client.get(f"/api/portfolios/{pid}/plans").json()
    assert data["plans"][0]["buy_levels"][1]["fraction"] == 0.5 and data["full_allocation"]["full"] > 0
    assert client.put(f"/api/portfolios/{pid}/settings", json={"changes": {"sizing_mode": "manual", "manual_allocation": 2000}}).json()["sizing_mode"] == "manual"
    assert client.put(f"/api/portfolios/{pid}/settings", json={"changes": {"bogus": 1}}).status_code == 400
    assert client.delete(f"/api/portfolios/{pid}/plans/AAA").json()["ok"]


def test_review_export_and_optionbook(client):
    pid = _pf(client)
    client.post(f"/api/portfolios/{pid}/orders/stock", json={"symbol": "AAA", "side": "BUY", "qty": 10})
    assert client.get(f"/api/portfolios/{pid}/review/what-if/nope").status_code == 400
    ex = client.get(f"/api/portfolios/{pid}/export").json()
    assert ex["verify"]["ok"] and len(ex["ledger"]) == 1
    snap = client.post("/api/optionbook/snapshots", json={
        "symbol": "AAA", "spot": 105, "as_of": "2026-11-11",
        "legs": [{"right": "P", "strike": 100, "expiry": "20270115", "qty": -1, "entry": 3.0}]}).json()
    rc = client.post(f"/api/optionbook/snapshots/{snap['id']}/recompute", json={"spot": 90, "iv_shift": 0.1}).json()
    assert rc["result"]["pnl_now"] < snap["result"]["pnl_now"]
    assert client.get("/api/optionbook/snapshots", params={"symbol": "AAA"}).json()[0]["id"] == snap["id"]
    assert client.post("/api/optionbook/snapshots", json={"symbol": "AAA"}).status_code == 400


def test_index_clears_the_browser_cache_once_per_version(client):
    first = client.get("/")
    assert first.headers.get("clear-site-data") == '"cache"' and "vmi_ui" in first.headers.get("set-cookie", "")
    again = client.get("/")                                 # the test client keeps the cookie
    assert "clear-site-data" not in again.headers


def test_analysis_modes_become_per_request_rules(client, monkeypatch):
    import vmi.analysis.pipeline as pl

    seen = {}

    def fake(sym, with_technicals=True, overrides=None, rules=None, **_):
        seen["rules"] = rules
        return {"ticker": sym}
    monkeypatch.setattr(pl, "analyse_ticker", fake)
    assert client.get("/api/analysis/AAA").json()["mode"] == {"ten_year_only": False, "normalise": None}
    assert seen["rules"].track.min_years == 5 and seen["rules"].normalise.enabled is False
    r = client.get("/api/analysis/AAA?ten_year_only=true&normalise=true").json()
    assert r["mode"] == {"ten_year_only": True, "normalise": True}
    assert seen["rules"].track.min_years == 10 and seen["rules"].normalise.enabled is True
    from vmi.rules import RULES
    assert RULES.track.min_years == 5 and RULES.normalise.enabled is False      # nothing leaks into Settings


def test_chart_bars_endpoint_validates_the_interval(client, monkeypatch):
    from vmi.data import market
    monkeypatch.setattr(market, "history", lambda *a, **k: __import__("pandas").DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [10.0]}, index=__import__("pandas").to_datetime(["2026-01-02"])))
    r = client.get("/api/bars/AAA?interval=1d").json()
    assert r["bars"][0] == {"time": "2026-01-02", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
    assert client.get("/api/bars/AAA?interval=3d").status_code == 400



def test_portfolio_quick_ai_uses_one_bounded_call_and_no_price_fetch(client, monkeypatch):
    import json

    from vmi import ai_helper
    from vmi.data import market

    def no_prices(*args, **kwargs):
        pytest.fail("Quick AI must use only the displayed summary")

    calls = []
    def chat(backend, messages, max_tokens, *, timeout):
        calls.append((backend, messages, max_tokens, timeout))
        return "**Cash** fell while the value of positions increased."

    monkeypatch.setattr(market, "history", no_prices)
    monkeypatch.setattr(market, "last_price", no_prices)
    monkeypatch.setattr(ai_helper, "status", lambda *, local_only: {"backend": "builtin" if local_only else None, "model": "mock-local"})
    monkeypatch.setattr(ai_helper, "overview_chat", chat)
    pid = _pf(client)
    path = f"/api/portfolios/{pid}/history/ask"
    body = {"question": "Why did cash go down?", "context": json.dumps({"primary": {"name": "A", "last": {"cash": 500}}})}
    res = client.post(path, json=body)
    assert res.json() == {"answer": "Cash fell while the value of positions increased.", "model": "mock-local"}
    assert len(calls) == 1
    backend, messages, tokens, timeout = calls[0]
    assert backend == "builtin" and tokens == 420 and timeout == 90
    assert "Why did cash go down?" in messages[1]["content"] and '"cash": 500' in messages[1]["content"]
    assert client.post(path, json={**body, "context": "[1]"}).status_code == 400
    assert client.post(path, json={**body, "question": "x" * 501}).status_code == 422
    monkeypatch.setattr(ai_helper, "status", lambda **kw: {"backend": None})
    assert client.post(path, json=body).status_code == 503
    assert len(calls) == 1


def test_holdings_performance_and_printable_report(client, monkeypatch):
    import pandas as pd

    from vmi.data import market

    pid = _pf(client)
    from vmi import store
    with store.session() as s:
        s.get(store.Portfolio, pid).name = '<Growth & Income>'
        s.commit()
    base = f"/api/portfolios/{pid}"
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
    prices = {"AAA": [100., 120., 130., 150.], "BBB": [30., 30., 40., 20.], "SPY": [50., 51., 52., 55.]}
    monkeypatch.setattr(market, "history", lambda symbol, *_: pd.DataFrame({"close": prices[symbol]}, index=dates))
    for symbol, side, qty, price, day, fees in [
        ("AAA", "BUY", 10, 100, "05", 0), ("AAA", "SELL", 10, 130, "07", 5),
        ("BBB", "BUY", 5, 40, "07", 0),
    ]:
        r = client.post(base + "/ledger", json={"symbol": symbol, "side": side, "qty": qty, "price": price,
                        "ts": f"2026-01-{day}T12:00:00-05:00", "fees": fees, "reason": "effective-dated fixture"})
        assert r.status_code == 200
    params = {"start": "2026-01-06", "end": "2026-01-08", "benchmark": "SPY"}
    res = client.get(base + "/history/performance", params=params)
    assert res.status_code == 200
    data = res.json()
    assert data["opening_equity"] == 10_000
    assert data["range_trades"] == 2 and data["range_fees"] == 5
    stock = {s["symbol"]: s for s in data["stocks"]}
    assert stock["AAA"]["pnl"] == [200, 295, 295]  # sale freezes contribution, but not its price series
    assert stock["AAA"]["price_return"] == pytest.approx([.2, .3, .5])
    assert stock["BBB"]["pnl"] == [0, 0, -100]
    assert data["benchmark"]["price_return"][-1] == pytest.approx(.1)
    assert data["points"][-1]["equity"] == 10_195
    assert client.get(base + "/history/performance", params={**params, "benchmark": "INVALID"}).status_code == 400
    report = client.get(base + "/history/report", params=params)
    assert report.status_code == 200 and report.headers["cache-control"] == "no-store"
    assert "Executive summary" in report.text and "Print / Save as PDF" in report.text
    assert "&lt;Growth &amp; Income&gt;" in report.text and "<Growth & Income>" not in report.text
    assert report.text.count("<svg") == 5 and "SPY price return" in report.text
    assert "$10,195.00" in report.text and "AAA added the most" in report.text
    export = client.get(base + "/history/report", params={**params, "download": True})
    assert 'attachment;' in export.headers["content-disposition"] and "report.html" in export.headers["content-disposition"]
    assert "<svg" in export.text and 'window.print' not in export.text


def test_stock_price_series_does_not_use_a_future_close():
    from datetime import date

    from vmi.paper.journal import _price_path

    a, b = date(2026, 1, 5), date(2026, 1, 6)
    path = _price_path(([a, b], {a: 100, b: 120}), a, [{"as_of": "2026-01-06T12:00:00-05:00"}])
    assert path == {"base_day": str(a), "price_return": [0.0]}
