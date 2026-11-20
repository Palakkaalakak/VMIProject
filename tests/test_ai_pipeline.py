"""Code-driven research: ranking, passage selection, plan parsing and the full loop with fake search/pages/model (offline)."""
from vmi import ai_pipeline as P


def test_primary_sources_rank_first_and_junk_is_dropped():
    urls = ["https://www.youtube.com/watch?v=1", "https://randomblog.example/post", "https://en.wikipedia.org/wiki/Visa_Inc.",
            "https://investor.visa.com/annual-report", "https://www.sec.gov/Archives/x"]
    ranked = sorted(urls, key=lambda u: -P._score(u, "Visa Inc.", "V"))
    assert ranked[0] in ("https://investor.visa.com/annual-report", "https://www.sec.gov/Archives/x")
    assert P._score("https://www.youtube.com/watch?v=1", "Visa Inc.", "V") == -10


def test_passages_keep_the_relevant_paragraphs():
    text = "Intro about the weather today and nothing else of use.\n\n" \
           "Visa competes with Mastercard; together they hold most of the card network market share worldwide.\n\n" \
           "The company cafeteria serves lunch from noon and has new chairs."
    out = P.passages(text, "What is Visa's market share versus competitors?", "Visa")
    assert out.startswith("Visa competes with Mastercard")


def test_plan_parsing_json_and_bullets():
    assert P._json_list('Sure: ["Q one about rivals?", "Q two about prices?"]') == ["Q one about rivals?", "Q two about prices?"]
    assert P._json_list("1. first question here\n2. second question here") == ["first question here", "second question here"]


def test_full_loop_with_fakes(monkeypatch):
    calls = []
    monkeypatch.setattr(P, "search", lambda q, n, t: [("Title", "https://example.org/a", "snippet"), ("T2", "https://example.org/b", "s2")])
    monkeypatch.setattr(P, "page_text", lambda u: ("Example Corp leads its market with 60% share and raised prices 5% a year. " * 10))
    monkeypatch.setattr(P, "sec_annual_report", lambda t: "ANNUAL REPORT [https://sec.gov/x]\nCompany's own Competition section: few rivals [https://sec.gov/x]")

    def chat(msgs, max_tokens):
        content = msgs[-1]["content"]
        if "research questions" in content:
            return '["Who are the competitors of Example Corp and their market share?", "Has Example Corp raised prices?"]'
        if "follow-up questions" in content:
            return "[]"
        return "- Example Corp has 60% share [https://example.org/a]"

    notes = P.research("EXC", "Example Corp", chat, on_tool=lambda n, a: calls.append(n), figures="ROE 30% [analysis page]")
    assert "APP FIGURES [analysis page]" in notes and "ANNUAL REPORT" in notes
    assert notes.count("Q: ") >= 2 and "[https://example.org/a]" in notes
    assert calls.count("read_page") >= 2 and calls.count("web_search") >= 2
