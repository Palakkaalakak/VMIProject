"""IBKR Client Portal Web API — the Fundamentals Explorer backend (financial statements, key ratios).

Research (2026-11), correcting the `PossibleIBFundamentalFix` note:
  * TWS itself does NOT expose a local REST server. The Web API is served locally by the separate
    **Client Portal Gateway** (Java `clientportal.gw`, or the IBeam docker image), default
    https://localhost:5000, after a browser login. Set `VMI_IB_CP_URL=https://localhost:5000`.
  * There is no `/mofw/...` route. The fundamentals routes used by IB's own portal (and wrapped by
    e.g. areed1192/interactive-broker-python-api) are:
        GET /v1/api/tws.proxy/fundamentals/financials/{conid}?type=income|balance|cash&annual=true|false
        GET /v1/api/fundamentals/financials/{conid}            (same params; older alias, tried second)
        GET /v1/api/fundamentals/landing/{conid}?widgets=key_ratios,...
        GET /v1/api/iserver/fundamentals/{conid}/summary
  * Ticker → conid: GET /v1/api/trsrv/stocks?symbols=AAPL (official), falling back to
    /iserver/secdef/search. Session: GET /iserver/auth/status, keep-alive POST /tickle.
  * These routes are undocumented, so the response schema is not guaranteed. The parser below is
    schema-tolerant (finds labelled rows + period columns anywhere in the JSON), maps labels onto our
    concepts, and `harmonize()` fixes units/period-ends against SEC. Run
        python -m vmi.data.ib_portal AAPL
    next to a logged-in gateway to check the session and dump raw responses to data/ib_portal_samples/.

Every failure trips the shared circuit breaker in `ib_fundamentals` ("cp" path), so scans never stall.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from vmi.config import get_settings
from vmi.data.cache import get_cache
from vmi.data.models import Fundamentals, Point

log = logging.getLogger("vmi.ib_portal")

FIN_PATHS = ("/tws.proxy/fundamentals/financials/{conid}", "/fundamentals/financials/{conid}")
STATEMENTS = ("income", "balance", "cash")

# Portal/Refinitiv row labels → concept (lower-case, punctuation-insensitive match).
LABELS = {
    "total revenue": "revenue", "revenue": "revenue", "total revenues": "revenue", "net sales": "revenue",
    "cost of revenue total": "cost_of_revenue", "cost of revenue": "cost_of_revenue",
    "gross profit": "gross_profit", "operating income": "operating_income",
    "total operating income": "operating_income",
    "net income before taxes": "pretax_income", "income before tax": "pretax_income",
    "provision for income taxes": "income_tax", "income tax": "income_tax",
    "net income": "net_income", "net income to common": "net_income",
    "net income available to common shareholders": "net_income",
    "diluted weighted average shares": "shares_diluted", "diluted shares outstanding": "shares_diluted",
    "diluted eps excluding extraordinary items": "eps_diluted", "diluted eps excluding extraord items": "eps_diluted",
    "diluted eps": "eps_diluted", "diluted normalized eps": "eps_diluted_norm",
    "dps common stock primary issue": "dps", "dividends per share": "dps",
    "interest expense": "interest_expense", "interest expense net non operating": "interest_expense",
    "depreciation amortization": "d_and_a", "depreciation depletion": "d_and_a",
    "cash from operating activities": "cfo", "operating cash flow": "cfo",
    "capital expenditures": "capex", "total cash dividends paid": "dividends_paid",
    "issuance retirement of stock net": "buybacks_net",
    "cash": "cash", "cash equivalents": "cash", "cash and short term investments": "cash_and_st",
    "total current assets": "current_assets", "total current liabilities": "current_liabilities",
    "total assets": "total_assets", "total liabilities": "total_liabilities", "total equity": "equity",
    "total stockholders equity": "equity", "total shareholders equity": "equity",
    "long term debt": "lt_debt", "total long term debt": "lt_debt",
    "notes payable short term debt": "st_debt", "current port of lt debt capital leases": "st_debt_cur",
    "goodwill net": "goodwill", "intangibles net": "intangibles",
    "total receivables net": "receivables", "accounts receivable trade net": "receivables",
    "total inventory": "inventory", "accounts payable": "payables",
    "total common shares outstanding": "shares_outstanding",
}
COA = {"RTLR": "revenue", "SREV": "revenue", "SGRP": "gross_profit", "SOPI": "operating_income",
       "EIBT": "pretax_income", "TTAX": "income_tax", "NINC": "net_income", "SDWS": "shares_diluted",
       "SDBF": "eps_diluted", "DDPS1": "dps", "STIE": "interest_expense", "OTLO": "cfo", "SCEX": "capex",
       "SDED": "d_and_a", "FCDP": "dividends_paid", "ACAE": "cash", "SCSI": "cash_and_st",
       "ATCA": "current_assets", "LTCL": "current_liabilities", "ATOT": "total_assets",
       "LTLL": "total_liabilities", "QTLE": "equity", "LTTD": "lt_debt", "LSTD": "st_debt",
       "AGWI": "goodwill", "AINT": "intangibles", "ATRC": "receivables", "AITL": "inventory",
       "LAPB": "payables", "QTCO": "shares_outstanding"}
PER_SHARE = {"eps_diluted", "eps_diluted_norm", "dps"}
INSTANTS = ("cash", "cash_and_st", "current_assets", "current_liabilities", "total_assets",
            "total_liabilities", "equity", "lt_debt", "st_debt", "goodwill", "intangibles", "receivables",
            "inventory", "payables", "shares_outstanding")
ABS = {"capex", "dividends_paid", "interest_expense"}
UNIT_WORDS = {"thousand": 1e3, "thousands": 1e3, "k": 1e3, "million": 1e6, "millions": 1e6, "m": 1e6,
              "billion": 1e9, "billions": 1e9, "b": 1e9, "units": 1.0, "u": 1.0}
LABEL_KEYS = ("title", "label", "name", "description", "item", "lineItem", "line_item", "desc")
CODE_KEYS = ("coaCode", "code", "id", "coa")
VALUE_KEYS = ("values", "data", "periods", "value_list", "vals")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"), 1)}


# --------------------------------------------------------------------------------------- client
def base_url() -> str:
    """Normalise VMI_IB_CP_URL: accept https://localhost:5000, …/v1/api or …/v1/api/."""
    b = (get_settings().ib_cp_url or "").strip().rstrip("/")
    if not b:
        return ""
    if not b.startswith("http"):
        b = "https://" + b
    return b if b.endswith("/v1/api") else b + "/v1/api"


