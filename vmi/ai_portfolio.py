"""Explicit, bounded read-only lookups for the local portfolio assistant."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import select

from vmi import store
from vmi.api.jsonsafe import clean
from vmi.data.market_hours import ET

SECTIONS = (
    "portfolios", "holdings", "trades", "audit", "snapshot", "performance", "review", "plans",
    "watchlists", "alerts", "touches", "scanner", "option_book", "option_chain", "analysis",
    "fundamentals", "quote", "prices", "judgements", "rules",
)
TOOL = {"type": "function", "function": {
    "name": "read_app_data",
    "description": "Look up read-only VMI app data. Portfolio ID defaults to the active portfolio. "
                   "Use record_id for a watchlist, saved scanner run or option capture. "
                   "Use an ISO date/time for snapshot, dates for trade or performance ranges, and ticker for market data.",
    "parameters": {"type": "object", "properties": {
        "section": {"type": "string", "enum": list(SECTIONS)},
        "portfolio_id": {"type": "integer", "minimum": 1},
        "benchmark": {"type": "string", "enum": ["SPY", "QQQ", "VTI"],
                      "description": "For performance: compare with the benchmark in the same date range."},
        "record_id": {"type": "integer", "minimum": 1},
        "ticker": {"type": "string", "maxLength": 20},
        "start": {"type": "string", "description": "YYYY-MM-DD, New York time"},
        "end": {"type": "string", "description": "YYYY-MM-DD, New York time"},
        "as_of": {"type": "string", "description": "ISO date or timestamp; accepts New York local time"},
        "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
    }, "required": ["section"], "additionalProperties": False},
}}


WEB_SEARCH = {"type": "function", "function": {
    "name": "web_search",
    "description": "Search public web sources using your own short query. Returns titles, URLs and excerpts. "
                   "Use public tickers, company names, dates, events or market terms only; omit private data.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 200}},
                   "required": ["query"], "additionalProperties": False},
}}


READ_BENCHMARK_SOURCE = {"type": "function", "function": {
    "name": "read_benchmark_source",
    "description": "Read a public SEC, ETF issuer, or index provider source to verify dated benchmark holdings and weights. "
                   "Use the source URL from a search result. Never include private data.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string", "maxLength": 500},
                   "offset": {"type": "integer", "minimum": 0, "maximum": 60000}},
                   "required": ["url"], "additionalProperties": False},
}}
_BENCHMARK_HOSTS = {"www.sec.gov", "www.ishares.com", "www.spglobal.com", "www.invesco.com", "investor.vanguard.com",
                    "institutional.vanguard.com", "www.ssga.com", "www.ssga-funds.com", "www.nasdaq.com", "indexes.nasdaqomx.com"}


def assistant_tools(pid: int, *, app_data: bool, web_research: bool, deep: bool = False):
    """Grant only requested capabilities and record the lookups the model actually makes."""
    tools = ([TOOL] if app_data else []) + (([WEB_SEARCH, READ_BENCHMARK_SOURCE] if deep else [WEB_SEARCH]) if web_research else [])
    app_run, app_lookups = runner(pid, enabled=app_data, max_calls=12 if deep else 5)
    searches: list[dict] = []
    seen: set[str] = set()
    read_sources: set[tuple] = set()
    activity = {}
    if app_data:
        activity["app_lookups"] = app_lookups
    if web_research:
        activity["public_research"] = searches

    def run(name: str, args) -> str:
        if name not in {"web_search", "read_benchmark_source"}:
            return app_run(name, args)
        if not web_research:
            return "Refused: web research is not enabled."
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, RecursionError):
                return "Invalid search arguments."
        if name == "read_benchmark_source":
            if not deep:
                return "Refused: source reading is available in Deep analysis."
            if not isinstance(args, dict) or args.keys() - {"url", "offset"}:
                return "Supply a public benchmark source URL."
            url, offset = args.get("url"), args.get("offset", 0)
            if not isinstance(url, str) or len(url) > 500 or type(offset) is not int or not 0 <= offset <= 60000:
                return "Invalid benchmark URL or offset."
            try:
                parsed = urlsplit(url)
                # Do not accept arbitrary destinations, embedded credentials, ports or custom query payloads.
                if parsed.scheme != "https" or parsed.netloc not in _BENCHMARK_HOSTS or parsed.query or parsed.fragment:
                    return "Use a direct HTTPS page on an approved issuer, index or SEC website (without query or fragment)."
            except ValueError:
                return "Invalid benchmark URL."
            key = (url, offset)
            if key in read_sources or len(read_sources) >= 5:
                return "Source was already read or source-reading budget exhausted."
            read_sources.add(key)
            from vmi.ai_tools import read_page

            try:
                raw = read_page(url, offset)
                excerpts = raw[:3200]
                if len(raw) > 3200:
                    excerpts += f"\n[Read the next excerpt with offset {offset + 3200}.]"
            except Exception:
                excerpts = "This public source could not be read."
            searches.append({"url": url, "offset": offset, "excerpts": excerpts})
            return f"Source: {url}\n{excerpts}"
        if not isinstance(args, dict) or args.keys() != {"query"}:
            return "Supply only a short public search query."
        raw_query = args["query"]
        if not isinstance(raw_query, str) or not 1 <= len(raw_query.strip()) <= 200:
            return "Supply a public query between 1 and 200 characters."
        query = " ".join(raw_query.split())
        key = query.casefold()
        if key in seen:
            return "Search already run; use the previous result."
        if len(seen) >= (9 if deep else 3):
            return "Search budget exhausted. Answer from available evidence."
        seen.add(key)
        from vmi.ai_tools import web_search

        try:
            excerpts = web_search(query, n=6 if deep else 4)
            if excerpts.startswith("no relevant results"):
                excerpts = "No relevant results. Try a different public query or report the gap."
        except Exception:
            excerpts = "Public search could not be completed."
        searches.append({"query": query, "excerpts": excerpts[:2500]})
        return searches[-1]["excerpts"]

    return tools, run, activity


def _page(rows, offset: int, size: int = 8) -> dict:
    return {"total": len(rows), "offset": offset, "rows": rows[offset:offset + size]}


def _records(model, offset, *conditions, order=None, omit=()):
    query = select(model).where(*conditions).order_by(*(order or (model.id.desc(),)))
    with store.session() as s:
        rows = [{k: v for k, v in store.to_dict(r).items() if k not in omit}
                for r in s.scalars(query.offset(offset).limit(9))]
    return {"offset": offset, "rows": rows[:8], "more": len(rows) > 8}


def read(default_pid: int, args: dict):
    from vmi.paper import engine, journal

    section = args["section"]
    pid = args.get("portfolio_id", default_pid)
    record = args.get("record_id")
    offset = args.get("offset", 0)
    symbol = args.get("ticker", "").strip().upper()
    if symbol and not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=-]{0,19}", symbol):
        raise ValueError("Invalid ticker.")
    start = date.fromisoformat(args["start"]) if args.get("start") else None
    end = date.fromisoformat(args["end"]) if args.get("end") else None
    if start and end and start > end:
        raise ValueError("Start must be on or before end.")
    if section == "portfolios":
        return _records(store.Portfolio, offset)
    if section == "holdings":
        result = engine.summary(pid, settle=False)
        positions = [p for p in result.pop("positions") if not symbol or p["symbol"] == symbol]
        return {"portfolio": result, "positions": _page(positions, offset)}
    if section in {"trades", "audit"}:
        model = store.Trade if section == "trades" else store.TradeAudit
        where = [model.portfolio_id == pid]
        if section == "trades" and symbol:
            where.append(model.symbol == symbol)
        if record:
            where.append(model.id == record)
        if start:
            where.append(model.ts >= datetime.combine(start, time.min, ET).astimezone(timezone.utc))
        if end:
            where.append(model.ts <= datetime.combine(end, time.max, ET).astimezone(timezone.utc))
        return _records(model, offset, *where, order=(model.ts.desc(), model.id.desc()),
                        omit=() if record else ("context", "before", "after"))
    if section == "snapshot":
        at = args.get("as_of") or (end.isoformat() if end else datetime.now(ET).date().isoformat())
        result = journal.snapshot(pid, at)
        result["positions"] = _page([p for p in result["positions"] if not symbol or p["symbol"] == symbol], offset)
        return result
    if section == "performance":
        end = end or datetime.now(ET).date()
        start = start or end - timedelta(days=90)
        if (end - start).days > 3660:
            raise ValueError("Select at most ten years per lookup.")
        result = journal.history(pid, start, end, include_performance=True, benchmark=args.get("benchmark"), include_attribution=True)
        points = result.pop("points")
        benchmark = result.pop("benchmark")
        if benchmark:
            benchmark_return = benchmark["price_return"][-1]
            fund = {"ticker": benchmark["symbol"], "first_price_day": benchmark["base_day"],
                    "price_return": benchmark_return, "holdings_and_weights": "Not supplied by historical price data."}
            if benchmark_return is not None and result["period_return"] is not None and benchmark["base_day"] < start.isoformat():
                fund["portfolio_minus_benchmark_pct_points"] = 100 * (result["period_return"] - benchmark_return)
            else:
                fund["coverage_note"] = "No eligible starting close before the requested range; not an aligned comparison."
            result["benchmark"] = fund
        stocks = [{**{k: v for k, v in row.items() if k not in {"pnl", "price_return"}},
                   "contribution_usd": row["pnl"][-1], "stock_price_return": row["price_return"][-1]}
                  for row in result.pop("stocks") if not symbol or row["symbol"] == symbol]
        stocks.sort(key=lambda row: -abs(row["contribution_usd"]))
        fields = ("day", "equity", "cash", "market_value", "estimated_positions")
        return {**result, "start": start, "end": end, "last": {k: points[-1][k] for k in fields},
                "stocks_by_absolute_contribution": _page(stocks, offset, 6)}
    if section == "review":
        from vmi.paper import review

        result = review.summary(pid)
        result["lots"] = _page([lot for lot in result["lots"] if not symbol or lot.get("symbol") == symbol], offset, 3)
        return result
    if section == "plans":
        from vmi.paper import autotrade

        rows = [p for p in autotrade.get_plans(pid) if not symbol or p["symbol"] == symbol]
        return {"settings": autotrade.settings(pid), **_page(rows, offset)}
    if section == "watchlists":
        if not record and not symbol:
            return _records(store.Watchlist, offset)
        where = []
        if record:
            where.append(store.WatchItem.watchlist_id == record)
        if symbol:
            where.append(store.WatchItem.symbol == symbol)
        return _records(store.WatchItem, offset, *where)
    if section in {"alerts", "touches"}:
        model = store.Alert if section == "alerts" else store.SupportTouch
        return _records(model, offset, *([model.symbol == symbol] if symbol else []))
    if section == "scanner":
        from vmi.scanner.funnel import latest_results

        result = latest_results(record)
        rows = [r for r in result.pop("results") if not symbol or symbol in (r.get("ticker"), r.get("symbol"))]
        return {**result, **_page(rows, offset)}
    if section == "option_book":
        from vmi.options import book

        if record:
            return book.get(record)
        where = [store.OptionSnapshot.portfolio_id == pid]
        if symbol:
            where.append(store.OptionSnapshot.symbol == symbol)
        return _records(store.OptionSnapshot, offset, *where, omit=("result",))
    if section == "rules":
        from vmi.settings import schema

        return _page(schema(), offset)
    if section == "judgements":
        return store.get_override(symbol) if symbol else _page(list(store.all_overrides().items()), offset)
    if not symbol:
        raise ValueError("Supply a ticker for this lookup.")
    if section == "option_chain":
        from vmi.options.chain import chain

        result = chain(symbol, expiry=end.strftime("%Y%m%d") if end else None, width=0.10)
        return {**result, "rows": _page(result["rows"], offset, 4)}
    if section == "analysis":
        from vmi.analysis.pipeline import analyse_ticker

        result = analyse_ticker(symbol, overrides=store.get_override(symbol))
        return {k: result.get(k) for k in ("ticker", "name", "price", "intrinsic_value", "steps", "metrics", "technicals")}
    if section == "fundamentals":
        from vmi.data.fundamentals import resolve

        fundamentals = resolve(symbol)
        if fundamentals is None:
            return {"ticker": symbol, "available": False}
        data = fundamentals.to_dict()
        annual = {name: points[-5:] for name, points in data["annual"].items()}
        return {"ticker": symbol, "source": data["source"], "annual": _page(list(annual.items()), offset, 5)}
    from vmi.data import market

    if section == "quote":
        return market.quote(symbol).to_dict()
    if section == "prices":
        frame = market.history(symbol, "10y" if start or end else "1mo")
        if start:
            frame = frame.loc[start.isoformat():]
        if end:
            frame = frame.loc[:end.isoformat()]
        rows = [{"day": str(day), **values} for day, values in frame.iloc[::-1].iterrows()]
        return _page(rows, offset)
    raise ValueError("Unknown app section.")


def _compact(value, depth=0):
    if depth > 6:
        return "[nested detail omitted]"
    if isinstance(value, dict):
        return {k: _compact(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_compact(v, depth + 1) for v in value[:8]]
    return value[:280] if isinstance(value, str) else value


def runner(pid: int, *, enabled: bool = True, max_calls: int = 5):
    used: list[dict] = []
    seen: set[str] = set()

    def run(name: str, args) -> str:
        if not enabled or name != "read_app_data":
            return "Refused: this tool is not enabled."
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, RecursionError):
                return "Invalid arguments."
        properties = TOOL["function"]["parameters"]["properties"]
        if not isinstance(args, dict) or args.keys() - properties.keys():
            return "Invalid arguments."
        if not isinstance(args.get("section"), str) or args["section"] not in SECTIONS:
            return "Choose an available app section."
        for key, value in args.items():
            spec = properties[key]
            if spec["type"] == "integer":
                if type(value) is not int or not spec["minimum"] <= value <= spec.get("maximum", 2**63 - 1):
                    return "Invalid ID or offset."
            elif not isinstance(value, str) or len(value) > spec.get("maxLength", 40):
                return "Invalid text argument."
        key = json.dumps(args, sort_keys=True)
        if key in seen:
            return "Already looked up; use the previous result."
        if len(seen) >= max_calls:
            return "Lookup budget exhausted. Answer from the evidence already returned."
        try:
            text = json.dumps(_compact(clean(read(pid, args))), ensure_ascii=False, default=str, separators=(",", ":") if args["section"] == "performance" else None)
            if len(text) > 3850:
                text = text[:3850] + "\n[Result shortened; narrow the lookup or use an offset.]"
            used.append({**args, "status": "read"})
        except Exception:
            text = "Lookup unavailable. Check the ticker, ID or date and try a narrower query."
            used.append({**args, "status": "unavailable"})
        seen.add(key)
        return text

    return run, used
