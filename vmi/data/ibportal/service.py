"""Cache-aware IB Portal operations. This is what the rest of the app calls.

    cached_fundamentals(ticker)   statements from the cache                               → Fundamentals | None
    cached_estimates(ticker)      analyst fields from the cache                           → {"eps_growth_5y": …}
    sync(tickers, portal)         bulk refresh on a logged-in Portal (parallel workers)   → report dict
    check(tickers, out, portal)   diagnostics: every route, parsed counts, raw JSON dumps → report dict
    prefetch_conids(tickers)      ticker → IB contract id via the TWS API, cached          → count

The app only READS the cache: a live fetch needs the browser login (browser.login), so it happens in `sync`.
Cache keys and TTLs are defined here and nowhere else.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.ibportal import parse, routes
from vmi.data.ibportal.client import Portal, PortalError
from vmi.data.models import Fundamentals

KEY_FUND = "ibportal:fund:v1:{}"
KEY_EST = "ibportal:est:v1:{}"
KEY_CONID = "ibportal:conid:{}"
CONID_TTL = 180 * 24 * 3600  # conids are permanent identifiers
NO_IB_DATA = "IB has no data for this stock (HTTP 404 MISSING_DATA); other sources cover it"
KNOWN_CONIDS = {"AAPL": 265598, "MSFT": 272093}  # check() only, when TWS is down (confirmed on real runs 2026-11-06)


def _ttl() -> int:
    return get_settings().ttl_ib_portal


# ------------------------------------------------------------------------------------------ cache reads
def cached_fundamentals(ticker: str) -> Fundamentals | None:
    hit = get_cache().get(KEY_FUND.format(ticker.upper()), _ttl())
    return Fundamentals.from_dict(hit) if hit else None


def cached_estimates(ticker: str) -> dict:
    return get_cache().get(KEY_EST.format(ticker.upper()), _ttl()) or {}


# ------------------------------------------------------------------------------------------------ sync
def sync(tickers: Iterable[str], portal: Portal, *, statements: bool = True, analyst: bool = True,
         workers: int | None = None, progress: Callable[[str], None] = lambda msg: None) -> dict:
    """Refresh IB data for many tickers on one logged-in Portal. One task per ticker (key metrics + 6 statements),
    run on `workers` threads when the Portal allows it; analyst `data_list` fields are batched 50 conids per call."""
    from vmi.data.fundamentals import invalidate

    syms = sorted({t.upper() for t in tickers})
    report = {"tickers": len(syms), "conids": 0, "analyst": 0, "statements": 0, "failed": {}}
    ids = _cached_conids(syms)
    report["conids"] = len(ids)
    report["failed"].update({s: "no contract id (run once with IB Gateway up)" for s in syms if s not in ids})
    listed = (parse.parse_analyst(portal.data_list(list(ids.values()), [n for n, _, _ in routes.ANALYST_FIELDS]))
              if analyst and ids else {})
    stop, lock, done = threading.Event(), threading.Lock(), [0]

    def one(sym: str, cid: int) -> None:
        if stop.is_set():
            return
        try:
            if analyst:
                values = dict(listed.get(cid) or {})
                for k, v in parse.parse_key_metrics(portal.key_metrics(cid)).items():
                    values.setdefault(k, v)
                if values:
                    get_cache().set(KEY_EST.format(sym), values)
                    with lock:
                        report["analyst"] += 1
            if statements:
                f = _fetch_statements(portal, sym, cid)
                if f is None:
                    with lock:
                        report["failed"][sym] = "no usable statements"
                else:
                    get_cache().set(KEY_FUND.format(sym), f.to_dict())
                    invalidate(sym)  # the merged fundamentals cache must pick up the new IB data
                    with lock:
                        report["statements"] += 1
        except PortalError as exc:
            if exc.status == 401:
                stop.set()  # the session ended: stop instead of failing every remaining ticker
            with lock:
                report["failed"][sym] = NO_IB_DATA if "MISSING_DATA" in str(exc) else str(exc)
        except Exception as exc:  # a parser surprise on one stock must not end a 500-stock run
            with lock:
                report["failed"][sym] = f"{type(exc).__name__}: {exc}"[:200]
        with lock:
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(ids):
                progress(f"{done[0]}/{len(ids)} tickers")

    n = (workers or get_settings().ib_portal_workers) if portal.parallel else 1
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        for fut in as_completed([ex.submit(one, s, c) for s, c in sorted(ids.items())]):
            fut.result()
    report["seconds"] = round(time.monotonic() - started, 1)
    report["workers"] = n
    if stop.is_set():
        report["stopped"] = "session ended (HTTP 401): log in again and re-run; finished tickers are cached"
    return report


def _fetch_statements(p: Portal, ticker: str, conid: int) -> Fundamentals | None:
    f = Fundamentals(ticker=ticker.upper(), source="ib_portal")
    f.meta["ib_conid"] = conid
    for statement in routes.STATEMENTS:
        parse.parse_financials(p.financials(conid, statement, annual=True), f)
        try:
            parse.parse_financials(p.financials(conid, statement, annual=False), f, quarterly=True)
        except PortalError as exc:
            if exc.status == 401:
                raise  # quarterly data is optional, a lost session is not
    return parse.finalize(f)


def login_and_sync(tickers: list[str], say: Callable[[str], None] = print, workers: int | None = None,
                   statements: bool = True) -> dict:
    """The whole refresh, shared by the CLI and the app's job: contract ids (TWS) → browser login → parallel sync.
    Raises PortalError when no ticker has a contract id."""
    from vmi.data.ibportal.browser import login

    say("Looking up contract ids not cached yet via IB Gateway (max ~1 min) ...")
    _, missing = prefetch_conids(tickers, say=say)
    if len(missing) == len({t.upper() for t in tickers}):
        raise PortalError("no contract ids: start IB Gateway (live login, API on) and try again")
    if missing:
        say(f"{len(missing)} tickers have no contract id yet and are skipped (re-run with IB Gateway answering): "
            f"{', '.join(missing[:10])}{' ...' if len(missing) > 10 else ''}")
    say("Opening the browser: sign in to IBKR with your PAPER username ...")
    with login(say=say) as portal:
        return sync(tickers, portal, statements=statements, workers=workers, progress=say)


# ----------------------------------------------------------------------------------------------- check
def check(tickers: Iterable[str], out_dir: Path, portal: Portal) -> dict:
    """Call every route for each ticker, save raw JSON to out_dir/<TICKER>.json, report what parsed and which
    IB row labels parse.LABELS does not map yet."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"mode": "fast (httpx)" if portal.parallel else "browser"}
    syms = [t.upper() for t in tickers]
    _, missing = prefetch_conids(syms)
    ids = {**{s: KNOWN_CONIDS[s] for s in missing if s in KNOWN_CONIDS}, **_cached_conids(syms)}
    for sym in syms:
        cid = ids.get(sym)
        entry: dict = {"conid": cid}
        report[sym] = entry
        if cid is None:
            continue
        calls = {f"{st}_{'annual' if a else 'quarter'}": (lambda st=st, a=a: portal.financials(cid, st, a))
                 for st in routes.STATEMENTS for a in (True, False)}
        fields = [n for n, _, _ in routes.ANALYST_FIELDS] + list(routes.PROBE_FIELDS)
        calls.update({"data_list": lambda: portal.data_list([cid], fields),
                      "key_metrics": lambda: portal.key_metrics(cid), "key_ratios": lambda: portal.key_ratios(cid)})
        raw: dict = {}
        for name, call in calls.items():
            try:
                raw[name] = call()
                entry[name] = "ok"
            except PortalError as exc:
                raw[name] = {"error": str(exc)}
                entry[name] = str(exc)
        f = Fundamentals(ticker=sym, source="ib_portal")
        for st in routes.STATEMENTS:
            parse.parse_financials(raw.get(f"{st}_annual"), f)
        f = parse.finalize(f)
        entry["parsed_annual"] = {c: len(v) for c, v in f.annual.items()} if f else {}
        data_list = raw.get("data_list") if isinstance(raw.get("data_list"), list) else []
        entry["analyst"] = {**parse.parse_key_metrics(raw.get("key_metrics")), **parse.parse_analyst(data_list).get(cid, {})}
        entry["unmapped_rows"] = _unmapped_rows(raw)
        (out_dir / f"{sym}.json").write_text(json.dumps(raw, indent=1, default=str))
        entry["raw_file"] = str(out_dir / f"{sym}.json")
    return report