class PortalError(RuntimeError):
    pass


class Portal:
    """Thin session wrapper. `transport` lets tests inject httpx.MockTransport."""

    def __init__(self, base: str | None = None, transport=None, timeout: float = 15.0):
        import httpx

        self.base = base if base is not None else base_url()
        if not self.base:
            raise PortalError("VMI_IB_CP_URL not set")
        s = get_settings()
        self.cl = httpx.Client(base_url=self.base, verify=s.ib_cp_verify, timeout=timeout,
                               transport=transport, headers={"User-Agent": "vmi-toolkit"})

    def close(self) -> None:
        self.cl.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def get(self, path: str, **params):
        r = self.cl.get(path, params=params or None)
        if r.status_code == 401:
            raise PortalError("401 not authenticated — log in to the Client Portal Gateway in a browser")
        if r.status_code != 200:
            raise PortalError(f"{path} → {r.status_code} {r.text[:120]}")
        return r.json() if r.content else None

    def authenticated(self) -> bool:
        try:
            self.cl.post("/tickle")
        except Exception:  # keep-alive is best effort
            pass
        st = self.get("/iserver/auth/status") or {}
        return bool(st.get("authenticated"))

    def conid(self, symbol: str) -> int | None:
        sym = symbol.upper()
        key = f"ibcp:conid:{sym}"
        hit = get_cache().get(key, 90 * 24 * 3600)
        if hit:
            return int(hit)
        cid = pick_conid(self.get("/trsrv/stocks", symbols=sym), sym)
        if cid is None:
            r = self.cl.post("/iserver/secdef/search", json={"symbol": sym, "secType": "STK", "name": False})
            cid = pick_conid(r.json() if r.status_code == 200 else None, sym)
        if cid is not None:
            get_cache().set(key, cid)
        return cid

    def financials(self, conid: int, typ: str, annual: bool = True):
        last: Exception | None = None
        for p in FIN_PATHS:
            try:
                return self.get(p.format(conid=conid), type=typ, annual=str(annual).lower())
            except PortalError as exc:
                last = exc
        raise last or PortalError("no financials route answered")

    def landing(self, conid: int, widgets: str = "key_ratios"):
        return self.get(f"/fundamentals/landing/{conid}", widgets=widgets)

    def summary(self, conid: int):
        return self.get(f"/iserver/fundamentals/{conid}/summary")


