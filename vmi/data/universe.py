"""Universes: S&P 500 (Wikipedia constituents table) and the full US market (NASDAQ screener API,
cross-referenced with the SEC ticker map). Both cached daily; both fall back to stale cache."""
from __future__ import annotations

import io

from vmi.config import get_settings
from vmi.data import http
from vmi.data.cache import get_cache


WIKI_UA = "VMI-Toolkit/0.1 (research; vmi-toolkit@example.com)"


def _sp500_wikipedia() -> list[dict]:
    import pandas as pd

    html = http.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", expect_json=False,
                    headers={"User-Agent": WIKI_UA})
    t = pd.read_html(io.StringIO(html))[0]
    return [{"symbol": str(r["Symbol"]).replace(".", "-").strip(), "name": r["Security"],
             "sector": r["GICS Sector"], "sub_industry": r["GICS Sub-Industry"],
             "cik": int(r["CIK"]) if str(r["CIK"]).isdigit() else None} for _, r in t.iterrows()]


def _sp500_github() -> list[dict]:
    import csv

    text = http.get("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
                    expect_json=False)
    return [{"symbol": r["Symbol"].replace(".", "-").strip(), "name": r["Security"], "sector": r["GICS Sector"],
             "sub_industry": r["GICS Sub-Industry"], "cik": int(r["CIK"]) if r.get("CIK", "").isdigit() else None}
            for r in csv.DictReader(io.StringIO(text))]


def _sp500_stockanalysis() -> list[dict]:
    from vmi.data.jsobj import find_objects

    html = http.get("https://stockanalysis.com/list/sp-500-stocks/", expect_json=False)
    rows = [o for o in find_objects(html, "{no:") if isinstance(o, dict) and o.get("s")]
    return [{"symbol": o["s"].replace(".", "-"), "name": o.get("n", ""), "sector": "", "sub_industry": "",
             "cik": None} for o in rows]


SP500_SOURCES = (_sp500_wikipedia, _sp500_github, _sp500_stockanalysis)


def sp500() -> list[dict]:
    """[{symbol, name, sector, sub_industry, cik}] — symbols in Yahoo/SEC dash form (BRK-B).
    Tries Wikipedia → GitHub datasets mirror → stockanalysis list; first source with ≥490 rows wins."""
    def fetch():
        last_exc = None
        for src in SP500_SOURCES:
            try:
                rows = src()
                if len(rows) >= 490:
                    return rows
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"all S&P 500 sources failed: {last_exc}")

    return get_cache().get_or_set("universe:sp500", get_settings().ttl_universe, fetch)


def us_market(min_market_cap: float = 0.0) -> list[dict]:
    """Every NASDAQ/NYSE/AMEX common stock: [{symbol, name, price, market_cap, volume, sector, industry, country}]."""
    def fetch():
        raw = http.get("https://api.nasdaq.com/api/screener/stocks",
                       params={"tableonly": "true", "limit": "25", "offset": "0", "download": "true"},
                       headers={"User-Agent": http.BROWSER_UA, "Accept": "application/json"})
        out = []
        for r in raw["data"]["rows"]:
            sym = (r.get("symbol") or "").strip().upper()
            if not sym or "^" in sym or "/" in sym:
                continue
            try:
                price = float((r.get("lastsale") or "0").replace("$", "").replace(",", "") or 0)
                mcap = float(r.get("marketCap") or 0)
                vol = float(r.get("volume") or 0)
            except ValueError:
                price, mcap, vol = 0.0, 0.0, 0.0
            out.append({"symbol": sym.replace(".", "-"), "name": r.get("name", ""), "price": price,
                        "market_cap": mcap, "volume": vol, "sector": r.get("sector", ""),
                        "industry": r.get("industry", ""), "country": r.get("country", "")})
        return out

    rows = get_cache().get_or_set("universe:us", get_settings().ttl_universe, fetch)
    return [r for r in rows if r["market_cap"] >= min_market_cap]


_EXCLUDE_NAME = (" warrant", " right", " unit", "preferred", " depositary", " notes due", "% ", " fund",
                 " etf", " trust units", "acquisition corp")


def is_common_stock(row: dict) -> bool:
    n = (row.get("name") or "").lower()
    return not any(k in n for k in _EXCLUDE_NAME)
