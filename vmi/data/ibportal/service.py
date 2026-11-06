"""Cache-aware IB Portal operations. This is what the rest of the app calls.

    fundamentals(ticker)    statements from cache, else live from the gateway        → Fundamentals | None
    estimates(ticker)       analyst fields from cache, else live                      → {"eps_growth_5y": …}
    sync(tickers)           bulk refresh for a universe in one gateway session        → report dict
    check(tickers, out)     diagnostics: session, conid, every route, raw JSON dumps   → report dict

Cache keys and the TTL are defined here and nowhere else. Live calls raise PortalError; callers
(vmi.data.ib_fundamentals) decide what to do with a refusal (circuit breaker).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Iterable

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.ibportal import parse, routes
from vmi.data.ibportal.client import Portal, PortalError, base_url
from vmi.data.models import Fundamentals

KEY_FUND = "ibportal:fund:v1:{}"
KEY_EST = "ibportal:est:v1:{}"
KEY_CONID = "ibportal:conid:{}"
CONID_TTL = 180 * 24 * 3600  # conids are permanent identifiers
KNOWN_CONIDS = {"AAPL": 265598, "MSFT": 272093}  # used only by check() when the contract route fails (confirmed on a real run 2026-11-06)


def enabled() -> bool:
    return bool(base_url())


def _ttl() -> int:
    return get_settings().ttl_ib_portal


# ------------------------------------------------------------------------------------------ cache reads
def cached_fundamentals(ticker: str) -> Fundamentals | None:
    hit = get_cache().get(KEY_FUND.format(ticker.upper()), _ttl())
    return Fundamentals.from_dict(hit) if hit else None


def cached_estimates(ticker: str) -> dict:
    return get_cache().get(KEY_EST.format(ticker.upper()), _ttl()) or {}


# ------------------------------------------------------------------------------------------- live reads
def fundamentals(ticker: str, *, live: bool = True, portal: Portal | None = None) -> Fundamentals | None:
    """Cached statements, else (live=True) fetch from the gateway and cache them."""
    if (hit := cached_fundamentals(ticker)) is not None or not live:
        return hit
    with _session(portal) as p:
        cid = _conids(p, [ticker]).get(ticker.upper())
        return _store_fundamentals(ticker, _fetch_statements(p, ticker, cid)) if cid else None


def estimates(ticker: str, *, live: bool = True, portal: Portal | None = None) -> dict:
    """Cached analyst fields, else (live=True) fetch from the gateway and cache them."""
    if (hit := cached_estimates(ticker)) or not live:
        return hit
    with _session(portal) as p:
        return _fetch_analyst(p, _conids(p, [ticker])).get(ticker.upper(), {})


def sync(tickers: Iterable[str], *, statements: bool = True, analyst: bool = True,
         portal: Portal | None = None, progress: Callable[[str], None] = lambda msg: None) -> dict:
    """Refresh IB data for many tickers in one session. Analyst fields are batched (50 conids per call)."""
    from vmi.data.fundamentals import invalidate

    syms = sorted({t.upper() for t in tickers})
    report = {"tickers": len(syms), "conids": 0, "analyst": 0, "statements": 0, "failed": {}}
    with _session(portal) as p:
        ids = _conids(p, syms)
        report["conids"] = len(ids)
        report["failed"].update({s: "no US stock conid" for s in syms if s not in ids})
        if analyst:
            report["analyst"] = len(_fetch_analyst(p, ids))
            progress(f"analyst fields: {report['analyst']}/{len(ids)}")
        for i, (sym, cid) in enumerate(sorted(ids.items()), 1):
            if not statements:
                break
            try:
                if _store_fundamentals(sym, _fetch_statements(p, sym, cid)) is not None:
                    report["statements"] += 1
                    invalidate(sym)  # the merged fundamentals cache must pick up the new IB data
                else:
                    report["failed"][sym] = "no usable statements"
            except PortalError as exc:
                if exc.status == 401:
                    raise  # the session ended: stop instead of failing every remaining ticker
                report["failed"][sym] = str(exc)
            if i % 25 == 0 or i == len(ids):
                progress(f"statements: {i}/{len(ids)}")
    return report


# ---------------------------------------------------------------------------------------------- check
def check(tickers: Iterable[str], out_dir: Path, portal: Portal | None = None) -> dict:
    """Try every route for each ticker, save raw JSON to out_dir/<TICKER>.json, and report what parsed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"gateway": base_url()}
    with _session(portal, require=False) as p:
        try:
            report["session"] = {"ok": True, "user": p.session().get("USER_NAME", "")}
        except PortalError as exc:
            report["session"] = {"ok": False, "error": str(exc)}
            if exc.status == 401:
                return report  # not logged in: nothing else can work. Otherwise keep probing the other routes.
        for sym in [t.upper() for t in tickers]:
            entry: dict = {}
            report[sym] = entry
            try:
                cid = entry["conid"] = _conids(p, [sym]).get(sym)
            except PortalError as exc:
                entry["conid"] = str(exc)
                cid = KNOWN_CONIDS.get(sym)  # still probe the fundamentals routes for a well-known ticker
                entry["conid_fallback"] = cid
            if cid is None:
                continue
            raw: dict = {}
            # one entry per route: name → zero-argument call (default args pin the loop variables)
            calls = {f"{st}_{'annual' if a else 'quarter'}": (lambda st=st, a=a: p.financials(cid, st, a))
                     for st in routes.STATEMENTS for a in (True, False)}
            fields = [n for n, _, _ in routes.ANALYST_FIELDS] + list(routes.PROBE_FIELDS)
            calls.update({"data_list": lambda: p.data_list([cid], fields),
                          "key_metrics": lambda: p.key_metrics(cid), "key_ratios": lambda: p.key_ratios(cid)})
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
            entry["analyst"] = parse.parse_analyst(raw.get("data_list") if isinstance(raw.get("data_list"), list)
                                                   else []).get(cid, {})
            entry["unmapped_rows"] = _unmapped_rows(raw)
            entry["fin_trends"] = _fin_trends_sample(p, cid, raw)
            entry["short_series_rows"] = _short_rows(raw, f) if f else {}
            kr = json.dumps(raw.get("key_ratios"), default=str)
            entry["key_ratios_head"] = kr[:700]
            km_raw = raw.get("key_metrics")
            entry["key_metrics_values"] = {str(r.get("field_name")): r.get("display_value") for r in km_raw
                                           if isinstance(r, dict)} if isinstance(km_raw, list) else None
            entry["data_list_values"] = parse.field_values(raw.get("data_list") if isinstance(raw.get("data_list"), list) else [])
            km = raw.get("key_metrics")
            entry["key_metrics_fields"] = sorted({str(r.get("field_name")) for r in km if isinstance(r, dict)})[:80] if isinstance(km, list) else None
            (out_dir / f"{sym}.json").write_text(json.dumps(raw, indent=1, default=str))
            entry["raw_file"] = str(out_dir / f"{sym}.json")
    return report


