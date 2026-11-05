"""Client Portal Gateway provider — offline, with httpx.MockTransport (no gateway needed)."""
import httpx
import pytest

from vmi.data import ib_portal as P
from vmi.data.models import Fundamentals, Point

# Shape A: column headers + rows with value arrays (Fundamentals Explorer table style), units in millions.
INCOME_A = {"currency": "USD", "units": "Millions",
            "columns": [{"date": "2022-09-24"}, {"date": "2023-09-30"}, {"date": "2024-09-28"}],
            "rows": [{"title": "Total Revenue", "values": ["394,328", "383,285", "391,035"]},
                     {"title": "Net Income", "values": [99803, 96995, 93736]},
                     {"title": "Diluted EPS Excluding Extraord Items", "values": [6.11, 6.13, 6.08]},
                     {"title": "Diluted Weighted Average Shares", "values": [16325.8, 15812.5, 15408.1]}]}
# Shape B: nested sections, per-value period objects, no units (scale inferred against SEC).
CASH_B = {"data": {"sections": [{"name": "Operating", "items": [
    {"label": "Cash from Operating Activities", "data": [{"period": "FY 2023", "value": 110543},
                                                         {"period": "FY 2024", "value": 118254}]},
    {"label": "Capital Expenditures", "data": [{"period": "FY 2023", "value": "(10959)"},
                                               {"period": "FY 2024", "value": "(9447)"}]}]}]}}
# Shape C: flat rows keyed by period.
BAL_C = {"result": [{"description": "Total Assets", "Sep 2023": 352583, "Sep 2024": 364980},
                    {"description": "Total Equity", "Sep 2023": 62146, "Sep 2024": 56950}]}


def test_parse_period_variants():
    assert P.parse_period("2024-09-28") == ("2024-09-28", 2024)
    assert P.parse_period("20240928") == ("2024-09-28", 2024)
    assert P.parse_period("9/28/2024") == ("2024-09-28", 2024)
    assert P.parse_period("Sep 2024") == ("2024-09-30", 2024)
    assert P.parse_period("FY 2024") == ("FY2024", 2024)
    assert P.parse_period({"fiscalYear": 2024, "endDate": "2024-09-28"}) == ("2024-09-28", 2024)
    assert P.parse_period("Total Revenue") is None


def test_parse_numbers():
    assert P._num("(1,234)") == -1234
    assert P._num("1.5B") == 1.5e9
    assert P._num({"value": "12"}) == 12
    assert P._num("n/a") is None


def test_parse_all_shapes_and_units():
    f = Fundamentals(ticker="AAPL", source="ib_cp")
    P.parse_statement(INCOME_A, f)
    P.parse_statement(CASH_B, f)
    P.parse_statement(BAL_C, f)
    f = P.finalize(f)
    assert f is not None
    # explicit "Millions" applies to money and share counts, never to per-share values
    assert f.annual["revenue"][-1].value == pytest.approx(391_035e6)
    assert f.annual["eps_diluted"][-1].value == pytest.approx(6.08)
    assert f.annual["capex"][-1].value > 0  # parenthesised negatives → absolute capex
    assert [p.fy for p in f.annual["cfo"]] == [2023, 2024]
    assert f.latest["total_assets"] == pytest.approx(364980e6)
    assert all(v == "ib_cp" for v in f.provenance.values())


def test_harmonize_scale_and_fy_ends_against_sec():
    f = Fundamentals(ticker="AAPL", source="ib_cp")
    P.parse_statement(CASH_B, f)
    P.parse_statement({"rows": [{"title": "Total Revenue", "values": [{"period": "FY2024", "value": 391035}]}]}, f)
    f = P.finalize(f)
    sec = Fundamentals(ticker="AAPL")
    sec.annual["revenue"] = [Point("2024-09-28", 391_035e6, 2024)]
    sec.annual["cfo"] = [Point("2023-09-30", 110_543e6, 2023), Point("2024-09-28", 118_254e6, 2024)]
    P.harmonize(f, sec)
    assert f.annual["cfo"][-1].value == pytest.approx(118_254e6)
    assert f.annual["cfo"][-1].end == "2024-09-28"
    assert f.annual["cfo"][0].end == "2023-09-30"


def test_pick_conid():
    trsrv = {"AAPL": [{"name": "APPLE INC", "assetClass": "STK",
                       "contracts": [{"conid": 38708077, "exchange": "MEXI", "isUS": False},
                                     {"conid": 265598, "exchange": "NASDAQ", "isUS": True}]}]}
    assert P.pick_conid(trsrv, "AAPL") == 265598
    search = [{"conid": "1", "symbol": "AAPL", "description": "MEXI", "sections": [{"secType": "STK"}]},
              {"conid": "265598", "symbol": "AAPL", "description": "NASDAQ", "sections": [{"secType": "STK"}]}]
    assert P.pick_conid(search, "AAPL") == 265598
    assert P.pick_conid({}, "AAPL") is None


def test_base_url_normalisation(monkeypatch):
    from vmi.config import get_settings

    s = get_settings()
    for raw, want in (("https://localhost:5000", "https://localhost:5000/v1/api"),
                      ("localhost:5000/v1/api/", "https://localhost:5000/v1/api"), ("", "")):
        monkeypatch.setattr(s, "ib_cp_url", raw)
        assert P.base_url() == want


def _gateway(authenticated=True, legacy_only=False):
    calls = []

    def handler(req: httpx.Request):
        path = req.url.path
        calls.append(path)
        if path.endswith("/tickle"):
            return httpx.Response(200, json={})
        if path.endswith("/iserver/auth/status"):
            return httpx.Response(200, json={"authenticated": authenticated})
        if path.endswith("/trsrv/stocks"):
            return httpx.Response(200, json={"ZZZT": [{"assetClass": "STK", "contracts": [{"conid": 42, "isUS": True}]}]})
        if "/fundamentals/financials/42" in path:
            if legacy_only and "tws.proxy" in path:
                return httpx.Response(404, text="not found")
            if req.url.params.get("annual") != "true":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"income": INCOME_A, "cash": CASH_B, "balance": BAL_C}[req.url.params["type"]])
        if "/fundamentals/landing/42" in path:
            return httpx.Response(200, json={"key_ratios": [{"title": "Beta", "value": 1.2},
                                                            {"title": "EPS LT Growth", "value": 9.5}]})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def test_end_to_end_with_mock_gateway():
    t, calls = _gateway(legacy_only=True)
    with P.Portal(base="https://gw/v1/api", transport=t) as p:
        f = P.fundamentals("ZZZT", portal=p)
    assert f is not None and f.meta["ib_conid"] == 42
    assert f.annual["revenue"][-1].value == pytest.approx(391_035e6)
    assert any("/v1/api/fundamentals/financials/42" in c for c in calls)  # fell back to the older alias
    est = P.estimates_from_ratios(f.meta["ib_key_ratios"])
    assert est == {"eps_growth_5y": pytest.approx(0.095), "beta": 1.2}


def test_unauthenticated_session_raises():
    t, _ = _gateway(authenticated=False)
    with P.Portal(base="https://gw/v1/api", transport=t) as p, pytest.raises(P.PortalError):
        P.fundamentals("ZZZT", portal=p)