def pick_conid(payload, symbol: str) -> int | None:
    """Choose the primary US stock conid from /trsrv/stocks or /iserver/secdef/search output."""
    if not payload:
        return None
    if isinstance(payload, dict):  # /trsrv/stocks → {SYM: [{name, assetClass, contracts:[…]}]}
        entries = payload.get(symbol) or payload.get(symbol.upper()) or []
        best = None
        for e in entries:
            if e.get("assetClass", "STK") != "STK":
                continue
            for c in e.get("contracts") or []:
                if c.get("isUS") and c.get("conid"):
                    return int(c["conid"])
                best = best or c.get("conid")
        return int(best) if best else None
    for e in payload:  # /iserver/secdef/search → [{conid, symbol, description, sections:[…]}]
        if not isinstance(e, dict) or not e.get("conid"):
            continue
        if (e.get("symbol") or symbol).upper() != symbol:
            continue
        secs = [s.get("secType") for s in e.get("sections") or []]
        desc = (e.get("description") or "").upper()
        if (not secs or "STK" in secs) and (not desc or any(x in desc for x in ("NASDAQ", "NYSE", "ARCA", "BATS", "AMEX"))):
            return int(e["conid"])
    first = next((e for e in payload if isinstance(e, dict) and e.get("conid")), None)
    return int(first["conid"]) if first else None


# --------------------------------------------------------------------------------------- parser
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("&", " "))).strip()


_NLABELS = {_norm(k): v for k, v in LABELS.items()}


def concept_for(label: str | None, code: str | None = None) -> str | None:
    if code and str(code).upper() in COA:
        return COA[str(code).upper()]
    return _NLABELS.get(_norm(label)) if label else None


