from vmi.analysis.iv_confidence import iv_confidence


def _m(**kw):
    return {k: {"applicable": True, "intrinsic_value": v} for k, v in kw.items()}


def test_agreeing_methods_are_not_flagged():
    r = iv_confidence(_m(dcf_fcf=100, dni=110, ps_mean=120), "dcf_fcf")
    assert not r["low"] and r["spread"] == 1.2


def test_disagreeing_methods_are_flagged_with_reason():
    r = iv_confidence(_m(dcf_fcf=300, dni=150, ps_mean=190), "dcf_fcf")
    assert r["low"] and "2.0×" in r["reasons"][0]


def test_single_method_or_inapplicable_values_give_no_flag():
    assert not iv_confidence(_m(dcf_fcf=300), "dcf_fcf")["low"]
    m = _m(dcf_fcf=300, dni=100)
    m["dni"]["applicable"] = False
    assert not iv_confidence(m, "dcf_fcf")["low"]
