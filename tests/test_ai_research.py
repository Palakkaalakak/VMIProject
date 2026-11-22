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


def test_checker_never_raises_to_wide(monkeypatch):
    _fake(monkeypatch, "MOAT VERDICT: NARROW — 6/10", "CHECKER VERDICT: WIDE")      # over-grading is the worst error: capped at NARROW
    assert AR.opinion("X", "X", run_checker=True)["final_checked"] == "NARROW"
    _fake(monkeypatch, "MOAT VERDICT: NONE — 3/10", "CHECKER VERDICT: NARROW")
    assert AR.opinion("X", "X", run_checker=True)["final_checked"] == "NARROW"


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


def test_three_levels_grow_in_depth():
    sizes = {}
    for name, cfg in AR.LEVELS.items():
        sizes[name] = len(cfg["adam"]) + len(cfg["checklist"])
        assert "FUTURE" in cfg["checklist"] and "14" in cfg["checklist"]
    assert sizes["quick"] < sizes["standard"] <= sizes["deep"]
    q, s_, d = AR.LEVELS["quick"], AR.LEVELS["standard"], AR.LEVELS["deep"]
    assert q["questions"] < s_["questions"] <= d["questions"] and q["followups"] < s_["followups"] <= d["followups"]


def test_unknown_level_falls_back_to_quick():
    assert AR._level("nonsense") is AR.LEVELS[AR.DEFAULT_LEVEL] and AR._level(None) is AR.LEVELS["quick"]


def test_opinion_passes_the_level_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(AR, "research", lambda t, n, base_url=None, on_tool=None, level=None: seen.setdefault("research", level) or "notes")
    monkeypatch.setattr(AR, "verdict", lambda *a, level=None, **k: seen.setdefault("verdict", level) and "MOAT VERDICT: WIDE — 8/10")
    monkeypatch.setattr(AR, "review", lambda v, n, base_url=None, level=None: seen.setdefault("review", level) and "MOAT VERDICT: WIDE — 8/10")
    r = AR.opinion("X", "X", level="standard")
    assert seen == {"research": "standard", "verdict": "standard", "review": "standard"} and r["level"] == "standard"


def test_ai_server_safeguards(monkeypatch):
    from vmi import ai_runtime as RT
    monkeypatch.setattr(RT, "free_ram_mb", lambda: 500.0)
    monkeypatch.setattr(RT, "gpu_state", lambda: {"temp": 60.0, "free_mb": 9000.0})
    assert "memory" in RT._danger()
    monkeypatch.setattr(RT, "free_ram_mb", lambda: 9000.0)
    monkeypatch.setattr(RT, "gpu_state", lambda: {"temp": 90.0, "free_mb": 9000.0})
    assert "°C" in RT._danger()
    monkeypatch.setattr(RT, "gpu_state", lambda: {"temp": 60.0, "free_mb": 100.0})
    assert "GPU memory" in RT._danger()
    monkeypatch.setattr(RT, "gpu_state", lambda: {"temp": 60.0, "free_mb": 9000.0})
    assert RT._danger() == ""