# ------------------------------------------------------------------------------------------- internals
def _fin_trends_sample(p: Portal, conid: int, raw: dict) -> dict:
    """Analyst-estimate rows (hasEsimates) → {row: [[fiscal_year, actual, estimate], …]} digest of fin_trends."""
    table = (raw.get("income_annual") or {}).get("table") if isinstance(raw.get("income_annual"), dict) else None
    rows = [r for r in (table or {}).get("rows", []) if isinstance(r, dict) and r.get("hasEsimates") and r.get("search_id")]
    out: dict = {}
    for r in rows[:6]:
        name = str(r.get("metric_name"))
        try:
            data = p.fin_trends(conid, r["search_id"])
        except PortalError as exc:
            out[name] = str(exc)[:200]
            continue
        raw.setdefault("fin_trends", {})[name] = data
        periods = (data or {}).get("periods") if isinstance(data, dict) else None
        out[name] = [[x.get("fiscal_year"), x.get("actual"), x.get("estimate")] for x in periods or []
                     if isinstance(x, dict)] or str(data)[:200]
    return out or {"none": "no income row had hasEsimates + search_id"}


def _short_rows(raw: dict, f: Fundamentals) -> dict[str, list]:
    """Mapped concepts with fewer than 4 annual points → the raw cells of their rows (why are periods missing?)."""
    most = max((len(v) for v in f.annual.values()), default=0)
    short = {c for c, v in f.annual.items() if len(v) < most}
    out: dict[str, list] = {}
    for st in routes.STATEMENTS:
        payload = raw.get(f"{st}_annual")
        table = payload.get("table") if isinstance(payload, dict) else None
        for label, cells in (parse._table_rows(table) if isinstance(table, dict) else []):
            if parse.concept_for(label) in short:
                out[f"{st}:{label}"] = [[c[0][0] if c[0] else None, c[1]] for c in cells]
    return out


