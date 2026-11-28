"""Offline coverage for the independent overview and its settings."""
import re

import pytest
from fastapi.testclient import TestClient

from vmi import ai_explain, ai_helper, ai_settings
from vmi.api import app as appmod
from vmi.config import get_settings
from vmi.data import fundamentals
from vmi.data.models import Fundamentals, Point


@pytest.fixture
def company():
    dates = ["2023-12-31", "2024-12-31", "2025-12-31"]

    def points(*values):
        return [Point(date, value) for date, value in zip(dates, values)]

    return Fundamentals("TEST", name="Example Co", currency="EUR",
                        annual={"net_income": points(4000, 2000, 4500), "equity": points(20000, 20000, -900),
                                "current_liabilities": points(3000, 4000, 3000)},
                        ratios={"roe": points(.20, .10, -.50),
                                "current_ratio": points(1.30, .90, 1.25) + [Point("2026-03-31", .60)]})


@pytest.fixture
def report():
    def step(number, *checks):
        return {"step": number, "checks": [{"name": name, "value": value, "passed": False} for name, value in checks]}

    return {"steps": [step(1, ("gross_margin_stable", .18)), step(2, ("projected_growth_positive", -.05)),
                      step(3, ("reinvestment_intensity", {"capex": .2}), ("reviewer_verdict", "PRIVATE_MOAT_VERDICT")),
                      step(4, ("cash_conversion_cycle", [25, 45])), step(5, ("interest_coverage", 1.9)),
                      step(6, ("below_intrinsic_value", 11)), step(7, ("entry_signal", "downtrend"))],
            "price": 11, "intrinsic_value": 9, "valuation": {"label": "Test DCF", "inputs": {"discount_rate": .1}},
            "technicals": {"daily": {"state": "downtrend"}, "signals": {"parabolic_up": False}},
            "volatility": {"max_drawdown": -.35, "years": 9}}


@pytest.fixture
def model(monkeypatch):
    prompts = []
    monkeypatch.setattr(ai_explain.research, "answer", lambda *a, **kw: "A filing says this. [https://example.com/filing]")

    monkeypatch.setattr(ai_explain.research, "annual_reports", lambda t: [])
    monkeypatch.setattr(ai_explain.research, "search", lambda *a: [])

    def chat(messages, tokens):
        prompts.append(messages[0]["content"])
        return "This is an **overview**."

    return chat, prompts


def test_quick_only_covers_the_business(company, model):
    chat, prompts = model
    result = ai_explain.explain(company, chat)
    assert [s["key"] for s in result["sections"]] == ["business", "drivers"]
    assert len(prompts) == 2 and all("Do not give a moat grade" in p for p in prompts)
    assert all(s["text"] == "This is an overview." and s["links"] == ["https://example.com/filing"] for s in result["sections"])


def test_deep_uses_dated_figures_and_distinguishes_causes(company, model):
    chat, prompts = model
    result = ai_explain.explain(company, chat, level="deep")
    figures = {s["key"]: s["figures"] for s in result["sections"] if "figures" in s}
    assert "2024-12-31: 2,000" in figures["profits"] and "money in EUR" in figures["profits"]
    assert "2024-12-31: 10.0%" in figures["returns"] and "nonpositive equity" in figures["returns"]
    assert "2024-12-31: 0.90x" in figures["liquidity"] and "2026-03-31" not in figures["liquidity"]
    assert any("pre-dip, trough and latest values" in p and "do not assume" in p for p in prompts)



def test_deep_feeds_all_step_evidence_without_the_moat_verdict(company, model, report):
    chat, prompts = model
    result = ai_explain.explain(company, chat, level="deep", report=report)
    sections = {s["key"]: s for s in result["sections"]}
    for key, phrase in {"profits": "gross margin stable", "outlook": "projected growth positive",
                        "industry": "reinvestment intensity", "returns": "cash conversion cycle",
                        "liquidity": "interest coverage", "valuation": "Test DCF", "chart": "-35.0%"}.items():
        assert phrase in sections[key]["figures"]
        assert any(phrase in prompt for prompt in prompts)
    assert all("PRIVATE_MOAT_VERDICT" not in prompt for prompt in prompts)
    assert "not met" not in sections["industry"]["figures"]
    assert not sections["valuation"]["links"] and not sections["chart"]["links"]
    assert ai_explain.explain(company, chat, level="deep", report=report)["cached"]
    report["price"] = 12
    assert not ai_explain.explain(company, chat, level="deep", report=report)["cached"]


def test_missing_chart_does_not_turn_default_check_into_a_signal(report):
    report["technicals"] = None
    evidence = ai_explain.evidence(report, 7)
    assert "No technical snapshot" in evidence and "entry signal" not in evidence


def test_overview_cache_respects_depth_refresh_and_opt_out(company, model):
    chat, prompts = model
    ai_explain.explain(company, chat)
    assert ai_explain.explain(company, chat)["cached"] and len(prompts) == 2
    assert not ai_explain.explain(company, chat, fresh=True)["cached"] and len(prompts) == 4
    assert not ai_explain.explain(company, chat, use_cache=False)["cached"] and len(prompts) == 6
    assert not ai_explain.explain(company, chat, level="standard")["cached"] and len(prompts) == 11
    assert not ai_explain.explain(company, chat, model="different")["cached"] and len(prompts) == 13


