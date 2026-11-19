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
    assert roe.passed and roe.value == pytest.approx((0.21 + 0.23 + 0.04) / 3, abs=1e-3) and "NORMALISED" in roe.note


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

    def fake(sym, with_technicals=True, overrides=None, **_):
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


def test_normalised_mode_is_labelled_everywhere_it_matters():
    f = fund_with_roe([0.20, 0.22, 0.21, 0.23, 0.04])
    on = S.step4_profitability(f, BizType.NORMAL, rules_with(enabled=True, years=3))
    assert "(NORMALISED)" in check(on, "roe").note and "(NORMALISED)" in check(on, "roic").note
    off = S.step4_profitability(f, BizType.NORMAL, RULES)
    assert "NORMALISED" not in check(off, "roe").note


def test_settings_page_save_turns_normalised_mode_on_in_the_live_rules(tmp_path, monkeypatch):
    """The path the Settings page uses (PUT /api/settings -> settings.update) must change the live rules at once."""
    from vmi import settings

    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "rules_settings.json")
    try:
        settings.update({"normalise": {"enabled": "true", "years": "4"}})
        assert RULES.normalise.enabled is True and RULES.normalise.years == 4
        f = fund_with_roe([0.20, 0.22, 0.21, 0.23, 0.04])
        res = S.step4_profitability(f, BizType.NORMAL, RULES)           # the module-level default rules, as the app uses
        assert "(NORMALISED)" in check(res, "roe").note
    finally:
        settings.update({"normalise": {"enabled": None, "years": None}})
    assert RULES.normalise.enabled is False


def test_ultra_excellent_strict_rules():
    from vmi.scanner import presets
    from vmi import settings

    u = presets.PRESETS["adam_ultra"]
    ch, course = presets.rule_changes("adam_ultra", None)
    assert ch["debt"]["min_core_ratios_passed"] == 3 and ch["debt"]["require_interest_coverage"] and ch["debt"]["min_interest_coverage"] == 5.0
    assert ch["profitability"]["min_roe"] == 0.15 and ch["profitability"]["min_roic"] == 0.15 and ch["track"]["min_years"] == 10
    with settings.temporary(ch, course_defaults=course):
        # all three core ratios needed, plus interest coverage
        f = make_fund(revenue=[100] * 6, net_income=[10] * 6, cfo=[20] * 6, ebitda=[30] * 6, operating_income=[25] * 6,
                      interest_expense=[10] * 6, current_assets=[150] * 6, current_liabilities=[100] * 6, lt_debt=[40] * 6, st_debt=[0] * 6)
        f.latest = {"current_assets": 150, "current_liabilities": 100, "lt_debt": 40, "st_debt": 0}
        res = S.step5_debt(f, BizType.NORMAL, None, RULES)
        assert check(res, "interest_coverage").passed is False and not res.passed            # coverage 2.5x < 5x
        f2 = make_fund(revenue=[100] * 6, net_income=[10] * 6, cfo=[20] * 6, ebitda=[30] * 6, operating_income=[60] * 6,
                       interest_expense=[5] * 6, current_assets=[150] * 6, current_liabilities=[100] * 6, lt_debt=[40] * 6, st_debt=[0] * 6)
        f2.latest = f.latest
        assert S.step5_debt(f2, BizType.NORMAL, None, RULES).passed                           # 12x coverage, all 3 core ratios ok
    assert RULES.debt.require_interest_coverage is False                                      # restored


def test_speculative_step1_exception_can_be_switched_off():
    f = make_fund(revenue=[1, 1.5, 2.2, 3.3, 5, 7], net_income=[1, -1, -2, -3, -2, 1], cfo=[1, -.2, -.5, -.6, -.1, 1.5],
                  gross_profit=[.5, .8, 1.2, 1.7, 2.5, 3.5])
    f.quarterly["cfo"] = [Point(end="2026-03-31", value=1.0), Point(end="2026-06-30", value=1.2)]
    f.quarterly["net_income"] = [Point(end="2026-03-31", value=.5), Point(end="2026-06-30", value=.6)]
    assert S.step1_track_record(f, BizType.SPECULATIVE, RULES).passed                       # Adam's exception: turned positive
    strict = RULES.with_overrides({"speculative": {"step1_exception": False}})
    res = S.step1_track_record(f, BizType.SPECULATIVE, strict)
    assert not res.passed and not any(c.name == "speculative_turned_positive" for c in res.checks)
