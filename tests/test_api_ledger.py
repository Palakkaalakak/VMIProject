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
