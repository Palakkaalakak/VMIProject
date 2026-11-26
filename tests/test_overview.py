"""'More detailed overview' tab: statements, trends, metrics, dividends, earnings, valuation preview (offline)."""
import math
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_fund
from vmi.analysis import overview
from vmi.data.models import Estimates, Point

YEARS = tuple(range(2016, 2026))


def fund(**kw):
    """Ten growing years of a plain industrial company (values in dollars)."""
    rev = [100e9 * 1.08 ** i for i in range(10)]
    series = dict(revenue=rev, gross_profit=[r * 0.4 for r in rev], operating_income=[r * 0.2 for r in rev],
                  net_income=[r * 0.15 for r in rev], cfo=[r * 0.2 for r in rev], capex=[r * 0.04 for r in rev],
                  fcf=[r * 0.16 for r in rev], receivables=[r * 0.1 for r in rev], eps_diluted=[3.0 + i * 0.3 for i in range(10)],
                  shares_diluted=[5e9] * 10, equity=[r * 0.5 for r in rev], cash=[10e9] * 10)
    series.update(kw.pop("series", {}))
    f = make_fund("TEST", ttm={"revenue": 250e9, "net_income": 35e9, "fcf": 40e9}, **series, **kw)
    f.cik, f.latest_date, f.name = 1234, "2026-03-31", "Test Co"
    f.ratios["roe"] = [Point(f"{y}-12-31", 0.10 + 0.01 * i) for i, y in enumerate(YEARS)]
    f.ratios["roic"] = [Point(f"{y}-12-31", 0.12) for y in YEARS]
    f.ratios["ccc"] = [Point(f"{y}-12-31", 40.0 + 2 * i) for i, y in enumerate(YEARS)]
    return f


def no_nan(o):
    if isinstance(o, float):
        assert math.isfinite(o)
    elif isinstance(o, dict):
        [no_nan(v) for v in o.values()]
    elif isinstance(o, list):
        [no_nan(v) for v in o]


# ---------------------------------------------------------------------------------------- statements
def test_statements_millions_ttm_and_missing_rows():
    out = overview.statements(fund(), "annual")
    assert [c["label"] for c in out["columns"]][-2:] == ["2025", "TTM"] and len(out["columns"]) == 11
    inc = next(s for s in out["sections"] if s["key"] == "income")
    rev = next(r for r in inc["rows"] if r["key"] == "revenue")
    assert rev["values"][0] == pytest.approx(100e3) and rev["values"][-1] == 250e3       # millions, TTM last
    assert rev["values"][0] < rev["values"][-2]                                          # oldest -> newest
    eps = next(r for r in inc["rows"] if r["key"] == "eps_diluted")
    assert eps["unit"] == "ps" and eps["values"][0] == 3.0 and eps["values"][-1] is None  # per share, no TTM known
    assert "cost_of_revenue" not in [r["key"] for r in inc["rows"]]                       # absent concept: row omitted
    no_nan(out)


def test_statements_quarterly_has_no_ttm_column():
    f = fund()
    f.quarterly["revenue"] = [Point(f"2025-{m:02d}-30", 1e9 * m, None) for m in (3, 6, 9)]
    out = overview.statements(f, "quarterly")
    assert [c["label"] for c in out["columns"]] == ["2025-03", "2025-06", "2025-09"]
    assert out["sections"][0]["rows"][0]["values"] == [3000.0, 6000.0, 9000.0]


# ---------------------------------------------------------------------------------------- trends
def test_trends_series_and_price_overlay():
    hist = pd.DataFrame({"close": [10.0, 11.0, 12.0]}, index=pd.to_datetime(["2025-01-10", "2025-01-30", "2025-02-14"]))
    prices = overview.month_end_prices(hist)
    assert prices == [{"date": "2025-01-31", "close": 11.0}, {"date": "2025-02-28", "close": 12.0}]
    out = overview.trends(fund(), "annual", prices)
    assert [s["key"] for s in out["series"]] == ["revenue", "operating_income", "net_income", "cfo", "fcf"]
    pts = out["series"][0]["points"]
    assert len(pts) == 10 and pts[0]["value"] < pts[-1]["value"] and out["price"] == prices


# ---------------------------------------------------------------------------------------- metrics
def test_metrics_averages_and_trend_words():
    out = overview.metrics(fund())
    roe = out["metrics"]["roe"]
    assert roe["latest"] == pytest.approx(0.19) and roe["avg5"] == pytest.approx(0.17) and roe["avg10"] == pytest.approx(0.145)
    assert roe["trend"] == "rising" and out["metrics"]["roic"]["trend"] == "stable"
    assert out["metrics"]["gross_profit"]["latest"] == pytest.approx(0.4) and "net_income" in out["metrics"]
    assert out["metrics"]["fcf"]["avg10"] == pytest.approx(0.16)
    assert out["revenue_vs_receivables"]["revenue_ahead"] is True
    assert len(out["revenue_vs_receivables"]["series"]) == 9
    assert out["cash_conversion_cycle"]["series"][-1]["days"] == 58.0 and out["cash_conversion_cycle"]["trend"] == "rising"
    no_nan(out)


