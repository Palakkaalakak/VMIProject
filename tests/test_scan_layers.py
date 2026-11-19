"""Scanner: runner-ups, deep-analysis cache, size floors for every universe, no-moat layer, quick reject."""
from vmi.scanner import funnel


def _rep(sym, fail=()):
    steps = [{"step": k, "passed": k not in fail, "checks": [{"name": f"c{k}", "passed": k not in fail}]} for k in range(1, 8)]
    return {"ticker": sym, "name": sym, "steps": steps, "metrics": {"margin_of_safety": 0.1}, "great_business": not fail, "valuation": {}}


def _patch(monkeypatch, plan, calls):
    import vmi.analysis.pipeline as pl

    def fake(sym, with_technicals=True, overrides=None, **_):
        calls.append(sym)
        return _rep(sym, plan[sym])
    monkeypatch.setattr(pl, "analyse_ticker", fake)
    funnel.STATE.__init__()


def test_runner_ups_are_the_closest_misses_and_never_counted_as_results(monkeypatch):
    calls = []
    _patch(monkeypatch, {"OK": (), "NEAR": (1,), "FAR": (1, 2, 4), "NEAR2": (4,)}, calls)
    cands = [funnel.Candidate(s, s, None) for s in ("OK", "NEAR", "FAR", "NEAR2")]
    p = funnel.ScanParams(universe="list", require_steps=[1, 2, 4, 5], workers=1, runner_ups=True, runner_up_misses=1, use_cache=False)
    kept = funnel.stage_deep(cands, p)
    assert [c.symbol for c in kept] == ["OK"]
    rows = funnel.STATE.results
    assert [r["symbol"] for r in rows if not r.get("runner_up")] == ["OK"]
    assert {r["symbol"] for r in rows if r.get("runner_up")} == {"NEAR", "NEAR2"}      # FAR misses 3 checks: not a runner-up
    assert all(r["missed"] for r in rows if r.get("runner_up"))


def test_runner_ups_off_by_default(monkeypatch):
    calls = []
    _patch(monkeypatch, {"OK": (), "NEAR": (1,)}, calls)
    funnel.stage_deep([funnel.Candidate("OK", "", None), funnel.Candidate("NEAR", "", None)],
                      funnel.ScanParams(universe="list", require_steps=[1, 2, 4, 5], workers=1, use_cache=False))
    assert [r["symbol"] for r in funnel.STATE.results] == ["OK"]


def test_deep_cache_reuses_an_analysis_with_the_same_rules(monkeypatch):
    calls = []
    _patch(monkeypatch, {"OK": ()}, calls)
    p = funnel.ScanParams(universe="list", require_steps=[1, 2, 4, 5], workers=1)
    funnel.stage_deep([funnel.Candidate("OK", "", None)], p)
    funnel.STATE.__init__()
    funnel.stage_deep([funnel.Candidate("OK", "", None)], p)
    assert calls == ["OK"]                                           # second scan: no new analysis
    from vmi import settings
    with settings.temporary({"profitability": {"min_roe": 0.2}}):    # other rules: analysed again
        funnel.stage_deep([funnel.Candidate("OK", "", None)], p)
    assert calls == ["OK", "OK"]
    funnel.stage_deep([funnel.Candidate("OK", "", None)], funnel.ScanParams(universe="list", require_steps=[1, 2, 4, 5], workers=1, use_cache=False))
    assert len(calls) == 3


def test_size_floor_applies_to_sp500_and_custom_lists(monkeypatch):
    monkeypatch.setattr(funnel.universe, "us_market", lambda *a, **k: [
        {"symbol": "BIG", "market_cap": 50e9, "price": 100}, {"symbol": "SMALL", "market_cap": 1e9, "price": 20},
        {"symbol": "PENNY", "market_cap": 20e9, "price": 2}])
    funnel.STATE.__init__()
    cands = [funnel.Candidate(s, s, None) for s in ("BIG", "SMALL", "PENNY", "UNKNOWN")]
    out = funnel._apply_size(cands, funnel.ScanParams(universe="list", min_market_cap=10e9, min_price=5))
    assert [c.symbol for c in out] == ["BIG", "UNKNOWN"]              # a ticker the screener does not list is kept
    assert "Size" in funnel.STATE.dropped["SMALL"] and "Size" in funnel.STATE.dropped["PENNY"]


def test_no_moat_industry_layer():
    funnel.STATE.__init__()
    cands = [funnel.Candidate("DAL", "Delta", None, industry="Air Freight/Delivery Services airline"),
             funnel.Candidate("MSFT", "", None, industry="Computer Software: Prepackaged Software")]
    assert [c.symbol for c in funnel.stage_no_moat_industry(cands, funnel.ScanParams(skip_no_moat_industries=False))] == ["DAL", "MSFT"]
    assert [c.symbol for c in funnel.stage_no_moat_industry(cands, funnel.ScanParams(skip_no_moat_industries=True))] == ["MSFT"]


def test_saved_scans_round_trip(temp_db):
    from vmi import store
    from vmi.scanner import funnel

    with store.session() as s:
        row = store.ScanRun(universe="list", params={"preset": "adam"}, status="done",
                            results=[{"symbol": "A"}, {"symbol": "B", "runner_up": True}])
        s.add(row)
        s.commit()
        rid = row.id
    assert funnel.list_saved() == []
    funnel.save_run(rid, "My ultra run")
    saved = funnel.list_saved()
    assert saved[0]["name"] == "My ultra run" and saved[0]["n_results"] == 1 and saved[0]["n_runner_ups"] == 1
    assert [r["symbol"] for r in funnel.latest_results(rid)["results"]] == ["A", "B"]
    funnel.unsave_run(rid)
    assert funnel.list_saved() == []
