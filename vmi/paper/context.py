"""What we knew when a trade was made, stored on the trade (Trade.context) for later review and what-if studies.

Best effort by design: a failed lookup is recorded as an error string and never blocks the order. The analysis part
is the VMI report trimmed to what decisions depend on (valuation methods and inputs, every step's checks, category,
moat, technicals and buy levels, IV-confidence flag, growth sources), so later questions we cannot foresee today can
still be answered from the stored data.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from vmi.config import get_settings

SCHEMA = 1


def _steps(rep: dict) -> list[dict]:
    out = []
    for s in rep.get("steps") or []:
        out.append({"step": s.get("step"), "name": s.get("name"), "passed": s.get("passed"),
                    "checks": [{k: c.get(k) for k in ("name", "value", "threshold", "passed", "note")}
                               for c in s.get("checks") or []],
                    "notes": s.get("notes") or []})
    return out


def _valuation(v: dict) -> dict:
    methods = {}
    for k, m in (v.get("methods") or {}).items():
        methods[k] = {"iv": m.get("intrinsic_value"), "applicable": m.get("applicable"),
                      "conservative": m.get("conservative"),
                      "scenarios": [{"name": s.get("name"), "value": s.get("value"), "growth": s.get("growth")}
                                    for s in m.get("scenarios") or []]}
    sel = (v.get("methods") or {}).get(v.get("selected")) or {}
    return {"selected": v.get("selected"), "selection_reason": v.get("selection_reason"),
            "intrinsic_value": v.get("intrinsic_value"), "conservative_value": v.get("conservative_value"),
            "margin_of_safety": v.get("margin_of_safety"), "methods": methods, "inputs": sel.get("inputs") or {},
            "notes": v.get("notes") or []}


def analysis_context(symbol: str, report: dict | None = None) -> dict:
    """Trimmed VMI report for `symbol` (computes one when not given)."""
    t0 = time.time()
    try:
        if report is None:
            from vmi.analysis.pipeline import analyse_ticker
            report = analyse_ticker(symbol, with_technicals=True)
        tech = report.get("technicals") or {}
        return {
            "price": report.get("price"), "intrinsic_value": report.get("intrinsic_value"),
            "valuation": _valuation(report.get("valuation") or {}), "metrics": report.get("metrics") or {},
            "steps": _steps(report), "category": report.get("category"), "style": report.get("style"),
            "biz_type": report.get("biz_type"), "moat": report.get("moat"), "moat_reviewed": report.get("moat_reviewed"),
            "great_business": report.get("great_business"), "vmi_pass": report.get("vmi_pass"),
            "allocation_multiplier": report.get("allocation_multiplier"), "iv_confidence": report.get("iv_confidence"),
            "technicals": {"daily": tech.get("daily"), "weekly": tech.get("weekly"), "monthly": tech.get("monthly"),
                           "buy_levels": tech.get("buy_levels"), "entry_ok": tech.get("entry_ok"),
                           "entry_reason": tech.get("entry_reason")},
            "growth_sources": (report.get("estimates") or {}).get("sources"),
            "overrides": report.get("overrides_applied"), "sector": report.get("sector"),
            "industry": report.get("industry"), "secs": round(time.time() - t0, 2),
        }
    except Exception as exc:  # never block a trade
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def portfolio_context(p, pos=None) -> dict:
    """Portfolio state just before the fill (cost basis, no quotes: fast and deterministic)."""
    invested = sum(x.qty * x.avg_cost * x.multiplier for x in p.positions if x.qty)
    return {"cash": p.cash, "invested_at_cost": invested, "equity_at_cost": p.cash + invested,
            "open_positions": sum(1 for x in p.positions if x.qty and x.sec_type == "STK"),
            "open_options": sum(1 for x in p.positions if x.qty and x.sec_type == "OPT"),
            "settings": dict(p.settings or {}), "target_positions": p.target_positions, "style": p.style,
            "position_before": ({"qty": pos.qty, "avg_cost": pos.avg_cost, "realized_pnl": pos.realized_pnl,
                                 "tranches_filled": pos.tranches_filled} if pos is not None else None)}


def market_context(quote=None) -> dict:
    out: dict[str, Any] = {"utc": datetime.now(timezone.utc).isoformat()}
    try:
        from vmi.data import market_hours
        out["session"] = market_hours.session_now()
    except Exception:
        pass
    if quote is not None:
        out["quote"] = {k: getattr(quote, k, None) for k in ("last", "bid", "ask", "close", "volume", "avg_volume",
                                                             "source", "session")}
    return out


def build(symbol: str, *, kind: str = "stock", quote=None, extra: dict | None = None, analyse: bool | None = None) -> dict:
    """Full context dict for a new trade. analyse=None follows settings.capture_trade_context."""
    ctx = {"schema": SCHEMA, "kind": kind, "market": market_context(quote), **(extra or {})}
    if analyse if analyse is not None else get_settings().capture_trade_context:
        ctx["analysis"] = analysis_context(symbol)
    return ctx