def _unmapped_rows(raw: dict) -> dict[str, list[str]]:
    """Per annual statement: row labels IB returned that LABELS does not map (to extend parse.LABELS from evidence)."""
    out: dict[str, list[str]] = {}
    for st in routes.STATEMENTS:
        table = (raw.get(f"{st}_annual") or {}).get("table") if isinstance(raw.get(f"{st}_annual"), dict) else None
        if isinstance(table, dict):
            out[st] = [str(label) for label, _ in parse._table_rows(table) if not parse.concept_for(label)][:60]
    return out



_validated_until: dict[str, float] = {}  # gateway root → time until which the login is known to be valid
SESSION_MEMO_S = 60


class _session:
    """Context manager: reuse the caller's Portal, or open a new one; validate the login (memoised 60 s)."""

    def __init__(self, portal: Portal | None, require: bool = True):
        self.portal, self.own, self.require = portal, portal is None, require

    def __enter__(self) -> Portal:
        if self.own:
            self.portal = Portal()
        if self.require and time.time() >= _validated_until.get(self.portal.base, 0):
            try:
                self.portal.session()
            except PortalError:
                self.__exit__()
                raise
            _validated_until[self.portal.base] = time.time() + SESSION_MEMO_S
        return self.portal

    def __exit__(self, *exc) -> None:
        if self.own and self.portal is not None:
            self.portal.close()


def _conids(p: Portal, tickers: list[str]) -> dict[str, int]:
    """{TICKER: conid}: cached conids first, one batched lookup for the rest."""
    cache, out, missing = get_cache(), {}, []
    for t in (t.upper() for t in tickers):
        hit = cache.get(KEY_CONID.format(t), CONID_TTL)
        if hit:
            out[t] = int(hit)
        else:
            missing.append(t)
    if missing:
        # The portal site has no symbol lookup that works without a trading session (/iserver/secdef/search answered
        # "no bridge", 2026-11-06), so a browser login resolves symbols through the TWS API connection instead.
        for t, cid in (_tws_conids(missing) if p.direct else p.conids(missing)).items():
            cache.set(KEY_CONID.format(t), cid)
            out[t] = cid
    return out


def _tws_conids(symbols: list[str], wait: float = 15.0) -> dict[str, int]:
    """{SYMBOL: conid} from the running IB Gateway/TWS connection (the app's normal one)."""
    from vmi.data.ib import gateway

    gw = gateway()
    gw.start()
    deadline = time.monotonic() + wait
    while not gw.connected and time.monotonic() < deadline:
        time.sleep(0.5)
    if not gw.connected:
        raise PortalError("symbol lookup needs IB Gateway/TWS running (API enabled): " + str(gw.info().get("last_error")))
    out = {}
    for s in symbols:
        try:
            out[s] = gw.conid(s)
        except Exception:
            pass  # unknown to IB: omitted, like the gateway lookup
    return out


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


def _store_fundamentals(ticker: str, f: Fundamentals | None) -> Fundamentals | None:
    if f is not None:
        get_cache().set(KEY_FUND.format(ticker.upper()), f.to_dict())
    return f


def _fetch_analyst(p: Portal, ids: dict[str, int]) -> dict[str, dict]:
    if not ids:
        return {}
    by_conid = parse.parse_analyst(p.data_list(list(ids.values()), [n for n, _, _ in routes.ANALYST_FIELDS]))
    out = {}
    for sym, cid in ids.items():
        values = dict(by_conid.get(cid) or {})
        try:  # one extra call per stock: the key metrics carry the consensus growth rate (see routes.KEY_METRIC_FIELDS)
            for k, v in parse.parse_key_metrics(p.key_metrics(cid)).items():
                values.setdefault(k, v)
        except PortalError as exc:
            if exc.status == 401:
                raise
        if values:
            out[sym] = values
    for sym, values in out.items():
        get_cache().set(KEY_EST.format(sym), values)
    return out
