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


def _norm(name: str) -> str:
    name = name.upper().replace("&", " ")
    name = re.sub(r"\b(INC|CORP|CORPORATION|CO|COMPANY|THE|HOLDINGS?|GROUP|FINANCIAL|BANCORP(ORATION)?|N\.?A\.?)\b", " ", name)
    return re.sub(r"[^A-Z0-9]+", " ", name).strip()


def _largest_cert(holding_name: str) -> dict | None:
    key = _norm(holding_name)
    if not key:
        return None
    first = key.split()[0]
    try:
        raw = http.get(f"{API}/institutions", params={
            "filters": f"ACTIVE:1 AND NAMEHCR:{first}*", "fields": "NAME,CERT,NAMEHCR,ASSET",
            "sort_by": "ASSET", "sort_order": "DESC", "limit": "25"})
    except http.HttpError:
        return None
    best = None
    for row in raw.get("data", []):
        d = row["data"]
        hcr = _norm(d.get("NAMEHCR", ""))
        if hcr and (hcr == key or hcr.startswith(key) or key.startswith(hcr)):
            if best is None or (d.get("ASSET") or 0) > (best.get("ASSET") or 0):
                best = d
    if best is None:  # fall back: bank itself named like the holding
        for row in raw.get("data", []):
            d = row["data"]
            if _norm(d.get("NAME", "")).startswith(key):
                best = d
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
