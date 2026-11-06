"""IB fundamentals: the one place that decides how the app gets fundamentals from Interactive Brokers.

Two paths, tried in this order, each behind its own circuit breaker (a refusal costs one call per pause):
  1. TWS API `reqFundamentalData` (LSEG XML: statements, snapshot ratios, analyst estimates).
     IBKR removed it from its API library in 10.47; current TWS/Gateway builds refuse it locally with error
     10358 unless the login carries IB's fundamentals-for-API permission. Kept because it costs one call to
     try, and it works automatically wherever IB still allows it.
  2. Client Portal Gateway → Fundamentals Explorer backend (vmi.data.ibportal): statements + analyst
     long-term growth. Read from the cache first; `sync` fills the cache for a whole universe at once.

CLI (run it on the PC where TWS and/or the gateway run):
    python -m vmi.data.ib_fundamentals check AAPL MSFT    # what works right now? raw JSON is saved
    python -m vmi.data.ib_fundamentals sync --sp500       # fill the IB cache for the S&P 500
Research notes and the setup decision: Log.md (2026-11-05).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
import xml.etree.ElementTree as ET

from vmi.config import get_settings
from vmi.data import ibportal
from vmi.data.breaker import Breaker
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

log = logging.getLogger("vmi.ib_fund")

TWS = Breaker("ib_tws_fundamentals", seconds=6 * 3600)
PORTAL = Breaker("ib_portal", seconds=60)  # not running / not logged in is the normal state: recheck every minute
TWS_REFUSALS = ("10358", "not allowed")  # account-wide refusal → pause; 430 (one security lacks data) is not

# ============================================================================================ TWS XML
# ReportsFinStatements COA code → concept. Map-item labels are matched too, for robustness.
COA = {
    "RTLR": "revenue", "SREV": "revenue", "SCOR": "cost_of_revenue", "SGRP": "gross_profit",
    "SOPI": "operating_income", "EIBT": "pretax_income", "TTAX": "income_tax", "NINC": "net_income",
    "SDWS": "shares_diluted", "SDBF": "eps_diluted", "DDPS1": "dps", "STIE": "interest_expense",
    "OTLO": "cfo", "SCEX": "capex", "SDED": "d_and_a", "FCDP": "dividends_paid",
    "ACAE": "cash", "SCSI": "cash_and_st", "ATCA": "current_assets", "LTCL": "current_liabilities",
    "ATOT": "total_assets", "LTLL": "total_liabilities", "QTLE": "equity", "LTTD": "lt_debt",
    "LCLD": "st_debt", "AGWI": "goodwill", "AINT": "intangibles", "AACR": "receivables",
    "AITL": "inventory", "LAPB": "payables", "QTCO": "shares_outstanding",
}
LABELS = {
    "total revenue": "revenue", "cost of revenue, total": "cost_of_revenue", "gross profit": "gross_profit",
    "operating income": "operating_income", "net income before taxes": "pretax_income",
    "provision for income taxes": "income_tax", "net income": "net_income",
    "diluted weighted average shares": "shares_diluted", "diluted eps excluding extraord items": "eps_diluted",
    "dps - common stock primary issue": "dps", "cash from operating activities": "cfo",
    "capital expenditures": "capex", "total current assets": "current_assets",
    "total current liabilities": "current_liabilities", "total assets": "total_assets",
    "total liabilities": "total_liabilities", "total equity": "equity", "long term debt": "lt_debt",
    "goodwill, net": "goodwill", "intangibles, net": "intangibles",
    "cash and short term investments": "cash_and_st", "total common shares outstanding": "shares_outstanding",
    "total inventory": "inventory", "accounts receivable - trade, net": "receivables",
    "accounts payable": "payables",
}
SCALE = {"M": 1e6, "K": 1e3, "B": 1e9, "U": 1.0}
NOT_SCALED = {"eps_diluted", "dps"}
INSTANTS = ("cash", "current_assets", "current_liabilities", "total_assets", "total_liabilities", "equity",
            "lt_debt", "st_debt", "goodwill", "intangibles", "receivables", "inventory", "payables",
            "shares_outstanding")


def parse_fin_statements(xml: str, ticker: str) -> Fundamentals | None:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    f = Fundamentals(ticker=ticker.upper(), source="ib")
    labels = {m.get("coaItem"): (m.text or "").strip().lower() for m in root.iter("mapItem")}
    units = (root.findtext(".//UnitsConvertedTo") or root.findtext(".//Units") or "M").strip()[:1].upper()
    scale = SCALE.get(units, 1e6)
    for period_tag, target in (("AnnualPeriods", f.annual), ("InterimPeriods", f.quarterly)):
        node = root.find(f".//{period_tag}")
        if node is None:
            continue
        for fp in node.findall("FiscalPeriod"):
            end = fp.get("EndDate", "")[:10]
            fy = int(fp.get("FiscalYear")) if (fp.get("FiscalYear") or "").isdigit() else None
            for st in fp.findall("Statement"):
                for li in st.findall("lineItem"):
                    code = li.get("coaCode", "")
                    concept = COA.get(code) or LABELS.get(labels.get(code, ""))
                    if not concept or li.text is None:
                        continue
                    try:
                        v = float(li.text)
                    except ValueError:
                        continue
                    if concept not in NOT_SCALED:
                        v *= scale
                    if concept in ("capex", "dividends_paid"):
                        v = abs(v)
                    series = target.setdefault(concept, [])
                    if not any(p.end == end for p in series):
                        series.append(Point(end=end, value=v, fy=fy))
    for d in (f.annual, f.quarterly):
        for k in d:
            d[k].sort(key=lambda p: p.end)
    if "cash_and_st" in f.annual and "cash" not in f.annual:
        f.annual["cash"] = f.annual["cash_and_st"]
    for c in INSTANTS:
        src = f.quarterly.get(c) or f.annual.get(c)
        if src:
            f.latest[c] = src[-1].value
    for c in ("revenue", "net_income", "cfo", "capex", "operating_income", "interest_expense", "d_and_a"):
        q = f.quarterly.get(c, [])
        if len(q) >= 4:
            f.ttm[c] = sum(p.value for p in q[-4:])
    for c in f.annual:
        f.provenance[c] = "ib"
    return f if f.annual.get("revenue") or f.annual.get("net_income") else None


def parse_snapshot(xml: str) -> dict:
    """ReportSnapshot → {FieldName: value}, incl. ProjLTGrowthRate, BETA, PEEXCLXOR, TTMROEPCT …"""
    out: dict = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for r in root.iter("Ratio"):
        name = r.get("FieldName")
        val = r.findtext("Value") if r.find("Value") is not None else r.text
        if name and val not in (None, ""):
            try:
                out[name] = float(val)
            except ValueError:
                out[name] = val
    return out


def parse_resc(xml: str) -> dict:
    """RESC analyst estimates → {'eps_ltg': mean long-term growth (decimal)}."""
    out: dict = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for est in root.iter("FYEstimate"):
        if (est.get("type") or "").upper() != "LTG":
            continue
        for ce in est.iter("ConsEstimate"):
            if ce.get("type") == "Mean":
                try:
                    out["eps_ltg"] = float(ce.findtext("ConsValue")) / 100
                except (TypeError, ValueError):
                    pass
    return out


# ========================================================================================= TWS requests
def _tws_request(symbol: str, report: str, timeout: float = 15.0) -> tuple[str | None, str]:
    """One reqFundamentalData call → (xml or None, error text). No cache, no breaker."""
    from vmi.data.ib import gateway

    gw = gateway()
    if not gw.connected:
        return None, f"TWS not connected ({gw.last_error or gw.status})"

    async def run():
        return await gw.ib.reqFundamentalDataAsync(await gw._stock(symbol), report)

    try:
        xml = gw.call(run, timeout=timeout)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return (xml, "") if xml else (None, gw.last_error or "empty answer")


def tws_report(symbol: str, report: str) -> str | None:
    """Cached, breaker-guarded reqFundamentalData (ReportsFinStatements / ReportSnapshot / RESC)."""
    key = f"ibf:{report}:{symbol.upper()}"
    if cached := get_cache().get(key, get_settings().ttl_fundamentals):
        return cached
    if not TWS.ready:
        return None
    xml, err = _tws_request(symbol, report)
    if xml:
        get_cache().set(key, xml)
    elif err.startswith("TimeoutError") or any(s in err.lower() for s in TWS_REFUSALS):
        TWS.trip(err)  # IB refused or ignored the request; a mere disconnect is not a refusal
    return xml


# ======================================================================================== Portal path
def _portal(read, ticker: str, empty):
    """Cache first; a live gateway call only when configured and not paused by the breaker."""
    live = ibportal.enabled() and PORTAL.ready
    try:
        return read(ticker, live=live)
    except Exception as exc:  # gateway down, not logged in, route changed …
        PORTAL.trip(f"{type(exc).__name__}: {exc}")
        return empty


# ============================================================================================= public
def fundamentals(ticker: str) -> Fundamentals | None:
    """TWS XML first, then the Client Portal Gateway; None when neither has data."""
    xml = tws_report(ticker, "ReportsFinStatements")
    f = parse_fin_statements(xml, ticker) if xml else None
    if f is not None:
        if snap := tws_report(ticker, "ReportSnapshot"):
            f.meta["ib_snapshot"] = parse_snapshot(snap)
        return f
    return _portal(ibportal.fundamentals, ticker, None)


def estimates(ticker: str) -> dict:
    """Analyst growth / beta from IB (decimals): TWS snapshot + RESC first, then the gateway."""
    out: dict = {}
    if snap := tws_report(ticker, "ReportSnapshot"):
        s = parse_snapshot(snap)
        if isinstance(s.get("ProjLTGrowthRate"), float):
            out["eps_growth_5y"] = s["ProjLTGrowthRate"] / 100
        for src, key in (("BETA", "beta"), ("PEEXCLXOR", "pe")):
            if isinstance(s.get(src), float):
                out[key] = s[src]
    resc = tws_report(ticker, "RESC")
    ltg = parse_resc(resc).get("eps_ltg") if resc else None
    if ltg is not None:
        out.setdefault("eps_growth_5y", ltg)
    for k, v in _portal(ibportal.estimates, ticker, {}).items():
        out.setdefault(k, v)
    return out


def status() -> dict:
    return {"tws": TWS.status(), "portal": {**PORTAL.status(), "configured": ibportal.enabled(),
                                            "gateway": ibportal.base_url()}}


# ================================================================================================ CLI
def tws_probe(symbol: str, wait: float = 10.0) -> dict:
    """Connect to TWS (as the app does) and try one ReportSnapshot, bypassing cache and breaker."""
    from vmi.data.ib import gateway

    gw = gateway()
    gw.start()
    deadline = time.time() + wait
    while not gw.connected and time.time() < deadline:
        time.sleep(0.5)
    xml, err = _tws_request(symbol, "ReportSnapshot", timeout=20)
    verdict = ("works" if xml else "not connected" if not gw.connected
               else "refused by IB for this login (10358)" if "10358" in err else "failed")
    return {"port": gw.port, "connected": gw.connected, "fundamentals": verdict, "detail": err}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m vmi.data.ib_fundamentals", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="test the TWS and gateway paths and save raw gateway JSON")
    c.add_argument("tickers", nargs="*", default=["AAPL"])
    c.add_argument("--no-tws", action="store_true", help="skip the TWS probe")
    c.add_argument("--browser", action="store_true", help="log in through a browser window instead of the gateway")
    p = sub.add_parser("probe", help="raw status/headers/body of every candidate gateway route (for debugging)")
    p.add_argument("conid", nargs="?", type=int, default=265598)
    s = sub.add_parser("sync", help="fill the IB cache from the gateway")
    s.add_argument("tickers", nargs="*")
    s.add_argument("--sp500", action="store_true", help="add every S&P 500 constituent")
    s.add_argument("--browser", action="store_true", help="log in through a browser window instead of the gateway")
    s.add_argument("--no-statements", action="store_true", help="analyst fields only (fast)")
    a = ap.parse_args(argv)

    if a.cmd == "probe":
        from vmi.data.ibportal.probe import probe

        print(json.dumps(probe(a.conid), indent=1))
        return
    if a.cmd == "check":
        report: dict = {}
        if not a.no_tws:
            report["tws"] = tws_probe(a.tickers[0])
        out = get_settings().data_dir / "ib_portal_samples"
        if a.browser:
            from vmi.data.ibportal.browser import browser_portal

            with browser_portal() as p:
                report["browser"] = ibportal.check(a.tickers, out, portal=p)
        else:
            report["gateway"] = (ibportal.check(a.tickers, out) if ibportal.enabled()
                                 else "VMI_IB_CP_URL not set (e.g. https://localhost:5000)")
        print(json.dumps(report, indent=2, default=str))
        return
    tickers = list(a.tickers)
    if a.sp500:
        from vmi.data.universe import sp500

        tickers += [r["symbol"] for r in sp500()]
    if not tickers:
        ap.error("give tickers or --sp500")
    if a.browser:
        from vmi.data.ibportal.browser import browser_portal

        with browser_portal() as p:
            report = ibportal.sync(tickers, statements=not a.no_statements, progress=print, portal=p)
    else:
        report = ibportal.sync(tickers, statements=not a.no_statements, progress=print)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
