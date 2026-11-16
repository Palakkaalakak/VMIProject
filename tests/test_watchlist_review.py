import pytest
from fastapi.testclient import TestClient

from vmi import store
from vmi.watchlist import service


def test_review_queue_is_separate_from_the_watchlist(temp_db):
    w = service.create("Growth")["id"]
    service.upsert_item(w, "AAA", 100)
    r = service.add_to_review(w, "WST", "scanner 4/7")
    assert r["stage"] == "review" and r["already"] is None
    assert service.add_to_review(w, "AAA")["already"] == "watching"          # already in the list: not moved
    assert service.add_to_review(w, "WST")["already"] == "review"
    lst = service.list_all()[0]
    assert (lst["count"], lst["review_count"]) == (1, 1)
    from vmi.paper import autotrade
    assert autotrade.watchlist_size(w) == 1                                    # sizing ignores candidates
    service.promote(w, "WST")
    assert service.list_all()[0]["count"] == 2 and autotrade.watchlist_size(w) == 2


def test_review_items_get_no_price_alerts(temp_db, monkeypatch):
    from vmi.data import market
    monkeypatch.setattr(market, "last_price", lambda s: 50.0)
    w = service.create("W")["id"]
    service.upsert_item(w, "AAA", 100, [60])
    service.add_to_review(w, "BBB")
    with store.session() as s:
        from sqlalchemy import select
        bb = s.scalar(select(store.WatchItem).where(store.WatchItem.symbol == "BBB"))
        bb.intrinsic_value, bb.supports = 100, [60]
        s.commit()
    service.check_all()
    msgs = [a["message"] for a in service.alerts()]
    assert any("AAA" in m for m in msgs) and not any("BBB" in m for m in msgs)


def test_api_review_and_promote(temp_db):
    from vmi.api import app as appmod
    c = TestClient(appmod.app)
    wid = c.post("/api/watchlists", json={"name": "W"}).json()["id"]
    assert c.post(f"/api/watchlists/{wid}/review/WST", json={"notes": "x"}).json()["stage"] == "review"
    assert c.post(f"/api/watchlists/{wid}/items/WST/promote").json()["stage"] == "watching"
