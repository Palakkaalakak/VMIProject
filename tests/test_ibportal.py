"""IB Client Portal Gateway provider (vmi.data.ibportal), offline with httpx.MockTransport.

The payload shapes mirror what IBKR's own portal JavaScript reads (see vmi/data/ibportal/routes.py).
"""
import httpx
import pytest

from vmi.config import get_settings
from vmi.data import ib_fundamentals, ibportal
from vmi.data.breaker import Breaker
from vmi.data.cache import get_cache
from vmi.data.ibportal import client as C
from vmi.data.ibportal import parse as P
from vmi.data.models import Fundamentals, Point

GW = "https://gw.test"


def table(columns, rows):
    """Build a Fundamentals Explorer financials payload: columns [(name, header)], rows [{...}]."""
    return {"generalInfo": [], "table": {"columns": [{"name": "metric_name", "value": ""}]
                                         + [{"name": n, "value": h} for n, h in columns]
                                         + [{"name": "trend", "value": ""}, {"name": "change", "value": "%"}],
                                         "rows": rows}}


ANNUAL_COLS = [("p0", "2022"), ("p1", "2023"), ("p2", "2024"), ("p3", "2025E")]
INCOME = table(ANNUAL_COLS, [
    {"metric_name": "Total Revenue", "metric_name_tag": "total_revenue", "p0": "394,328", "p1": "383,285",
     "p2": "391,035", "p3": "410,000", "trend": [], "change": 2.0},
    {"metric_name": "Net Income", "p0": "99,803", "p1": "96,995", "p2": "93,736", "p3": "99,000"},
    {"metric_name": "Diluted EPS Excluding Extraord Items", "p0": "6.11", "p1": "6.13", "p2": "6.08"},
    {"metric_name": "Diluted Weighted Average Shares", "p0": "16,325.82", "p1": "15,812.55", "p2": "15,408.10"},
])
CASH = table(ANNUAL_COLS, [
    {"metric_name_tag": "CashFromOperatingActivities", "p0": "122,151", "p1": "110,543", "p2": "118,254"},
    {"metric_name": "Capital Expenditures", "p0": "(10,708)", "p1": "(10,959)", "p2": "(9,447)"},
])
BALANCE = table(ANNUAL_COLS, [{"metric_name": "Total Assets", "p0": "352,755", "p1": "352,583", "p2": "364,980"}])
QUARTER = table([("q0", "Dec '23"), ("q1", "Mar '24"), ("q2", "Jun '24"), ("q3", "Sep '24")],
                [{"metric_name": "Total Revenue", "q0": "119,575", "q1": "90,753", "q2": "85,777", "q3": "94,930"}])


def sec_reference() -> Fundamentals:
    ref = Fundamentals(ticker="AAPL")
    ref.annual["revenue"] = [Point("2023-09-30", 383_285e6, 2023), Point("2024-09-28", 391_035e6, 2024)]
    return ref


# ------------------------------------------------------------------------------------------------ parse
def test_scalars():
    assert P.to_number("(1,234)") == -1234
    assert P.to_number("1.5B") == 1.5e9
    assert P.to_number("9.07%") == pytest.approx(9.07)
    assert P.to_number({"value": "12"}) == 12
    assert P.to_number("-") is None and P.to_number("N/A") is None
    assert P.concept_for("CashFromOperatingActivities") == P.concept_for("cash_from_operating_activities") == "cfo"


@pytest.mark.parametrize("label,want", [
    ("2024-09-28", ("2024-09-28", 2024)), ("20240928", ("2024-09-28", 2024)), ("9/28/2024", ("2024-09-28", 2024)),
    ("Sep 2024", ("2024-09-30", 2024)), ("Sep 28, 2024", ("2024-09-28", 2024)), ("Sep '24", ("2024-09-30", 2024)),
    ("FY 2024", ("FY2024", 2024)), ("2024", ("FY2024", 2024)), ("2026E", None), ("Total Revenue", None),
])
def test_parse_period(label, want):
    assert P.parse_period(label) == want


def test_financials_table_skips_estimates_and_non_period_columns():
    f = Fundamentals(ticker="AAPL", source="ib_portal")
    for payload in (INCOME, CASH, BALANCE):
        P.parse_financials(payload, f)
    f = P.finalize(f)
    assert [p.fy for p in f.annual["revenue"]] == [2022, 2023, 2024]  # 2025E never becomes history
    assert f.annual["capex"][-1].value == 9_447  # parenthesised outflow stored positive
    assert f.annual["eps_diluted"][-1].value == pytest.approx(6.08)
    assert f.provenance["revenue"] == "ib_portal"


