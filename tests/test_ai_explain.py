"""Company explainer: offline (fake model, fake research). Real-model quality is checked by the owner."""
from vmi import ai_explain as AE
from vmi import ai_pipeline as P

REP = {"price": 100, "intrinsic_value": 150, "metrics": {"roe": -0.071, "roe_latest": 0.32, "roe_avg5": -0.071, "roe_loss_years": 3, "roic": -0.147,
                                                         "growth": 0.45, "revenue_cagr": 0.4, "margin_of_safety": 0.33, "pe": 20, "peg": 1.1,
                                                         "dividend_yield": 0, "beta": 1.3, "basis": {"label": "3-year average", "kind": "avg"}},
       "steps": [{"step": 4, "checks": [{"name": "roe", "value": -0.071, "passed": False, "threshold": ">= 15%", "note": "(NORMALISED)"},
                                        {"name": "roe_not_declining", "value": [-0.13, -0.10, -0.06, -0.27, 0.21], "passed": True, "threshold": ""}]},
                 {"step": 1, "checks": [{"name": "gross_margin_stable", "value": 0.9, "passed": True, "threshold": ">= avg"}]}]}


def _fake(monkeypatch, calls):
    monkeypatch.setattr(P, "answer", lambda q, name, ticker, chat, on_tool=None, pages=3, words=None: f"- finding for {q[:20]} [https://example.com/{abs(hash(q)) % 999}]")
    monkeypatch.setattr(P, "sec_annual_report", lambda t: "ANNUAL REPORT [https://sec.gov/x]")

    def chat(msgs, mt):
        calls.append(msgs[0]["content"])
        return "A plain **explanation** [https://example.com/src]." if "explaining" in msgs[0]["content"] else "ARR: annual recurring revenue"
    return chat


def test_metric_facts_carry_the_apps_numbers_and_basis():
    f = AE.metric_facts(REP, {"gross margin": {2024: 0.9, 2025: 0.91}})
    assert "judged on the 3-year average: -7.1% (latest fiscal year 32.0%" in f["returns"] and "3 loss year(s)" in f["returns"]
    assert "roe not declining: -13.0%, -10.0%" in f["returns"] and "FAIL" in f["returns"]
    assert "gross margin by year: 2024 90.0%, 2025 91.0%" in f["margins"]
    assert "intrinsic value 150" in f["valuation"]


def test_explainer_has_every_section_links_and_no_markdown(monkeypatch, temp_db):
    calls = []
    out = AE.explain("RDDT", "Reddit Inc", REP, _fake(monkeypatch, calls), level="quick", cik=1713445)
    titles = [s["title"] for s in out["sections"]]
    assert titles[:3] == ["How it makes money", "Industry and competitors", "History"]
    assert {"Returns: ROE and ROIC", "Margins", "Growth and consistency", "Debt and balance sheet", "Cash flow and efficiency", "Valuation", "Glossary"} <= set(titles)
    assert all("**" not in s["text"] for s in out["sections"])
    assert any("example.com" in u for u in out["further_reading"]) and any("sec.gov/cgi-bin/browse-edgar" in u and "1713445" in u for u in out["further_reading"])
    ret = next(s for s in out["sections"] if s["key"] == "m_returns")
    assert "ROE judged on the 3-year average" in ret["figures"]


def test_prompts_hand_over_the_figures_and_forbid_guessing(monkeypatch, temp_db):
    calls = []
    AE.explain("RDDT", "Reddit Inc", REP, _fake(monkeypatch, calls), use_cache=False)
    section_prompts = [c for c in calls if "explaining" in c]
    assert section_prompts and all("never recompute or contradict them" in c and "not found in the sources" in c and "No buy or sell advice" in c and "need NO source" in c for c in section_prompts)
    returns = next(c for c in section_prompts if 'section "Returns: ROE and ROIC"' in c)
    assert "latest fiscal year 32.0%" in returns and "why it is at THIS level" in returns


def test_second_call_is_cached(monkeypatch, temp_db):
    calls = []
    chat = _fake(monkeypatch, calls)
    AE.explain("RDDT", "Reddit Inc", REP, chat)
    n = len(calls)
    again = AE.explain("RDDT", "Reddit Inc", REP, chat)
    assert again["cached"] is True and len(calls) == n


def test_endpoint_needs_the_builtin_ai(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from vmi import ai_helper
    from vmi.api import app as appmod
    monkeypatch.setattr(ai_helper, "status", lambda: {"backend": None, "model": "x", "available": False})
    r = TestClient(appmod.app).post("/api/analysis/AAA/ai-explain")
    assert r.status_code == 503 and "built-in AI" in r.json()["detail"]