def test_metrics_bank_without_gross_profit_and_short_history():
    f = fund(series={"gross_profit": []})
    f.annual.pop("gross_profit")
    f.annual["receivables"] = []
    out = overview.metrics(f)
    assert "gross_profit" not in out["metrics"] and out["revenue_vs_receivables"]["series"] == []
    assert overview.trend_word([0.1, 0.1, 0.1]) is None
    short = overview._summary("x", {2023: 0.1, 2024: 0.1, 2025: 0.1})
    assert short["avg5"] == pytest.approx(0.1) and short["avg10"] is None


def test_metrics_ignore_the_ttm_ratio_point():
    f = fund()
    f.ratios["roe"].append(Point("TTM", 0.5))          # real data ends ratio series with a point whose end is "TTM"
    f.ratios["roic"].append(Point("TTM", 0.5))
    out = overview.metrics(f)
    assert out["metrics"]["roe"]["latest"] == pytest.approx(0.19) and len(out["metrics"]["roe"]["series"]) == 10


# ---------------------------------------------------------------------------------------- dividends
def divs():
    out = []
    for y in range(2014, 2026):                      # 1.00, 1.10, ... paid in four equal parts
        amount = 1.0 + 0.1 * (y - 2014)
        out += [{"date": f"{y}-{m:02d}-15", "amount": amount / 4} for m in (3, 6, 9, 12)]
    return out + [{"date": "2026-03-15", "amount": 0.4}]


def test_dividend_maths():
    prices = [{"date": f"{y}-12-31", "close": 50.0} for y in range(2014, 2026)]
    out = overview.dividends(fund(), divs(), prices, calendar={"ex_dividend_date": "2026-06-01", "dividend_date": "2026-06-15"},
                             today=date(2026, 4, 1))
    row = {r["year"]: r for r in out["years"]}
    assert row[2025]["dps"] == pytest.approx(2.1) and row[2026]["partial"] is True
    assert row[2025]["payout_eps"] == pytest.approx(2.1 / 5.7) and row[2025]["payout_fcf"] == pytest.approx(2.1 / (fund().series("fcf")[-1] / 5e9))
    g = out["growth"]                                # complete years only: 2025 vs 2022 / 2020 / 2015
    assert g["cagr_3y"] == pytest.approx((2.1 / 1.8) ** (1 / 3) - 1) and g["cagr_10y"] == pytest.approx((2.1 / 1.1) ** 0.1 - 1)
    assert out["yield_history"][-1] == {"date": "2025-12-31", "yield": pytest.approx(2.1 / 50)}
    assert out["next_ex_date"] == "2026-06-01" and out["pays_dividend"]
    no_nan(out)


def test_non_payer():
    out = overview.dividends(fund(), [], [], today=date(2026, 4, 1))
    assert out["pays_dividend"] is False and out["years"] == [] and out["growth"]["cagr_5y"] is None


