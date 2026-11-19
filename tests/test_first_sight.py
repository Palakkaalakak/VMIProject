from tests.conftest import make_fund
from vmi.analysis import first_sight

OK1 = [{"step": 1, "passed": True, "checks": []}]


def _f(gross, rev=None):
    rev = rev or [100] * 6
    return make_fund(revenue=rev, gross_profit=[r * g for r, g in zip(rev, gross)], operating_income=[r * 0.3 for r in rev])


def test_visa_like_margins_read_wide():
    out = first_sight.assess(_f([0.76, 0.77, 0.78, 0.78, 0.79, 0.80]), OK1,
                             {"rows": [1], "summary": {"peers": 3, "ranks": {"operating_margin": 1}, "share": 0.4, "top_dog_hint": True}})
    assert out["leaning"] == "wide-looking" and "At first sight" in out["paragraph"]


def test_airline_like_margins_and_falling_trend_read_weak():
    out = first_sight.assess(_f([0.22, 0.20, 0.18, 0.17, 0.16, 0.15]), [{"step": 1, "passed": False, "checks": []}])
    assert out["leaning"] == "weak" and out["bad"] >= 2


def test_no_moat_industry_is_weak_whatever_the_numbers():
    out = first_sight.assess(_f([0.7] * 6), OK1, None, no_moat_industry=True)
    assert out["leaning"] == "weak"


def test_fragmented_competition_is_flagged():
    out = first_sight.assess(_f([0.5] * 6), OK1, {"rows": [1], "summary": {"peers": 9, "ranks": {"operating_margin": 5}, "share": 0.05}})
    assert any(s["label"] == "Industry position" and s["reading"] == "bad" for s in out["signals"])


def test_missing_data_is_unknown_not_a_crash():
    out = first_sight.assess(make_fund(revenue=[100, 110]), [])
    assert out["leaning"] in ("unclear", "weak") and all(s["reading"] in ("good", "bad", "unknown") for s in out["signals"])
