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
    from vmi.analysis.valuation.growth import GrowthControls, choose_growth
    from vmi.data.models import Estimates

    est = Estimates(ticker="X")
    est.sources = {"finviz": {"eps_growth_5y": 0.20}, "zacks": {"eps_growth_5y": 0.24},
                   "yahoo": {"eps_growth_5y": 0.18}}
    assert choose_growth(est).value == pytest.approx(0.18) and choose_growth(est).method == "lowest"  # growth stock
    assert choose_growth(est, controls=GrowthControls(blend="average")).value == pytest.approx(0.2067, abs=1e-4)
    assert choose_growth(est, controls=GrowthControls(blend="median")).value == pytest.approx(0.20)
    assert choose_growth(est, controls=GrowthControls(blend="nonsense")).method == "lowest"  # unknown → rule default
    slow = Estimates(ticker="Y")
    slow.sources = {"finviz": {"eps_growth_5y": 0.08}, "zacks": {"eps_growth_5y": 0.10},
                    "yahoo": {"eps_growth_5y": 0.09}}
    assert choose_growth(slow).method == "median" and choose_growth(slow).value == pytest.approx(0.09)  # defensive


def test_disagreeing_sources_use_median_unless_set_per_ticker():
    from vmi.analysis.valuation.growth import GrowthControls, choose_growth
    from vmi.data.models import Estimates

    est = Estimates(ticker="NVDA")
    est.sources = {"finviz": {"eps_growth_5y": 0.65}, "zacks": {"eps_growth_5y": 0.14}}
    auto = choose_growth(est)
    assert auto.method == "median" and auto.value == pytest.approx(0.395) and "disagree" in auto.notes[0]
    assert choose_growth(est, controls=GrowthControls(blend="lowest")).value == pytest.approx(0.14)  # per-ticker choice wins


def test_uncertainty_haircut_for_growth_stocks_and_single_source(fund_factory):
    from vmi.analysis.valuation.methods import ValuationContext
    from vmi.data.models import Estimates

    def ctx(sources, **kw):
        est = Estimates(ticker="X")
        est.sources = {k: {"eps_growth_5y": v} for k, v in sources.items()}
        return ValuationContext(fund_factory(), est, 100.0, **kw)

    assert ctx({"finviz": 0.10, "zacks": 0.11}).haircut == 0.0                     # slow grower, 2 sources
    assert ctx({"finviz": 0.20, "zacks": 0.22}).haircut == pytest.approx(0.075)     # growth stock
    assert ctx({"finviz": 0.10}).haircut == pytest.approx(0.075)                    # single source
    assert ctx({"finviz": 0.20, "zacks": 0.22}, growth_override=0.2).haircut == 0.0  # human judgement
    assert ctx({"finviz": 0.20}, haircut_override=0.0).haircut == 0.0               # per-ticker override


def test_moat_follows_adam_until_reviewed(fund_factory):
    from vmi.analysis.classify import BizType
    from vmi.analysis.steps import moat_verdict, step3_moat
    from vmi.data.models import Estimates

    f = fund_factory(revenue=[100, 110, 121, 133, 146, 161], gross_profit=[60, 66, 73, 80, 88, 97],
                     net_income=[20, 22, 24, 27, 29, 32], cfo=[25, 27, 30, 33, 36, 40])
    est = Estimates(ticker="TEST")
    raw = step3_moat(f, est, True, BizType.NORMAL)
    assert raw.extra["reviewed"] is False and raw.passed and "UNREVIEWED" in raw.notes[1]
    assert not step3_moat(f, est, False, BizType.NORMAL).passed          # 10-year downtrend = no competitive advantage
    miner = Estimates(ticker="X", industry="Gold")
    assert not step3_moat(f, miner, True, BizType.NORMAL).passed          # structurally no-moat industry
    assert all(c.passed is None for c in raw.checks if "margin" in c.name)  # no invented margin thresholds
    reviewed = step3_moat(f, est, True, BizType.NORMAL, {"moat_grade": "none", "moat_score": 9})
    assert reviewed.extra["reviewed"] and not reviewed.passed             # the reviewer's verdict decides
    # every supplied test must hold: grade wide/narrow, ≥3 sources, score ≥7 (6/10 is 'not strong enough')
    assert moat_verdict({"moat_grade": "narrow", "moat_score": 6})["passes"] is False
    assert moat_verdict({"moat_grade": "wide", "moat_sources": ["a", "b", "c"], "moat_score": 8})["passes"] is True
    assert moat_verdict({"moat_sources": ["a", "b"]})["passes"] is False
    assert moat_verdict({"moat_sources": ["a", "b", "c"]})["grade"] is None  # sources never imply wide vs narrow
    assert moat_verdict({"moat": {"sources": ["a", "b", "c"], "grade": "wide"}})["passes"] is True  # legacy format
    assert moat_verdict({}) is None


