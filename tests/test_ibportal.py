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


# ----------------------------------------------------------------------------------------------- client
def fake_portal(logged_in=True, throttle_first=0):
    """A mock portal site: fundamentals routes under /tws.proxy only (as verified on real runs)."""
    calls, state = [], {"throttled": 0}
    ltg = {265598: "9.07", 272093: "12.5"}

    def handler(req: httpx.Request):
        path, q = req.url.path, req.url.params
        calls.append(path)
        if not logged_in:
            return httpx.Response(401, json={"error": "not authenticated"})
        if state["throttled"] < throttle_first:
            state["throttled"] += 1
            return httpx.Response(429, headers={"retry-after": "0"})
        if not path.startswith("/tws.proxy/fundamentals/"):
            return httpx.Response(404, text="not found")
        route = path[len("/tws.proxy"):]
        if route == "/fundamentals/data_list":
            return httpx.Response(200, json=[{"conid": int(c), "field_name": "LONG_TERM_GROWTH",
                                              "display_value": ltg[int(c)]} for c in q["conids"].split(",")])
        if route.startswith("/fundamentals/data/predefined/nextg_qd/"):
            return httpx.Response(200, json=[{"field_name": "EPSTRENDGR", "display_value": "8.00%"}])
        if route.startswith("/fundamentals/financials/"):
            if q["annual"] != "true":
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"income": INCOME, "cash": CASH, "balance": BALANCE}[q["type"]])
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def portal(transport):
    return C.Portal(base=GW, transport=transport, max_rps=1000)


def seed_conids(cache, **ids):
    from vmi.data.ibportal.service import KEY_CONID

    for sym, cid in ids.items():
        cache.set(KEY_CONID.format(sym), cid)


def test_client_refuses_brokerage_routes():
    t, calls = fake_portal()
    with portal(t) as p, pytest.raises(C.PortalError, match="read-only"):
        p._send("/portal.proxy/v1/portal/iserver/accounts")
    assert calls == []


def test_not_logged_in_is_a_401_portal_error():
    t, _ = fake_portal(logged_in=False)
    with portal(t) as p, pytest.raises(C.PortalError) as err:
        p.financials(265598, "income")
    assert err.value.status == 401


def test_throttled_requests_are_retried():
    t, calls = fake_portal(throttle_first=2)
    with portal(t) as p:
        assert p.financials(265598, "income")["table"]["rows"]
    assert len(calls) == 3  # two 429s, then the answer


def test_non_json_answer_is_reported():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}))
    with portal(t) as p, pytest.raises(C.PortalError, match="not JSON.*text/html.*login"):
        p.financials(1, "income")


def test_rate_limiter_spaces_requests_across_threads():
    import time
    from concurrent.futures import ThreadPoolExecutor

    limit = C.RateLimiter(rps=50)  # 20 ms apart
    started = time.monotonic()
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda _: limit.wait(), range(11)))
    assert time.monotonic() - started >= 0.18  # 10 gaps of 20 ms, whatever the thread count


# ---------------------------------------------------------------------------------------------- service
def test_sync_fills_cache_in_parallel(isolated_cache):
    import threading

    t, calls = fake_portal()
    threads = set()
    real = t.handle_request
    t.handle_request = lambda req: (threads.add(threading.get_ident()), real(req))[1]
    from vmi.data.fundamentals import MERGED_KEY

    seed_conids(isolated_cache, AAPL=265598, MSFT=272093)
    isolated_cache.set(MERGED_KEY.format("AAPL"), {"stale": True})
    with portal(t) as p:
        report = ibportal.sync(["aapl", "MSFT", "NOPE"], p, workers=4)
    assert report["conids"] == 2 and report["analyst"] == 2 and report["statements"] == 2
    assert list(report["failed"]) == ["NOPE"] and report["workers"] == 4
    assert ibportal.cached_estimates("AAPL") == {"eps_growth_5y": pytest.approx(0.0907)}  # data_list wins over key metric
    assert ibportal.cached_fundamentals("MSFT").annual["revenue"][-1].fy == 2024
    assert isolated_cache.get(MERGED_KEY.format("AAPL")) is None  # merged cache invalidated
    assert not any("/iserver" in c for c in calls)
    assert len(threads) > 1  # really ran on several threads