def test_harmonize_scales_money_not_per_share_and_fixes_fy_ends():
    f = Fundamentals(ticker="AAPL", source="ib_portal")
    for payload in (INCOME, CASH, BALANCE):
        P.parse_financials(payload, f)
    f = P.finalize(f)
    P.harmonize(f, sec_reference())
    assert f.annual["revenue"][-1].value == pytest.approx(391_035e6)  # millions → units, snapped to SEC
    assert f.annual["shares_diluted"][-1].value == pytest.approx(15_408.10e6)
    assert f.annual["eps_diluted"][-1].value == pytest.approx(6.08)  # per-share values untouched
    assert f.annual["revenue"][-1].end == "2024-09-28"  # FY placeholder takes SEC's fiscal-year end
    assert f.latest["total_assets"] == pytest.approx(364_980e6)


def test_quarterly_table_gives_ttm():
    f = Fundamentals(ticker="AAPL", source="ib_portal")
    P.parse_financials(INCOME, f)
    P.parse_financials(QUARTER, f, quarterly=True)
    f = P.finalize(f)
    assert [p.end for p in f.quarterly["revenue"]][-1] == "2024-09-30"
    assert f.ttm["revenue"] == pytest.approx(119_575 + 90_753 + 85_777 + 94_930)


def test_parse_analyst_converts_percent():
    rows = [{"conid": 265598, "field_name": "LONG_TERM_GROWTH", "display_value": "9.07"},
            {"conid": "265598", "field_name": "BETA", "display_value": "1.21"},
            {"conid": 1, "field_name": "LONG_TERM_GROWTH", "display_value": "-"},
            {"conid": 2, "field_name": "SOMETHING_ELSE", "display_value": "5"}]
    assert P.parse_analyst(rows) == {265598: {"eps_growth_5y": pytest.approx(0.0907), "beta": 1.21}}


def test_pick_conid_prefers_us_listing():
    payload = {"AAPL": [{"assetClass": "STK", "contracts": [{"conid": 38708077, "isUS": False},
                                                            {"conid": 265598, "isUS": True}]}]}
    assert P.pick_conid(payload, "AAPL") == 265598
    assert P.pick_conid({}, "AAPL") is None


# ----------------------------------------------------------------------------------------------- client
@pytest.mark.parametrize("raw,want", [("https://localhost:5000", "https://localhost:5000"),
                                      ("localhost:5000/v1/api/", "https://localhost:5000"), ("", "")])
def test_base_url(monkeypatch, raw, want):
    monkeypatch.setattr(get_settings(), "ib_cp_url", raw)
    assert C.base_url() == want


def fake_gateway(logged_in=True, tws_service=True):
    """A mock gateway: fundamentals at /tws.proxy (portal profile), or only at /v1/api when tws_service=False."""
    calls = []
    ltg = {"AAPL": "9.07", "MSFT": "12.5"}
    conids = {"AAPL": 265598, "MSFT": 272093}

    def handler(req: httpx.Request):
        path, q = req.url.path, req.url.params
        calls.append(path)
        if not logged_in:
            return httpx.Response(401, json={"error": "not authenticated"})
        if path == "/v1/api/sso/validate":
            return httpx.Response(200, json={"RESULT": True, "USER_NAME": "paperuser"})
        if path == "/v1/api/tickle":
            return httpx.Response(200, json={"session": "x"})
        if path == "/v1/api/trsrv/stocks":
            return httpx.Response(200, json={s: [{"assetClass": "STK", "contracts": [{"conid": conids[s], "isUS": True}]}]
                                             for s in q["symbols"].split(",") if s in conids})
        base = "/tws.proxy" if tws_service else "/v1/api"
        if not path.startswith(base + "/fundamentals/"):
            return httpx.Response(404, text="not found")
        route = path[len(base):]
        if route == "/fundamentals/data_list":
            by_conid = {v: k for k, v in conids.items()}
            return httpx.Response(200, json=[{"conid": int(c), "field_name": "LONG_TERM_GROWTH",
                                              "display_value": ltg[by_conid[int(c)]]} for c in q["conids"].split(",")])
        if route.startswith("/fundamentals/financials/"):
            if q["annual"] != "true":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"income": INCOME, "cash": CASH, "balance": BALANCE}[q["type"]])
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def portal(transport):
    return C.Portal(base=GW, transport=transport, max_rps=1000)


