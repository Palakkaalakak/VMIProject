import pytest

from vmi.watchlist import stats


def row(sym, low, avg, high, great, steps, **kw):
    return {"symbol": sym, "name": sym, "growth_low": low, "growth_avg": avg, "growth_high": high, "growth": low,
            "great_business": great, "steps": steps, "steps_passed": sum(steps.values()), "sector": "Tech", "industry": "X", **kw}


def test_growth_spread_and_failures():
    ok = {1: True, 2: True, 3: True, 4: True, 5: True, 6: False, 7: False}
    bad = {1: False, 2: True, 3: True, 4: True, 5: True, 6: False, 7: False}
    r = stats.compute([row("A", .10, .15, .20, True, ok), row("B", .20, .25, .30, False, bad, roe=.2),
                       {"symbol": "ERR", "error": "boom"}], threshold=0.15)
    g = r["growth_spread"]
    assert g["avg_of_lowest"] == pytest.approx(.15) and g["avg_of_average"] == pytest.approx(.20) and g["avg_of_highest"] == pytest.approx(.25)
    assert (g["n_growth_by_lowest"], g["n_growth_by_average"], g["n_growth_by_highest"]) == (1, 2, 2)
    assert r["n_stocks"] == 3 and r["n_analysed"] == 2 and r["errors"][0]["symbol"] == "ERR"
    assert r["fails_great_business"] == [{"symbol": "B", "name": "B", "first_failed_step": 1, "steps_passed": 4}]
    assert r["step_pass_counts"]["1"] == 1 and r["numbers"]["roe"]["mean"] == .2
    assert r["concentration"]["top_sector"] == "Tech"