# ---------------------------------------------------------------------------------------- earnings
def test_8k_item_202_filter():
    filings = [{"form": "8-K", "accession": f"0001234-26-00000{i}", "document": f"d{i}.htm", "filed": f"2026-0{i}-01", "items": it}
               for i, it in enumerate(["5.02", "2.02,9.01", "7.01", "2.02", "2.02,9.01"], 1)]
    out = overview.earnings_releases(filings, 1234, limit=2)
    assert [r["filed"] for r in out] == ["2026-05-01", "2026-04-01"]             # newest first, only item 2.02, capped
    assert out[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1234/000123426000005/d5.htm"
    assert out[0]["index_url"].endswith("0001234-26-000005-index.htm")
    assert overview.earnings_releases([{**filings[0], "items": "12.02"}], 1234) == []     # no substring match


def test_earnings_history_next_date_and_quarters():
    f = fund()
    f.quarterly["revenue"] = [Point("2025-12-31", 5e9), Point("2026-03-31", 6e9)]
    f.quarterly["net_income"] = [Point("2026-03-31", 1e9)]
    dates = [{"date": "2026-07-30", "eps_estimate": 1.0, "eps_actual": None, "surprise_pct": None},
             {"date": "2026-04-28", "eps_estimate": 1.0, "eps_actual": 1.1, "surprise_pct": 10.0}]
    out = overview.earnings(f, dates, [], today=date(2026, 5, 15))
    assert out["next_date"] == "2026-07-30" and [h["date"] for h in out["history"]] == ["2026-04-28"]
    assert out["quarters"][-1] == {"end": "2026-03-31", "revenue": 6000.0, "net_income": 1000.0, "eps": None}
    assert "transcripts" in out["transcripts_note"].lower()


# ---------------------------------------------------------------------------------------- valuation preview
def valuation_fixture(monkeypatch):
    from vmi.analysis import pipeline
    f = fund()
    f.latest.update(cash=10e9, total_debt=20e9, lt_debt=20e9)
    f.sector = "Industrials"
    est = Estimates(ticker="TEST", eps_growth_5y=0.10, beta=1.0, sector="Industrials")
    hist = pd.DataFrame({"close": [100.0] * 30, "open": [100.0] * 30, "high": [100.0] * 30, "low": [100.0] * 30, "volume": [1e6] * 30},
                        index=pd.date_range("2025-01-01", periods=30))
    monkeypatch.setattr(pipeline, "resolve", lambda t: f)
    monkeypatch.setattr(pipeline, "get_estimates", lambda t: est)
    monkeypatch.setattr(pipeline.market, "last_price", lambda t: 100.0)
    monkeypatch.setattr(pipeline.market, "history", lambda *a, **k: hist)
    return f, est, hist


def test_preview_equals_analysis_when_unchanged(monkeypatch):
    from vmi.analysis.pipeline import analyse_ticker
    f, est, hist = valuation_fixture(monkeypatch)
    rep = analyse_ticker("TEST", with_technicals=False, overrides={"growth": 0.12})
    prev = overview.preview_valuation(f, est, 100.0, hist, {"growth": 0.12}, {})
    assert prev["intrinsic_value"] == rep["intrinsic_value"] and prev["selected"] == rep["valuation"]["selected"]
    assert prev["conservative_value"] == rep["valuation"]["conservative_value"] and prev["changed"] == []
    assert prev["intrinsic_value"]


def test_preview_moves_the_right_way(monkeypatch):
    f, est, hist = valuation_fixture(monkeypatch)
    iv = lambda **e: overview.preview_valuation(f, est, 100.0, hist, {}, e)["intrinsic_value"]  # noqa: E731
    base = iv()
    assert iv(growth=0.15) > base > iv(growth=0.03)
    assert iv(discount_rate=0.12) < base < iv(discount_rate=0.07)
    assert overview.preview_valuation(f, est, 100.0, hist, {}, {"growth": 0.15})["changed"] == ["growth"]


# ---------------------------------------------------------------------------------------- endpoints
@pytest.fixture
def client(temp_db, monkeypatch):
    from vmi.api import app as appmod
    from vmi.data import filings, market
    f = fund()
    f.quarterly["revenue"] = [Point("2026-03-31", float("nan"))]
    monkeypatch.setattr("vmi.data.fundamentals.resolve", lambda t: f)
    monkeypatch.setattr("vmi.data.estimates.get_estimates", lambda t: Estimates(ticker=t, pe=20.0, dividend_yield=0.03))
    monkeypatch.setattr(market, "history", lambda *a, **k: pd.DataFrame(
        {"close": [10.0, 12.0]}, index=pd.to_datetime(["2025-05-30", "2025-06-30"])))
    monkeypatch.setattr(market, "last_price", lambda t: 12.0)
    monkeypatch.setattr(market, "dividends", lambda t: divs())
    monkeypatch.setattr(market, "calendar", lambda t: {"earnings_date": "2026-07-30"})
    monkeypatch.setattr(market, "earnings_dates", lambda t, limit=12: [])
    monkeypatch.setattr(filings, "recent_8k", lambda cik: [{"form": "8-K", "accession": "0001-26-1", "document": "a.htm",
                                                            "filed": "2026-04-01", "items": "2.02"}])
    return TestClient(appmod.app)


@pytest.mark.parametrize("path, keys", [
    ("statements", {"columns", "sections", "unit"}), ("statements?period=quarterly", {"columns", "sections"}),
    ("trends", {"series", "price"}), ("metrics", {"metrics", "revenue_vs_receivables", "cash_conversion_cycle"}),
    ("snapshot", {"price", "market_cap", "pe", "next_earnings", "low_52w", "high_52w"}),
    ("dividends", {"years", "growth", "yield_history", "next_ex_date"}),
    ("earnings", {"next_date", "history", "quarters", "releases", "transcripts_note"})])
def test_endpoints_return_clean_json(client, path, keys):
    r = client.get(f"/api/analysis/TEST/{path}")
    assert r.status_code == 200 and keys <= set(r.json())
    assert "NaN" not in r.text


def test_bad_period_and_preview_endpoint(client, monkeypatch):
    assert client.get("/api/analysis/TEST/statements?period=weekly").status_code == 400
    f = fund()
    f.latest.update(cash=10e9, lt_debt=20e9)
    monkeypatch.setattr("vmi.data.fundamentals.resolve", lambda t: f)
    r = client.post("/api/analysis/TEST/valuation/preview", json={"growth": 0.1})
    assert r.status_code == 200 and {"intrinsic_value", "methods", "selected", "changed"} <= set(r.json())
    assert client.get("/api/analysis/TEST/override").json() == {}                      # nothing was saved