def test_client_refuses_brokerage_routes():
    t, calls = fake_gateway()
    with portal(t) as p, pytest.raises(C.PortalError, match="read-only"):
        p._send("GET", "/v1/api/iserver/accounts")
    assert calls == []


def test_fundamentals_base_falls_back_and_is_remembered():
    C._working_base.clear()
    t, calls = fake_gateway(tws_service=False)
    with portal(t) as p:
        assert p.financials(265598, "income")["table"]["rows"]
        p.financials(265598, "cash")
    assert calls.count("/tws.proxy/fundamentals/financials/265598") == 1  # tried once, then remembered
    assert calls.count("/v1/api/fundamentals/financials/265598") == 2
    C._working_base.clear()


def test_not_logged_in_is_a_401_portal_error():
    t, _ = fake_gateway(logged_in=False)
    with portal(t) as p, pytest.raises(C.PortalError) as err:
        p.session()
    assert err.value.status == 401


# ---------------------------------------------------------------------------------------------- service
def test_sync_fills_cache_without_touching_brokerage_routes(isolated_cache):
    C._working_base.clear()
    t, calls = fake_gateway()
    from vmi.data.fundamentals import MERGED_KEY

    isolated_cache.set(MERGED_KEY.format("AAPL"), {"stale": True})
    with portal(t) as p:
        report = ibportal.sync(["aapl", "MSFT", "NOPE"], portal=p)
    assert report["conids"] == 2 and report["analyst"] == 2 and report["statements"] == 2
    assert report["failed"] == {"NOPE": "no US stock conid"}
    assert ibportal.cached_estimates("AAPL") == {"eps_growth_5y": pytest.approx(0.0907)}
    assert ibportal.cached_fundamentals("MSFT").annual["revenue"][-1].fy == 2024
    assert isolated_cache.get(MERGED_KEY.format("AAPL")) is None  # merged cache invalidated
    assert not any("/iserver" in c for c in calls)


def test_live_reads_use_cache_after_first_call():
    C._working_base.clear()
    t, calls = fake_gateway()
    with portal(t) as p:
        assert ibportal.estimates("MSFT", portal=p) == {"eps_growth_5y": pytest.approx(0.125)}
        n = len(calls)
        assert ibportal.estimates("MSFT", portal=p)["eps_growth_5y"] == pytest.approx(0.125)
    assert len(calls) == n


# -------------------------------------------------------------------------------- ib_fundamentals glue
def test_portal_path_trips_breaker_and_falls_back_to_cache(monkeypatch):
    monkeypatch.setattr(get_settings(), "ib_cp_url", GW)
    monkeypatch.setattr(ib_fundamentals, "PORTAL", Breaker("test_portal", seconds=60))

    def broken(ticker, live):
        if live:
            raise C.PortalError("gateway unreachable")
        return {"eps_growth_5y": 0.1}

    assert ib_fundamentals._portal(broken, "AAPL", {}) == {}
    assert not ib_fundamentals.PORTAL.ready  # paused after the failure …
    assert ib_fundamentals._portal(broken, "AAPL", {}) == {"eps_growth_5y": 0.1}  # … cache-only meanwhile


def test_breaker():
    b = Breaker("test_breaker", seconds=60)
    assert b.ready
    b.trip("nope")
    assert not b.ready and b.status()["last_error"] == "nope"
    b.reset()
    assert b.ready
    assert get_cache() is not None


def test_check_reports_routes_and_saves_raw_json(tmp_path):
    C._working_base.clear()
    t, _ = fake_gateway()
    with portal(t) as p:
        report = ibportal.check(["AAPL"], tmp_path, portal=p)
    assert report["session"] == {"ok": True, "user": "paperuser"}
    entry = report["AAPL"]
    assert entry["conid"] == 265598 and entry["income_annual"] == "ok"
    assert entry["parsed_annual"]["revenue"] == 3
    assert entry["analyst"] == {"eps_growth_5y": pytest.approx(0.0907)}
    assert (tmp_path / "AAPL.json").exists()