def test_moat_evidence_history_decline_age_pricing_power_and_recurring_revenue(fund_factory):
    from datetime import date

    from vmi.analysis import moat_evidence as ME
    from vmi.data.models import Point

    years = tuple(range(2017, 2026))
    steady = fund_factory(years=years, revenue=[100] * 9, gross_profit=[60, 61, 62, 61, 62, 63, 62, 63, 64],
                          deferred_revenue=[10, 11, 12, 14, 16, 18, 21, 24, 27], rd=[8] * 9)
    sliding = fund_factory(years=years, revenue=[100] * 9, gross_profit=[60] * 6 + [59.9, 59.8, 59.7],
                           fcf=[20, 19, 18, 17, 16, 15, 14, 13, 12])
    assert ME.margin_decline(steady) == []
    decline = ME.margin_decline(sliding)  # no minimum size (Adam gives none); FCF margin is not a profit margin
    assert len(decline) == 1 and "gross margin fell 2 years in a row" in decline[0]
    sliding.ratios["roic"] = [Point("2023-12-31", 0.20), Point("2024-12-31", 0.18), Point("2025-12-31", 0.15)]
    assert any("ROIC fell 2 years" in r for r in ME.margin_decline(sliding))
    assert ME.margin_history(steady)["gross margin"][2025] == 0.64
    sw = ME.switching_costs(steady)
    assert sw["available"] and sw["deferred_trend"] == "rising" and not ME.switching_costs(sliding)["available"]
    assert ME.intensity(steady)["rd"]["latest"] == 0.08

    # approved pricing-power test: margin in 2021-23 vs the three years before, operating margin as fallback
    held = fund_factory(years=years, revenue=[100] * 9, gross_profit=[60, 60, 61, 60, 59, 60, 61, 62, 62])
    cut = fund_factory(years=years, revenue=[100] * 9, gross_profit=[60, 60, 60, 60, 52, 48, 50, 55, 58])
    assert ME.pricing_power(held)["held"] is True and ME.pricing_power(cut)["held"] is False
    assert ME.pricing_power(fund_factory(years=(2024, 2025), revenue=[1, 1], gross_profit=[.5, .5]))["held"] is None
    no_gross = fund_factory(years=years, revenue=[100] * 9, operating_income=[30, 30, 31, 30, 29, 30, 31, 30, 30])
    assert ME.pricing_power(no_gross)["held"] is True and "operating" in ME.pricing_power(no_gross)["measure"]

    # approved review age: older than 365 days, or no date, is due; nothing is due without a verdict
    today = date(2026, 11, 5)
    assert ME.review_status("2024-01-01", steady, today=today)["reasons"] == ["verdict is 1039 days old (limit 365)"]
    assert not ME.review_status("2026-06-01", steady, today=today)["due"]
    assert ME.review_status(None, steady)["reasons"] == ["no review date recorded"]
    assert not ME.review_status(None, sliding, reviewed=False)["due"]
    from vmi.rules import RULES
    off = RULES.with_overrides({"moat": {"review_alerts_enabled": False}})  # owner switch: alert off entirely
    assert not ME.review_status("2024-01-01", sliding, off, today=today)["due"]



