"""The research pipeline: grades are parsed, the self-review can only lower the verdict, the optional checker sets the grade."""
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


def test_checker_can_raise(monkeypatch):
    _fake(monkeypatch, "MOAT VERDICT: NARROW — 6/10", "CHECKER VERDICT: WIDE")
    assert AR.opinion("X", "X", run_checker=True)["final_checked"] == "WIDE"


def test_no_readable_grade_counts_as_none(monkeypatch):
    _fake(monkeypatch, "CLAIMS: ... (no grade line)", "")
    assert AR.opinion("X", "X")["final"] == "NONE"


def test_grade_parsing_variants():
    assert AR._grade("MOAT VERDICT: **Wide** — 9/10", "MOAT VERDICT") == "WIDE"
    assert AR._grade("MOAT VERDICT: No moat — 2/10", "MOAT VERDICT") == "NONE"
    assert AR._grade("nothing here", "MOAT VERDICT") is None


def test_nuance_checklist_is_in_every_pass():
    n = len([ln for ln in AR.CHECKLIST.split("\n") if ln[:3].strip(". ").isdigit()])
    assert n == 14
    assert "CHECKLIST:" in AR.VERDICT_RULES                       # the verdict must answer every item
    assert "INDEPENDENT RE-VERIFICATION" in AR.REVIEW_RULES         # the final pass re-verifies each item itself
    assert "MY CHECKLIST" in AR.CHECK_RULES                         # the checker answers it independently first


def test_checklist_is_sent_with_each_pass(monkeypatch):
    seen = {}

    def fake(base_url, messages, max_tokens=1200):
        seen[messages[0]["content"][:30]] = messages[0]["content"]
        return "MOAT VERDICT: WIDE — 8/10 CHECKER VERDICT: WIDE"
    monkeypatch.setattr(AR, "_chat", fake)
    AR.verdict("X", "X", "notes")
    AR.review("v", "notes")
    AR.check("v", "notes", "figures")
    assert len(seen) >= 2 and all("NUANCE CHECKLIST" in v for v in seen.values())
