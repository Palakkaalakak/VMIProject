"""Portfolio breakdown for the pie charts: the portfolio's market value split by sector, country, category or strategy tag.

Pure functions: the caller passes the summary's positions, the cash, a `profiles` dict (symbol -> {sector, country, category})
and the strategy `tags` (symbol -> tag). Cash is its own slice. Option positions are not mapped to their underlying's sector:
they form one "Options" slice valued at the absolute market value of the option legs (short legs count as positive exposure
of the premium), so a covered-call book does not double count the shares.
"""
from __future__ import annotations

from sqlalchemy import select

from vmi import store

BY = ("sector", "country", "category", "strategy")
STRATEGIES = ("Growth", "Dividend", "Predictable", "Deep value", "Speculative", "Turnaround", "Other")
CATEGORY_LABELS = {"speculative_growth": "Speculative growth", "deep_cyclical": "Deep cyclical", "large_growth": "Large growth",
                   "growth": "Growth", "predictable": "Predictable", "dividend": "Dividend", "turnaround": "Turnaround"}
UNKNOWN = "Unknown"
UNTAGGED = "Untagged"


def label_for(by: str, symbol: str, profile: dict, tags: dict) -> str:
    if by == "strategy":
        return tags.get(symbol) or UNTAGGED
    v = (profile or {}).get(by)
    if by == "category":
        return CATEGORY_LABELS.get(v, str(v).replace("_", " ").capitalize()) if v else UNKNOWN
    return str(v).strip() if v and str(v).strip() else UNKNOWN


def breakdown(by: str, positions: list[dict], cash: float, profiles: dict[str, dict], tags: dict[str, str]) -> dict:
    """{by, total, slices: [{label, value, weight, symbols}]} largest first; weights add to 1 (or the list is empty)."""
    if by not in BY:
        raise ValueError(f"by must be one of {', '.join(BY)}")
    acc: dict[str, dict] = {}

    def add(label: str, value: float, symbol: str | None):
        s = acc.setdefault(label, {"label": label, "value": 0.0, "symbols": []})
        s["value"] += value
        if symbol and symbol not in s["symbols"]:
            s["symbols"].append(symbol)

    for p in positions:
        value = float(p.get("market_value") or 0.0)
        if p.get("sec_type") == "OPT":
            add("Options", abs(value), p["symbol"])
        elif value > 0:
            add(label_for(by, p["symbol"], profiles.get(p["symbol"], {}), tags), value, p["symbol"])
    if cash and cash > 0:
        add("Cash", float(cash), None)
    total = sum(s["value"] for s in acc.values())
    slices = sorted(({**s, "value": round(s["value"], 2), "weight": s["value"] / total} for s in acc.values() if s["value"] > 0),
                    key=lambda s: -s["value"])
    return {"by": by, "total": round(total, 2), "slices": slices}


def holdings(positions: list[dict], tags: dict[str, str]) -> list[dict]:
    """One row per stock holding for the tag editor: symbol, market value, strategy tag (None = untagged)."""
    return sorted(({"symbol": p["symbol"], "value": round(float(p.get("market_value") or 0.0), 2), "tag": tags.get(p["symbol"])}
                   for p in positions if p.get("sec_type") == "STK" and (p.get("market_value") or 0) > 0), key=lambda r: -r["value"])


# ------------------------------------------------------------------------------------------ strategy tags (store)
def get_tags(pid: int) -> dict[str, str]:
    with store.session() as s:
        return {t.symbol: t.tag for t in s.scalars(select(store.PositionTag).where(store.PositionTag.portfolio_id == pid))}


def set_tag(pid: int, symbol: str, tag: str | None) -> dict[str, str]:
    """Set (or clear, with an empty tag) the strategy of one holding; returns all tags of the portfolio."""
    sym = symbol.strip().upper()
    if tag and tag not in STRATEGIES:
        raise ValueError(f"tag must be one of {', '.join(STRATEGIES)}")
    with store.session() as s:
        if not s.get(store.Portfolio, pid):
            raise ValueError("portfolio not found")
        row = s.scalar(select(store.PositionTag).where(store.PositionTag.portfolio_id == pid, store.PositionTag.symbol == sym))
        if not tag:
            if row:
                s.delete(row)
        elif row:
            row.tag = tag
        else:
            s.add(store.PositionTag(portfolio_id=pid, symbol=sym, tag=tag))
        s.commit()
    return get_tags(pid)