def parse_period(v) -> tuple[str, int | None] | None:
    """Period descriptor → (ISO end or 'FY<year>' placeholder, fiscal year)."""
    if isinstance(v, dict):
        for k in ("endDate", "end_date", "end", "date", "periodEnd", "period", "fiscalPeriod", "label",
                  "title", "name", "year", "fiscalYear", "fy"):
            if v.get(k) not in (None, ""):
                r = parse_period(v[k])
                if r:
                    fy = v.get("fiscalYear") or v.get("fy") or v.get("year")
                    return (r[0], int(fy) if str(fy or "").isdigit() else r[1])
        return None
    s = str(v).strip()
    if not s:
        return None
    if isinstance(v, (int, float)) and 1e11 < v < 1e14:  # epoch millis
        d = date.fromtimestamp(v / 1000)
        return d.isoformat(), d.year
    m = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]}", int(m[1])
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}", int(m[3])
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(?:(\d{1,2}),?\s+)?(\d{4}|'\d{2})\b", s)
    if m and m[1].lower() in MONTHS:
        yy = m[3].lstrip("'")
        y = int(yy) + (2000 if len(yy) == 2 else 0)
        mo = MONTHS[m[1].lower()]
        day = int(m[2]) if m[2] else _month_end(y, mo)
        return f"{y}-{mo:02d}-{day:02d}", y
    m = re.search(r"(?:FY|Q[1-4])?\s*'?(\d{4})\b", s)
    if m and 1980 < int(m[1]) < 2100:
        return f"FY{m[1]}", int(m[1])
    return None


def _month_end(y: int, m: int) -> int:
    from calendar import monthrange
    return monthrange(y, m)[1]


def _num(v) -> float | None:
    if isinstance(v, dict):
        for k in ("value", "v", "amount", "val", "raw"):
            if k in v:
                return _num(v[k])
        return None
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    mult = 1.0
    if s and s[-1].upper() in "KMB" and re.fullmatch(r"-?[\d.]+[KMBkmb]", s):
        mult, s = {"K": 1e3, "M": 1e6, "B": 1e9}[s[-1].upper()], s[:-1]
    try:
        x = float(s) * mult
    except ValueError:
        return None
    return -x if neg else x


def _find_units(node) -> float | None:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            for k, v in n.items():
                if k.lower() in ("units", "unit", "scale", "currencyunits", "unitsconvertedto") and isinstance(v, str):
                    u = UNIT_WORDS.get(v.strip().lower()) or UNIT_WORDS.get(v.strip().lower().split()[-1])
                    if u:
                        return u
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(n, list):
            stack.extend(x for x in n if isinstance(x, (dict, list)))
    return None


def _find_columns(node) -> list | None:
    """First list of ≥2 period descriptors (columns/headers/periods) anywhere in the payload."""
    stack = [node]
    while stack:
        n = stack.pop(0)
        if isinstance(n, dict):
            for k, v in n.items():
                if k.lower() in ("columns", "headers", "periods", "dates", "years", "fiscalperiods", "header") \
                        and isinstance(v, list) and len(v) >= 2:
                    parsed = [parse_period(x) for x in v]
                    if sum(p is not None for p in parsed) >= 2:
                        return parsed
            stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
        elif isinstance(n, list):
            stack.extend(x for x in n if isinstance(x, (dict, list)))
    return None


def _rows(node):
    """Yield (label, code, values) for every labelled row found anywhere in the payload."""
    if isinstance(node, list):
        for x in node:
            yield from _rows(x)
        return
    if not isinstance(node, dict):
        return
    label = next((node[k] for k in LABEL_KEYS if isinstance(node.get(k), str)), None)
    code = next((node[k] for k in CODE_KEYS if isinstance(node.get(k), str)), None)
    vals = next((node[k] for k in VALUE_KEYS if isinstance(node.get(k), (list, dict))), None)
    used = None
    if label and vals is not None and _has_numbers(vals):
        used = vals
        yield label, code, vals
    elif label and vals is None:  # flat row: {"title": "Revenue", "2023-09-30": 1.0, "2022-09-24": …}
        dated = {k: v for k, v in node.items() if k not in LABEL_KEYS and parse_period(k) and _num(v) is not None}
        if len(dated) >= 1:
            yield label, code, dated
    for k, v in node.items():
        if isinstance(v, (dict, list)) and v is not used:
            yield from _rows(v)


def _has_numbers(vals) -> bool:
    it = vals.values() if isinstance(vals, dict) else vals
    return any(_num(v) is not None for v in it)


def parse_statement(payload, f: Fundamentals, quarterly: bool = False) -> int:
    """Merge one statement payload into `f`. Returns the number of points added."""
    if payload is None:
        return 0
    cols = _find_columns(payload)
    scale = _find_units(payload)
    if scale:
        f.meta["cp_scale"] = scale
    target = f.quarterly if quarterly else f.annual
    added = 0
    for label, code, vals in _rows(payload):
        concept = concept_for(label, code)
        if not concept:
            continue
        pairs: list[tuple[tuple[str, int | None] | None, float | None]] = []
        if isinstance(vals, dict):
            pairs = [(parse_period(k), _num(v)) for k, v in vals.items()]
        else:
            for i, v in enumerate(vals):
                per = parse_period(v) if isinstance(v, dict) else None
                if per is None and cols and i < len(cols):
                    per = cols[i]
                pairs.append((per, _num(v)))
        series = target.setdefault(concept, [])
        for per, x in pairs:
            if per is None or x is None or (quarterly and per[0].startswith("FY")):
                continue  # a year-only label cannot place a quarter
            if concept in ABS:
                x = abs(x)
            if not any(p.end == per[0] for p in series):
                series.append(Point(end=per[0], value=x, fy=per[1]))
                added += 1
    return added


def _scale_values(f: Fundamentals, k: float) -> None:
    if k == 1.0:
        return
    for d in (f.annual, f.quarterly):
        for c, pts in d.items():
            if c in PER_SHARE:
                continue
            d[c] = [Point(p.end, p.value * k, p.fy) for p in pts]


def finalize(f: Fundamentals) -> Fundamentals | None:
    """Apply explicit units, sort, derive latest/TTM. Returns None when nothing usable was parsed."""
    scale = f.meta.get("cp_scale")
    if scale:
        _scale_values(f, scale)
        f.meta["cp_scaled"] = True
    if "cash" not in f.annual and "cash_and_st" in f.annual:
        f.annual["cash"] = f.annual["cash_and_st"]
    for d in (f.annual, f.quarterly):
        for c in list(d):
            d[c] = sorted((p for p in d[c]), key=lambda p: (p.fy or 0, p.end))
            if not d[c]:
                del d[c]
    for c in INSTANTS:
        src = f.quarterly.get(c) or f.annual.get(c)
        if src:
            f.latest[c] = src[-1].value
    for c in ("revenue", "net_income", "cfo", "capex", "operating_income", "interest_expense", "d_and_a"):
        q = f.quarterly.get(c, [])
        if len(q) >= 4:
            f.ttm[c] = sum(p.value for p in q[-4:])
    for c in f.annual:
        f.provenance[c] = "ib_cp"
    return f if (f.annual.get("revenue") or f.annual.get("net_income")) else None


def harmonize(f: Fundamentals, ref: Fundamentals | None) -> None:
    """Fix unit scale and 'FY<year>' placeholder ends against a reference (SEC) when available.

    Scale is snapped to the power of 1000 that best matches the reference revenue (or net income) of
    a shared fiscal year — a units-only correction, never a fitted transform.
    """
    if not f.meta.get("cp_scaled"):
        k = _ref_scale(f, ref)
        if k is None:  # no reference: statements of listed companies are reported in millions
            rev = [p.value for p in f.annual.get("revenue", [])]
            k = 1e6 if rev and max(abs(x) for x in rev) < 5e7 else 1.0
        _scale_values(f, k)
        for c in f.latest:
            src = f.quarterly.get(c) or f.annual.get(c)
            if src:
                f.latest[c] = src[-1].value
        for c in list(f.ttm):
            f.ttm[c] *= k
        f.meta["cp_scaled"] = True
    ref_end = {}
    if ref is not None:
        for pts in ref.annual.values():
            for p in pts:
                if p.fy:
                    ref_end.setdefault(p.fy, p.end)
    for d in (f.annual, f.quarterly):
        for c, pts in d.items():
            d[c] = [Point(ref_end.get(p.fy, f"{p.fy}-12-31") if p.end.startswith("FY") else p.end, p.value, p.fy)
                    for p in pts]


def _ref_scale(f: Fundamentals, ref: Fundamentals | None) -> float | None:
    if ref is None:
        return None
    for c in ("revenue", "net_income", "total_assets"):
        mine = {p.fy: p.value for p in f.annual.get(c, []) if p.fy and p.value}
        theirs = {p.fy: p.value for p in ref.annual.get(c, []) if p.fy and p.value}
        for fy in sorted(set(mine) & set(theirs), reverse=True):
            ratio = abs(theirs[fy] / mine[fy])
            for k in (1.0, 1e3, 1e6, 1e9):
                if 0.7 < ratio / k < 1.4:
                    return k
    return None


# --------------------------------------------------------------------------------------- public
def fundamentals(ticker: str, portal: Portal | None = None, quarterly: bool = True) -> Fundamentals | None:
    """Financial statements from the portal, or None (caller handles the breaker)."""
    own = portal is None
    p = portal or Portal()
    try:
        if not p.authenticated():
            raise PortalError("gateway session not authenticated — log in at the gateway URL")
        cid = p.conid(ticker)
        if cid is None:
            return None
        f = Fundamentals(ticker=ticker.upper(), source="ib_cp")
        f.meta["ib_conid"] = cid
        raw = {}
        for typ in STATEMENTS:
            raw[f"{typ}_annual"] = p.financials(cid, typ, True)
            parse_statement(raw[f"{typ}_annual"], f)
            if quarterly:
                try:
                    raw[f"{typ}_quarter"] = p.financials(cid, typ, False)
                    parse_statement(raw[f"{typ}_quarter"], f, quarterly=True)
                except PortalError:
                    pass
        try:
            f.meta["ib_key_ratios"] = key_ratios(p.landing(cid, "key_ratios"))
        except PortalError:
            pass
        get_cache().set(f"ibcp:raw:{ticker.upper()}", raw)
        return finalize(f)
    finally:
        if own:
            p.close()


def key_ratios(payload) -> dict:
    """Flatten a key_ratios widget into {normalised label: number}."""
    out: dict = {}
    for label, _code, vals in _rows(payload):
        it = list(vals.values()) if isinstance(vals, dict) else list(vals)
        nums = [x for x in (_num(v) for v in it) if x is not None]
        if nums:
            out[_norm(label)] = nums[-1]
    stack = [payload]
    while stack:  # simple {label: value} pairs
        n = stack.pop()
        if isinstance(n, dict):
            lab = next((n[k] for k in LABEL_KEYS if isinstance(n.get(k), str)), None)
            val = _num(n.get("value")) if "value" in n else None
            if lab and val is not None:
                out.setdefault(_norm(lab), val)
            stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
        elif isinstance(n, list):
            stack.extend(n)
    return out


def estimates_from_ratios(r: dict) -> dict:
    out: dict = {}
    for k, v in r.items():
        if ("long term growth" in k or "lt growth" in k or "ltg" in k.split()) and abs(v) < 200:
            out["eps_growth_5y"] = v / 100 if abs(v) > 1 else v
        elif k == "beta":
            out["beta"] = v
    return out


def main(argv: list[str] | None = None) -> None:
    """Diagnose the gateway and dump raw responses: python -m vmi.data.ib_portal AAPL [MSFT …]."""
    import sys

    syms = (argv if argv is not None else sys.argv[1:]) or ["AAPL"]
    out_dir = get_settings().data_dir / "ib_portal_samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("gateway:", base_url() or "(VMI_IB_CP_URL not set)")
    with Portal() as p:
        print("authenticated:", p.authenticated())
        for s in syms:
            cid = p.conid(s)
            print(f"{s}: conid={cid}")
            if cid is None:
                continue
            dump = {}
            for typ in STATEMENTS:
                for ann in (True, False):
                    try:
                        dump[f"{typ}_{'annual' if ann else 'quarter'}"] = p.financials(cid, typ, ann)
                    except PortalError as exc:
                        dump[f"{typ}_{'annual' if ann else 'quarter'}"] = {"error": str(exc)}
            for name, fn in (("key_ratios", lambda: p.landing(cid)), ("summary", lambda: p.summary(cid))):
                try:
                    dump[name] = fn()
                except PortalError as exc:
                    dump[name] = {"error": str(exc)}
            path = out_dir / f"{s.upper()}.json"
            path.write_text(json.dumps(dump, indent=1, default=str))
            f = Fundamentals(ticker=s.upper(), source="ib_cp")
            for typ in STATEMENTS:
                parse_statement(dump.get(f"{typ}_annual"), f)
            f = finalize(f)
            got = {c: len(v) for c, v in (f.annual.items() if f else [])}
            print(f"  raw → {path}\n  parsed annual concepts: {got or 'NONE — share the JSON so the mapping can be extended'}")


if __name__ == "__main__":
    main()
