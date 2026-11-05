"""FDIC BankFind API — regulatory capital ratios (CET1) for US banks (Step 5 bank exception: CET1 > 10%).

Free, official, no key. CET1 is reported per *insured bank subsidiary*; for a holding company we take
its largest insured subsidiary (that is where virtually all risk-weighted assets sit). The holding name
is matched on NAMEHCR. Fields: RBCT1CER = CET1 capital ratio (%), RBCRWAJ = total risk-based ratio (%).
"""
from __future__ import annotations

import re

from vmi.data import http
from vmi.data.cache import get_cache

API = "https://api.fdic.gov/banks"


# FDIC abbreviates holding names ("PNC FINL SVC GROUP INC THE", "U S BCORP", "BANK OF NY MELLON CORP THE");
# both sides are reduced to the same distinctive tokens before matching.
_DROP = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "THE", "HOLDING", "HOLDINGS", "GROUP",
         "GRP", "FINANCIAL", "FINL", "FNCL", "FIN", "SERVICES", "SERVICE", "SVC", "SVCS", "BANCORP", "BCORP",
         "BANCORPORATION", "BANCSHARES", "BSHRS", "NA", "N", "A", "NATIONAL", "ASSOCIATION", "ASSN", "LTD", "PLC"}
_EXPAND = {"NY": "NEW YORK", "AMER": "AMERICA", "INTL": "INTERNATIONAL", "BK": "BANK"}


def _norm(name: str) -> str:
    raw = re.sub(r"[^A-Z0-9]+", " ", name.upper().replace("&", " ").replace(".", "")).split()
    joined = re.sub(r"\b([A-Z]) (?=[A-Z]\b)", r"\1", " ".join(raw))  # "U S BCORP" → "US BCORP"
    toks = " ".join(_EXPAND.get(t, t) for t in joined.split()).split()
    return " ".join(t for t in toks if t not in _DROP)


def _score(key: str, other: str) -> int:
    """3 = same distinctive tokens; 2 = one contains the other with ≥2 shared tokens; 0 = no match.
    Single-token keys (KEYCORP, US …) must match exactly, so "U.S. Bancorp" never becomes "US Metro"."""
    if not key or not other:
        return 0
    if key == other:
        return 3
    ta, tb = set(key.split()), set(other.split())
    return 2 if min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta) else 0


def _query(field: str, token: str) -> list[dict]:
    try:
        raw = http.get(f"{API}/institutions", params={
            "filters": f"ACTIVE:1 AND {field}:{token}*", "fields": "NAME,CERT,NAMEHCR,ASSET",
            "sort_by": "ASSET", "sort_order": "DESC", "limit": "50"})
    except http.HttpError:
        return []
    return [row["data"] for row in raw.get("data", [])]


def _largest_cert(holding_name: str) -> dict | None:
    """Largest active insured bank owned by the holding company (or the bank itself if it has none)."""
    key = _norm(holding_name)
    if not key:
        return None
    toks = re.sub(r"[^A-Z0-9]+", " ", holding_name.upper().replace(".", "")).split()
    token = max((t for t in toks if t not in _DROP and t not in ("BANK", "FIRST", "OF")), key=len,
                default=key.split()[0])
    if len(token) <= 3:  # FDIC splits initials ("U S BCORP"): widen to the first letter, rank by asset
        token = token[0]
    best, best_rank = None, (0, 0)
    for field in ("NAMEHCR", "NAME"):
        for d in _query(field, token):
            sc = _score(key, _norm(d.get(field, "")))
            rank = (sc + (1 if field == "NAMEHCR" else 0) if sc else 0, d.get("ASSET") or 0)
            if sc and rank > best_rank:
                best, best_rank = d, rank
        if best_rank[0] >= 4:  # exact holding-company match: no need to search bank names
            break
    return best


def capital_ratios(holding_name: str) -> dict:
    """{'cet1': 0.1503, 'total_capital': 0.162, 'report_date': '20260630', 'bank': 'JPMorgan Chase Bank, NA'}"""
    def fetch():
        inst = _largest_cert(holding_name)
        if not inst:
            return {}
        raw = http.get(f"{API}/financials", params={
            "filters": f"CERT:{inst['CERT']}", "fields": "CERT,REPDTE,RBCT1CER,RBCRWAJ,RBC1RWAJ",
            "sort_by": "REPDTE", "sort_order": "DESC", "limit": "1"})
        rows = raw.get("data", [])
        if not rows:
            return {}
        d = rows[0]["data"]
        cet1 = d.get("RBCT1CER")
        return {"cet1": cet1 / 100 if cet1 is not None else None,
                "total_capital": (d.get("RBCRWAJ") or 0) / 100 or None,
                "report_date": d.get("REPDTE"), "bank": inst.get("NAME"), "cert": inst.get("CERT")}

    try:
        return get_cache().get_or_set(f"fdic:cap:{_norm(holding_name)}", 7 * 24 * 3600, fetch) or {}
    except Exception:
        return {}
