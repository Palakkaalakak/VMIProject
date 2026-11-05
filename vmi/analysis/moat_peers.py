"""Peer comparison for the moat review: "is it the top dog?" (Adam: invest in the clear leader of its industry).

Peers = the S&P 500 companies in the same sub-industry, or the tickers a reviewer lists in the `peers` override.
Numbers come from SEC frames (one call per concept and year covers every filer, cached), so it is cheap.
Evidence only: the ranking is a hint, the verdict stays with the reviewer.
"""
from __future__ import annotations

from datetime import date

from vmi.data import sec, universe

CONCEPTS = ("revenue", "gross_profit", "cost_of_revenue", "operating_income", "net_income")


def latest_calendar_year(today: date | None = None) -> int:
    """Most recent calendar year whose annual filings are in (frames lag the year end by about two months)."""
    today = today or date.today()
    return today.year - (1 if today.month >= 3 else 2)


def peer_group(symbol: str, listed: list[str] | None = None) -> tuple[list[dict], str]:
    """([{symbol, name, cik}], how the group was chosen). The target is always included."""
    rows = universe.sp500()
    by_symbol = {r["symbol"].upper(): r for r in rows}
    sym = symbol.upper()
    if listed:
        chosen = [sym] + [s for s in listed if s != sym]
        return [_member(by_symbol.get(s), s) for s in chosen], "peers listed by the reviewer"
    me = by_symbol.get(sym)
    if me is None or not me.get("sub_industry"):
        return [], "not an S&P 500 company: list peers in the Judgement overrides (Moat review → Peer tickers)"
    group = [r for r in rows if r.get("sub_industry") == me["sub_industry"]]
    return [_member(r, r["symbol"].upper()) for r in group], f"S&P 500 sub-industry: {me['sub_industry']}"


def _member(row: dict | None, symbol: str) -> dict:
    cik = (row or {}).get("cik")
    if not cik:
        cik = (sec.ticker_map().get(symbol) or {}).get("cik")
    return {"symbol": symbol, "name": (row or {}).get("name", ""), "cik": int(cik) if cik else None}


def compare(symbol: str, listed: list[str] | None = None, year: int | None = None) -> dict:
    """Side-by-side table of the group: size, share of group revenue, margins, 3-year sales growth, plus ranks."""
    members, how = peer_group(symbol, listed)
    year = year or latest_calendar_year()
    out = {"basis": how, "year": year, "rows": [], "summary": {}}
    if not members:
        return out
    now = {c: sec.frame_concept(c, f"CY{year}") for c in CONCEPTS}
    before = sec.frame_concept("revenue", f"CY{year - 3}")
    rows = []
    for m in members:
        cik = m["cik"]
        rev = now["revenue"].get(cik)
        if not cik or not rev:
            continue
        pct = lambda concept: (now[concept][cik] / rev) if cik in now[concept] else None  # noqa: E731
        gross = pct("gross_profit")
        if gross is None and cik in now["cost_of_revenue"]:  # many filers tag cost of revenue, not gross profit
            gross = 1 - now["cost_of_revenue"][cik] / rev
        old = before.get(cik)
        rows.append({"symbol": m["symbol"], "name": m["name"], "revenue": rev, "gross_margin": gross,
                     "operating_margin": pct("operating_income"), "net_margin": pct("net_income"),
                     "growth_3y": (rev / old) ** (1 / 3) - 1 if old and old > 0 else None})
    total = sum(r["revenue"] for r in rows)
    for r in rows:
        r["share"] = r["revenue"] / total if total else None
    rows.sort(key=lambda r: -r["revenue"])
    out["rows"] = rows
    out["summary"] = _summary(rows, symbol.upper())
    return out


def _summary(rows: list[dict], symbol: str) -> dict:
    me = next((r for r in rows if r["symbol"] == symbol), None)
    if me is None or len(rows) < 2:
        return {}
    rank = lambda key: 1 + sum(1 for r in rows if r.get(key) is not None and me.get(key) is not None  # noqa: E731
                               and r[key] > me[key])
    ranks = {k: rank(k) for k in ("revenue", "operating_margin", "growth_3y")}
    return {"peers": len(rows) - 1, "ranks": ranks, "share": me["share"],
            "top_dog_hint": ranks["revenue"] == 1 and ranks["operating_margin"] <= max(1, len(rows) // 2)}
