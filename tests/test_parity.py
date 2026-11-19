"""The scanner row and the analysis report must show the SAME ROE / ROIC / net margin: the value the steps judged, basis named."""
import pandas as pd

from tests.conftest import make_fund
from vmi.data.models import Estimates, Point
from vmi.rules import RULES


def _run(monkeypatch, normalise):
    import vmi.analysis.pipeline as pl
    from vmi.scanner.funnel import compact

    f = make_fund(revenue=[100, 110, 121, 133, 146, 160], net_income=[10, 12, 14, 16, 18, 4],
                  gross_profit=[50, 55, 60, 66, 73, 80], equity=[100] * 6, total_assets=[200] * 6)
    f.ratios["roe"] = [Point(end=f"{y}-12-31", value=v, fy=y) for y, v in zip(range(2020, 2026), [0.10, 0.12, 0.14, 0.16, 0.18, 0.04])]
    f.ratios["roic"] = [Point(end=f"{y}-12-31", value=v, fy=y) for y, v in zip(range(2020, 2026), [0.09, 0.10, 0.12, 0.13, 0.15, 0.05])]
    f.latest = {"equity": 100.0}
    monkeypatch.setattr(pl, "resolve", lambda t: f)
    monkeypatch.setattr(pl, "get_estimates", lambda t: Estimates(ticker=t))
    monkeypatch.setattr(pl.market, "last_price", lambda t: 10.0)
    monkeypatch.setattr(pl.market, "history", lambda *a, **k: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
    rules = RULES.with_overrides({"normalise": {"enabled": normalise, "years": 3}})
    rep = pl.analyse_ticker("AAA", with_technicals=False, rules=rules)
    return rep, compact(rep)


def _check(rep, step, name):
    return next(c["value"] for s in rep["steps"] if s["step"] == step for c in s["checks"] if c["name"] == name)


def test_row_equals_the_value_the_steps_judged_latest_year(monkeypatch):
    rep, row = _run(monkeypatch, False)
    assert row["roe"] == _check(rep, 4, "roe") and row["roic"] == _check(rep, 4, "roic")
    assert row["net_margin"] == _check(rep, 1, "net_margin_stable")
    assert row["basis_kind"] == "latest" and "latest" in row["basis"]


def test_row_equals_the_value_the_steps_judged_when_normalised(monkeypatch):
    rep, row = _run(monkeypatch, True)
    assert row["roe"] == _check(rep, 4, "roe") and row["basis_kind"] == "avg" and "3-year" in row["basis"]
    assert row["roe_latest"] == 0.04 and row["roe"] != row["roe_latest"]          # the flattering/odd latest year stays visible, labelled
