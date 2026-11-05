"""Adam-rule helpers: cash-flow normalisation (steady_base), negative equity, growth-capex dip."""
import pytest
from vmi.analysis.consistency import growth_capex_dip
from vmi.analysis.negative_equity import assess
from vmi.analysis.valuation.methods import steady_base


def test_steady_base_keeps_ttm_for_steady_compounder(fund_factory):
    f = fund_factory(fcf=[50, 58, 67, 77, 89, 100], ttm={"fcf": 118})       # ~15%/yr trend, TTM in line
    v, desc = steady_base(f, "fcf")
    assert v == 118 and desc.startswith("TTM")


def test_steady_base_sudden_jump_uses_last_fy(fund_factory):
    f = fund_factory(fcf=[9, 10, 9.5, 10.5, 10, 11], ttm={"fcf": 21})       # ASML-style 1.9x spike
    v, desc = steady_base(f, "fcf")
    assert v == 11 and "sudden jump" in desc


def test_steady_base_plunge_uses_average(fund_factory):
    f = fund_factory(fcf=[10, 11, 12, 13], ttm={"fcf": 5})
    v, desc = steady_base(f, "fcf")
    assert v == (10 + 11 + 12 + 13) / 4 and "average" in desc


def _buyback_co(fund_factory, fcf):
    return fund_factory(
        net_income=[1.6, 1.7, 1.9, 2.2, 2.4, 2.5], fcf=fcf, cfo=[1.6, 2.1, 2.7, 2.9, 3.0, 3.2],
        capex=[0.4, 0.45, 0.6, 0.8, 1.1, 1.4], buybacks=[1.5, 2.0, 3.0, 4.0, 4.5, 5.0],
        latest={"equity": -2.5, "treasury_stock": 1.0})


def test_negative_equity_buyback_compounder_passes(fund_factory):
    a = assess(_buyback_co(fund_factory, fcf=[1.2, 1.4, 1.6, 1.8, 1.9, 2.0]))
    assert a.applies and a.passes and a.buyback_driven


def test_negative_equity_growth_capex_dip_passes(fund_factory):
    # AZO-style: FCF falls because capex ramps while CFO keeps rising (doc Amazon rule)
    f = _buyback_co(fund_factory, fcf=[1.2, 1.65, 2.1, 2.1, 1.9, 1.8])
    ok, _ = growth_capex_dip(f)
    assert ok
    assert assess(f).passes


def test_negative_equity_from_losses_fails(fund_factory):
    f = fund_factory(net_income=[1, -0.5, 0.8, -1, 0.2, -0.3], fcf=[1, 0.5, 0.8, 0.2, 0.1, 0.0],
                     latest={"equity": -3.0})
    a = assess(f)
    assert a.applies and not a.passes and not a.buyback_driven


def test_positive_equity_not_applicable(fund_factory):
    assert not assess(fund_factory(net_income=[1, 2], latest={"equity": 5})).applies


def test_managed_care_is_not_an_insurer():
    from vmi.analysis.classify import BizType, classify

    assert classify(6324, "Hospital & Medical Service Plans", "Healthcare", "Healthcare Plans") == BizType.NORMAL
    assert classify(6331, "Fire, Marine & Casualty Insurance", "Financial Services",
                    "Insurance - Property & Casualty") == BizType.INSURANCE


def test_growth_blend_default_lowest_and_per_ticker_override():
    from vmi.analysis.valuation.growth import choose_growth
    from vmi.data.models import Estimates

    est = Estimates(ticker="X")
    est.sources = {"finviz": {"eps_growth_5y": 0.12}, "zacks": {"eps_growth_5y": 0.14},
                   "yahoo": {"eps_growth_5y": 0.10}}
    assert choose_growth(est).value == pytest.approx(0.10) and choose_growth(est).method == "lowest"
    assert choose_growth(est, blend="average").value == pytest.approx(0.12)
    assert choose_growth(est, blend="median").value == pytest.approx(0.12)
    assert choose_growth(est, blend="nonsense").method == "lowest"  # unknown → rule default


def test_disagreeing_sources_use_median_unless_set_per_ticker():
    from vmi.analysis.valuation.growth import choose_growth
    from vmi.data.models import Estimates

    est = Estimates(ticker="NVDA")
    est.sources = {"finviz": {"eps_growth_5y": 0.65}, "zacks": {"eps_growth_5y": 0.14}}
    auto = choose_growth(est)
    assert auto.method == "median" and auto.value == pytest.approx(0.395) and "disagree" in auto.notes[0]
    assert choose_growth(est, blend="lowest").value == pytest.approx(0.14)  # per-ticker choice wins


def test_uncertainty_haircut_for_growth_stocks_and_single_source(fund_factory):
    from vmi.analysis.valuation.methods import ValuationContext
    from vmi.data.models import Estimates

    def ctx(sources, **kw):
        est = Estimates(ticker="X")
        est.sources = {k: {"eps_growth_5y": v} for k, v in sources.items()}
        return ValuationContext(fund_factory(), est, 100.0, **kw)

    assert ctx({"finviz": 0.10, "zacks": 0.11}).haircut == 0.0                     # slow grower, 2 sources
    assert ctx({"finviz": 0.20, "zacks": 0.22}).haircut == pytest.approx(0.05)      # growth stock
    assert ctx({"finviz": 0.10}).haircut == pytest.approx(0.05)                     # single source
    assert ctx({"finviz": 0.20, "zacks": 0.22}, growth_override=0.2).haircut == 0.0  # human judgement
    assert ctx({"finviz": 0.20}, haircut_override=0.0).haircut == 0.0               # per-ticker override


def test_moat_is_evidence_until_reviewed(fund_factory):
    from vmi.analysis.classify import BizType
    from vmi.analysis.steps import moat_verdict, step3_moat
    from vmi.data.models import Estimates

    f = fund_factory(revenue=[100, 110, 121, 133, 146, 161], gross_profit=[60, 66, 73, 80, 88, 97],
                     net_income=[20, 22, 24, 27, 29, 32], cfo=[25, 27, 30, 33, 36, 40])
    est = Estimates(ticker="TEST")
    raw = step3_moat(f, est, True, BizType.NORMAL)
    assert raw.extra["reviewed"] is False and raw.extra["hint"] in ("wide", "narrow", "none")
    assert "UNREVIEWED" in raw.notes[1] and set(raw.extra["sources"]) >= {"brand", "scale"}
    reviewed = step3_moat(f, est, True, BizType.NORMAL, {"moat_grade": "none", "moat_score": 9})
    assert reviewed.extra["reviewed"] and not reviewed.passed  # the reviewer's verdict decides
    assert moat_verdict({"moat_sources": ["brand", "scale", "switching_costs"]})["grade"] == "narrow"
    assert moat_verdict({"moat_score": 8})["grade"] == "wide"
    assert moat_verdict({"moat": {"sources": ["a", "b", "c", "d"]}})["grade"] == "wide"  # legacy format
    assert moat_verdict({}) is None
