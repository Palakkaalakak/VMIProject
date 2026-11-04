"""Adam's DCF engine against the worked examples in the master document."""
import pytest

from vmi.analysis.valuation.core import discount_rate, discounted_value, growth_path


def test_apple_cfo_worked_example():
    # VMI doc §5.5: AAPL discounted CFO → base IV $256
    iv = discounted_value(135_472e6, growth_path(0.1229), 0.066, 90_509e6, 66_907e6, 14_810.36e6)
    assert iv == pytest.approx(256, abs=3)


def test_apple_conservative_case():
    # same example: yrs 1-5 = 11.23% (lowest source), yrs 6-10 = 5.61% → ~$200
    iv = discounted_value(135_472e6, growth_path(0.1123, g6_10=0.0561), 0.066, 90_509e6, 66_907e6, 14_810.36e6)
    assert iv == pytest.approx(200, abs=4)


def test_growth_path_caps():
    p = growth_path(0.30)
    assert (p.g1_5, p.g6_10, p.g11_20) == (0.30, 0.15, 0.04)       # yrs 6-10 capped at 15%
    assert growth_path(0.9).g1_5 == 0.40                             # hard sanity cap


@pytest.mark.parametrize("beta,rate", [(0.28, 0.058), (0.83, 0.061), (1.10, 0.066), (1.40, 0.074), (1.49, 0.077)])
def test_discount_rate_table_rows(beta, rate):
    assert discount_rate(beta) == pytest.approx(rate)


def test_discount_rate_interpolates_and_floors():
    assert 0.061 < discount_rate(1.0) < 0.066
    assert discount_rate(0.1) == 0.058
    assert discount_rate(None) == discount_rate(1.0)


def test_zero_shares_returns_none():
    assert discounted_value(1e9, growth_path(0.1), 0.06, 0, 0, 0) is None