def test_sync_stops_when_the_session_ends(isolated_cache):
    t, _ = fake_portal(logged_in=False)
    seed_conids(isolated_cache, AAPL=265598)
    with portal(t) as p, pytest.raises(C.PortalError):
        ibportal.sync(["AAPL"], p)  # data_list is the first call: a 401 there aborts at once


def test_app_reads_ib_portal_data_from_cache_only(isolated_cache, monkeypatch):
    from vmi.data.ibportal.service import KEY_EST

    monkeypatch.setattr(ib_fundamentals, "tws_report", lambda *a, **k: None)
    isolated_cache.set(KEY_EST.format("AAPL"), {"eps_growth_5y": 0.1})
    assert ib_fundamentals.estimates("AAPL") == {"eps_growth_5y": 0.1}
    assert ib_fundamentals.fundamentals("ZZZZ") is None  # nothing cached: no network attempt


def test_breaker():
    b = Breaker("test_breaker", seconds=60)
    assert b.ready
    b.trip("nope")
    assert not b.ready and b.status()["last_error"] == "nope"
    b.reset()
    assert b.ready
    assert get_cache() is not None


def test_check_reports_routes_and_saves_raw_json(tmp_path, isolated_cache):
    t, _ = fake_portal()
    seed_conids(isolated_cache, AAPL=265598)
    with portal(t) as p:
        report = ibportal.check(["AAPL"], tmp_path, p)
    entry = report["AAPL"]
    assert report["mode"] == "fast (httpx)"
    assert entry["conid"] == 265598 and entry["income_annual"] == "ok"
    assert entry["parsed_annual"]["revenue"] == 3
    assert entry["analyst"] == {"eps_growth_5y": pytest.approx(0.0907)}
    assert (tmp_path / "AAPL.json").exists()


def test_tws_port_is_found_without_configuration():
    from vmi.config import Settings
    from vmi.data.ib import AUTO_PORTS, candidate_ports

    assert Settings().ib_port == 0  # defaults need no .env
    assert candidate_ports(0) == AUTO_PORTS and candidate_ports(7497) == (7497,)  # a configured port is used alone


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

    p = C.Portal("https://site.test", http=BrowserHttp(Ctx, "https://site.test"))
    assert not p.parallel and p.data_list([1], ["BETA"])[0]["field_name"] == "BETA"  # browser fallback: serial


def test_real_aapl_row_names_map_to_concepts():
    from vmi.data.ibportal.parse import concept_for

    seen = {"Cost of Rev.": "cost_of_revenue", "Rsrch and Dev. Exp.": "rd", "Net Inc. Incl. Ex. Items": "net_income",
            "Diluted EPS Excluding ExtraOrd Items": "eps_diluted", "Cash from Op. Act.": "cfo",
            "Selling/General/Admin. Expenses, Total": "sga", "Shares Outstanding": "shares_outstanding"}
    assert {k: concept_for(k) for k in seen} == seen


def test_epstrendgr_key_metric_becomes_the_five_year_growth_source():
    from vmi.data.ibportal.parse import parse_key_metrics

    rows = [{"field_name": "EPSTRENDGR", "display_value": "9.85%"}, {"field_name": "MKTCAP", "display_value": "5.08T"}]
    assert parse_key_metrics(rows)["eps_growth_5y"] == pytest.approx(0.0985) and parse_key_metrics(None) == {}


def test_ib_ab_drops_only_ib_growth_and_restores_the_source(monkeypatch):
    from vmi.analysis import calibrate, ib_ab
    from vmi.data import estimates

    monkeypatch.setattr(estimates, "from_ib", lambda t: {"eps_growth_5y": 0.1, "beta": 1.2})
    seen = []
    monkeypatch.setattr(calibrate, "run", lambda syms, tech, judged: seen.append(estimates.SOURCES["ib"]("X")) or [])
    original = estimates.SOURCES["ib"]
    ib_ab._run(None, False, keep_ib_growth=False)
    ib_ab._run(None, False, keep_ib_growth=True)
    assert seen == [{"beta": 1.2}, {"eps_growth_5y": 0.1, "beta": 1.2}]
    assert estimates.SOURCES["ib"] is original
