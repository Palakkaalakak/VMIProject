"""track.min_years above the 6-point recent window (ultra preset, the analysis '10-year only' switch) judges the whole record."""
from dataclasses import replace

from tests.conftest import make_fund
from vmi.analysis.consistency import series_trend
from vmi.rules import RULES


def _rules(min_years):
    return RULES.with_overrides({"track": {"min_years": min_years}})


def test_ten_year_record_can_pass():
    f = make_fund(revenue=[100 * 1.1 ** i for i in range(10)])
    assert series_trend(f, "revenue", _rules(10)).consistent


def test_short_record_fails_a_ten_year_rule_but_passes_five():
    f = make_fund(years=tuple(range(2021, 2026)), revenue=[100 * 1.1 ** i for i in range(5)])
    t = series_trend(f, "revenue", _rules(10))
    assert not t.consistent and "only 5 years" in t.reason
    assert series_trend(f, "revenue", _rules(5)).consistent


def test_ten_year_rule_rejects_an_old_collapse():
    f = make_fund(revenue=[100, 90, 80, 70, 60, 100, 110, 120, 130, 150])
    assert series_trend(f, "revenue", _rules(5)).consistent        # the last 5 years look fine
    assert not series_trend(f, "revenue", _rules(10)).consistent   # but the 10-year record has too many down years


def test_brand_or_pricing_power_is_one_source():
    from vmi.analysis.steps import moat_verdict
    two = moat_verdict({"moat_grade": "wide", "moat_score": 8, "moat_sources": ["brand", "pricing_power", "scale"]})
    assert two["passes"] is False                                   # brand + pricing power + scale = 2 sources, Adam wants 3
    three = moat_verdict({"moat_grade": "wide", "moat_score": 8, "moat_sources": ["pricing_power", "scale", "barriers"]})
    assert three["passes"] is True
