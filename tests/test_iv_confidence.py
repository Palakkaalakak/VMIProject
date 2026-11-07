from dataclasses import replace

from vmi.analysis.iv_confidence import iv_confidence
from vmi.rules import RULES

V = RULES.valuation


def _m(**kw):
    return {k: {"applicable": True, "intrinsic_value": v} for k, v in kw.items()}


def _flag(methods, selected="dcf_fcf", growth=0.10, fcf=100, ni=80, ni_fy=80, rules=V):
    return iv_confidence(methods, selected, growth, fcf, ni, ni_fy, rules)


def test_selected_far_above_a_credible_alternative_is_flagged():
    r = _flag(_m(dcf_fcf=300, dni=150, ps_mean=190))
    assert r["low"] and r["ratio"] == 2.0 and "dni" in r["reasons"][0]


def test_agreeing_methods_are_not_flagged():
    assert not _flag(_m(dcf_fcf=100, dni=110, ps_mean=120))["low"]


def test_ps_is_ignored_for_fast_growers_and_dni_when_fcf_far_above_ni():
    m = _m(dcf_fcf=300, dni=100, ps_mean=100)
    assert not _flag(m, growth=0.30, fcf=500, ni=80)["low"]
    assert _flag(m, growth=0.30, fcf=100, ni=80)["low"]      # NI credible again


def test_net_income_jump_is_not_a_credible_comparator():
    m = _m(dcf_fcf=300, dni=100)
    assert _flag(m, ni=80, ni_fy=40)["low"] is False         # TTM NI 2× last FY: abnormal
    assert _flag(m, ni=80, ni_fy=70)["low"] is True


def test_too_low_values_and_unsupported_methods_are_not_flagged():
    assert not _flag(_m(dcf_fcf=100, dni=300, ps_mean=300))["low"]
    assert not _flag(_m(pb_bank=900, dcf_fcf=100), selected="pb_bank")["low"]


def test_switch_turns_the_flag_off():
    off = replace(V, iv_flag_enabled=False)
    assert not _flag(_m(dcf_fcf=300, dni=150), rules=off)["low"]
