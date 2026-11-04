"""stockanalysis.com provider — second independent fundamentals source (free, server-rendered).

Pages embed full statement tables as JS object literals ({datekey:[...], revenue:[...], ...});
we parse them with vmi.data.jsobj (tokenizer, no regex hacks). Gives ~5–6 annual years + TTM and
20 quarters of income statement, cash-flow, balance sheet and ratio history (ROE, ROIC, P/B, P/S,
current ratio, Debt/EBITDA …) for every US listing — used to fill any gap left by SEC XBRL and to
cross-check it.
"""
from __future__ import annotations

from vmi.config import get_settings
from vmi.data import http
from vmi.data.cache import get_cache
from vmi.data.jsobj import find_objects
from vmi.data.models import Fundamentals, Point

BASE = "https://stockanalysis.com/stocks/{sym}/{page}"

PAGES = {
    "income": "financials/",
    "income_q": "financials/?p=quarterly",
    "cash": "financials/cash-flow-statement/",
    "cash_q": "financials/cash-flow-statement/?p=quarterly",
    "balance": "financials/balance-sheet/",
    "ratios": "financials/ratios/",
}
# the overview pages hold the full statement only on the dedicated sub-page
PAGES["income"] = "financials/income-statement/"
PAGES["income_q"] = "financials/income-statement/?p=quarterly"

# stockanalysis field → our concept, sign (capex is negative there)
INCOME_MAP = {"revenue": "revenue", "cor": "cost_of_revenue", "gp": "gross_profit", "opinc": "operating_income",
              "pretax": "pretax_income", "taxexp": "income_tax", "netinccmn": "net_income",
              "interestExpense": "interest_expense", "depAmorEbitda": "d_and_a", "ebitda": "ebitda",
              "epsdil": "eps_diluted", "dps": "dps", "sharesDiluted": "shares_diluted"}
CASH_MAP = {"ncfo": "cfo", "capex": "capex", "fcf": "fcf", "commonDividendCF": "dividends_paid",
            "commonRepurchased": "buybacks", "sbcomp": "sbc", "cashInterestPaid": "interest_paid"}
BAL_MAP = {"cashneq": "cash", "investmentsc": "st_investments", "assetsc": "current_assets",
           "currentLiabilities": "current_liabilities", "assets": "total_assets", "liabilities": "total_liabilities",
           "equity": "equity", "goodwill": "goodwill", "otherIntangibles": "intangibles", "debtnc": "lt_debt",
           "debtc": "st_debt", "accountsReceivable": "receivables", "inventory": "inventory",
           "accountsPayable": "payables", "sharesOutTotalCommon": "shares_outstanding", "bvps": "bvps",
           "tangibleBookValue": "tangible_book", "debt": "total_debt"}
RATIO_MAP = {"roe": "roe", "roic": "roic", "roa": "roa", "currentratio": "current_ratio",
             "debtebitda": "debt_ebitda", "debtequity": "debt_equity", "pb": "pb", "ps": "ps", "pe": "pe",
             "pegRatio": "peg", "payoutratio": "payout", "dividendyield": "dividend_yield",
             "buybackyield": "buyback_yield", "marketcap": "market_cap", "lastCloseRatios": "price"}


def _slug(ticker: str) -> str:
    return ticker.lower().replace(".", "-")


def _table(ticker: str, page: str) -> dict:
    sym = _slug(ticker)

    def fetch():
        html = http.get(BASE.format(sym=sym, page=PAGES[page]), expect_json=False)
        objs = [o for o in find_objects(html, "{datekey:[") if isinstance(o, dict)]
        if not objs:
            return {}
        return max(objs, key=len)

    try:
        return get_cache().get_or_set(f"sa:{page}:{sym}", get_settings().ttl_fundamentals, fetch) or {}
    except Exception:
        return {}


