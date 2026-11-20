"""The research pipeline: grades are parsed, and the checker can only lower the verdict (owner rule: the lower opinion wins)."""
from vmi import ai_research as AR


def _fake(monkeypatch, verdict_text, check_text):
    monkeypatch.setattr(AR, "research", lambda *a, **k: "- leader in payments [https://x]\nOPEN QUESTIONS: none")
    monkeypatch.setattr(AR, "verdict", lambda *a, **k: verdict_text)
    monkeypatch.setattr(AR, "review", lambda v, *a, **k: v)
    monkeypatch.setattr(AR, "check", lambda *a, **k: check_text)
    monkeypatch.setattr(AR.ai_tools, "app_analysis", lambda t: "figures")


def test_checker_lowers_wide_to_none(monkeypatch):
    _fake(monkeypatch, "CLAIMS:\n- a [x]\nREASONING: r\nMOAT VERDICT: WIDE — 8/10", "CHECKS:\n- a -> UNSUPPORTED\nCHECKER VERDICT: NONE")
    r = AR.opinion("PYPL", "PayPal", run_checker=True)
    assert (r["verdict_grade"], r["checker_grade"], r["final_checked"]) == ("WIDE", "NONE", "NONE")


def test_checker_is_off_by_default(monkeypatch):
    _fake(monkeypatch, "MOAT VERDICT: WIDE — 8/10", "CHECKER VERDICT: NONE")
    r = AR.opinion("X", "X")
    assert r["final"] == "WIDE" and "checker_grade" not in r


def test_self_review_can_only_lower(monkeypatch):
    _fake(monkeypatch, "MOAT VERDICT: WIDE — 8/10", "")
    monkeypatch.setattr(AR, "review", lambda *a, **k: "MOAT VERDICT: NARROW — 6/10")
    assert AR.opinion("X", "X")["final"] == "NARROW"


def test_checker_cannot_raise(monkeypatch):
    _fake(monkeypatch, "MOAT VERDICT: NARROW — 6/10", "CHECKER VERDICT: WIDE")
    assert AR.opinion("X", "X", run_checker=True)["final_checked"] == "NARROW"


def test_grade_parsing_variants():
    assert AR._grade("MOAT VERDICT: **Wide** — 9/10", "MOAT VERDICT") == "WIDE"
    assert AR._grade("MOAT VERDICT: No moat — 2/10", "MOAT VERDICT") == "NONE"
    assert AR._grade("nothing here", "MOAT VERDICT") is None
