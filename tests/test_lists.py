"""Watchlist metric columns + flags, portfolio breakdown + strategy tags, S&P 500 heatmap (all offline)."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from vmi import heatmap
from vmi.data.models import Quote
from vmi.paper import breakdown
from vmi.rules import RULES
from vmi.watchlist.flags import FLAGS, flag, flags_for


@pytest.fixture
def client(temp_db, monkeypatch):
    from vmi.api import app as appmod
    from vmi.paper import engine

    monkeypatch.setattr(engine, "_stock_quote", lambda s: Quote(s, last=100, avg_volume=1e7, source="yahoo"))
    monkeypatch.setattr(appmod.gateway(), "start", lambda: None, raising=False)
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------------------- flags
def test_flags_follow_the_rule_thresholds():
    p, v = RULES.profitability, RULES.valuation
    assert flag("roe", p.excellent_roe, RULES) == "green" and flag("roe", p.min_roe, RULES) == "yellow"
    assert flag("roe", p.min_roe - 0.01, RULES) == "red" and flag("roic", p.excellent_roic + 0.1, RULES) == "green"
    assert flag("peg", v.peg_attractive, RULES) == "green" and flag("peg", v.peg_screen, RULES) == "yellow"
    assert flag("peg", v.peg_screen + 0.1, RULES) == "red" and flag("peg", -1, RULES) is None
    assert flag("margin_of_safety", 0.2, RULES) == "green" and flag("margin_of_safety", -0.1, RULES) == "red"
    assert [flag("steps_passed", n, RULES) for n in (7, 5, 4, 3, 2)] == ["green", "green", "yellow", "yellow", "red"]
    assert flag("growth", 0.2, RULES) == "green" and flag("growth", 0.05, RULES) == "yellow" and flag("growth", -0.02, RULES) == "red"
    assert flag("dividend_yield", 0.06, RULES) == "green" and flag("dividend_yield", 0.035, RULES) == "yellow"
    assert flag("dividend_yield", 0.01, RULES) is None
    assert flag("moat", "wide", RULES) == "green" and flag("moat", "narrow", RULES) == "yellow" and flag("moat", "unreviewed", RULES) is None
    assert flag("distance_to_level", 0.02, RULES) == "green" and flag("distance_to_level", 0.5, RULES) is None
    assert flag("net_margin", -0.1, RULES) == "red" and flag("net_margin", 0.2, RULES) is None


def test_flag_ignores_missing_unknown_and_garbage():
    assert flag("roe", None, RULES) is None and flag("roe", float("nan"), RULES) is None
    assert flag("beta", 1.2, RULES) is None and flag("roe", "abc", RULES) is None
    assert flags_for({"roe": 0.3, "peg": 3.0, "beta": 1.1, "moat": None}, RULES) == {"roe": "green", "peg": "red"}
    assert set(FLAGS) >= {"growth", "roe", "roic", "margin_of_safety", "peg", "steps_passed"}


# ---------------------------------------------------------------------------------------- watchlist metrics
def test_watchlist_metrics_endpoint_flags_errors_and_distance(client, monkeypatch):
    from vmi.watchlist import metrics

    def fake(sym):
        if sym == "BAD":
            raise ValueError("no fundamentals")
        return {"growth": 0.18, "roe": 0.2, "roic": 0.1, "peg": 1.2, "steps_passed": 6, "moat": "wide", "market_cap": 3e12,
                "beta": 0.9, "margin_of_safety": 0.1, "sector": "Technology", "name": "Mega"}

    monkeypatch.setattr(metrics, "compact_cached", fake)
    wid = client.post("/api/watchlists", json={"name": "W"}).json()["id"]
    client.post(f"/api/watchlists/{wid}/items", json={"symbol": "AAA", "intrinsic_value": 150, "supports": [95, 80]})
    client.post(f"/api/watchlists/{wid}/items", json={"symbol": "BAD"})
    client.post(f"/api/watchlists/{wid}/review/REV", json={})          # review-queue stocks are not analysed
    from vmi import store
    with store.session() as s:                                         # a known price so the distance to the next level exists
        it = s.query(store.WatchItem).filter_by(symbol="AAA").one()
        it.last_price = 100.0
        s.commit()
    out = client.get(f"/api/watchlists/{wid}/metrics").json()
    assert set(out["metrics"]) == {"AAA", "BAD"}
    a = out["metrics"]["AAA"]
    assert a["error"] is None and a["flags"]["roe"] == "green" and a["flags"]["roic"] == "red" and a["flags"]["peg"] == "green"
    assert a["flags"]["steps_passed"] == "green" and a["flags"]["moat"] == "green" and "beta" not in a["flags"]
    assert a["distance_to_level"] == pytest.approx(0.05) and a["flags"]["distance_to_level"] == "yellow"
    bad = out["metrics"]["BAD"]
    assert bad["roe"] is None and bad["flags"] == {} and "no fundamentals" in bad["error"]
    assert out["rules"]["min_roe"] == RULES.profitability.min_roe
    assert client.get("/api/watchlists/999/metrics").status_code == 400


def test_compact_cached_uses_the_cache(monkeypatch):
    from vmi.analysis import pipeline
    from vmi.scanner import funnel
    from vmi.watchlist import metrics

    calls = []
    monkeypatch.setattr(pipeline, "analyse_ticker", lambda s, **k: calls.append(s) or {"ticker": s})
    monkeypatch.setattr(funnel, "compact", lambda rep: {"symbol": rep["ticker"], "roe": 0.2})
    assert metrics.compact_cached("msft") == {"symbol": "MSFT", "roe": 0.2}
    assert metrics.compact_cached("MSFT")["roe"] == 0.2 and calls == ["MSFT"]


# ---------------------------------------------------------------------------------------- breakdown
POS = [{"symbol": "KO", "sec_type": "STK", "market_value": 600.0}, {"symbol": "MSFT", "sec_type": "STK", "market_value": 300.0},
       {"symbol": "AAPL", "sec_type": "STK", "market_value": 100.0},
       {"symbol": "KO", "sec_type": "OPT", "market_value": -50.0}]
PROF = {"KO": {"sector": "Consumer Defensive", "country": "United States", "category": "predictable"},
        "MSFT": {"sector": "Technology", "country": "United States", "category": "large_growth"}, "AAPL": {}}


def test_breakdown_slices_cash_options_and_unknown():
    out = breakdown.breakdown("sector", POS, 50.0, PROF, {})
    by = {s["label"]: s for s in out["slices"]}
    assert out["total"] == 1100.0 and sum(s["weight"] for s in out["slices"]) == pytest.approx(1)
    assert by["Consumer Defensive"]["value"] == 600 and by["Cash"]["value"] == 50 and by["Options"]["value"] == 50   # abs() of the short
    assert by["Unknown"]["symbols"] == ["AAPL"] and [s["label"] for s in out["slices"]][0] == "Consumer Defensive"
    assert {s["label"] for s in breakdown.breakdown("category", POS, 0, PROF, {})["slices"]} == {"Predictable", "Large growth", "Unknown", "Options"}
    assert breakdown.breakdown("country", POS, 0, PROF, {})["slices"][0]["label"] == "United States"
    st = breakdown.breakdown("strategy", POS, 0, {}, {"KO": "Dividend"})
    assert {s["label"]: s["value"] for s in st["slices"]} == {"Dividend": 600, "Untagged": 400, "Options": 50}
    assert breakdown.breakdown("sector", [], 0, {}, {}) == {"by": "sector", "total": 0, "slices": []}
    with pytest.raises(ValueError):
        breakdown.breakdown("colour", POS, 0, PROF, {})


def test_breakdown_endpoint_and_tags(client, monkeypatch):
    from vmi.paper import profiles as profmod
    monkeypatch.setattr(profmod, "profiles", lambda syms: {s: {"sector": "Consumer Defensive", "country": "United States", "category": "predictable"} for s in syms})
    pid = client.post("/api/portfolios", json={"name": "B", "cash": 10_000}).json()["id"]
    assert client.post(f"/api/portfolios/{pid}/orders/stock", json={"symbol": "KO", "side": "BUY", "qty": 10}).status_code == 200
    r = client.get(f"/api/portfolios/{pid}/breakdown?by=sector").json()
    assert {s["label"] for s in r["slices"]} == {"Consumer Defensive", "Cash"} and r["holdings"][0]["symbol"] == "KO"
    assert r["strategies"][0] == "Growth" and r["holdings"][0]["tag"] is None
    assert client.post(f"/api/portfolios/{pid}/tags", json={"symbol": "ko", "tag": "Dividend"}).json() == {"tags": {"KO": "Dividend"}}
    s = client.get(f"/api/portfolios/{pid}/breakdown?by=strategy").json()
    assert {x["label"] for x in s["slices"]} == {"Dividend", "Cash"} and s["holdings"][0]["tag"] == "Dividend"
    assert client.post(f"/api/portfolios/{pid}/tags", json={"symbol": "KO", "tag": "Moonshot"}).status_code == 400
    assert client.post(f"/api/portfolios/{pid}/tags", json={"symbol": "KO", "tag": None}).json() == {"tags": {}}
    assert client.get(f"/api/portfolios/{pid}/breakdown?by=zodiac").status_code == 400
    assert client.post("/api/portfolios/999/tags", json={"symbol": "KO", "tag": "Growth"}).status_code == 400
    client.post(f"/api/portfolios/{pid}/tags", json={"symbol": "KO", "tag": "Growth"})
    client.delete(f"/api/portfolios/{pid}")
    assert breakdown.get_tags(pid) == {}                     # tags go with the portfolio


# ---------------------------------------------------------------------------------------- heatmap
def closes(values, start="2025-12-24"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"close": values}, index=idx)


def test_price_changes_1d_1m_ytd():
    df = closes([float(100 + i) for i in range(40)], start="2025-12-01")         # runs into 2026
    out = heatmap.price_changes(df)
    last = df["close"].iloc[-1]
    assert out["price"] == last and out["change_1d"] == pytest.approx(last / df["close"].iloc[-2] - 1)
    assert out["change_1m"] == pytest.approx(last / df["close"].iloc[-22] - 1)
    assert out["ytd"] == pytest.approx(last / df.loc[:"2025-12-31", "close"].iloc[-1] - 1)
    short = heatmap.price_changes(closes([10.0, 11.0]))
    assert short["change_1d"] == pytest.approx(0.1) and short["change_1m"] is None
    assert heatmap.price_changes(None)["price"] is None and heatmap.price_changes(pd.DataFrame())["change_1d"] is None


def test_build_tiles_skips_no_cap_and_greys_without_iv():
    members = [{"symbol": "AAA", "name": "A", "sector": "Tech"}, {"symbol": "BBB", "name": "B", "sector": ""},
               {"symbol": "CCC", "name": "C", "sector": "Tech"}]
    hist = {"AAA": closes([100.0, 110.0]), "BBB": closes([50.0, 45.0])}
    tiles = heatmap.build_tiles(members, {"AAA": 2e12, "BBB": 1e11}, hist, {"AAA": 220.0})
    assert [t["symbol"] for t in tiles] == ["AAA", "BBB"]                       # CCC has no market cap
    a, b = tiles
    assert a["discount_to_iv"] == pytest.approx(0.5) and b["discount_to_iv"] is None and b["sector"] == "Other"
    assert b["change_1d"] == pytest.approx(-0.1)


def _patch_sp500(monkeypatch, n=3, prices=True):
    from vmi.data import market, universe
    members = [{"symbol": f"S{i}", "name": f"Stock {i}", "sector": "Tech" if i % 2 else "Energy"} for i in range(n)]
    monkeypatch.setattr(universe, "sp500", lambda: members)
    monkeypatch.setattr(universe, "us_market", lambda min_market_cap=0.0: [{"symbol": m["symbol"], "market_cap": 1e9 * (i + 1)} for i, m in enumerate(members)])
    calls = []
    monkeypatch.setattr(market, "bulk_history", lambda syms, period="2y": calls.append(1) or ({s: closes([10.0, 11.0]) for s in syms} if prices else {}))
    monkeypatch.setattr(heatmap, "_latest_scan_ivs", lambda: ({"S1": 22.0}, 7))
    return calls


def test_heatmap_endpoint_metrics_and_cache(client, monkeypatch):
    calls = _patch_sp500(monkeypatch)
    r = client.get("/api/heatmap?metric=change_1d").json()
    assert r["metric"] == "change_1d" and len(r["tiles"]) == 3 and r["tiles"][0]["value"] == pytest.approx(0.1)
    assert r["n_iv"] == 1 and r["scan_run_id"] == 7
    iv = client.get("/api/heatmap?metric=discount_to_iv").json()
    assert {t["symbol"]: t["value"] for t in iv["tiles"]}["S1"] == pytest.approx(0.5) and sum(t["value"] is None for t in iv["tiles"]) == 2
    assert len(calls) == 1                                                      # assembled once, 15-minute cache
    assert client.get("/api/heatmap?metric=nope").status_code == 400


def test_heatmap_failures_are_clear_503(client, monkeypatch):
    from vmi.data import universe
    _patch_sp500(monkeypatch, prices=False)
    r = client.get("/api/heatmap")
    assert r.status_code == 503 and "Prices could not be downloaded" in r.json()["detail"]
    def boom():
        raise RuntimeError("all S&P 500 sources failed")
    monkeypatch.setattr(universe, "sp500", boom)
    r = client.get("/api/heatmap")
    assert r.status_code == 503 and "S&P 500 list could not be loaded" in r.json()["detail"]
