"""Scanner presets and scan-only rule overrides."""
import pytest
from fastapi.testclient import TestClient

from vmi import settings
from vmi.rules import RULES
from vmi.scanner import presets


def test_temporary_overrides_apply_and_restore():
    before = RULES.profitability.min_roic
    with settings.temporary({"profitability": {"min_roic": 0.2}}):
        assert RULES.profitability.min_roic == 0.2
    assert RULES.profitability.min_roic == before


def test_restores_even_when_the_block_fails():
    before = RULES.profitability.min_roe
    with pytest.raises(RuntimeError):
        with settings.temporary({"profitability": {"min_roe": 0.3}}):
            raise RuntimeError("boom")
    assert RULES.profitability.min_roe == before


def test_unknown_rule_is_rejected_without_changing_anything():
    before = RULES.profitability.min_roe
    with pytest.raises(ValueError):
        with settings.temporary({"profitability": {"min_roe": 0.3, "nope": 1}}):
            pass
    assert RULES.profitability.min_roe == before


def test_course_defaults_ignore_what_the_settings_page_changed():
    object.__setattr__(RULES.profitability, "min_roe", 0.2)               # the owner raised it in Settings
    try:
        with settings.temporary({}, course_defaults=True):
            assert RULES.profitability.min_roe == 0.12                      # Adam's number for this scan
        assert RULES.profitability.min_roe == 0.2
    finally:
        object.__setattr__(RULES.profitability, "min_roe", 0.12)


def test_preset_rule_changes_and_per_scan_edits_stack():
    ch, course = presets.rule_changes("adam_excellent", {"profitability": {"min_roic": 0.18}, "debt": {"max_debt_to_ebitda": 2}})
    assert course and ch["profitability"] == {"min_roe": 0.15, "min_roic": 0.18} and ch["debt"]["max_debt_to_ebitda"] == 2
    with pytest.raises(ValueError):
        presets.rule_changes("nope", None)


def test_presets_endpoint_and_start_merges_preset_params(temp_db, monkeypatch):
    from vmi.api import app as appmod
    from vmi.scanner import funnel

    c = TestClient(appmod.app)
    d = c.get("/api/scan/presets").json()
    assert {"current", "adam", "adam_excellent", "adam_speculative", "custom"} <= set(d["presets"])
    assert any(s["key"] == "min_roic" for s in d["schema"])
    seen = {}
    monkeypatch.setattr(funnel, "start_background", lambda params: seen.update(params) or {"running": True})
    c.post("/api/scan/start", json={"preset": "adam", "universe": "sp500", "min_price": 8,
                                    "rules": {"profitability": {"min_roic": 0.2}}})
    assert seen["min_market_cap"] == 10e9 and seen["include_speculative"] is False and seen["min_price"] == 8
    assert seen["rules"]["profitability"]["min_roic"] == 0.2 and seen["preset"] == "adam"


def test_scan_rows_carry_low_avg_high_growth():
    from vmi.analysis.pipeline import _growth_spread
    from vmi.analysis.valuation.growth import GrowthControls
    from vmi.data.models import Estimates

    est = Estimates("X", sources={"finviz": {"eps_growth_5y": 0.10}, "zacks": {"eps_growth_5y": 0.20}, "yahoo": {"eps_growth_5y": 0.15}})
    g = _growth_spread(est, GrowthControls())
    assert g["low"] == 0.10 and g["high"] == 0.20 and g["avg"] == pytest.approx(0.15) and g["n"] == 3
    assert _growth_spread(Estimates("Y"), GrowthControls())["n"] == 0


def test_all_presets_are_valid_and_sourced():
    from vmi.scanner.funnel import ScanParams
    ids = set(presets.PRESETS)
    assert {"adam_predictable", "adam_large_growth", "adam_dividend", "adam_turnaround", "adam_finviz"} <= ids
    for pid, pr in presets.PRESETS.items():
        ScanParams.from_dict(presets.resolved_params(pid))               # params are real scan options
        ch, course = presets.rule_changes(pid, None)
        with settings.temporary(ch, course_defaults=course):             # every rule override is a real rule
            pass
    assert presets.PRESETS["adam_turnaround"]["params"]["require_steps"] == [2, 4, 5]
    assert presets.PRESETS["adam_finviz"]["rules"]["profitability"]["min_roe"] == 0.10
