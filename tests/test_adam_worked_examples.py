"""Adam's own worked DCF/DNI examples (Master doc l.1438-1582): his inputs must give his intrinsic values."""
import pytest

from vmi.analysis.valuation.core import GrowthPath, discount_rate, discounted_value

CASES = {  # base, total debt, cash, growth yrs 1-5, yrs 6-10, shares, discount rate, Adam's IV
    "MA (FCF)": (16186, 19000, 11459, .1553, .15, 898, .061, 655.97),
    "AMZN (normalised capex)": (61065, 68396, 123329, .1817, .15, 10863, .074, 206),
    "AAPL (CFO)": (135472, 90509, 66907, .1229, .1229, 14810.36, .066, 256),
    "SGX (FCF, non-US)": (755.25, 332.303, 2046.023, .0822, .0822, 1070, .058, 17.67),
    "BLK (net income)": (5553, 12768, 11468, .1153, .1153, 165.4, .077, 795),
}


@pytest.mark.parametrize("name", CASES)
def test_engine_reproduces_adams_worked_examples(name):
    base, debt, cash, g1, g2, shares, rate, adam = CASES[name]
    assert discounted_value(base, GrowthPath(g1, g2, .04), rate, debt, cash, shares) == pytest.approx(adam, rel=0.002)


def test_discount_rate_table_matches_adams_rows():
    for beta, rate in ((0.28, .058), (0.83, .061), (1.1, .066), (1.4, .074), (1.49, .077)):
        assert discount_rate(beta) == pytest.approx(rate)
