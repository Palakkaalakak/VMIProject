"""IB fundamentals provider — tried FIRST, guarded by a circuit breaker.

Research summary (2026-11):
  * TWS API: `reqFundamentalData` (ReportsFinStatements / ReportSnapshot / RESC) was de-supported in
    TWS API 10.47 (May 2026); tick 47/258 removed. Since ~Apr 2026 IB servers answer older clients with
    error 10358 "Fundamentals data is not allowed". ib_async still exposes the call, so we keep trying
    it: any account/build that still receives the Refinitiv XML benefits automatically.
  * Client Portal Web API: fundamental snapshot tags (P/E, EPS, Beta, dividend …) deprecated Jan 2026.
    The portal's Fundamentals Explorer backend (`/fundamentals/financials/{conid}`) is undocumented; it is
    tried only when `VMI_IB_CP_URL` points at a running, logged-in Client Portal Gateway.

When IB answers, its data (Refinitiv/LSEG, FactSet-grade consensus) takes priority, including the
projected long-term growth rate (ProjLTGrowthRate) as an estimate source. On refusal the breaker opens
for BREAKER_SECONDS so scans are never slowed down by repeated failing calls.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

log = logging.getLogger("vmi.ib_fund")

BREAKER_SECONDS = 6 * 3600
_breaker: dict[str, float] = {}
_last_error: dict[str, str] = {}

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


def _open(path: str) -> bool:
    return time.time() >= _breaker.get(path, 0)


def _trip(path: str, err: str) -> None:
    _breaker[path] = time.time() + BREAKER_SECONDS
    _last_error[path] = err[:200]
    log.info("IB fundamentals path %s disabled for %ss: %s", path, BREAKER_SECONDS, err)


def status() -> dict:
    now = time.time()
    return {p: {"available": now >= _breaker.get(p, 0), "retry_in_s": max(0, int(_breaker.get(p, 0) - now)),
                "last_error": _last_error.get(p, "")} for p in ("tws", "cp")}


# ---------------------------------------------------------------------------------------- TWS XML
def tws_report(symbol: str, report: str, timeout: float = 15.0) -> str | None:
    if not _open("tws"):
        return None
    from vmi.data.ib import gateway

    gw = gateway()
    if not gw.connected:
        return None
    key = f"ibf:{report}:{symbol.upper()}"
    cached = get_cache().get(key, get_settings().ttl_fundamentals)
    if cached:
        return cached

    async def run():
        c = await gw._stock(symbol)
        return await gw.ib.reqFundamentalDataAsync(c, report)

    try:
        xml = gw.call(run, timeout=timeout)
    except Exception as exc:
        _trip("tws", f"{type(exc).__name__}: {exc}")
        return None
    if not xml:
        err = gw.last_error
        if "10358" in err or "430" in err or "not allowed" in err.lower():
            _trip("tws", err)
        return None
    get_cache().set(key, xml)
    return xml


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


# ---------------------------------------------------------------------------------- Client Portal
def cp_financials(symbol: str) -> dict | None:
    base = get_settings().ib_cp_url
    if not base or not _open("cp"):
        return None
    import httpx

    try:
        with httpx.Client(verify=False, timeout=15) as cl:
            r = cl.get(f"{base}/iserver/secdef/search", params={"symbol": symbol, "secType": "STK"})
            conid = (r.json() or [{}])[0].get("conid")
            if not conid:
                return None
            out = {}
            for typ in ("income", "balance", "cash"):
                rr = cl.get(f"{base}/fundamentals/financials/{conid}", params={"type": typ, "annual": "true"})
                if rr.status_code != 200:
                    raise RuntimeError(f"{rr.status_code} {rr.text[:80]}")
                out[typ] = rr.json()
            return out
    except Exception as exc:
        _trip("cp", f"{type(exc).__name__}: {exc}")
        return None


# ------------------------------------------------------------------------------------------ public
def fundamentals(ticker: str) -> Fundamentals | None:
    xml = tws_report(ticker, "ReportsFinStatements")
    if not xml:
        return None
    f = parse_fin_statements(xml, ticker)
    if f is not None:
        snap = tws_report(ticker, "ReportSnapshot")
        if snap:
            f.meta["ib_snapshot"] = parse_snapshot(snap)
    return f


def estimates(ticker: str) -> dict:
    """Growth/beta from IB when available (decimals)."""
    out: dict = {}
    snap = tws_report(ticker, "ReportSnapshot")
    if snap:
        s = parse_snapshot(snap)
        if isinstance(s.get("ProjLTGrowthRate"), float):
            out["eps_growth_5y"] = s["ProjLTGrowthRate"] / 100
        for k_src, k in (("BETA", "beta"), ("PEEXCLXOR", "pe")):
            if isinstance(s.get(k_src), float):
                out[k] = s[k_src]
    resc = tws_report(ticker, "RESC")
    if resc:
        r = parse_resc(resc)
        if r.get("eps_ltg") is not None:
            out.setdefault("eps_growth_5y", r["eps_ltg"])
    return out
