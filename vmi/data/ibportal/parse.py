"""Pure parsing helpers for IB Portal payloads: no network, no cache, fully unit-testable.

Entry points:
    pick_conid(payload, symbol)               /trsrv/stocks answer → primary US stock conid
    parse_financials(payload, f, quarterly)   one statement payload → Points added to `f`
    finalize(f)                               after all statements: sort, latest values, TTM, provenance
    harmonize(f, sec)                         units + fiscal-year end dates checked against SEC
    parse_analyst(rows)                       data_list rows → {conid: {"eps_growth_5y": …, "beta": …}}

To map another IB row label onto one of our concepts, add it to LABELS (matching ignores case/punctuation).
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date

from vmi.data.ibportal import routes
from vmi.data.models import Fundamentals, Point

# IB / LSEG row label → our concept name (see vmi.data.models / fundamentals.REQUIREMENTS).
LABELS = {
    # income statement
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
    # cash flow
    "cash from operating activities": "cfo", "operating cash flow": "cfo",
    "capital expenditures": "capex", "total cash dividends paid": "dividends_paid",
    # balance sheet
    "cash": "cash", "cash equivalents": "cash", "cash and short term investments": "cash_and_st",
    "total current assets": "current_assets", "total current liabilities": "current_liabilities",
    "total assets": "total_assets", "total liabilities": "total_liabilities", "total equity": "equity",
    "total stockholders equity": "equity", "total shareholders equity": "equity",
    "long term debt": "lt_debt", "total long term debt": "lt_debt", "notes payable short term debt": "st_debt",
    "goodwill net": "goodwill", "intangibles net": "intangibles",
    "total receivables net": "receivables", "accounts receivable trade net": "receivables",
    "total inventory": "inventory", "accounts payable": "payables",
    "total common shares outstanding": "shares_outstanding",
}
PER_SHARE = {"eps_diluted", "eps_diluted_norm", "dps"}             # never unit-scaled
ABSOLUTE = {"capex", "dividends_paid", "interest_expense"}         # stored as positive outflows
INSTANTS = ("cash", "cash_and_st", "current_assets", "current_liabilities", "total_assets", "total_liabilities",
            "equity", "lt_debt", "st_debt", "goodwill", "intangibles", "receivables", "inventory", "payables",
            "shares_outstanding")
TTM_FLOWS = ("revenue", "net_income", "cfo", "capex", "operating_income", "interest_expense", "d_and_a")
NON_PERIOD_COLUMNS = {"metric_name", "trend", "change"}
UNIT_WORDS = {"thousand": 1e3, "thousands": 1e3, "million": 1e6, "millions": 1e6, "billion": 1e9,
              "billions": 1e9}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"), 1)}


# ------------------------------------------------------------------------------------------------ scalars
def normalise_label(s: str) -> str:
    """'Total Revenue', 'total_revenue' and 'TotalRevenue' all become 'total revenue'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(s))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower().replace("&", " ")).split())


_LABELS = {normalise_label(k): v for k, v in LABELS.items()}


def concept_for(label: str | None) -> str | None:
    return _LABELS.get(normalise_label(label)) if label else None


def to_number(v) -> float | None:
    """'1,234' → 1234 · '(10.5)' → -10.5 · '1.5B' → 1.5e9 · '9.07%' → 9.07 · '-'/'N/A' → None."""
    if isinstance(v, dict):
        return to_number(v.get("value"))
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "").rstrip("%")
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    mult = 1.0
    if re.fullmatch(r"-?[\d.]+[KMBT]", s, re.I):
        mult, s = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1].upper()], s[:-1]
    try:
        x = float(s) * mult
    except ValueError:
        return None
    return -x if negative else x