def _unmapped_rows(raw: dict) -> dict[str, list[str]]:
    """Per annual statement: row labels IB returned that LABELS does not map (to extend parse.LABELS from evidence)."""
    out: dict[str, list[str]] = {}
    for st in routes.STATEMENTS:
        payload = raw.get(f"{st}_annual")
        table = payload.get("table") if isinstance(payload, dict) else None
        if isinstance(table, dict):
            out[st] = [str(label) for label, _ in parse._table_rows(table) if not parse.concept_for(label)][:60]
    return out


# ---------------------------------------------------------------------------------------- contract ids
def _cached_conids(tickers: list[str]) -> dict[str, int]:
    cache, out = get_cache(), {}
    for t in tickers:
        if hit := cache.get(KEY_CONID.format(t), CONID_TTL):
            out[t] = int(hit)
    return out


def prefetch_conids(tickers: Iterable[str], say: Callable[[str], None] = print) -> tuple[int, list[str]]:
    """Look up and cache the conids of tickers not cached yet via the TWS API (bounded to ~1 minute).
    Returns (looked up now, tickers that still have no conid). Never raises: the caller decides whether to go on.
    (The portal's own symbol search needs a trading session: /iserver/secdef/search → "no bridge", 2026-11-06.)"""
    syms = sorted({t.upper() for t in tickers})
    todo = [s for s in syms if s not in _cached_conids(syms)]
    found = 0
    if todo:
        try:
            found = len(_tws_conids(todo, say=say))
        except PortalError as exc:
            say(f"Contract ids: {exc}")
    return found, [s for s in syms if s not in _cached_conids(syms)]


def _tws_conids(symbols: list[str], wait: float = 15.0, say: Callable[[str], None] = print) -> dict[str, int]:
    """{SYMBOL: conid} from the running IB Gateway/TWS connection (the app's normal one); cached."""
    if not symbols:
        return {}
    from vmi.data.ib import gateway

    gw = gateway()
    gw.start()
    deadline = time.monotonic() + wait
    while not gw.connected and time.monotonic() < deadline:
        time.sleep(0.5)
    if not gw.connected:
        info = gw.info()
        raise PortalError(f"symbol lookup needs IB Gateway/TWS reachable on {info['host']}. Ports tried: "
                          f"{info.get('port_errors') or info['tried_ports']}. In IB Gateway check Configure > Settings > "
                          "API > Settings (socket port, 'Allow connections from localhost only'); force a port with "
                          "VMI_IB_PORT=<port>")
    found = gw.conids(symbols, progress=say)
    for t, cid in found.items():
        get_cache().set(KEY_CONID.format(t), cid)
    return found