def test_cli_check_without_gateway(monkeypatch, capsys):
    monkeypatch.setattr(get_settings(), "ib_cp_url", "")
    ib_fundamentals.main(["check", "AAPL", "--no-tws"])
    assert "VMI_IB_CP_URL not set" in capsys.readouterr().out


def test_gateway_and_tws_port_are_found_without_configuration():
    from vmi.config import Settings
    from vmi.data.ib import AUTO_PORTS, candidate_ports

    assert Settings().ib_cp_url == "https://localhost:5000" and Settings().ib_port == 0  # defaults need no .env
    assert candidate_ports(0) == AUTO_PORTS and candidate_ports(7497) == (7497,)  # a configured port is used alone


def test_non_json_answer_falls_back_to_the_next_route_and_is_reported():
    C._working_base.clear()
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path.startswith("/tws.proxy/"):
            return httpx.Response(200, text="<html>Client login</html>", headers={"content-type": "text/html"})
        return httpx.Response(200, json=INCOME)

    with portal(httpx.MockTransport(handler)) as p:
        assert p.financials(1, "income")["table"]["rows"]   # second route served it
    assert calls[0].startswith("/tws.proxy/") and calls[1].startswith("/v1/portal/fundamentals/")
    C._working_base.clear()

    with portal(httpx.MockTransport(lambda r: httpx.Response(200, text="<html>nope</html>",
                                                               headers={"content-type": "text/html"}))) as p:
        with pytest.raises(C.PortalError, match="not JSON.*text/html.*nope.*start_cp_gateway"):
            p.financials(1, "income")
    C._working_base.clear()


def test_redirect_answer_reports_where_it_points_and_tries_the_next_route():
    C._working_base.clear()

    def handler(req: httpx.Request):
        if req.url.path.startswith("/tws.proxy/"):
            return httpx.Response(302, headers={"location": "https://gw.test/sso/Login?x=1"})
        return httpx.Response(200, json=INCOME)

    with portal(httpx.MockTransport(handler)) as p:
        assert p.financials(1, "income")["table"]["rows"]
    C._working_base.clear()
    with portal(httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "https://gw.test/sso/Login"}))) as p:
        with pytest.raises(C.PortalError, match="HTTP 302 → redirected to https://gw.test/sso/Login"):
            p.financials(1, "income")
    C._working_base.clear()


def test_web_api_routes_fall_back_to_portal_proxy_on_the_tws_profile():
    """conf.tws.yaml forwards to the portal website: /v1/api 404s there, /portal.proxy/v1/portal answers."""
    C._working_base.clear()
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path.startswith("/v1/api/"):
            return httpx.Response(404, text="<html><body><h1>Resource not found</h1></body></html>")
        return httpx.Response(200, json={"USER_NAME": "paper1", "RESULT": True})

    with portal(httpx.MockTransport(handler)) as p:
        assert p.session()["USER_NAME"] == "paper1"
    assert calls[:2] == ["/v1/api/sso/validate", "/v1/portal/sso/validate"]
    assert calls[2] == "/v1/portal/tickle"  # the working base is remembered for the group
    C._working_base.clear()


def test_redirect_to_the_same_path_is_retried_with_the_cookie_it_set():
    C._working_base.clear()
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.headers.get("cookie", ""))
        if "probe=1" not in req.headers.get("cookie", ""):
            return httpx.Response(302, headers={"location": "https://ndcdyn.example" + req.url.path,
                                                "set-cookie": "probe=1; Path=/"})
        return httpx.Response(200, json=INCOME)

    with portal(httpx.MockTransport(handler)) as p:
        assert p.financials(1, "income")["table"]["rows"]
    assert len(seen) == 2 and "probe=1" in seen[1]
    C._working_base.clear()


def test_browser_http_adapter_feeds_portal_like_httpx():
    from vmi.data.ibportal.browser import BrowserHttp

    class R:  # playwright APIResponse subset
        status, headers = 200, {"Content-Type": "application/json"}

        def body(self):
            return b'[{"conid": 1, "field_name": "BETA", "display_value": "1.2"}]'

    class Ctx:
        class request:
            @staticmethod
            def fetch(url, **kw):
                assert url == "https://site.test/tws.proxy/fundamentals/data_list" and kw["method"] == "GET"
                return R()

    C._working_base.clear()
    p = C.Portal(http=BrowserHttp(Ctx, "https://site.test"))
    assert p.session() == {} and p.data_list([1], ["BETA"])[0]["field_name"] == "BETA"
    C._working_base.clear()