def parse_period(v) -> tuple[str, int | None] | None:
    """Period label → (ISO end date, fiscal year). A year-only label gives the placeholder 'FY<year>'."""
    if isinstance(v, dict):
        for k in ("endDate", "end_date", "date", "period", "value", "name", "title", "year", "fiscalYear"):
            if v.get(k) not in (None, ""):
                r = parse_period(v[k])
                if r:
                    return r
        return None
    if isinstance(v, (int, float)) and 1e11 < v < 1e14:  # epoch milliseconds
        d = date.fromtimestamp(v / 1000)
        return d.isoformat(), d.year
    s = str(v).strip()
    if m := re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?", s):
        return f"{m[1]}-{m[2]}-{m[3]}", int(m[1])
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s):
        return f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}", int(m[3])
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(?:(\d{1,2}),?\s+)?(\d{4}|'\d{2})\b", s)
    if m and m[1].lower() in MONTHS:
        yy = m[3].lstrip("'")
        year = int(yy) + (2000 if len(yy) == 2 else 0)
        month = MONTHS[m[1].lower()]
        day = int(m[2]) if m[2] else monthrange(year, month)[1]
        return f"{year}-{month:02d}-{day:02d}", year
    if (m := re.search(r"\b(?:FY|Q[1-4])?\s*'?((?:19|20)\d{2})\b", s)) and not is_estimate(s):
        return f"FY{m[1]}", int(m[1])
    return None


def is_estimate(label) -> bool:
    """Column headers for forecasts ('2026E', 'FY2026 Est.', 'Forecast') must never become history."""
    return bool(re.search(r"\d\s*E\b|\b(est|estimate|estimated|forecast|projected|proj)\b", str(label), re.I))


# ------------------------------------------------------------------------------------------------ conid
def pick_conid(payload, symbol: str) -> int | None:
    """/trsrv/stocks → {SYM: [{assetClass, contracts: [{conid, isUS}]}]}: prefer the US listing."""
    entries = (payload or {}).get(symbol.upper()) or [] if isinstance(payload, dict) else []
    fallback = None
    for entry in entries:
        if entry.get("assetClass", "STK") != "STK":
            continue
        for contract in entry.get("contracts") or []:
            if contract.get("conid") and contract.get("isUS"):
                return int(contract["conid"])
            fallback = fallback or contract.get("conid")
    return int(fallback) if fallback else None


# ------------------------------------------------------------------------------------------- statements
def parse_financials(payload, f: Fundamentals, quarterly: bool = False) -> int:
    """Merge one financials payload into `f.annual` (or `f.quarterly`). Returns points added."""
    if not payload:
        return 0
    table = payload.get("table") if isinstance(payload, dict) else None
    rows = _table_rows(table) if isinstance(table, dict) else _generic_rows(payload)
    if scale := _explicit_scale(payload):
        f.meta["ib_portal_scale"] = scale
    target = f.quarterly if quarterly else f.annual
    added = 0
    for label, cells in rows:
        concept = concept_for(label)
        if not concept:
            continue
        series = target.setdefault(concept, [])
        for period, value in cells:
            if period is None or value is None or (quarterly and period[0].startswith("FY")):
                continue  # a year-only label cannot place a quarter
            if concept in ABSOLUTE:
                value = abs(value)
            if all(p.end != period[0] for p in series):
                series.append(Point(end=period[0], value=value, fy=period[1]))
                added += 1
    return added


def _table_rows(table: dict):
    """The Fundamentals Explorer shape: table.columns [{name, value}] + table.rows [{<column name>: value}]."""
    columns = []
    for i, col in enumerate(table.get("columns") or []):
        name, header = col.get("name"), col.get("value")
        if i == 0 or name in NON_PERIOD_COLUMNS or is_estimate(header) or is_estimate(name):
            continue
        period = parse_period(header) or parse_period(name)
        if period:
            columns.append((name, period))
    for row in table.get("rows") or []:
        label = row.get("metric_name") or row.get("metric_name_tag")
        yield label, [(period, to_number(row.get(name))) for name, period in columns]


def _generic_rows(node):
    """Fallback for an unexpected shape: any {label, values[]} or {label, '<period>': value} object."""
    if isinstance(node, list):
        for x in node:
            yield from _generic_rows(x)
        return
    if not isinstance(node, dict):
        return
    label = next((node[k] for k in ("metric_name", "title", "label", "name") if isinstance(node.get(k), str)), None)
    values = node.get("values")
    if label and isinstance(values, list):
        yield label, [(parse_period(v), to_number(v)) for v in values if isinstance(v, dict)]
    elif label:
        cells = [(parse_period(k), to_number(v)) for k, v in node.items() if not is_estimate(k) and parse_period(k)]
        if cells:
            yield label, cells
    for v in node.values():
        if isinstance(v, (dict, list)) and v is not values:
            yield from _generic_rows(v)


def _explicit_scale(payload) -> float | None:
    """Unit declared anywhere in the payload ('units': 'Millions'), else None (then harmonize decides)."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() in ("units", "unit", "scale") and isinstance(v, str):
                    word = v.strip().lower().split()[-1] if v.strip() else ""
                    if word in UNIT_WORDS:
                        return UNIT_WORDS[word]
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            stack.extend(x for x in node if isinstance(x, (dict, list)))
    return None


def _scale_money(f: Fundamentals, k: float) -> None:
    if k == 1.0:
        return
    for d in (f.annual, f.quarterly):
        for c, pts in d.items():
            if c not in PER_SHARE:
                d[c] = [Point(p.end, p.value * k, p.fy) for p in pts]


def _refresh_derived(f: Fundamentals) -> None:
    f.latest = {c: (f.quarterly.get(c) or f.annual[c])[-1].value for c in INSTANTS if f.annual.get(c)}
    f.ttm = {c: sum(p.value for p in f.quarterly[c][-4:]) for c in TTM_FLOWS if len(f.quarterly.get(c, [])) >= 4}


def finalize(f: Fundamentals) -> Fundamentals | None:
    """Call once after all statements were parsed. Returns None when nothing usable was found."""
    if scale := f.meta.get("ib_portal_scale"):
        _scale_money(f, scale)
        f.meta["ib_portal_scaled"] = True
    if "cash" not in f.annual and "cash_and_st" in f.annual:
        f.annual["cash"] = list(f.annual["cash_and_st"])
    for d in (f.annual, f.quarterly):
        for c in [c for c, pts in d.items() if not pts]:
            del d[c]
        for c in d:
            d[c].sort(key=lambda p: (p.fy or 0, p.end))
    _refresh_derived(f)
    f.provenance.update({c: "ib_portal" for c in f.annual})
    return f if (f.annual.get("revenue") or f.annual.get("net_income")) else None


# -------------------------------------------------------------------------------------------- harmonize
def harmonize(f: Fundamentals, ref: Fundamentals | None) -> None:
    """Units and period ends checked against a reference (SEC) — a units-only correction, never a fit.

    Scale: the power of 1000 that best matches the reference revenue / net income / assets of a shared
    fiscal year. Without a reference, statements of listed companies are assumed to be in millions when
    revenue is implausibly small. 'FY<year>' placeholder ends take the reference's end date for that year.
    """
    if not f.meta.get("ib_portal_scaled"):
        k = _reference_scale(f, ref)
        if k is None:
            revenue = [abs(p.value) for p in f.annual.get("revenue", [])]
            k = 1e6 if revenue and max(revenue) < 5e7 else 1.0
        _scale_money(f, k)
        f.meta["ib_portal_scaled"] = True
    ends: dict[int, str] = {}
    for pts in (ref.annual.values() if ref else ()):
        for p in pts:
            if p.fy:
                ends.setdefault(p.fy, p.end)
    for d in (f.annual, f.quarterly):
        for c, pts in d.items():
            d[c] = [Point(ends.get(p.fy, f"{p.fy}-12-31") if p.end.startswith("FY") else p.end, p.value, p.fy)
                    for p in pts]
    _refresh_derived(f)


def _reference_scale(f: Fundamentals, ref: Fundamentals | None) -> float | None:
    if ref is None:
        return None
    for concept in ("revenue", "net_income", "total_assets"):
        mine = {p.fy: p.value for p in f.annual.get(concept, []) if p.fy and p.value}
        theirs = {p.fy: p.value for p in ref.annual.get(concept, []) if p.fy and p.value}
        for fy in sorted(set(mine) & set(theirs), reverse=True):
            ratio = abs(theirs[fy] / mine[fy])
            for k in (1.0, 1e3, 1e6, 1e9):
                if 0.7 < ratio / k < 1.4:
                    return k
    return None


# ---------------------------------------------------------------------------------------------- analyst
def parse_analyst(rows) -> dict[int, dict[str, float]]:
    """data_list rows [{conid, field_name, display_value}] → {conid: {our key: value}} (routes.ANALYST_FIELDS)."""
    spec = {name: (key, unit) for name, key, unit in routes.ANALYST_FIELDS}
    out: dict[int, dict[str, float]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("field_name") not in spec or not row.get("conid"):
            continue
        key, unit = spec[row["field_name"]]
        value = to_number(row.get("display_value"))
        if value is not None:
            out.setdefault(int(row["conid"]), {})[key] = value / 100 if unit == "pct" else value
    return out


def field_values(rows) -> dict[str, str]:
    """[{field_name, display_value}] → {field_name: display_value} (used by the check command's report)."""
    return {r["field_name"]: r.get("display_value") for r in rows or [] if isinstance(r, dict) and r.get("field_name")}
