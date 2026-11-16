"""Normalised (multi-year average) mode for the Step 1/4/5 numbers, and the data-checkable-steps drop."""
from dataclasses import replace

import pytest

from tests.conftest import make_fund
from vmi.analysis import steps as S
from vmi.analysis.classify import BizType
from vmi.data.models import Point
from vmi.rules import RULES


def rules_with(**kw):
    return RULES.with_overrides({"normalise": kw})


def fund_with_roe(values):
    f = make_fund(revenue=[100] * 6, net_income=[10] * 6)
    f.ratios["roe"] = [Point(end=f"{2020 + i}-12-31", value=v, fy=2020 + i) for i, v in enumerate(values)]
    f.ratios["roic"] = [Point(end=f"{2020 + i}-12-31", value=0.20, fy=2020 + i) for i in range(len(values))]
    return f


def check(res, name):
    return next(c for c in res.checks if c.name == name)


def test_one_bad_year_fails_roe_latest_but_passes_when_normalised():
    f = fund_with_roe([0.20, 0.22, 0.21, 0.23, 0.04])           # latest year distorted (write-off)
    assert not check(S.step4_profitability(f, BizType.NORMAL, RULES), "roe").passed
    res = S.step4_profitability(f, BizType.NORMAL, rules_with(enabled=True, years=3))
    roe = check(res, "roe")
    assert roe.passed and roe.value == pytest.approx((0.21 + 0.23 + 0.04) / 3, abs=1e-3) and "normalised" in roe.note


def test_normalised_current_ratio_and_debt_ratios():
    f = make_fund(revenue=[100] * 6, net_income=[10] * 6, cfo=[20] * 6, ebitda=[30, 30, 30, 30, 10], operating_income=[25] * 6,
                  current_assets=[150, 150, 150, 150, 80], current_liabilities=[100] * 5, lt_debt=[40] * 5, st_debt=[0] * 5)
    f.latest = {"current_assets": 80, "current_liabilities": 100, "lt_debt": 40, "st_debt": 0}
    plain = S.step5_debt(f, BizType.NORMAL, None, RULES)
    assert check(plain, "current_ratio").passed is False and check(plain, "debt_to_ebitda").passed is False   # 0.8 and 4.0
    norm = S.step5_debt(f, BizType.NORMAL, None, rules_with(enabled=True, years=3))
    assert check(norm, "current_ratio").passed and check(norm, "debt_to_ebitda").passed                     # ~1.2 and ~1.7


def test_off_by_default():
    assert RULES.normalise.enabled is False and RULES.normalise.years == 3


def test_failed_required_steps_text_and_scan_drop():
    from vmi.scanner import funnel

    rep = {"steps": [{"step": 1, "passed": False, "checks": [{"name": "earnings_consistent", "passed": False},
                                                            {"name": "cfo_consistent", "passed": True}]},
                     {"step": 3, "passed": False, "checks": []}, {"step": 4, "passed": True, "checks": []}]}
    assert funnel.failed_required_steps(rep, [1, 2, 4, 5]) == "Step 1: earnings_consistent"
    assert funnel.failed_required_steps(rep, [4]) is None and funnel.failed_required_steps(rep, []) is None


def test_stage_deep_drops_failures_of_required_steps(monkeypatch):
    from vmi.scanner import funnel

    def fake(sym, with_technicals=True, overrides=None):
        ok = sym != "BAD"
        steps = [{"step": k, "passed": ok or k != 1, "checks": [{"name": "earnings_consistent", "passed": ok or k != 1}]} for k in range(1, 8)]
        return {"ticker": sym, "name": sym, "steps": steps, "metrics": {}, "great_business": ok, "valuation": {}}
    import vmi.analysis.pipeline as pl
    monkeypatch.setattr(pl, "analyse_ticker", fake)
    funnel.STATE.__init__()
    cands = [funnel.Candidate("GOOD", "g", None), funnel.Candidate("BAD", "b", None)]
    kept = funnel.stage_deep(cands, funnel.ScanParams(universe="list", require_steps=[1, 2, 4, 5], workers=1))
    assert [c.symbol for c in kept] == ["GOOD"] and [r["symbol"] for r in funnel.STATE.results] == ["GOOD"]
    assert funnel.STATE.dropped["BAD"] == "Step 1: earnings_consistent"
