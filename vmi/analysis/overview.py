"""Data for the "More detailed overview" tab: statements, trends, company metrics, snapshot, valuation preview,
dividends and earnings. Pure functions over a `Fundamentals` object or plain lists, so they test offline; the
routes in vmi/api/app.py fetch the data (prices, dividends, filings) and pass it in.

    statements(f, period)              income / balance / cash-flow rows, millions, oldest -> newest (+ TTM column)
    trends(f, period, prices)          the five headline series (+ month-end price for the overlay)
    metrics(f)                         margins, ROE, ROIC (series, latest, 5y / 10y average, trend) + efficiency series
    snapshot(f, est, price, hist, ...) the at-a-glance figures
    preview_valuation(...)             intrinsic value with edited inputs; nothing is saved
    dividends(f, divs, prices, ...)    DPS per year, yield history, payout ratios, DPS growth
    earnings(f, history, ...)          past quarters, next date, 8-K Item 2.02 earnings releases

Missing values are None (JSON null), never NaN.
"""
from __future__ import annotations

import math
from datetime import date

from vmi.analysis.moat_evidence import MARGINS, _ratio_by_year
from vmi.analysis.trends import cagr, mean
from vmi.data.models import Fundamentals, Point

MILLION = 1e6
ANNUAL_COLUMNS, QUARTERLY_COLUMNS = 10, 12      # statements table width
TREND_YEARS, TREND_QUARTERS = 10, 40
TREND_DEADBAND = 0.01                           # a margin / return moving < 1 percentage point is "stable"

# (concept, label, unit) per statement; unit: "m" = millions of currency, "ps" = per share, "sh" = millions of shares
STATEMENTS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "income": ("Income statement", [
        ("revenue", "Revenue", "m"), ("cost_of_revenue", "Cost of revenue", "m"), ("gross_profit", "Gross profit", "m"),
        ("rd", "Research & development", "m"), ("sga", "Selling, general & administrative", "m"),
        ("operating_income", "Operating income", "m"), ("interest_expense", "Interest expense", "m"),
        ("pretax_income", "Pre-tax income", "m"), ("income_tax", "Income tax", "m"), ("net_income", "Net income", "m"),
        ("eps_diluted", "Diluted EPS", "ps"), ("shares_diluted", "Diluted shares", "sh")]),
    "balance": ("Balance sheet", [
        ("cash", "Cash & equivalents", "m"), ("st_investments", "Short-term investments", "m"),
        ("receivables", "Receivables", "m"), ("inventory", "Inventory", "m"), ("current_assets", "Current assets", "m"),
        ("goodwill", "Goodwill", "m"), ("intangibles", "Intangibles", "m"), ("total_assets", "Total assets", "m"),
        ("payables", "Payables", "m"), ("deferred_revenue", "Deferred revenue", "m"),
        ("current_liabilities", "Current liabilities", "m"), ("st_debt", "Short-term debt", "m"),
        ("lt_debt", "Long-term debt", "m"), ("total_liabilities", "Total liabilities", "m"),
        ("equity", "Shareholders' equity", "m"), ("retained_earnings", "Retained earnings", "m"),
        ("shares_outstanding", "Shares outstanding", "sh")]),
    "cashflow": ("Cash flow", [
        ("cfo", "Operating cash flow", "m"), ("capex", "Capital expenditure", "m"), ("fcf", "Free cash flow", "m"),
        ("d_and_a", "Depreciation & amortisation", "m"), ("sbc", "Share-based compensation", "m"),
        ("dividends_paid", "Dividends paid", "m"), ("buybacks", "Share buybacks", "m")]),
}