def test_settings_and_overview_endpoints(company, model, report, monkeypatch, tmp_path):
    chat, _ = model
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    modes = []

    def analyse(symbol, *, ten_year_only, normalise):
        modes.append((symbol, ten_year_only, normalise))
        return report

    monkeypatch.setattr(appmod, "analyse", analyse)
    client = TestClient(appmod.app)
    assert client.get("/api/ai/settings").json()["overview_depth"] == "quick"
    assert client.put("/api/ai/settings", json={"max_gpu_temp_c": 99}).status_code == 422
    saved = client.put("/api/ai/settings", json={"overview_depth": "deep", "cache_overviews": False,
                                               "max_gpu_temp_c": 76, "max_run_minutes": 20})
    assert saved.status_code == 200 and ai_settings.load().max_gpu_temp_c == 76
    monkeypatch.setattr(ai_helper, "status", lambda: {"backend": None})
    assert client.post("/api/analysis/TEST/ai-explain").status_code == 503
    monkeypatch.setattr(ai_helper, "status", lambda: {"backend": "ollama", "model": "local"})
    monkeypatch.setattr(fundamentals, "resolve", lambda symbol: company if symbol == "TEST" else None)
    monkeypatch.setattr(ai_helper, "overview_chat", lambda backend, msgs, tokens: chat(msgs, tokens))
    assert client.post("/api/analysis/UNKNOWN/ai-explain").status_code == 404
    assert client.post("/api/analysis/TEST/ai-explain?level=huge").status_code == 422
    deep = client.post("/api/analysis/TEST/ai-explain?ten_year_only=true&normalise=false").json()
    assert deep["level"] == "deep" and any(s["key"] == "chart" for s in deep["sections"])
    assert client.post("/api/analysis/TEST/ai-explain?level=quick").json()["level"] == "quick"
    assert modes == [("TEST", True, False)]


def test_deep_reads_the_filing_and_only_keeps_sourced_causes(company, model, monkeypatch):
    prompts = []
    filing = {"form": "10-K", "filed": "2025-02-01", "period": "2024-12-31", "url": "https://www.sec.gov/f24.htm", "accession": "a"}
    mdna = "Net income decreased primarily due to a one-time tax charge on revenue. " * 5
    monkeypatch.setattr(ai_explain.research, "annual_reports", lambda t: [filing])
    monkeypatch.setattr(ai_explain.research, "report_sections", lambda f: {"business": "We sell widgets to plumbers. " * 3000, "mdna": mdna})

    def chat(messages, tokens):
        prompt = messages[0]["content"]
        prompts.append((prompt, tokens))
        if prompt.startswith("Example Co (TEST), fiscal year"):
            return "- A tax charge cut profit. [https://www.sec.gov/f24.htm]\n- Invented cause. [https://made.up/x]\n- No link."
        return "Text."

    result = ai_explain.explain(company, chat, level="deep", use_cache=False)
    causes = next(s for s in result["sections"] if s["key"] == "causes")["text"]
    assert "A tax charge cut profit" in causes and "Invented" not in causes and "No link" not in causes
    assert "No sourced cause found." in causes                    # the 2025 swing has no source for that year
    business = next(p for p, _ in prompts if "What the company does" in p)
    assert "We sell widgets to plumbers" in business and "no word limit" in business and len(business) > 30000
    from vmi import ai_runtime
    assert all(len(p) / ai_runtime.CHARS_PER_TOKEN + t <= ai_runtime.CTX for p, t in prompts)


def test_deep_moat_prompts_have_no_word_caps_and_fit_the_context(monkeypatch):
    from vmi import ai_research as r, ai_runtime
    seen = []
    monkeypatch.setattr(r, "_chat", lambda base, msgs, max_tokens=1200: seen.append((msgs, max_tokens)) or "x")
    notes = "\n\n".join(["Q: something [https://a.b]\n" + "word " * 2000] * 9)
    r.verdict("X", "X Co", notes, level="deep")
    r.review("claims " * 1500, notes, level="deep")
    r.check("claims " * 500, notes, "figures " * 300, level="deep")
    for msgs, tokens in seen:
        assert not re.search(r"at most \d+ words|one or two", msgs[0]["content"].split("NUANCE CHECKLIST")[-1])
        assert sum(len(m["content"]) for m in msgs) / ai_runtime.CHARS_PER_TOKEN + tokens <= ai_runtime.CTX


def test_filing_sections_survive_split_headings_and_skip_cross_references():
    from vmi.data import filings
    body = "We sell widgets. " * 200
    text = (f"ITEM 1. BUSINESS 5 ITEM 1A. RISK FACTORS 9 \nITEM 1.\nBUS\nINESS\n{body}ITEM 1A. RISK FACTORS "
            f"see “Item 1. Business—Rules” {body * 2}Item 1A. Risk Factors")
    out = filings.section_text(text, *filings.SECTION_MARKS["10-K"]["business"])
    assert out.startswith("ITEM 1.\nBUS\nINESS") and len(out) < len(body) + 100
