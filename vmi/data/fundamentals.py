"""Unified fundamentals resolver — the ONLY entry point analysis code uses for company financials.

Source priority per concept (each value tagged with provenance):
  1. SEC EDGAR XBRL       — official, longest history (10+ yrs), nightly.
  2. stockanalysis.com    — independent normalised statements + ratio history; fills SEC gaps
                            (missing tags, non-standard filers, TTM, interest expense, EBITDA …).
  3. Yahoo (yfinance)     — last-resort statements (4 yrs) and key stats.
  4. Derived              — computed from other concepts (e.g. FCF = CFO − capex, GP = Rev − COGS).
  5. FDIC                 — bank CET1 ratio.

IB note: IBKR removed reqFundamentalData + fundamental-ratio ticks in TWS API 10.47 (2026), so IB is
not a fundamentals source; it provides prices/history/options (vmi.data.market, vmi.data.ib).

`resolve(ticker)` returns a merged Fundamentals plus a completeness map; `REQUIRED` lists every input
the 7-step checks + valuation need, so `vmi.data.coverage` can prove completeness for any universe.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from vmi.config import get_settings
from vmi.data import sec, stockanalysis
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

log = logging.getLogger("vmi.fundamentals")

# Concepts the VMI pipeline needs, by kind. "annual" = ≥5y history required.
REQUIRED_ANNUAL = ("revenue", "net_income", "cfo", "capex", "operating_income", "shares_diluted", "eps_diluted")
REQUIRED_LATEST = ("cash", "equity", "total_assets")
REQUIRED_RATIOS = ("roe",)
OPTIONAL = ("gross_profit", "interest_expense", "ebitda", "dps", "receivables", "inventory", "payables",
            "current_assets", "current_liabilities", "lt_debt", "st_debt", "goodwill", "intangibles", "roic",
            "current_ratio", "debt_ebitda")


def _merge_series(primary: list[Point], secondary: list[Point]) -> list[Point]:
    """Union by fiscal period end (±20 days); primary wins on overlap."""
    out = list(primary)
    for p in secondary:
        if not any(abs((_d(p.end) - _d(q.end))) <= 20 for q in out):
            out.append(p)
    out.sort(key=lambda p: p.end)
    return out


def _d(s: str) -> int:
    from datetime import date
    try:
        return date.fromisoformat(s[:10]).toordinal()
    except ValueError:
        return 0


def _yahoo_statements(ticker: str) -> Fundamentals | None:
    """Last-resort statements from Yahoo (≈4 annual years)."""
    def fetch():
        import yfinance as yf

        t = yf.Ticker(ticker.upper().replace(".", "-"))
        out: dict = {"annual": {}, "latest": {}}
        rows = {
            "income_stmt": {"Total Revenue": "revenue", "Net Income": "net_income", "Operating Income": "operating_income",
                            "Gross Profit": "gross_profit", "Interest Expense": "interest_expense", "EBITDA": "ebitda",
                            "Diluted EPS": "eps_diluted", "Diluted Average Shares": "shares_diluted",
                            "Reconciled Depreciation": "d_and_a"},
            "cashflow": {"Operating Cash Flow": "cfo", "Capital Expenditure": "capex", "Free Cash Flow": "fcf",
                         "Cash Dividends Paid": "dividends_paid", "Repurchase Of Capital Stock": "buybacks"},
            "balance_sheet": {"Cash And Cash Equivalents": "cash", "Stockholders Equity": "equity",
                              "Total Assets": "total_assets", "Current Assets": "current_assets",
                              "Current Liabilities": "current_liabilities", "Long Term Debt": "lt_debt",
                              "Current Debt": "st_debt", "Goodwill": "goodwill", "Accounts Receivable": "receivables",
                              "Inventory": "inventory", "Accounts Payable": "payables",
                              "Other Short Term Investments": "st_investments",
                              "Total Liabilities Net Minority Interest": "total_liabilities",
                              "Ordinary Shares Number": "shares_outstanding"},
        }
        for attr, mapping in rows.items():
            try:
                df = getattr(t, attr)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            for label, concept in mapping.items():
                if label not in df.index:
                    continue
                pts = []
                for col, v in df.loc[label].items():
                    if v == v and v is not None:
                        val = abs(float(v)) if concept in ("capex", "dividends_paid", "buybacks") else float(v)
                        pts.append({"end": str(col)[:10], "value": val, "fy": None})
                pts.sort(key=lambda p: p["end"])
                if pts:
                    out["annual"][concept] = pts
                    if attr == "balance_sheet":
                        out["latest"][concept] = pts[-1]["value"]
        return out if out["annual"] else None

    try:
        d = get_cache().get_or_set(f"yf:stmts:{ticker.upper()}", get_settings().ttl_fundamentals, fetch)
    except Exception:
        return None
    if not d:
        return None
    f = Fundamentals(ticker=ticker.upper(), source="yahoo")
    f.annual = {k: [Point(**p) for p in v] for k, v in d["annual"].items()}
    f.latest = dict(d["latest"])
    return f


def _fill(target: Fundamentals, donor: Fundamentals | None, tag: str) -> None:
    if donor is None:
        return
    for c, pts in donor.annual.items():
        if not pts:
            continue
        mine = target.annual.get(c, [])
        newest_mine = mine[-1].end if mine else ""
        if not mine:
            target.annual[c] = list(pts)
            target.provenance[c] = tag
        else:
            merged = _merge_series(mine, pts)
            if len(merged) > len(mine):
                target.annual[c] = merged
                if pts[-1].end > newest_mine:
                    target.provenance[c] = f"{target.provenance.get(c, 'sec')}+{tag}"
    for c, v in donor.ttm.items():
        if c not in target.ttm and v is not None:
            target.ttm[c] = v
            target.provenance.setdefault(f"ttm:{c}", tag)
    for c, pts in donor.quarterly.items():
        if c not in target.quarterly and pts:
            target.quarterly[c] = list(pts)
    for c, v in donor.latest.items():
        if c not in target.latest and v is not None:
            target.latest[c] = v
            target.provenance.setdefault(c, tag)
    for c, pts in donor.ratios.items():
        if c not in target.ratios and pts:
            target.ratios[c] = list(pts)
    if not target.latest_date and donor.latest_date:
        target.latest_date = donor.latest_date


def _derive(f: Fundamentals) -> None:
    """Fill computable concepts and ratio histories (ROE, ROIC, current ratio, Debt/EBITDA, CCC)."""
    A = {c: {p.end: p.value for p in pts} for c, pts in f.annual.items()}

    def put_ratio(name: str, values: dict[str, float]):
        if values and name not in f.ratios:
            f.ratios[name] = [Point(end=k, value=v) for k, v in sorted(values.items())]
            f.provenance[f"ratio:{name}"] = "derived"

    if "fcf" not in f.annual and "cfo" in A:
        f.annual["fcf"] = [Point(e, v - abs(A.get("capex", {}).get(e, 0.0))) for e, v in sorted(A["cfo"].items())]
    if "fcf" not in f.ttm and "cfo" in f.ttm:
        f.ttm["fcf"] = f.ttm["cfo"] - abs(f.ttm.get("capex", 0.0))
    if "gross_profit" not in f.annual and "revenue" in A and "cost_of_revenue" in A:
        f.annual["gross_profit"] = [Point(e, v - A["cost_of_revenue"][e]) for e, v in sorted(A["revenue"].items())
                                    if e in A["cost_of_revenue"]]
    if "ebitda" not in f.annual and "operating_income" in A:
        f.annual["ebitda"] = [Point(e, v + A.get("d_and_a", {}).get(e, 0.0)) for e, v in sorted(A["operating_income"].items())]

    def match(series: dict[str, float], end: str) -> float | None:
        if end in series:
            return series[end]
        for k, v in series.items():
            if abs(_d(k) - _d(end)) <= 20:
                return v
        return None

    eq, ni = A.get("equity", {}), A.get("net_income", {})
    roe = {}
    for e, n in ni.items():
        cur, prev_e = match(eq, e), None
        if cur and cur > 0:
            roe[e] = n / cur
    put_ratio("roe", roe)
    # ROIC ≈ NOPAT / (equity + debt − cash)
    roic = {}
    for e, oi in A.get("operating_income", {}).items():
        tax_rate = 0.21
        pre, tax = match(A.get("pretax_income", {}), e), match(A.get("income_tax", {}), e)
        if pre and tax and pre > 0:
            tax_rate = min(0.35, max(0.0, tax / pre))
        ic = (match(eq, e) or 0) + (match(A.get("lt_debt", {}), e) or 0) + (match(A.get("st_debt", {}), e) or 0) \
            - (match(A.get("cash", {}), e) or 0)
        if ic > 0:
            roic[e] = oi * (1 - tax_rate) / ic
    put_ratio("roic", roic)
    cr = {e: ca / cl for e, ca in A.get("current_assets", {}).items()
          if (cl := match(A.get("current_liabilities", {}), e))}
    put_ratio("current_ratio", cr)
    de = {}
    for e, eb in A.get("ebitda", {}).items():
        debt = (match(A.get("lt_debt", {}), e) or 0) + (match(A.get("st_debt", {}), e) or 0)
        if eb and eb > 0:
            de[e] = debt / eb
    put_ratio("debt_ebitda", de)
    # Cash conversion cycle = DSO + DIO − DPO
    ccc = {}
    for e, rev in A.get("revenue", {}).items():
        ar = match(A.get("receivables", {}), e)
        if not rev or ar is None:
            continue
        cogs = match(A.get("cost_of_revenue", {}), e) or (rev - (match(A.get("gross_profit", {}), e) or 0))
        inv, ap = match(A.get("inventory", {}), e) or 0, match(A.get("payables", {}), e) or 0
        if cogs and cogs > 0:
            ccc[e] = ar / rev * 365 + inv / cogs * 365 - ap / cogs * 365
    put_ratio("ccc", ccc)


def resolve(ticker: str, force: bool = False, use_stockanalysis: bool = True,
            use_yahoo: bool = True) -> Fundamentals | None:
    """Merged, provenance-tagged fundamentals for one ticker (cached as a whole)."""
    key = f"fund:merged:v2:{ticker.upper()}"
    cache = get_cache()
    if not force:
        hit = cache.get(key, get_settings().ttl_fundamentals)
        if hit:
            return Fundamentals.from_dict(hit)
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_sec = ex.submit(sec.fundamentals, ticker)
        f_sa = ex.submit(stockanalysis.fundamentals, ticker) if use_stockanalysis else None
        base = f_sec.result()
        sa = f_sa.result() if f_sa else None
    if base is None:
        base = sa or (_yahoo_statements(ticker) if use_yahoo else None)
        if base is None:
            stale = cache.get(key, allow_stale=True)
            return Fundamentals.from_dict(stale) if stale else None
        base.ticker = ticker.upper()
        sa = None if base is sa else sa
    for c in base.annual:
        base.provenance.setdefault(c, base.source)
    # SEC sometimes lags (latest 10-K not yet tagged) — if stockanalysis has a newer FY, prefer it there.
    if sa is not None:
        for c in ("revenue", "net_income", "cfo", "capex", "operating_income", "shares_diluted", "eps_diluted"):
            mine, theirs = base.annual.get(c, []), sa.annual.get(c, [])
            if theirs and (not mine or _d(theirs[-1].end) - _d(mine[-1].end) > 200):
                base.annual[c] = _merge_series(theirs, mine)
                base.provenance[c] = "stockanalysis+sec"
        # interest expense: stockanalysis reports it negative
        if "interest_expense" in sa.annual:
            sa.annual["interest_expense"] = [Point(p.end, abs(p.value), p.fy) for p in sa.annual["interest_expense"]]
        if "interest_expense" in sa.ttm:
            sa.ttm["interest_expense"] = abs(sa.ttm["interest_expense"])
        _fill(base, sa, "stockanalysis")
        # stockanalysis ratio histories are authoritative for the ratio checks
        for k, v in sa.ratios.items():
            base.ratios[k] = v
    missing_core = [c for c in REQUIRED_ANNUAL if len(base.annual.get(c, [])) < 3]
    if missing_core and use_yahoo:
        _fill(base, _yahoo_statements(ticker), "yahoo")
    _derive(base)
    base.meta["completeness"] = completeness(base)
    cache.set(key, base.to_dict())
    return base


def completeness(f: Fundamentals) -> dict:
    missing = []
    for c in REQUIRED_ANNUAL:
        n = len(f.annual.get(c, []))
        if n < 5:
            missing.append(f"{c} ({n}y)")
    for c in REQUIRED_LATEST:
        if f.latest.get(c) is None:
            missing.append(c)
    for c in REQUIRED_RATIOS:
        if not f.ratios.get(c):
            missing.append(f"ratio:{c}")
    opt_missing = [c for c in OPTIONAL if not (f.annual.get(c) or f.latest.get(c) is not None or f.ratios.get(c))]
    return {"ok": not missing, "missing": missing, "optional_missing": opt_missing}
