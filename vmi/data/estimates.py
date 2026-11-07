"""Consensus growth estimates — the free substitute for FactSet.

Adam's procedure (Lesson 5 §4.6): average the projected 3–5y EPS growth from three sources
(StockOracle/FactSet, FinViz, Zacks). StockOracle is paid, so we blend the free equivalents:

  * FinViz  "EPS next 5Y"           (also PEG, P/E, ROE, ROIC, beta, current ratio, …)
  * Zacks   "Exp EPS Growth (3-5yr)" (Zacks consensus)
  * Yahoo   LTG / +1y growth estimate (yfinance growth_estimates / earnings_estimate)

Each source is independently cached and fault-tolerant: if one fails, the blend uses the rest.
"""
from __future__ import annotations

import re
from typing import Callable

from bs4 import BeautifulSoup

from vmi.config import get_settings
from vmi.data import http
from vmi.data.cache import get_cache
from vmi.data.models import Estimates


def _pct(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s in ("", "-", "N/A", "NA"):
        return None
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100
        return float(s)
    except ValueError:
        return None


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    mult = 1.0
    if s and s[-1] in "KMBT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------- FinViz
def finviz_snapshot(ticker: str) -> dict:
    def fetch():
        html = http.get(f"https://finviz.com/quote.ashx?t={ticker.upper()}&p=d", expect_json=False)
        soup = BeautifulSoup(html, "lxml")
        cells = [c.get_text(strip=True) for c in soup.select("table.snapshot-table2 td")]
        raw = dict(zip(cells[::2], cells[1::2]))
        # sector / industry links in the quote header
        links = [a.get_text(strip=True) for a in soup.select("div.quote-links a.tab-link")]
        return {"raw": raw, "links": links[:4]}

    try:
        return get_cache().get_or_set(f"fv:{ticker.upper()}", get_settings().ttl_estimates, fetch)
    except Exception:
        return {}


def from_finviz(ticker: str) -> dict:
    snap = finviz_snapshot(ticker)
    r = snap.get("raw", {})
    if not r:
        return {}
    links = snap.get("links", [])
    return {
        "eps_growth_5y": _pct(r.get("EPS next 5Y")),
        "eps_growth_next_year": _pct(r.get("EPS next Y")) if "%" in (r.get("EPS next Y") or "") else None,
        "eps_past_5y": _pct(r.get("EPS past 5Y")),
        "sales_past_5y": _pct(r.get("Sales past 5Y")),
        "pe": _num(r.get("P/E")),
        "forward_pe": _num(r.get("Forward P/E")),
        "peg": _num(r.get("PEG")),
        "pb": _num(r.get("P/B")),
        "ps": _num(r.get("P/S")),
        "roe": _pct(r.get("ROE")),
        "roic": _pct(r.get("ROIC")) or _pct(r.get("ROI")),
        "beta": _num(r.get("Beta")),
        "current_ratio": _num(r.get("Current Ratio")),
        "debt_eq": _num(r.get("Debt/Eq")),
        "dividend_yield": _pct((r.get("Dividend TTM") or r.get("Dividend %") or "").split("(")[-1].rstrip(")")),
        "payout": _pct(r.get("Payout")),
        "earnings": r.get("Earnings", ""),
        "sector": links[0] if links else "",
        "industry": links[1] if len(links) > 1 else "",
    }


# -------------------------------------------------------------------------------------------- Zacks
_ZACKS_RE = re.compile(r"Exp EPS Growth.*?<dd>.*?([-\d.]+%|NA)", re.S)
_ZACKS_NEXT_RE = re.compile(r"Next Year EPS Growth</dt>\s*<dd>([-\d.]+%|NA)", re.S)


def from_zacks(ticker: str) -> dict:
    def fetch():
        html = http.get(f"https://www.zacks.com/stock/quote/{ticker.upper()}", expect_json=False)
        m = _ZACKS_RE.search(html)
        n = _ZACKS_NEXT_RE.search(html)
        if m is None and n is None:  # blocked / changed page: raise so get_or_set does not cache an empty result
            raise ValueError("Zacks page has no EPS growth fields")
        return {"eps_growth_5y": _pct(m.group(1)) if m else None,
                "eps_growth_next_year": _pct(n.group(1)) if n else None}

    try:
        return get_cache().get_or_set(f"zacks:{ticker.upper()}", get_settings().ttl_estimates, fetch)
    except Exception:
        return {}


# -------------------------------------------------------------------------------------------- Yahoo
def from_yahoo(ticker: str) -> dict:
    def fetch():
        import yfinance as yf

        t = yf.Ticker(ticker.upper())
        out: dict = {}
        try:
            ge = t.growth_estimates
            if ge is not None and not ge.empty:
                col = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
                for label, key in (("LTG", "eps_growth_5y"), ("+5y", "eps_growth_5y"),
                                   ("+1y", "eps_growth_next_year"), ("0y", "eps_growth_this_year")):
                    if label in ge.index:
                        v = ge.loc[label, col]
                        if v == v and v is not None:
                            out.setdefault(key, float(v))
        except Exception:
            pass
        try:
            re_ = t.revenue_estimate
            if re_ is not None and not re_.empty and "growth" in re_.columns:
                for label, key in (("+1y", "revenue_growth_next_year"), ("0y", "revenue_growth_this_year")):
                    if label in re_.index:
                        v = re_.loc[label, "growth"]
                        if v == v:
                            out[key] = float(v)
        except Exception:
            pass
        try:
            info = t.info or {}
        except Exception:
            info = {}
        dy = info.get("dividendYield")
        if dy is not None and dy > 0.5:  # yfinance ≥0.2.5x returns percent units for this field
            dy = dy / 100
        out.update({
            "beta": info.get("beta"),
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg": info.get("trailingPegRatio") or info.get("pegRatio"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "bvps": info.get("bookValue"),
            "dividend_yield": dy,
            "dps": info.get("dividendRate") or info.get("trailingAnnualDividendRate"),
            "payout": info.get("payoutRatio"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "avg_volume": info.get("averageVolume"),
            "market_cap": info.get("marketCap"),
            "name": info.get("longName") or info.get("shortName", ""),
            "currency": info.get("currency", "USD"),
            "financial_currency": info.get("financialCurrency", ""),
            "roe": info.get("returnOnEquity"),
            "current_ratio": info.get("currentRatio"),
            "total_debt": info.get("totalDebt"),
            "ebitda": info.get("ebitda"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "quote_type": info.get("quoteType", ""),
        })
        return out

    try:
        return get_cache().get_or_set(f"yf:est:{ticker.upper()}", get_settings().ttl_estimates, fetch)
    except Exception:
        return {}


def from_ib(ticker: str) -> dict:
    from vmi.data import ib_fundamentals

    try:
        return ib_fundamentals.estimates(ticker)
    except Exception:
        return {}


def from_stockanalysis(ticker: str) -> dict:
    """Next-year EPS / revenue growth implied by stockanalysis' analyst forecast arrays."""
    from vmi.data import stockanalysis

    out: dict = {}
    try:
        fc = stockanalysis.forecast(ticker)
        f = stockanalysis.fundamentals(ticker)
    except Exception:
        return out
    eps, rev = fc.get("eps") or [], fc.get("revenue") or []
    n_eps = len(f.annual.get("eps_diluted", [])) if f else 0
    n_rev = len(f.annual.get("revenue", [])) if f else 0
    if n_eps and len(eps) > n_eps and eps[n_eps - 1] and eps[n_eps - 1] > 0 and eps[n_eps] > 0:
        out["eps_growth_next_year"] = eps[n_eps] / eps[n_eps - 1] - 1
    if n_rev and len(rev) > n_rev and rev[n_rev - 1]:
        out["revenue_growth_next_year"] = rev[n_rev] / rev[n_rev - 1] - 1
    return out


SOURCES: dict[str, Callable[[str], dict]] = {"ib": from_ib, "finviz": from_finviz, "zacks": from_zacks,
                                             "yahoo": from_yahoo, "stockanalysis": from_stockanalysis}


def _blend(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _first(*vals):
    for v in vals:
        if v not in (None, "", 0):
            return v
    return None


def get_estimates(ticker: str,
                  sources: tuple[str, ...] = ("ib", "finviz", "zacks", "yahoo", "stockanalysis")) -> Estimates:
    data = {name: (SOURCES[name](ticker) or {}) for name in sources if name in SOURCES}
    fv, zk, yh = data.get("finviz", {}), data.get("zacks", {}), data.get("yahoo", {})
    ibd, sad = data.get("ib", {}), data.get("stockanalysis", {})
    est = Estimates(ticker=ticker.upper())
    est.sources = {n: {"eps_growth_5y": d.get("eps_growth_5y"),
                       "eps_growth_next_year": d.get("eps_growth_next_year")} for n, d in data.items()}
    est.eps_growth_5y = _blend([d.get("eps_growth_5y") for d in data.values()])
    est.eps_growth_next_year = _blend([d.get("eps_growth_next_year") for d in data.values()])
    lows = [d.get("eps_growth_5y") for d in data.values() if d.get("eps_growth_5y") is not None]
    est.long_term_growth = min(lows) if lows else None  # conservative case = lowest of the sources
    est.revenue_growth_next_year = _first(yh.get("revenue_growth_next_year"), sad.get("revenue_growth_next_year"))
    est.beta = _first(ibd.get("beta"), yh.get("beta"), fv.get("beta"))
    est.pe = _first(fv.get("pe"), yh.get("pe"))
    est.forward_pe = _first(fv.get("forward_pe"), yh.get("forward_pe"))
    est.peg = _first(fv.get("peg"), yh.get("peg"))
    est.dividend_yield = _first(yh.get("dividend_yield"), fv.get("dividend_yield"))
    est.dividend_per_share = yh.get("dps")
    est.payout_ratio = _first(yh.get("payout"), fv.get("payout"))
    est.price_to_book = _first(yh.get("pb"), fv.get("pb"))
    est.price_to_sales = _first(yh.get("ps"), fv.get("ps"))
    est.book_value_per_share = yh.get("bvps")
    est.sector = _first(yh.get("sector"), fv.get("sector")) or ""
    est.industry = _first(yh.get("industry"), fv.get("industry")) or ""
    est.earnings_date = fv.get("earnings", "")
    est.extra = {"finviz": fv, "yahoo": {k: v for k, v in yh.items()}, "zacks": zk}
    return est
