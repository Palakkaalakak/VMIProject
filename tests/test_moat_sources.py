"""Moat evidence that needs the network (peers via SEC frames, annual-report excerpts): offline with fakes."""
from datetime import date

import pytest

from vmi.analysis import moat_peers
from vmi.data import filings


def test_latest_calendar_year_respects_filing_lag():
    assert moat_peers.latest_calendar_year(date(2026, 11, 5)) == 2025
    assert moat_peers.latest_calendar_year(date(2026, 1, 20)) == 2024


def test_peer_comparison_ranks_and_derives_gross_margin(monkeypatch):
    rows = [{"symbol": s, "name": s, "sub_industry": "Payments", "cik": c} for s, c in (("AAA", 1), ("BBB", 2), ("CCC", 3))]
    monkeypatch.setattr(moat_peers.universe, "sp500", lambda: rows)
    data = {"CY2025": {"revenue": {1: 100.0, 2: 60.0, 3: 40.0}, "gross_profit": {1: 70.0},
                       "cost_of_revenue": {2: 30.0}, "operating_income": {1: 40.0, 2: 12.0, 3: 12.0}, "net_income": {}},
            "CY2022": {"revenue": {1: 80.0, 2: 60.0, 3: 50.0}}}
    monkeypatch.setattr(moat_peers.sec, "frame_concept", lambda concept, period: data[period].get(concept, {}))
    out = moat_peers.compare("AAA")
    assert out["basis"].startswith("S&P 500 sub-industry") and [r["symbol"] for r in out["rows"]] == ["AAA", "BBB", "CCC"]
    assert out["rows"][1]["gross_margin"] == pytest.approx(0.5)  # 1 − cost/revenue
    assert out["summary"]["ranks"] == {"revenue": 1, "operating_margin": 1, "growth_3y": 1}
    assert out["summary"]["top_dog_hint"] and out["summary"]["share"] == pytest.approx(0.5)
    listed = moat_peers.compare("AAA", ["CCC"])
    assert listed["basis"] == "peers listed by the reviewer" and len(listed["rows"]) == 2
    assert moat_peers.compare("ZZZ")["rows"] == [] and "not an S&P 500" in moat_peers.compare("ZZZ")["basis"]


FILING_TEXT = """Business
Competition
We compete with several large and many small companies in each market. The principal competitive factors are
performance, price, breadth of product offerings, software support and manufacturing capability. Several of our
competitors have substantially greater financial resources and may be able to respond faster to new technology.
Customers
Two direct customers accounted for 17% and 16% of our revenue for fiscal 2025. Revenue from customers
headquartered outside of the United States accounted for 31% of total revenue.
"""


def test_filing_excerpts_extraction():
    comp = filings.competition_passage(FILING_TEXT)
    assert comp.startswith("We compete with several") and "principal competitive factors" in comp
    sentences = filings.concentration_sentences(FILING_TEXT)
    assert len(sentences) == 1 and "17% and 16%" in sentences[0]  # the geography split is not concentration
    assert filings.competition_passage("Competition\nshort.") == ""