def _num(v) -> float | None:
    """A finite float, else None."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _scale(v, unit: str) -> float | None:
    v = _num(v)
    if v is None:
        return None
    return round(v if unit == "ps" else v / MILLION, 4 if unit == "ps" else 3)


def _label(p: Point, quarterly: bool) -> str:
    return p.end[:7] if quarterly else str(p.fy or p.end[:4])


# ------------------------------------------------------------------------------------------ statements
def statements(f: Fundamentals, period: str = "annual") -> dict:
    """{"columns": [{end, label}], "sections": [{key, title, rows: [{key, label, unit, values}]}]}; every row has one
    value per column (None where missing). Annual adds a final TTM column; flows only (the balance sheet shows the
    latest quarter's instant there when it is newer than the last fiscal year)."""
    quarterly = period == "quarterly"
    src = f.quarterly if quarterly else f.annual
    width = QUARTERLY_COLUMNS if quarterly else ANNUAL_COLUMNS
    ends = sorted({p.end for series in src.values() for p in series})[-width:]
    labels = {}
    for series in src.values():
        for p in series:
            labels.setdefault(p.end, _label(p, quarterly))
    columns = [{"end": e, "label": labels[e]} for e in ends]
    add_ttm = not quarterly and bool(ends)
    if add_ttm:
        columns.append({"end": f.latest_date or None, "label": "TTM"})
    newer_latest = bool(f.latest_date and ends and f.latest_date > ends[-1])
    sections = []
    for key, (title, rows) in STATEMENTS.items():
        out = []
        for concept, label, unit in rows:
            by_end = {p.end: p.value for p in src.get(concept, [])}
            if not by_end:
                continue                                    # banks lack gross profit etc.: leave the row out
            values = [_scale(by_end.get(e), unit) for e in ends]
            if add_ttm:
                tail = f.ttm.get(concept)
                if tail is None and newer_latest and key == "balance":
                    tail = f.latest.get(concept)
                values.append(_scale(tail, unit))
            out.append({"key": concept, "label": label, "unit": unit, "values": values})
        if out:
            sections.append({"key": key, "title": title, "rows": out})
    return {"symbol": f.ticker, "period": "quarterly" if quarterly else "annual", "currency": f.currency,
            "unit": "millions", "columns": columns, "sections": sections}


# ------------------------------------------------------------------------------------------ trends
TREND_SERIES = (("revenue", "Revenue"), ("operating_income", "Operating income"), ("net_income", "Net income"),
                ("cfo", "Operating cash flow"), ("fcf", "Free cash flow"))


def month_end_prices(hist) -> list[dict]:
    """[{date, close}] last close of each month from a daily OHLCV DataFrame (empty list when there is none)."""
    if hist is None or len(hist) == 0:
        return []
    close = hist["close"].dropna().resample("ME").last().dropna()
    return [{"date": i.strftime("%Y-%m-%d"), "close": round(float(v), 4)} for i, v in close.items()]


def trends(f: Fundamentals, period: str = "annual", prices: list[dict] | None = None) -> dict:
    """Headline series in millions, oldest -> newest: {"series": [{key, label, points: [{end, label, value}]}], "price": [...]}."""
    quarterly = period == "quarterly"
    src = f.quarterly if quarterly else f.annual
    n = TREND_QUARTERS if quarterly else TREND_YEARS
    series = []
    for key, label in TREND_SERIES:
        pts = [{"end": p.end, "label": _label(p, quarterly), "value": _scale(p.value, "m")} for p in src.get(key, [])[-n:]]
        if pts:
            series.append({"key": key, "label": label, "points": pts})
    return {"symbol": f.ticker, "period": "quarterly" if quarterly else "annual", "currency": f.currency,
            "unit": "millions", "series": series, "price": prices or []}


# ------------------------------------------------------------------------------------------ company metrics
def trend_word(values: list[float], deadband: float = TREND_DEADBAND) -> str | None:
    """rising / falling / stable: mean of the last 3 values against the mean of up to 3 before them (None under 4 values)."""
    if len(values) < 4:
        return None
    recent, prior = mean(values[-3:]), mean(values[-6:-3])
    diff = recent - prior
    return "rising" if diff > deadband else "falling" if diff < -deadband else "stable"


def _summary(label: str, by_year: dict[int, float]) -> dict:
    years = sorted(by_year)
    vals = [by_year[y] for y in years]
    last5, last10 = vals[-5:], vals[-10:]
    return {"label": label, "series": [{"year": y, "value": _num(by_year[y])} for y in years][-10:],
            "latest": _num(vals[-1]) if vals else None,
            "avg5": _num(mean(last5)) if len(last5) >= 3 else None,
            "avg10": _num(mean(last10)) if len(last10) >= 6 else None,
            "trend": trend_word(vals)}


def _ratio_years(f: Fundamentals, name: str) -> dict[int, float]:
    return {int(p.end[:4]): p.value for p in f.ratios.get(name, []) if _num(p.value) is not None}


def _growth_series(by_year: dict[int, float]) -> dict[int, float]:
    ys = sorted(by_year)
    return {b: by_year[b] / by_year[a] - 1 for a, b in zip(ys, ys[1:]) if by_year[a] and by_year[a] > 0 and by_year[b] > 0}


def metrics(f: Fundamentals) -> dict:
    """Margins, ROE and ROIC with latest / 5y / 10y averages and a trend word, plus the two efficiency series
    (revenue vs receivables growth, cash conversion cycle) that Step 4 judges."""
    out = {}
    for label, concept in MARGINS:
        by_year = _ratio_by_year(f, concept)
        if by_year:
            out[concept] = _summary(label, by_year)
    for key, label in (("roe", "Return on equity"), ("roic", "Return on invested capital")):
        by_year = _ratio_years(f, key)
        if by_year:
            out[key] = _summary(label, by_year)
    rev = {int(p.end[:4]): p.value for p in f.annual.get("revenue", [])}
    rec = {int(p.end[:4]): p.value for p in f.annual.get("receivables", [])}
    rg, ag = _growth_series(rev), _growth_series(rec)
    years = [y for y in sorted(rg) if y in ag][-10:]
    recv = {"series": [{"year": y, "revenue_growth": _num(rg[y]), "receivables_growth": _num(ag[y])} for y in years],
            "revenue_cagr_3y": None, "receivables_cagr_3y": None, "revenue_ahead": None}
    ys = sorted(set(rev) & set(rec))
    if len(ys) >= 4 and rev[ys[-4]] > 0 and rec[ys[-4]] > 0:          # same 3-year window as Step 4
        a, b = cagr(rev[ys[-4]], rev[ys[-1]], 3), cagr(rec[ys[-4]], rec[ys[-1]], 3)
        recv.update(revenue_cagr_3y=_num(a), receivables_cagr_3y=_num(b),
                    revenue_ahead=None if a is None or b is None else a >= b - 0.02)
    ccc = _ratio_years(f, "ccc")
    return {"symbol": f.ticker, "currency": f.currency, "metrics": out, "revenue_vs_receivables": recv,
            "cash_conversion_cycle": {"series": [{"year": y, "days": _num(ccc[y])} for y in sorted(ccc)][-10:],
                                      "trend": trend_word([ccc[y] for y in sorted(ccc)], deadband=3.0)}}


# ------------------------------------------------------------------------------------------ snapshot
def snapshot(f: Fundamentals, est, price: float | None, hist, next_earnings: str | None = None) -> dict:
    """At-a-glance figures; anything unknown is None (the page shows "—")."""
    yahoo = (est.extra or {}).get("yahoo") or {}
    shares = f.ttm.get("shares_diluted") or f.last("shares_diluted") or yahoo.get("shares_outstanding")
    revenue = f.ttm.get("revenue") or f.last("revenue")
    eps = f.ttm.get("eps_diluted") or f.last("eps_diluted")
    cap = yahoo.get("market_cap") or (price * shares if price and shares else None)
    lo = hi = None
    if hist is not None and len(hist):
        window = hist["close"].dropna().iloc[-252:]
        if len(window):
            lo, hi = float(window.min()), float(window.max())
    return {"symbol": f.ticker, "name": f.name, "currency": f.currency, "price": _num(price), "market_cap": _num(cap),
            "shares_diluted": _num(shares), "pe": _num(est.pe), "forward_pe": _num(est.forward_pe), "peg": _num(est.peg),
            "beta": _num(est.beta), "revenue_per_share": _num(revenue / shares) if revenue and shares else None,
            "eps": _num(eps), "dividend_yield": _num(est.dividend_yield), "low_52w": _num(lo), "high_52w": _num(hi),
            "next_earnings": next_earnings or est.earnings_date or None, "sector": est.sector or f.sector,
            "industry": est.industry or f.industry}


# ------------------------------------------------------------------------------------------ valuation preview
EDITABLE = ("growth", "growth_6_10", "growth_11_20", "discount_rate", "base_cf", "shares", "cash", "debt", "method")


def preview_valuation(f: Fundamentals, est, price: float, hist, saved: dict, edits: dict, rules=None) -> dict:
    """Intrinsic value with `edits` layered over the saved overrides, through the same code as the analysis page.
    With no edits the result equals the analysis. Nothing is saved. Edit keys are the override keys in EDITABLE."""
    from vmi.analysis.pipeline import build_context, classify_business
    from vmi.analysis.valuation.selector import value_company
    from vmi.rules import RULES

    rules = rules or RULES
    changes = {k: v for k, v in edits.items() if k in EDITABLE and v not in (None, "")}
    ov = {**saved, **changes}
    ctx = build_context(f, est, price, hist, ov, rules)
    val = value_company(ctx, classify_business(f, est, ov), ov.get("method"))
    iv = ov.get("iv_override") or val.intrinsic_value
    cons = ov.get("conservative_override") or val.conservative_value
    sel = val.methods.get(val.selected)
    return {"symbol": f.ticker, "price": _num(price), "changed": sorted(changes), "selected": val.selected,
            "selection_reason": val.selection_reason, "intrinsic_value": _num(iv), "conservative_value": _num(cons),
            "margin_of_safety": _num((iv - price) / iv) if iv and price else None, "biz_type": val.biz_type,
            "inputs": dict(sel.inputs) if sel else {},
            "methods": {k: {"label": r.label, "applicable": r.applicable, "intrinsic_value": _num(r.intrinsic_value),
                            "conservative": _num(r.conservative)} for k, r in val.methods.items()},
            "notes": val.notes}


# ------------------------------------------------------------------------------------------ dividends
def _by_year(divs: list[dict]) -> dict[int, float]:
    out: dict[int, float] = {}
    for d in divs:
        out[int(d["date"][:4])] = out.get(int(d["date"][:4]), 0.0) + d["amount"]
    return out


def dps_growth(per_year: dict[int, float], today: date | None = None) -> dict:
    """3 / 5 / 10-year DPS CAGR over COMPLETE years (the current, part-paid year is left out)."""
    year = (today or date.today()).year
    full = {y: v for y, v in per_year.items() if y < year}
    last = max(full) if full else None
    out = {}
    for n in (3, 5, 10):
        a, b = full.get(last - n) if last else None, full.get(last) if last else None
        out[f"cagr_{n}y"] = _num(cagr(a, b, n)) if a and b and a > 0 and b > 0 else None
    return out


def yield_history(divs: list[dict], prices: list[dict]) -> list[dict]:
    """[{date, yield}] per month end: dividends paid in the 12 months to that date / the month-end price."""
    out = []
    for p in prices:
        end = p["date"]
        start = f"{int(end[:4]) - 1}{end[4:]}"
        ttm = sum(d["amount"] for d in divs if start < d["date"] <= end)
        if p["close"]:
            out.append({"date": end, "yield": _num(ttm / p["close"])})
    first = divs[0]["date"] if divs else None
    return [r for r in out if first and r["date"] >= f"{int(first[:4]) + 1}{first[4:]}"]    # needs a full year of history


def dividends(f: Fundamentals, divs: list[dict], prices: list[dict], est=None, calendar: dict | None = None,
              today: date | None = None) -> dict:
    """Dividend picture: history, DPS per year, yield history, payout vs EPS and vs FCF per share, DPS growth."""
    today = today or date.today()
    per_year = _by_year(divs)
    eps = {int(p.end[:4]): p.value for p in f.annual.get("eps_diluted", [])}
    fcf = {int(p.end[:4]): p.value for p in f.annual.get("fcf", [])}
    shares = {int(p.end[:4]): p.value for p in f.annual.get("shares_diluted", [])}
    years = []
    for y in sorted(per_year)[-12:]:
        fps = fcf[y] / shares[y] if y in fcf and shares.get(y) else None
        years.append({"year": y, "dps": round(per_year[y], 4), "partial": y == today.year,
                      "eps": _num(eps.get(y)), "fcf_per_share": _num(fps),
                      "payout_eps": _num(per_year[y] / eps[y]) if eps.get(y) and eps[y] > 0 else None,
                      "payout_fcf": _num(per_year[y] / fps) if fps and fps > 0 else None})
    cal = calendar or {}
    ttm_dps = sum(d["amount"] for d in divs if d["date"] > f"{today.year - 1}{today.isoformat()[4:]}")
    return {"symbol": f.ticker, "pays_dividend": bool(divs), "ttm_dps": _num(ttm_dps) if divs else None,
            "current_yield": _num(est.dividend_yield) if est else None, "years": years,
            "growth": dps_growth(per_year, today), "yield_history": yield_history(divs, prices),
            "history": divs[-60:], "next_ex_date": cal.get("ex_dividend_date"), "next_pay_date": cal.get("dividend_date")}


# ------------------------------------------------------------------------------------------ earnings
def earnings_releases(filings: list[dict], cik: int | None, limit: int = 8) -> list[dict]:
    """The latest `limit` 8-K filings that carry Item 2.02 (results of operations = the earnings press release), newest
    first, each with the filing's document and index links. `filings` rows are {form, accession, document, filed, items}."""
    rows = [r for r in filings if "2.02" in [i.strip() for i in str(r.get("items", "")).split(",")]]
    rows.sort(key=lambda r: r["filed"], reverse=True)
    out = []
    for r in rows[:limit]:
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{r['accession'].replace('-', '')}" if cik else None
        out.append({"filed": r["filed"], "form": r["form"], "items": r.get("items", ""),
                    "url": f"{base}/{r['document']}" if base and r.get("document") else None,
                    "index_url": f"{base}/{r['accession']}-index.htm" if base else None})
    return out


def earnings(f: Fundamentals, dates: list[dict], filings: list[dict], calendar: dict | None = None,
             today: date | None = None, limit: int = 8) -> dict:
    """Next date, past quarters (EPS actual vs estimate vs surprise when Yahoo has them; revenue / net income from the
    statements) and the latest earnings press releases. Call transcripts are paid data and not included."""
    today_s = (today or date.today()).isoformat()
    future = sorted(d["date"] for d in dates if d["date"] >= today_s and d.get("eps_actual") is None)
    next_date = (calendar or {}).get("earnings_date") or (future[0] if future else None)
    past = [d for d in dates if d.get("eps_actual") is not None or d["date"] < today_s]
    quarters = []
    for p in f.quarterly.get("revenue", [])[-8:]:
        ni = next((q.value for q in f.quarterly.get("net_income", []) if q.end == p.end), None)
        eps = next((q.value for q in f.quarterly.get("eps_diluted", []) if q.end == p.end), None)
        quarters.append({"end": p.end, "revenue": _scale(p.value, "m"), "net_income": _scale(ni, "m"), "eps": _num(eps)})
    return {"symbol": f.ticker, "next_date": next_date, "history": past[:limit], "quarters": quarters,
            "releases": earnings_releases(filings, f.cik, limit),
            "transcripts_note": "Earnings-call transcripts are paid data and are not included; the press releases above "
                                "are the company's own filings on SEC EDGAR."}
