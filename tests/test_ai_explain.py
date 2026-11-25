"""Offline coverage for the independent overview and its settings."""
import pytest
from fastapi.testclient import TestClient

from vmi import ai_explain, ai_helper, ai_settings
from vmi.api.app import app
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
def model(monkeypatch):
    prompts = []
    monkeypatch.setattr(ai_explain.research, "answer", lambda *a, **kw: "A filing says this. [https://example.com/filing]")

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


def test_overview_cache_respects_depth_refresh_and_opt_out(company, model):
    chat, prompts = model
    ai_explain.explain(company, chat)
    assert ai_explain.explain(company, chat)["cached"] and len(prompts) == 2
    assert not ai_explain.explain(company, chat, fresh=True)["cached"] and len(prompts) == 4
    assert not ai_explain.explain(company, chat, use_cache=False)["cached"] and len(prompts) == 6
    assert not ai_explain.explain(company, chat, level="standard")["cached"] and len(prompts) == 11
    assert not ai_explain.explain(company, chat, model="different")["cached"] and len(prompts) == 13


def test_settings_and_overview_endpoints(company, model, monkeypatch, tmp_path):
    chat, _ = model
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    client = TestClient(app)
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
    assert client.post("/api/analysis/TEST/ai-explain").json()["level"] == "deep"
    assert client.post("/api/analysis/TEST/ai-explain?level=quick").json()["level"] == "quick"
