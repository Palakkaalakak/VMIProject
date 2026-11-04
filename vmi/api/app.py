"""FastAPI application — the single local server (run next to TWS / IB Gateway).

    python -m vmi.api            # or: uvicorn vmi.api.app:app --host 0.0.0.0 --port 8000

Routers are grouped by feature; heavy work runs in the threadpool (sync def endpoints) so the event loop
stays responsive. A background task checks watchlists every 60s while the app is open.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vmi import store
from vmi.api.jsonsafe import SafeJSONResponse, SafeRoute, clean
from vmi.config import ROOT
from vmi.data import ib_fundamentals, market
from vmi.data.ib import gateway
from vmi.rules import RULES

log = logging.getLogger("vmi.api")
STATIC = ROOT / "static"


async def _watch_loop():
    from vmi.watchlist import service as wl

    while True:
        try:
            await asyncio.to_thread(wl.check_all)
        except Exception as exc:
            log.info("watchlist check failed: %s", exc)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.engine()
    from vmi.paper.engine import ensure_default_portfolios
    ensure_default_portfolios()
    gateway().start()
    task = asyncio.create_task(_watch_loop())
    yield
    task.cancel()


app = FastAPI(title="VMI Toolkit", version="0.2.0", lifespan=lifespan, default_response_class=SafeJSONResponse)


@app.exception_handler(ValueError)
async def value_error(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ======================================================================================== system
sysr = APIRouter(prefix="/api", tags=["system"], route_class=SafeRoute)


@sysr.get("/health")
def health():
    return {"ok": True, "ib": gateway().info(), "ib_fundamentals": ib_fundamentals.status()}


@sysr.get("/rules")
def rules():
    return RULES.to_dict()


@sysr.get("/quote/{symbol}")
def quote(symbol: str):
    return market.quote(symbol).to_dict()


@sysr.get("/history/{symbol}")
def history(symbol: str, period: str = "2y", interval: str = "1d"):
    from vmi.analysis.technicals import add_mas
    df = market.history(symbol, period, interval)
    d = add_mas(df).reset_index()
    d["date"] = d["date"].dt.strftime("%Y-%m-%d")
    return {"symbol": symbol.upper(), "rows": d.astype(object).where(d.notna(), None).to_dict(orient="records")}


# ======================================================================================== analysis
ar = APIRouter(prefix="/api/analysis", tags=["analysis"], route_class=SafeRoute)


@ar.get("/{symbol}")
def analyse(symbol: str, technicals: bool = True):
    from vmi.analysis.pipeline import analyse_ticker
    return analyse_ticker(symbol, with_technicals=technicals, overrides=store.get_override(symbol))


class OverrideIn(BaseModel):
    growth: float | None = None
    growth_6_10: float | None = None
    growth_11_20: float | None = None
    discount_rate: float | None = None
    method: str | None = None
    biz_type: str | None = None
    iv_override: float | None = None
    base_cf: float | None = None
    moat: dict | None = None
    note: str = ""


@ar.get("/{symbol}/override")
def get_override(symbol: str):
    return store.get_override(symbol)


@ar.put("/{symbol}/override")
def put_override(symbol: str, body: OverrideIn):
    return store.set_override(symbol, body.model_dump(exclude={"note"}), body.note)


@ar.get("/{symbol}/fundamentals")
def fundamentals(symbol: str):
    from vmi.data.fundamentals import resolve
    f = resolve(symbol)
    if f is None:
        raise HTTPException(404, "no fundamentals")
    return f.to_dict()


@ar.get("/{symbol}/size")
def size(symbol: str, portfolio_id: int, multiplier: float = 1.0):
    from vmi.paper.engine import size_for
    return size_for(portfolio_id, symbol, multiplier)


# ======================================================================================== scanner
sr = APIRouter(prefix="/api/scan", tags=["scanner"], route_class=SafeRoute)


class ScanIn(BaseModel):
    universe: str = "us"
    symbols: list[str] = Field(default_factory=list)
    min_market_cap: float = 2e9
    min_price: float = 5.0
    min_roe: float = RULES.profitability.min_roe
    require_ten_year_uptrend: bool = True
    deep_limit: int = 400
    workers: int = 4
    include_speculative: bool = True


@sr.post("/start")
def scan_start(body: ScanIn):
    from vmi.scanner import funnel
    return funnel.start_background(body.model_dump())


@sr.get("/status")
def scan_status():
    from vmi.scanner import funnel
    return funnel.status_dict()


@sr.get("/results")
def scan_results(run_id: int | None = None, sort: str = "margin_of_safety", desc: bool = True,
                 only_great: bool = False, style: str | None = None, min_growth: float | None = None,
                 max_growth: float | None = None):
    from vmi.scanner import funnel
    res = funnel.latest_results(run_id)
    rows = res.get("results") or []
    if only_great:
        rows = [r for r in rows if r.get("great_business")]
    if style:
        rows = [r for r in rows if r.get("style") == style]
    if min_growth is not None:
        rows = [r for r in rows if (r.get("growth") or -9) >= min_growth]
    if max_growth is not None:
        rows = [r for r in rows if (r.get("growth") or 9) < max_growth]
    have = sorted([r for r in rows if r.get(sort) is not None], key=lambda r: r[sort], reverse=desc)
    return {**res, "results": have + [r for r in rows if r.get(sort) is None]}


@sr.get("/dropped")
def scan_dropped():
    from vmi.scanner import funnel
    return funnel.dropped_reasons()


# ======================================================================================== portfolios
pr = APIRouter(prefix="/api/portfolios", tags=["paper trading"], route_class=SafeRoute)


class PortfolioIn(BaseModel):
    name: str
    style: str = "balanced"
    cash: float | None = None
    target_positions: int | None = None


class StockOrder(BaseModel):
    symbol: str
    side: str
    qty: float | None = None
    dollars: float | None = None
    tranche: bool = False          # auto-size one VMI tranche
    multiplier: float = 1.0        # category multiplier (½ speculative, ¾ narrow moat)
    note: str = ""


class OptionOrder(BaseModel):
    symbol: str
    expiry: str
    strike: float
    right: str
    side: str
    contracts: int
    note: str = ""


@pr.get("")
def list_portfolios():
    from vmi.paper import engine
    return engine.list_portfolios()


@pr.post("")
def create_portfolio(body: PortfolioIn):
    from vmi.paper import engine
    return engine.create_portfolio(body.name, body.style, body.cash, body.target_positions)


@pr.get("/{pid}")
def get_portfolio(pid: int):
    from vmi.paper import engine
    return engine.summary(pid)


@pr.delete("/{pid}")
def delete_portfolio(pid: int):
    from vmi.paper import engine
    engine.delete_portfolio(pid)
    return {"ok": True}


@pr.post("/{pid}/reset")
def reset_portfolio(pid: int):
    from vmi.paper import engine
    return engine.reset_portfolio(pid)


@pr.get("/{pid}/trades")
def portfolio_trades(pid: int):
    from vmi.paper import engine
    return engine.trades(pid)


@pr.post("/{pid}/orders/stock")
def stock_order(pid: int, body: StockOrder):
    from vmi.paper import engine
    qty, dollars = body.qty, body.dollars
    if body.tranche and body.side.upper() == "BUY":
        plan = engine.size_for(pid, body.symbol, body.multiplier)
        if plan["remaining_value"] <= 0:
            raise ValueError(plan["warning"] or "full allocation reached")
        dollars, qty = min(plan["tranche_value"], plan["remaining_value"]), None
    return engine.trade_stock(pid, body.symbol, body.side, qty, dollars, body.note)


@pr.post("/{pid}/orders/option")
def option_order(pid: int, body: OptionOrder):
    from vmi.paper import engine
    return engine.trade_option(pid, body.symbol, body.expiry, body.strike, body.right, body.side, body.contracts,
                               body.note)


# ======================================================================================== watchlists
wr = APIRouter(prefix="/api/watchlists", tags=["watchlists"], route_class=SafeRoute)


class WatchlistIn(BaseModel):
    name: str


class ItemIn(BaseModel):
    symbol: str
    intrinsic_value: float | None = None
    supports: list[float] | None = None
    notes: str | None = None


class ImportIn(BaseModel):
    text: str
    auto_fill: bool = False


@wr.get("")
def wl_list():
    from vmi.watchlist import service
    return service.list_all()


@wr.post("")
def wl_create(body: WatchlistIn):
    from vmi.watchlist import service
    return service.create(body.name)


@wr.get("/{wid}")
def wl_get(wid: int):
    from vmi.watchlist import service
    return service.get(wid)


@wr.delete("/{wid}")
def wl_delete(wid: int):
    from vmi.watchlist import service
    service.delete(wid)
    return {"ok": True}


@wr.post("/{wid}/items")
def wl_upsert(wid: int, body: ItemIn):
    from vmi.watchlist import service
    return service.upsert_item(wid, body.symbol, body.intrinsic_value, body.supports, body.notes)


@wr.delete("/{wid}/items/{symbol}")
def wl_remove(wid: int, symbol: str):
    from vmi.watchlist import service
    service.remove_item(wid, symbol)
    return {"ok": True}


@wr.post("/{wid}/items/{symbol}/autofill")
def wl_autofill(wid: int, symbol: str):
    from vmi.watchlist import service
    return service.autofill(wid, symbol)


@wr.post("/{wid}/import")
def wl_import(wid: int, body: ImportIn):
    from vmi.watchlist import service
    return service.import_text(wid, body.text, body.auto_fill)


@wr.post("/{wid}/scan")
def wl_scan(wid: int):
    """Run the superscanner deep pass on this watchlist (universe=list)."""
    from vmi.scanner import funnel
    from vmi.watchlist import service
    syms = [i["symbol"] for i in service.get(wid)["items"]]
    return funnel.start_background({"universe": "list", "symbols": syms, "require_ten_year_uptrend": False})


alr = APIRouter(prefix="/api/alerts", tags=["alerts"], route_class=SafeRoute)


@alr.get("")
def alerts(unseen: bool = False):
    from vmi.watchlist import service
    return service.alerts(unseen)


@alr.post("/seen")
def alerts_seen(ids: list[int] | None = None):
    from vmi.watchlist import service
    service.mark_seen(ids)
    return {"ok": True}


@alr.post("/check")
def alerts_check():
    from vmi.watchlist import service
    return service.check_all()


# ======================================================================================== options
orr = APIRouter(prefix="/api/options", tags=["options"], route_class=SafeRoute)


@orr.get("/{symbol}/expirations")
def opt_exps(symbol: str):
    from vmi.options import chain
    return chain.expirations(symbol)


@orr.get("/{symbol}/chain")
def opt_chain(symbol: str, expiry: str | None = None, width: float = Query(0.30, ge=0.05, le=1.0)):
    from vmi.options import chain
    return chain.chain(symbol, expiry, width)


@orr.get("/{symbol}/suggest")
def opt_suggest(symbol: str, strategy: str = "CSP", expiry: str | None = None):
    from vmi.options import chain
    from vmi.watchlist import service
    levels, iv = [], None
    for w in service.list_all():         # use watchlist levels/IV when the symbol is watched
        for it in service.get(w["id"])["items"]:
            if it["symbol"] == symbol.upper():
                levels, iv = it.get("supports") or [], it.get("intrinsic_value")
    return chain.suggest(symbol, strategy, expiry, levels, iv)


for r in (sysr, ar, sr, pr, wr, alr, orr):
    app.include_router(r)

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    if (STATIC / "index.html").exists():
        return FileResponse(STATIC / "index.html")
    return {"app": "VMI Toolkit", "docs": "/docs"}
