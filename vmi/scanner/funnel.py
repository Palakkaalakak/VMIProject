"""Superscanner — the whole US market through Adam's filters, broadest/cheapest first.

Stage order is chosen so each stage removes the most companies for the least cost:

  0. universe        NASDAQ screener (~6,600 listings, 1 request): common stocks, market cap ≥ min,
                     price ≥ min, excludes funds/warrants/units/SPACs.                         [free, local]
  1. track_record    SEC XBRL *frames* — one request returns a concept for ALL filers, so revenue / net
                     income / operating income / CFO for 6 calendar years ≈ 24 requests for the whole
                     market. Step 1 "consistently increasing" (Adam: eliminates ~95%).          [~24 requests]
  2. profitability   ROE proxy from frames (NI ÷ equity) ≥ 12% (Step 4) — banks/insurers judged later.
  3. long_term_chart 10-year monthly uptrend (Lesson 6 §3.3 hard filter) via one batched download.
  4. deep            full 7-step analysis + auto-selected valuation per survivor (vmi.analysis.pipeline),
                     parallel, with per-ticker overrides applied.

Every stage records its in/out counts (the funnel) and why each ticker was dropped, so the result is
auditable. Stages are plain functions in STAGES — add/reorder without touching the runner.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from vmi import store
from vmi.analysis.trends import trend
from vmi.data import sec, universe
from vmi.rules import RULES

log = logging.getLogger("vmi.scanner")


@dataclass
class ScanParams:
    universe: str = "us"                 # "us" | "sp500" | "list"
    symbols: list[str] = field(default_factory=list)   # for universe="list" (imported watchlist etc.)
    min_market_cap: float = 2e9
    min_price: float = 5.0
    min_roe: float = RULES.profitability.min_roe
    require_ten_year_uptrend: bool = True
    deep_limit: int = 400                # safety cap on deep analyses per run
    workers: int = 4
    include_speculative: bool = True     # keep 50%+ revenue growers even if NI not yet consistent

    @classmethod
    def from_dict(cls, d: dict | None) -> "ScanParams":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Candidate:
    symbol: str
    name: str = ""
    cik: int | None = None
    market_cap: float = 0.0
    sector: str = ""
    industry: str = ""
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanState:
    run_id: int | None = None
    stage: str = "idle"
    progress: float = 0.0
    message: str = ""
    funnel: list[dict] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    running: bool = False
    started: float = 0.0
    error: str = ""


STATE = ScanState()
_lock = threading.Lock()


# ------------------------------------------------------------------------------------------ stages
def stage_universe(cands: list[Candidate], p: ScanParams) -> list[Candidate]:
    if p.universe == "list":
        tm = sec.ticker_map()
        return [Candidate(s.upper(), (tm.get(s.upper()) or {}).get("name", ""), (tm.get(s.upper()) or {}).get("cik"))
                for s in p.symbols]
    tm = sec.ticker_map()
    if p.universe == "sp500":
        return [Candidate(r["symbol"], r["name"], r.get("cik") or (tm.get(r["symbol"]) or {}).get("cik"),
                          0.0, r.get("sector", ""), r.get("sub_industry", "")) for r in universe.sp500()]
    out = []
    for r in universe.us_market():
        if not universe.is_common_stock(r):
            STATE.dropped[r["symbol"]] = "not a common stock"
            continue
        if r["market_cap"] < p.min_market_cap or r["price"] < p.min_price:
            continue
        rec = tm.get(r["symbol"]) or tm.get(r["symbol"].replace("-", "."))
        if not rec:
            STATE.dropped[r["symbol"]] = "no SEC filer record (foreign/OTC) — use universe=list to force"
            continue
        out.append(Candidate(r["symbol"], r["name"], rec["cik"], r["market_cap"], r["sector"], r["industry"]))
    return out


def _calendar_years(n: int = 6) -> list[int]:
    last_full = date.today().year - 1
    # frames for the latest calendar year fill in through Q1; fall back one year early in the year
    if date.today().month < 4:
        last_full -= 1
    return list(range(last_full - n + 1, last_full + 1))


def _frame_series(concept: str, years: list[int]) -> dict[int, list[float | None]]:
    per_year = {y: sec.frame_concept(concept, f"CY{y}") for y in years}
    ciks = set().union(*[set(d) for d in per_year.values()])
    return {c: [per_year[y].get(c) for y in years] for c in ciks}


def stage_track_record(cands: list[Candidate], p: ScanParams) -> list[Candidate]:
    years = _calendar_years(6)
    STATE.message = f"SEC frames {years[0]}–{years[-1]} (revenue, NI, operating income, CFO, equity)"
    rev = _frame_series("revenue", years)
    ni = _frame_series("net_income", years)
    oi = _frame_series("operating_income", years)
    cfo = _frame_series("cfo", years)
    r = RULES.track
    out = []
    for c in cands:
        if c.cik is None:
            out.append(c)          # no frame data path — let the deep stage decide
            continue
        rv = [v for v in rev.get(c.cik, []) if v is not None]
        if len(rv) < 4:
            out.append(c)          # frames incomplete (fiscal-year filers, tag gaps) — defer to deep stage
            c.notes["track"] = "frames incomplete — deferred"
            continue
        rt = trend(rv, r.max_down_years_5y, 4)
        if not rt.consistent:
            growth = (rv[-1] / rv[-2] - 1) if len(rv) >= 2 and rv[-2] > 0 else 0
            STATE.dropped[c.symbol] = f"Step 1: revenue {rt.reason}"
            continue
        nv = [v for v in ni.get(c.cik, []) if v is not None]
        ov = [v for v in oi.get(c.cik, []) if v is not None]
        earn_ok = (len(nv) >= 4 and trend(nv, r.max_down_years_5y, 4).consistent) or \
                  (len(ov) >= 4 and trend(ov, r.max_down_years_5y, 4).consistent)
        if not earn_ok:
            growth = (rv[-1] / rv[0]) ** (1 / max(1, len(rv) - 1)) - 1 if rv[0] > 0 else 0
            if p.include_speculative and growth >= RULES.speculative.min_revenue_growth:
                c.notes["speculative"] = True
            elif len(nv) >= 4 or len(ov) >= 4:
                STATE.dropped[c.symbol] = "Step 1: net income / operating income not consistently increasing"
                continue
        c.notes["revenue_cagr"] = rt.cagr
        cv = [v for v in cfo.get(c.cik, []) if v is not None]
        c.notes["cfo_consistent"] = len(cv) >= 4 and trend(cv, r.max_down_years_5y, 4).consistent
        out.append(c)
    return out


def stage_profitability(cands: list[Candidate], p: ScanParams) -> list[Candidate]:
    y = _calendar_years(1)[0]
    ni = sec.frame_concept("net_income", f"CY{y}")
    eq = sec.frame_concept("equity", f"CY{y}Q4I")
    out = []
    for c in cands:
        n, e = ni.get(c.cik or -1), eq.get(c.cik or -1)
        if n is None or e is None or e <= 0 or c.notes.get("speculative"):
            out.append(c)          # can't judge cheaply (negative equity from buybacks, banks …) → deep stage
            continue
        roe = n / e
        c.notes["roe_proxy"] = roe
        if roe < p.min_roe:
            STATE.dropped[c.symbol] = f"Step 4: ROE {roe:.1%} < {p.min_roe:.0%}"
            continue
        out.append(c)
    return out


def stage_long_term_chart(cands: list[Candidate], p: ScanParams) -> list[Candidate]:
    if not p.require_ten_year_uptrend or not cands:
        return cands
    import numpy as np
    import yfinance as yf

    out = []
    syms = [c.symbol for c in cands]
    by = {c.symbol: c for c in cands}
    for i in range(0, len(syms), 150):
        chunk = syms[i:i + 150]
        STATE.message = f"10-year monthly charts {i + len(chunk)}/{len(syms)}"
        try:
            data = yf.download([s.replace(".", "-") for s in chunk], period="10y", interval="1mo",
                               group_by="ticker", auto_adjust=True, threads=True, progress=False)
        except Exception as exc:
            log.warning("monthly download failed: %s", exc)
            out.extend(by[s] for s in chunk)
            continue
        for s in chunk:
            try:
                sub = data[s.replace(".", "-")] if len(chunk) > 1 else data
                closes = sub["Close"].dropna()
            except Exception:
                out.append(by[s])
                continue
            if len(closes) < 36:   # young listing: can't judge 10y — keep (speculative path / deep stage)
                by[s].notes["ten_year"] = "insufficient history"
                out.append(by[s])
                continue
            slope = np.polyfit(np.arange(len(closes)), np.log(closes.values), 1)[0]
            ret = closes.iloc[-1] / closes.iloc[0] - 1
            by[s].notes["ten_year_return"] = float(ret)
            if slope > 0 and ret > 0.5:
                out.append(by[s])
            else:
                STATE.dropped[s] = f"Lesson 6: 10-year chart not in a long-term uptrend ({ret:+.0%})"
    return out


def stage_deep(cands: list[Candidate], p: ScanParams) -> list[Candidate]:
    from vmi.analysis.pipeline import analyse_ticker

    todo = cands[: p.deep_limit]
    overrides = store.all_overrides()
    done = 0
    results: list[dict] = []

    def work(c: Candidate):
        ov = (overrides.get(c.symbol) or {}).get("data")
        return c, analyse_ticker(c.symbol, with_technicals=True, overrides=ov)

    with ThreadPoolExecutor(max_workers=p.workers) as ex:
        futs = [ex.submit(work, c) for c in todo]
        for fut in as_completed(futs):
            done += 1
            STATE.progress = 0.6 + 0.4 * done / max(1, len(todo))
            try:
                c, rep = fut.result()
            except Exception as exc:
                STATE.message = f"deep analysis error: {exc}"
                continue
            STATE.message = f"deep analysis {done}/{len(todo)} — {c.symbol}"
            results.append(compact(rep, c))
    results.sort(key=lambda r: (not r["great_business"], -(r.get("margin_of_safety") or -9)))
    STATE.results = results
    return [c for c in todo]


STAGES: list[tuple[str, Callable[[list[Candidate], ScanParams], list[Candidate]]]] = [
    ("universe", stage_universe),
    ("track_record", stage_track_record),
    ("profitability", stage_profitability),
    ("long_term_chart", stage_long_term_chart),
    ("deep", stage_deep),
]


def compact(rep: dict, c: Candidate | None = None) -> dict:
    """Flat, sortable row for the results table (growth, ROE, MOS, category …)."""
    m = rep.get("metrics", {})
    steps = {s["step"]: s["passed"] for s in rep.get("steps", [])}
    tech = rep.get("technicals") or {}
    return {
        "symbol": rep["ticker"], "name": rep.get("name", ""), "sector": rep.get("sector", ""),
        "industry": rep.get("industry", ""), "price": rep.get("price"), "intrinsic_value": rep.get("intrinsic_value"),
        "conservative_value": (rep.get("valuation") or {}).get("conservative_value"),
        "method": (rep.get("valuation") or {}).get("selected"), "margin_of_safety": m.get("margin_of_safety"),
        "growth": m.get("growth"), "roe": m.get("roe"), "roic": m.get("roic"), "net_margin": m.get("net_margin"),
        "pe": m.get("pe"), "peg": m.get("peg"), "dividend_yield": m.get("dividend_yield"), "beta": m.get("beta"),
        "market_cap": m.get("market_cap") or (c.market_cap if c else None), "category": rep.get("category"),
        "style": rep.get("style"), "biz_type": rep.get("biz_type"), "moat": rep.get("moat"),
        "great_business": rep.get("great_business"), "undervalued": rep.get("undervalued"),
        "entry_ok": rep.get("entry_ok"), "vmi_pass": rep.get("vmi_pass"),
        "steps_passed": sum(1 for v in steps.values() if v), "steps": steps,
        "trend": (tech.get("daily") or {}).get("state"), "buy_levels": [b["price"] for b in tech.get("buy_levels", [])],
        "entry_reason": tech.get("entry_reason"), "allocation_multiplier": rep.get("allocation_multiplier"),
        "pinned": (c.notes.get("pinned") if c else None),
    }



# ------------------------------------------------------------------------------------- judgement pins
def _pinned_candidates(cands: list[Candidate]) -> dict[str, Candidate]:
    """Tickers with a human judgement / DB override (e.g. TMO: distorted consensus, Adam keeps it).
    The cheap pre-filters work on raw data and would drop them, so they always reach the deep stage,
    where the full 7-step report (with the override applied) is the honest verdict."""
    ov = store.all_overrides()
    return {c.symbol: c for c in cands if c.symbol in ov}


def _restore_pinned(cands: list[Candidate], pinned: dict[str, Candidate]) -> list[Candidate]:
    have = {c.symbol for c in cands}
    back = [c for sym, c in pinned.items() if sym not in have]
    for c in back:
        why = STATE.dropped.pop(c.symbol, "")
        c.notes["pinned"] = f"judgement override — kept despite pre-filter ({why})" if why else "judgement override"
    return back + cands


# ------------------------------------------------------------------------------------------ runner
def run(params: dict | None = None) -> dict:
    p = ScanParams.from_dict(params)
    with _lock:
        if STATE.running:
            raise RuntimeError("a scan is already running")
        STATE.__init__()
        STATE.running, STATE.started = True, time.time()
    with store.session() as s:
        row = store.ScanRun(universe=p.universe, params=p.__dict__, status="running")
        s.add(row)
        s.commit()
        STATE.run_id = row.id
    cands: list[Candidate] = []
    pinned: dict[str, Candidate] = {}
    try:
        for i, (name, fn) in enumerate(STAGES):
            STATE.stage = name
            STATE.progress = min(0.6, i / (len(STAGES) - 1) * 0.6)
            t0 = time.time()
            n_in = len(cands)
            if name == "deep":
                cands = _restore_pinned(cands, pinned)
            cands = fn(cands, p)
            if name == "universe":
                pinned = _pinned_candidates(cands)
            STATE.funnel.append({"stage": name, "in": n_in, "out": len(cands), "secs": round(time.time() - t0, 1)})
        status = "done"
    except Exception as exc:
        STATE.error = f"{type(exc).__name__}: {exc}"
        log.error("scan failed: %s", traceback.format_exc())
        status = "error"
    finally:
        STATE.running = False
        STATE.stage = status
        STATE.progress = 1.0
        with store.session() as s:
            row = s.get(store.ScanRun, STATE.run_id)
            row.finished_at, row.status, row.funnel, row.results = store.now(), status, \
                {"stages": STATE.funnel, "dropped_count": len(STATE.dropped), "error": STATE.error}, STATE.results
            s.commit()
    return status_dict()


def start_background(params: dict | None = None) -> dict:
    if STATE.running:
        raise RuntimeError("a scan is already running")
    threading.Thread(target=run, args=(params,), daemon=True, name="vmi-scan").start()
    time.sleep(0.2)
    return status_dict()


def status_dict() -> dict:
    return {"run_id": STATE.run_id, "running": STATE.running, "stage": STATE.stage, "progress": round(STATE.progress, 3),
            "message": STATE.message, "funnel": STATE.funnel, "n_results": len(STATE.results), "error": STATE.error,
            "elapsed": round(time.time() - STATE.started, 1) if STATE.started else 0}


def latest_results(run_id: int | None = None) -> dict:
    if STATE.results and (run_id is None or run_id == STATE.run_id):
        return {"run_id": STATE.run_id, "results": STATE.results, "funnel": STATE.funnel}
    with store.session() as s:
        from sqlalchemy import select
        q = select(store.ScanRun).order_by(store.ScanRun.id.desc())
        if run_id:
            q = select(store.ScanRun).where(store.ScanRun.id == run_id)
        row = s.scalar(q.limit(1))
        if not row:
            return {"run_id": None, "results": [], "funnel": []}
        return {"run_id": row.id, "results": row.results, "funnel": (row.funnel or {}).get("stages", []),
                "params": row.params, "status": row.status}


def dropped_reasons(limit: int = 2000) -> dict[str, str]:
    return dict(list(STATE.dropped.items())[:limit])
