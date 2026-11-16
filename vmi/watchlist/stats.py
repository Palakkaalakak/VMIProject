"""Watchlist stats: what a whole list looks like on average (equal weight). Each stock is analysed like in the scanner
(`funnel.compact` rows, so the numbers match the scanner columns); analysis failures are listed, never hidden.

Growth is summarised three ways from each stock's analyst estimates: the average of the LOWEST estimates, of the AVERAGES and of
the HIGHEST ones (plus the displayed growth = lowest source). Stocks with a single source have low = avg = high.
"""
from __future__ import annotations

import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from vmi import store
from vmi.scanner import funnel

NUMERIC = [("growth_low", "Growth: lowest estimate"), ("growth_avg", "Growth: average estimate"),
           ("growth_high", "Growth: highest estimate"), ("growth", "Growth shown (lowest source)"),
           ("roe", "ROE"), ("roic", "ROIC"), ("net_margin", "Net margin"), ("margin_of_safety", "Margin of safety"),
           ("pe", "P/E"), ("peg", "PEG"), ("beta", "Beta"), ("dividend_yield", "Dividend yield"),
           ("market_cap", "Market cap"), ("steps_passed", "Steps passed (of 7)")]


def _summary(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {"n": len(vals), "mean": sum(vals) / len(vals), "median": statistics.median(vals), "min": min(vals),
            "max": max(vals)}


def _row(symbol: str) -> dict:
    from vmi.analysis.pipeline import analyse_ticker
    try:
        rep = analyse_ticker(symbol, with_technicals=False)
        return funnel.compact(rep)
    except Exception as exc:
        return {"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"[:200]}


def first_failed_step(row: dict) -> int | None:
    for k in range(1, 6):
        if not (row.get("steps") or {}).get(k, (row.get("steps") or {}).get(str(k))):
            return k
    return None


def compute(rows: list[dict], threshold: float = 0.15) -> dict[str, Any]:
    ok = [r for r in rows if not r.get("error")]
    nums = {k: {"label": lab, **_summary([r[k] for r in ok if r.get(k) is not None])} for k, lab in NUMERIC}
    count = lambda key: dict(Counter((r.get(key) or "unknown") for r in ok).most_common())
    step_pass = {str(k): sum(1 for r in ok if (r.get("steps") or {}).get(k, (r.get("steps") or {}).get(str(k)))) for k in range(1, 8)}
    fails = [{"symbol": r["symbol"], "name": r.get("name", ""), "first_failed_step": first_failed_step(r),
              "steps_passed": r.get("steps_passed")} for r in ok if not r.get("great_business")]
    caps = sorted(((r.get("market_cap") or 0) for r in ok), reverse=True)
    sector_n = Counter(r.get("sector") or "unknown" for r in ok)
    top_sector = sector_n.most_common(1)[0] if sector_n else None
    low, high = nums["growth_low"]["mean"], nums["growth_high"]["mean"]
    return {
        "n_stocks": len(rows), "n_analysed": len(ok), "errors": [{"symbol": r["symbol"], "error": r["error"]} for r in rows if r.get("error")],
        "numbers": nums,
        "growth_spread": {"avg_of_lowest": low, "avg_of_average": nums["growth_avg"]["mean"], "avg_of_highest": high,
                          "n_growth_by_lowest": sum(1 for r in ok if (r.get("growth_low") if r.get("growth_low") is not None else r.get("growth")) is not None
                                                    and (r.get("growth_low") if r.get("growth_low") is not None else r.get("growth")) >= threshold),
                          "n_growth_by_average": sum(1 for r in ok if (r.get("growth_avg") or 0) >= threshold),
                          "n_growth_by_highest": sum(1 for r in ok if (r.get("growth_high") or 0) >= threshold), "threshold": threshold},
        "flags": {"great_business": sum(1 for r in ok if r.get("great_business")), "below_iv": sum(1 for r in ok if r.get("undervalued")),
                  "entry_ok": sum(1 for r in ok if r.get("entry_ok")), "vmi_pass": sum(1 for r in ok if r.get("vmi_pass")),
                  "iv_low_confidence": sum(1 for r in ok if r.get("iv_low_confidence")),
                  "moat_reviewed": sum(1 for r in ok if r.get("moat_reviewed"))},
        "step_pass_counts": step_pass,
        "fails_great_business": fails,
        "mix": {"sector": count("sector"), "industry": count("industry"), "category": count("category"), "style": count("style"),
                "moat": count("moat"), "method": count("method"), "trend": count("trend")},
        "concentration": {"top_sector": top_sector[0] if top_sector else None, "top_sector_share": (top_sector[1] / len(ok)) if top_sector and ok else None,
                          "largest_cap": caps[0] if caps else None, "smallest_cap": caps[-1] if caps else None},
        "rows": ok,
    }


def watchlist_stats(wid: int, threshold: float = 0.15, workers: int = 4) -> dict:
    with store.session() as s:
        w = s.get(store.Watchlist, wid)
        if not w:
            raise ValueError("watchlist not found")
        symbols = sorted({i.symbol for i in w.items})
        name = w.name
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(_row, symbols))
    return {"watchlist": name, "id": wid, **compute(rows, threshold)}
