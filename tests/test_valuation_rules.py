"""Adam-rule helpers: cash-flow normalisation (steady_base), negative equity, growth-capex dip."""
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
