"""HTTP client for the local IBKR Client Portal Gateway. Read-only by construction.

    with Portal() as p:                      # base URL from VMI_IB_CP_URL, e.g. https://localhost:5000
        p.session()                          # raises PortalError("not logged in …") when needed
        ids = p.conids(["AAPL", "MSFT"])     # {"AAPL": 265598, …}
        income = p.financials(ids["AAPL"], "income", annual=True)

All network I/O of the package lives here; parsing lives in parse.py, caching in service.py.
"""
from __future__ import annotations

import time

from vmi.config import get_settings
from vmi.data.ibportal import routes

_working_base: dict[tuple[str, str], str] = {}  # (gateway root, route group) → base that answered

NOT_JSON = 200  # PortalError.status for "answered 200 but the body is not JSON"
NOT_SERVED = (301, 302, 303, 307, 308, 404, 405, NOT_JSON)  # "this base does not serve the route": try the next
SELF_REDIRECT_RETRIES = 2


def _same_path(location: str, path: str) -> bool:
    """True when a redirect points back at the path we asked for (any host)."""
    from urllib.parse import urlsplit

    return bool(location) and urlsplit(location).path.rstrip("/") == path.rstrip("/")


class PortalError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def base_url() -> str:
    """Gateway root from VMI_IB_CP_URL ('' = disabled). Accepts 'localhost:5000' or a URL ending in /v1/api."""
    raw = (get_settings().ib_cp_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith("http"):
        raw = "https://" + raw
    return raw[: -len(routes.WEB_API)] if raw.endswith(routes.WEB_API) else raw


class Portal:
    """One gateway connection. `transport` lets tests inject httpx.MockTransport."""

    def __init__(self, base: str | None = None, *, transport=None, timeout: float = 20.0,
                 max_rps: float | None = None, http=None):
        """`http` replaces the HTTP client (browser.BrowserHttp: direct portal access with a browser login)."""
        import httpx

        self.direct = http is not None
        self.base = http.base if self.direct else (base_url() if base is None else base.rstrip("/"))
        if not self.base:
            raise PortalError("VMI_IB_CP_URL is not set (e.g. https://localhost:5000)")
        s = get_settings()
        self._gap = 1.0 / (max_rps or s.ib_cp_max_rps)
        self._last = 0.0
        if self.direct:
            self._http = http
            return
        self._http = httpx.Client(base_url=self.base, verify=s.ib_cp_verify, timeout=timeout,
                                  transport=transport, headers={"User-Agent": "vmi-toolkit"})

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Portal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------------------------------ transport
    def _send(self, method: str, path: str, params: dict | None = None):
        import httpx

        if "/iserver" in path and not any(path.endswith(ok) for ok in routes.READ_ONLY_EXCEPTIONS):
            raise PortalError(f"refusing {path}: this client is read-only (no brokerage-session routes)")
        wait = self._last + self._gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = self._http.request(method, path, params=params)
            # IBKR's backend answers some first requests with a 302 to the SAME path (it sets a cookie and
            # expects a retry). The gateway passes that 302 through, so retry ourselves; the httpx cookie
            # jar now holds what was set, and the gateway forwards our cookies upstream.
            for _ in range(SELF_REDIRECT_RETRIES):
                if not (300 <= r.status_code < 400 and _same_path(r.headers.get("location", ""), path)):
                    break
                time.sleep(0.3)
                r = self._http.request(method, path, params=params)
        except httpx.HTTPError as exc:
            raise PortalError(f"gateway unreachable at {self.base}: {type(exc).__name__}: {exc}") from exc
        if r.status_code == 401:
            raise PortalError(f"not logged in: open {self.base} in a browser and log in", 401)
        if r.status_code != 200:
            where = (f" → redirected to {r.headers.get('location')} (set-cookie: {'yes' if 'set-cookie' in r.headers else 'no'})"
                     if 300 <= r.status_code < 400 else "")
            raise PortalError(f"{method} {path} → HTTP {r.status_code}{where}: {r.text[:160]}", r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:  # 200 OK but not JSON (a login/error web page, an empty route): say what came back
            raise PortalError(f"{method} {path} → HTTP 200 but not JSON ({r.headers.get('content-type', '?')}): "
                              f"{r.text[:160]!r}", NOT_JSON) from None

    def _routed(self, group: str, bases: tuple[str, ...], method: str, route: str, params: dict):
        """Send to the first base in `bases` that serves `route`; remember it per gateway and group."""
        memo = (self.base, group)
        known = _working_base.get(memo)
        tried: list[str] = []
        for b in [known] if known else bases:
            try:
                data = self._send(method, b + route, params or None)
            except PortalError as exc:
                if exc.status in NOT_SERVED and not known:  # not served under this base: try the next
                    tried.append(str(exc))
                    continue
                raise
            _working_base[memo] = b
            return data
        raise PortalError(f"no {group} route answered with data: " + " | ".join(tried) + " — "
                          + routes.GATEWAY_CONFIG_HINT, NOT_JSON)

    def _api(self, method: str, route: str, **params):
        bases = routes.DIRECT_API_BASES if self.direct else routes.API_BASES
        return self._routed("api", bases, method, route, params)

    def _fundamentals(self, route: str, **params):
        bases = routes.DIRECT_FUNDAMENTALS_BASES if self.direct else routes.FUNDAMENTALS_BASES
        return self._routed("fundamentals", bases, "GET", route, params)

    # ------------------------------------------------------------------------------------------- session
    def session(self) -> dict:
        """Validate the gateway login (raises PortalError when not logged in) and keep it alive."""
        if self.direct:  # browser login: browser_portal() already waited until the routes answered
            return {}
        info = self._api("GET", routes.SESSION_VALIDATE) or {}
        try:
            self._api("POST", routes.KEEPALIVE)
        except PortalError:
            pass  # keep-alive is best effort
        if isinstance(info, dict) and info.get("RESULT") is False:
            raise PortalError(f"not logged in: open {self.base} in a browser and log in", 401)
        return info if isinstance(info, dict) else {}

    # ------------------------------------------------------------------------------------------ contracts
    def conids(self, symbols) -> dict[str, int]:
        """{SYMBOL: conid} for US stock listings (batched; symbols without a listing are omitted)."""
        from vmi.data.ibportal.parse import pick_conid, pick_secdef_conid

        syms = [s.upper() for s in symbols]
        out: dict[str, int] = {}
        if self.direct:  # portal site: no /trsrv; one contract search per symbol
            for s in syms:
                rows = self._api("GET", routes.SECDEF_SEARCH, symbol=s.replace("-", " ").replace(".", " ")) or []
                if (cid := pick_secdef_conid(rows, s)) is not None:
                    out[s] = cid
            return out
        for i in range(0, len(syms), routes.SYMBOLS_PER_REQUEST):
            chunk = syms[i:i + routes.SYMBOLS_PER_REQUEST]
            payload = self._api("GET", routes.STOCKS_BY_SYMBOL, symbols=",".join(chunk)) or {}
            for s in chunk:
                if (cid := pick_conid(payload, s)) is not None:
                    out[s] = cid
        return out

    # --------------------------------------------------------------------------------------- fundamentals
    def financials(self, conid: int, statement: str, annual: bool = True):
        return self._fundamentals(routes.FINANCIALS.format(conid=conid), annual=str(annual).lower(), type=statement)

    def data_list(self, conids, fields) -> list[dict]:
        """[{conid, field_name, display_value}] for many conids at once (batched)."""
        ids, names, rows = [str(c) for c in conids], ",".join(fields), []
        for i in range(0, len(ids), routes.CONIDS_PER_DATA_LIST):
            chunk = ",".join(ids[i:i + routes.CONIDS_PER_DATA_LIST])
            rows.extend(self._fundamentals(routes.DATA_LIST, conids=chunk, field_names=names) or [])
        return rows

    def key_metrics(self, conid: int):
        return self._fundamentals(routes.KEY_METRICS.format(conid=conid), show="translations")

    def key_ratios(self, conid: int):
        return self._fundamentals(routes.KEY_RATIOS.format(conid=conid))
