"""SEC EDGAR XBRL provider — free, official, 10+ years of statements for every US filer.

Two access patterns:
  * companyfacts (per company)  → full normalised history for deep analysis
  * frames (per concept/period) → ONE request returns a concept for ALL filers. This is what makes
    the superscanner's broad first pass (Step 1 track record) cheap: ~50 requests cover the market.

Fair-access policy: descriptive User-Agent + ≤10 req/s (we use 8, see vmi.data.http).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from vmi.config import get_settings
from vmi.data import http
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

# ---------------------------------------------------------------------------------------------
# Concept aliases. Order = preference. Values are merged per period (companies switch tags over
# time, e.g. SalesRevenueNet → RevenueFromContractWithCustomer... after ASC 606 in 2018).
# ---------------------------------------------------------------------------------------------
FLOW_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
        "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense",
        "TotalRevenuesAndOtherIncome", "RealEstateRevenueNet", "OperatingLeasesIncomeStatementLeaseRevenue",
        "InterestAndDividendIncomeOperating",
    ),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense", "InterestPaidNet"),
    "d_and_a": ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                "DepreciationAmortizationAndAccretionNet", "Depreciation"),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements", "PaymentsToAcquireOtherPropertyPlantAndEquipment",
              "PaymentsToAcquireRealEstate"),
    "dividends_paid": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "sbc": ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
}
PER_SHARE_CONCEPTS: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"),
    "dps": ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"),
}
SHARE_FLOW_CONCEPTS: dict[str, tuple[str, ...]] = {
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                       "WeightedAverageNumberOfSharesOutstandingBasic"),
}
INSTANT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash",
             "CashAndDueFromBanks"),
    "st_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent",
                       "AvailableForSaleSecuritiesDebtSecuritiesCurrent", "OtherShortTermInvestments"),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_assets": ("Assets",),
    "total_liabilities": ("Liabilities",),
    "equity": ("StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "goodwill": ("Goodwill",),
    "intangibles": ("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"),
    "lt_debt": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt",
                "LongTermNotesPayable", "SeniorLongTermNotes", "UnsecuredLongTermDebt"),
    "st_debt": ("LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                "ShortTermBorrowings", "CommercialPaper", "NotesPayableCurrent"),
    "receivables": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
                    "AccountsNotesAndLoansReceivableNetCurrent"),
    "inventory": ("InventoryNet",),
    "payables": ("AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"),
    "shares_outstanding": ("CommonStockSharesOutstanding",),
}
DEI_SHARES = "EntityCommonStockSharesOutstanding"


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent}


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


# ---------------------------------------------------------------------------------------------
# Ticker ↔ CIK map
# ---------------------------------------------------------------------------------------------
def ticker_map() -> dict[str, dict]:
    """{TICKER: {cik, name, exchange}} for every SEC-registered listed company."""
    def fetch():
        raw = http.get("https://www.sec.gov/files/company_tickers_exchange.json", headers=_headers())
        out = {}
        for cik, name, ticker, exch in raw["data"]:
            if ticker:
                out[ticker.upper()] = {"cik": int(cik), "name": name, "exchange": exch or ""}
        return out

    return get_cache().get_or_set("sec:tickers", get_settings().ttl_universe, fetch)


def cik_for(ticker: str) -> int | None:
    t = ticker.upper().replace(".", "-")
    m = ticker_map()
    rec = m.get(t) or m.get(t.replace("-", "."))
    return rec["cik"] if rec else None


# ---------------------------------------------------------------------------------------------
# Normalisation of companyfacts
# ---------------------------------------------------------------------------------------------
def _facts_for(raw: dict, tag: str, units: Iterable[str]) -> list[dict]:
    for ns in ("us-gaap", "ifrs-full", "dei"):
        node = raw.get("facts", {}).get(ns, {}).get(tag)
        if node:
            for u in units:
                if u in node.get("units", {}):
                    return node["units"][u]
    return []


def _annual_flows(facts: list[dict]) -> dict[str, tuple[float, str, int | None]]:
    """end-date → (value, filed, fy) for ~1-year durations from annual reports (latest filing wins)."""
    out: dict[str, tuple[float, str, int | None]] = {}
    for f in facts:
        if "start" not in f or f.get("form", "") not in ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "10-KT"):
            continue
        d = _days(f["start"], f["end"])
        if not 330 <= d <= 400:
            continue
        prev = out.get(f["end"])
        if prev is None or f.get("filed", "") >= prev[1]:
            out[f["end"]] = (float(f["val"]), f.get("filed", ""), f.get("fy"))
    return out


def _quarterly_flows(facts: list[dict]) -> dict[str, float]:
    """end-date → single-quarter value. Derives quarters from YTD cumulatives (cash-flow statements
    are only reported YTD in 10-Qs) and Q4 = FY − 9M."""
    by_start: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    for f in facts:
        if "start" not in f:
            continue
        d = _days(f["start"], f["end"])
        if 80 <= d <= 380:
            prev = by_start[f["start"]].get(f["end"])
            if prev is None or f.get("filed", "") >= prev[1]:
                by_start[f["start"]][f["end"]] = (float(f["val"]), f.get("filed", ""))
    quarters: dict[str, float] = {}
    for start, ends in by_start.items():
        ordered = sorted(ends.items())
        prev_end, prev_val = start, 0.0
        for end, (val, _) in ordered:
            span = _days(prev_end, end)
            if 80 <= span <= 100:
                q = val - prev_val
                if end not in quarters or _days(start, end) <= 100:
                    quarters[end] = q
            prev_end, prev_val = end, val
    return quarters


def _ttm(facts: list[dict], annual: dict[str, tuple[float, str, int | None]]) -> float | None:
    """TTM = last FY + (current YTD − prior-year YTD) when a 10-Q is newer than the last 10-K."""
    if not annual:
        return None
    last_end = max(annual)
    fy_val = annual[last_end][0]
    ytd = [f for f in facts if "start" in f and f["end"] > last_end and 80 <= _days(f["start"], f["end"]) <= 300]
    if not ytd:
        return fy_val
    cur = max(ytd, key=lambda f: (f["end"], _days(f["start"], f["end"]), f.get("filed", "")))
    span = _days(cur["start"], cur["end"])
    cur_end = date.fromisoformat(cur["end"])
    for f in facts:
        if "start" not in f:
            continue
        e = date.fromisoformat(f["end"])
        if abs((cur_end - e).days - 365) <= 12 and abs(_days(f["start"], f["end"]) - span) <= 12:
            return fy_val + float(cur["val"]) - float(f["val"])
    return fy_val


def _instants(facts: list[dict]) -> dict[str, float]:
    out: dict[str, tuple[float, str]] = {}
    for f in facts:
        if "start" in f:
            continue
        prev = out.get(f["end"])
        if prev is None or f.get("filed", "") >= prev[1]:
            out[f["end"]] = (float(f["val"]), f.get("filed", ""))
    return {k: v[0] for k, v in out.items()}


def _merge_aliases(raw: dict, tags: tuple[str, ...], units: tuple[str, ...], kind: str):
    """Merge alias tags period-by-period (first alias with a value for that period wins)."""
    annual: dict[str, tuple[float, str, int | None]] = {}
    quarterly: dict[str, float] = {}
    instants: dict[str, float] = {}
    ttm_val: float | None = None
    ttm_end = ""
    for tag in tags:
        facts = _facts_for(raw, tag, units)
        if not facts:
            continue
        if kind == "instant":
            for k, v in _instants(facts).items():
                instants.setdefault(k, v)
            continue
        a = _annual_flows(facts)
        for k, v in a.items():
            annual.setdefault(k, v)
        for k, v in _quarterly_flows(facts).items():
            quarterly.setdefault(k, v)
        t = _ttm(facts, a)
        latest_end = max([f["end"] for f in facts if "start" in f] or [""])
        if t is not None and latest_end > ttm_end:
            ttm_val, ttm_end = t, latest_end
    return annual, quarterly, instants, ttm_val


def _to_points(d: dict, max_n: int = 12, annual: bool = True) -> list[Point]:
    items = sorted(d.items())
    # collapse to one value per fiscal period: drop entries whose end is within 300 days of the next
    pts: list[Point] = []
    for end, val in items:
        v = val[0] if isinstance(val, tuple) else val
        fy = val[2] if isinstance(val, tuple) and len(val) > 2 else None
        if annual and pts and _days(pts[-1].end, end) < 300:
            pts[-1] = Point(end=end, value=v, fy=fy)
            continue
        pts.append(Point(end=end, value=v, fy=fy))
    return pts[-max_n:]


def normalise(raw: dict, ticker: str) -> Fundamentals:
    fund = Fundamentals(ticker=ticker.upper(), cik=int(raw.get("cik", 0)) or None,
                        name=raw.get("entityName", ""), source="sec")
    groups = (
        (FLOW_CONCEPTS, ("USD",), "flow"),
        (PER_SHARE_CONCEPTS, ("USD/shares",), "flow"),
        (SHARE_FLOW_CONCEPTS, ("shares",), "flow"),
        (INSTANT_CONCEPTS, ("USD", "shares"), "instant"),
    )
    # detect reporting currency for foreign filers (20-F in non-USD)
    for name, tags, in (("revenue", FLOW_CONCEPTS["revenue"]),):
        for tag in tags:
            for ns in ("us-gaap", "ifrs-full"):
                node = raw.get("facts", {}).get(ns, {}).get(tag)
                if node and "USD" not in node.get("units", {}) and node.get("units"):
                    fund.currency = next(iter(node["units"]))
    cur = fund.currency
    latest_instant = ""
    for concepts, units, kind in groups:
        units = tuple(u.replace("USD", cur) for u in units)
        for name, tags in concepts.items():
            annual, quarterly, instants, ttm_val = _merge_aliases(raw, tags, units, kind)
            if kind == "instant":
                if instants:
                    end = max(instants)
                    fund.latest[name] = instants[end]
                    latest_instant = max(latest_instant, end)
                    # year-end balance sheet history (for ROE/ROIC/CCC/AR trends)
                    fund.annual[name] = _to_points(instants, 40, annual=False)
                continue
            if annual:
                fund.annual[name] = _to_points(annual)
            if quarterly:
                fund.quarterly[name] = [Point(end=k, value=v) for k, v in sorted(quarterly.items())][-12:]
            if ttm_val is not None and name not in ("eps_diluted", "dps", "shares_diluted"):
                fund.ttm[name] = ttm_val
    dei = _facts_for(raw, DEI_SHARES, ("shares",))
    if dei:
        last = max(dei, key=lambda f: (f["end"], f.get("filed", "")))
        fund.latest["shares_outstanding"] = float(last["val"])
    # Keep instant histories aligned to fiscal year ends of revenue (annual balance sheets)
    fy_ends = set(fund.years("revenue")) | set(fund.years("net_income"))
    for name in INSTANT_CONCEPTS:
        pts = fund.annual.get(name)
        if pts and fy_ends:
            aligned = [p for p in pts if p.end in fy_ends]
            fund.annual[name] = aligned[-12:]
    fund.latest_date = latest_instant
    _drop_stale_and_derive(fund)
    if not fund.annual.get("revenue"):
        fund.warnings.append("No revenue history found in XBRL")
    return fund


def _drop_stale_and_derive(fund: Fundamentals) -> None:
    """Remove alias series that stopped years ago (company switched tags) and derive missing ones."""
    rev = fund.annual.get("revenue") or fund.annual.get("net_income")
    if rev:
        ref_end = rev[-1].end
        for name in list(fund.annual):
            pts = fund.annual[name]
            if pts and _days(pts[-1].end, ref_end) > 800:
                del fund.annual[name]
                fund.ttm.pop(name, None)
                fund.quarterly.pop(name, None)
    # Gross profit = revenue − cost of revenue (many filers do not tag GrossProfit)
    if "gross_profit" not in fund.annual and "cost_of_revenue" in fund.annual and "revenue" in fund.annual:
        cogs = {p.end: p.value for p in fund.annual["cost_of_revenue"]}
        gp = [Point(end=p.end, value=p.value - cogs[p.end], fy=p.fy) for p in fund.annual["revenue"] if p.end in cogs]
        if gp:
            fund.annual["gross_profit"] = gp
            if "revenue" in fund.ttm and "cost_of_revenue" in fund.ttm:
                fund.ttm["gross_profit"] = fund.ttm["revenue"] - fund.ttm["cost_of_revenue"]
    # Free cash flow series
    if "cfo" in fund.annual:
        capex = {p.end: p.value for p in fund.annual.get("capex", [])}
        fund.annual["fcf"] = [Point(end=p.end, value=p.value - abs(capex.get(p.end, 0.0)), fy=p.fy)
                              for p in fund.annual["cfo"]]
        if "cfo" in fund.ttm:
            fund.ttm["fcf"] = fund.ttm["cfo"] - abs(fund.ttm.get("capex", 0.0))
    # EBITDA ≈ operating income + D&A
    if "operating_income" in fund.annual:
        da = {p.end: p.value for p in fund.annual.get("d_and_a", [])}
        fund.annual["ebitda"] = [Point(end=p.end, value=p.value + da.get(p.end, 0.0), fy=p.fy)
                                 for p in fund.annual["operating_income"]]
        if "operating_income" in fund.ttm:
            fund.ttm["ebitda"] = fund.ttm["operating_income"] + fund.ttm.get("d_and_a", 0.0)


def fundamentals(ticker: str, force: bool = False) -> Fundamentals | None:
    cik = cik_for(ticker)
    if cik is None:
        return None
    cache = get_cache()
    key = f"sec:fund:v4:{cik}"
    if not force:
        cached = cache.get(key, get_settings().ttl_fundamentals)
        if cached:
            return Fundamentals.from_dict(cached)
    try:
        raw = http.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=_headers())
    except http.HttpError:
        stale = cache.get(key, allow_stale=True)
        return Fundamentals.from_dict(stale) if stale else None
    fund = normalise(raw, ticker)
    meta = submissions_meta(cik)
    fund.sic = meta.get("sic")
    fund.sic_description = meta.get("sicDescription", "")
    cache.set(key, fund.to_dict())
    return fund


def submissions_meta(cik: int) -> dict:
    def fetch():
        raw = http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=_headers())
        sic = raw.get("sic")
        return {"sic": int(sic) if sic else None, "sicDescription": raw.get("sicDescription", ""),
                "name": raw.get("name", ""), "fiscalYearEnd": raw.get("fiscalYearEnd", ""),
                "tickers": raw.get("tickers", []), "exchanges": raw.get("exchanges", [])}
    try:
        return get_cache().get_or_set(f"sec:sub:{cik}", 30 * 24 * 3600, fetch)
    except http.HttpError:
        return {}


# ---------------------------------------------------------------------------------------------
# Frames — cross-sectional snapshots of a concept for all filers
# ---------------------------------------------------------------------------------------------
def frame(tag: str, period: str, unit: str = "USD") -> dict[int, float]:
    """{cik: value} for e.g. tag='NetCashProvidedByUsedInOperatingActivities', period='CY2024'."""
    def fetch():
        try:
            raw = http.get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/{unit}/{period}.json",
                           headers=_headers())
        except http.HttpError:
            return {}
        return {str(r["cik"]): float(r["val"]) for r in raw.get("data", [])}

    ttl = 3 * 24 * 3600
    data = get_cache().get_or_set(f"sec:frame:{tag}:{unit}:{period}", ttl, fetch)
    return {int(k): v for k, v in data.items()}


def frame_concept(concept: str, period: str) -> dict[int, float]:
    """Alias-merged frame for a normalised concept name (e.g. 'revenue')."""
    tags = FLOW_CONCEPTS.get(concept) or INSTANT_CONCEPTS.get(concept) or (concept,)
    merged: dict[int, float] = {}
    for tag in tags:
        for cik, v in frame(tag, period).items():
            merged.setdefault(cik, v)
    return merged