def test_no_moat_industry_matches_whole_words_only():
    from vmi.analysis.classify import is_no_moat_industry as no_moat

    assert all(map(no_moat, ["Airlines", "Marine Shipping", "Gold", "Oil & Gas E&P", "Steel"]))
    assert not any(map(no_moat, ["Fire, Marine & Casualty Insurance", "Security & Commodity Exchanges",
                                 "Goldman Sachs", "Software - Application"]))


def test_step5_two_of_three_core_ratios_and_financials_exempt(fund_factory):
    from vmi.analysis.classify import BizType
    from vmi.analysis.steps import step5_debt

    # ServiceNow-like: current ratio < 1 (deferred revenue), no debt, strong cash flow → passes 2 of 3
    f = fund_factory(cfo=[50, 60, 70, 80, 90], ttm={"cfo": 90.0, "ebitda": 100.0, "interest_expense": 0.0},
                     latest={"current_assets": 90.0, "current_liabilities": 400.0})
    assert step5_debt(f, BizType.NORMAL).passed
    assert step5_debt(f, BizType.INSURANCE).passed and step5_debt(f, BizType.INSURANCE).checks == []


def _ctx(f, growth=None):
    from vmi.analysis.valuation.methods import ValuationContext
    from vmi.data.models import Estimates

    est = Estimates(ticker="X")
    if growth is not None:
        est.sources = {"finviz": {"eps_growth_5y": growth}, "zacks": {"eps_growth_5y": growth}}
    return ValuationContext(f, est, 100.0)


def test_profitable_speculative_growth_is_valued_by_dcf_not_psg(fund_factory):
    """Adam: P/S growth only for companies without consistent profits and cash flow (l.2264, l.2858)."""
    from vmi.analysis.classify import BizType
    from vmi.analysis.valuation.selector import candidate_methods

    profitable = fund_factory(revenue=[1, 1.5, 2.2, 3.3, 5], net_income=[-1, -.5, .2, .5, 1], cfo=[-.2, .3, .6, 1, 1.5],
                              fcf=[-.3, .2, .5, .9, 1.4])
    loss_making = fund_factory(revenue=[1, 1.5, 2.2, 3.3, 5], net_income=[-1, -.8, -.6, -.5, -.4],
                               cfo=[-.5, -.4, -.2, -.1, -.05], fcf=[-.6, -.5, -.3, -.2, -.1])
    assert candidate_methods(_ctx(profitable), BizType.SPECULATIVE)[0][0] == "dcf_fcf"
    assert candidate_methods(_ctx(loss_making), BizType.SPECULATIVE)[0][0] == "psg"


def test_inconsistent_cfo_and_profit_fall_back_to_price_to_sales(fund_factory):
    """Fails Step 1; reference value by P/S, the one method Adam names for inconsistent profits (l.1510)."""
    from vmi.analysis.classify import BizType
    from vmi.analysis.valuation.selector import REFERENCE_ONLY, candidate_methods

    choppy = fund_factory(revenue=[10, 8, 11, 7, 12], net_income=[1, -1, 2, -.5, 1], cfo=[2, -1, 3, -.5, 2],
                          fcf=[1, -2, 2, -1, 1])
    order, reason = candidate_methods(_ctx(choppy), BizType.NORMAL)
    assert order[0] == "ps_mean" and reason == REFERENCE_ONLY


def test_turnaround_is_valued_on_the_multi_year_average_base(fund_factory):
    """Adam l.2898 (turnaround) + l.2502 (abnormal latest year → average of the last 3-4 years)."""
    from vmi.analysis.classify import BizType
    from vmi.analysis.valuation.selector import TURNAROUND, candidate_methods, value_company

    f = fund_factory(revenue=[50, 55, 60, 66, 70, 64], net_income=[5, 5.6, 6.2, 7, 7.5, 3.5],
                     cfo=[6, 7, 5, 8, 9, 4], fcf=[5, 6, 4, 7, 8, 3], shares_diluted=[1] * 6)
    order, reason = candidate_methods(_ctx(f), BizType.NORMAL)
    assert reason == TURNAROUND and order[0] == "dcf_fcf"
    rep = value_company(_ctx(f, growth=0.08), BizType.NORMAL)
    assert rep.selected == "dcf_fcf" and "average" in rep.methods["dcf_fcf"].inputs["base_desc"]
