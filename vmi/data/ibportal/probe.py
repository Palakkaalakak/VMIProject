"""Raw diagnostics: what does the gateway really answer for each candidate route? (status, headers, body start)

    python -m vmi.data.ib_fundamentals probe [conid]

No parsing, no fallbacks, no hiding: redirects are shown as-is, then followed by hand (up to 5 hops, cookies kept).
Read-only: only GETs, never /iserver.
"""
from __future__ import annotations

import time

from vmi.config import get_settings
from vmi.data.ibportal import routes
from vmi.data.ibportal.client import base_url

SHOW_HEADERS = ("location", "content-type", "server", "www-authenticate", "x-request-id")


def _hop(http, path: str, params: dict | None) -> dict:
    r = http.get(path, params=params, follow_redirects=False)
    return {"url": str(r.url), "status": r.status_code,
            "headers": {k: v for k, v in r.headers.items() if k.lower() in SHOW_HEADERS},
            "set_cookie_names": [c.split("=", 1)[0] for c in r.headers.get_list("set-cookie")],
            "body": r.text[:300]}


def probe(conid: int = 265598) -> list[dict]:
    import httpx

    out: list[dict] = []
    fin = routes.FINANCIALS.format(conid=conid)
    targets = [(b + route, params) for b, route, params in
               [(b, routes.SESSION_VALIDATE, None) for b in routes.API_BASES]
               + [(b, fin, {"annual": "true", "type": "income"}) for b in routes.FUNDAMENTALS_BASES]
               + [("/portal.proxy", "/v1/portal/fundamentals/financials/%d" % conid, {"annual": "true", "type": "income"}),
                  ("/portal.proxy", "/v1/portal/fundamentals/data_list", {"conids": str(conid), "field_names": "BETA"})]]
    with httpx.Client(base_url=base_url(), verify=get_settings().ib_cp_verify, timeout=20,
                      headers={"User-Agent": "vmi-toolkit"}) as http:
        for path, params in targets:
            chain, nxt = [], path
            for _ in range(5):
                try:
                    hop = _hop(http, nxt, params if not chain else None)
                except httpx.HTTPError as exc:
                    chain.append({"error": f"{type(exc).__name__}: {exc}"})
                    break
                chain.append(hop)
                loc = hop["headers"].get("location")
                if not (300 <= hop["status"] < 400 and loc):
                    break
                nxt = loc if loc.startswith("/") else "/" + loc.split("://", 1)[-1].split("/", 1)[-1]
                time.sleep(0.3)
            out.append({"path": path, "chain": chain})
        out.append({"cookies_held": sorted({c.name for c in http.cookies.jar})})
    return out