def _split(table: dict, field: str) -> tuple[list[Point], float | None]:
    """→ (oldest→newest annual/quarterly points, TTM value)."""
    keys, vals = table.get("datekey") or [], table.get(field) or []
    fys = table.get("fiscalYear") or []
    pts, ttm = [], None
    for i, (k, v) in enumerate(zip(keys, vals)):
        if v is None or isinstance(v, str):
            continue
        if k == "TTM":
            ttm = float(v)
            continue
        fy = None
        try:
            fy = int(fys[i]) if i < len(fys) else None
        except (TypeError, ValueError):
            pass
        pts.append(Point(end=k, value=float(v), fy=fy))
    pts.sort(key=lambda p: p.end)
    return pts, ttm


def fundamentals(ticker: str) -> Fundamentals | None:
    inc, cash, bal, rat = (_table(ticker, p) for p in ("income", "cash", "balance", "ratios"))
    if not (inc or cash or bal):
        return None
    inc_q, cash_q = _table(ticker, "income_q"), _table(ticker, "cash_q")
    f = Fundamentals(ticker=ticker.upper(), source="stockanalysis")
    for table, qtable, mapping in ((inc, inc_q, INCOME_MAP), (cash, cash_q, CASH_MAP)):
        for src, dst in mapping.items():
            pts, ttm = _split(table, src)
            if dst == "capex":
                pts = [Point(p.end, abs(p.value), p.fy) for p in pts]
                ttm = abs(ttm) if ttm is not None else None
            if dst in ("dividends_paid", "buybacks"):
                pts = [Point(p.end, abs(p.value), p.fy) for p in pts]
                ttm = abs(ttm) if ttm is not None else None
            if pts:
                f.annual[dst] = pts
                f.provenance[dst] = "stockanalysis"
            if ttm is not None and dst not in ("eps_diluted", "dps", "shares_diluted"):
                f.ttm[dst] = ttm
            qpts, _ = _split(qtable, src)
            if qpts:
                if dst in ("capex", "dividends_paid", "buybacks"):
                    qpts = [Point(p.end, abs(p.value), p.fy) for p in qpts]
                f.quarterly[dst] = qpts
    for src, dst in BAL_MAP.items():
        pts, ttm = _split(bal, src)
        if pts:
            f.annual[dst] = pts
            f.latest[dst] = ttm if ttm is not None else pts[-1].value
            f.provenance[dst] = "stockanalysis"
    for src, dst in RATIO_MAP.items():
        pts, ttm = _split(rat, src)
        if ttm is not None:
            pts = pts + [Point(end="TTM", value=ttm)]
        if pts:
            f.ratios[dst] = pts
    keys = [k for k in (bal.get("datekey") or []) if k != "TTM"]
    f.latest_date = max(keys) if keys else ""
    return f


def statistics(ticker: str) -> dict:
    """Key/value stats page (beta, shares, ROIC, PEG, …) — {id: hover_value}."""
    sym = _slug(ticker)

    def fetch():
        html = http.get(BASE.format(sym=sym, page="statistics/"), expect_json=False)
        out: dict[str, str] = {}
        for o in find_objects(html, "{id:"):
            if isinstance(o, dict) and "id" in o and ("hover" in o or "value" in o):
                out[str(o["id"])] = str(o.get("hover") or o.get("value"))
        return out

    try:
        return get_cache().get_or_set(f"sa:stats:{sym}", get_settings().ttl_estimates, fetch) or {}
    except Exception:
        return {}


def forecast(ticker: str) -> dict:
    """Analyst forecast page: projected EPS/revenue by year → implied growth rates."""
    sym = _slug(ticker)

    def fetch():
        html = http.get(BASE.format(sym=sym, page="forecast/"), expect_json=False)
        out: dict = {}
        for key in ("eps", "revenue"):
            marker = f"{key}:["
            i = html.find(marker)
            while i >= 0:
                from vmi.data.jsobj import balanced, parse
                try:
                    arr = parse(balanced(html, i + len(key) + 1))
                except Exception:
                    arr = None
                if isinstance(arr, list) and len(arr) >= 4:
                    out[key] = [x for x in arr if isinstance(x, (int, float))]
                    break
                i = html.find(marker, i + 1)
        return out

    try:
        return get_cache().get_or_set(f"sa:fc:{sym}", get_settings().ttl_estimates, fetch) or {}
    except Exception:
        return {}
