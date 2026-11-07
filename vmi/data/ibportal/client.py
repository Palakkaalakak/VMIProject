"""HTTP client for IBKR's Fundamentals Explorer routes on the portal site. Read-only by construction.

    with browser.login() as p:                    # a Portal on the logged-in session
        income = p.financials(265598, "income", annual=True)

`Portal` is thread-safe when it runs on httpx (the fast mode): many workers share one connection pool and one rate
limit. On the browser fallback (`http=BrowserHttp`) it must be used from one thread (`p.parallel` is False).
All network I/O of the package lives here; parsing lives in parse.py, caching in service.py.
"""
from __future__ import annotations

import threading
import time

from vmi.config import get_settings
from vmi.data.ibportal import routes

NOT_JSON = 200          # PortalError.status for "answered 200 but the body is not JSON"
RETRY_STATUSES = (429, 502, 503, 504)  # throttled or briefly unavailable: wait and retry
RETRIES = 4


class PortalError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RateLimiter:
    """At most `rps` request starts per second across all threads."""

    def __init__(self, rps: float):
        self._gap, self._next, self._lock = 1.0 / rps, 0.0, threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self._gap
        if start > now:
            time.sleep(start - now)


class Portal:
    """One logged-in portal session. Pass `http` (browser fallback) or cookies/headers (fast httpx mode);
    `transport` lets tests inject httpx.MockTransport."""

    def __init__(self, base: str = routes.SITE, *, http=None, cookies=None, headers: dict | None = None,
                 transport=None, max_rps: float | None = None, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.parallel = http is None
        self._limit = RateLimiter(max_rps or get_settings().ib_portal_max_rps)
        if http is not None:
            self._http = http
        else:
            import httpx

            self._http = httpx.Client(base_url=self.base, cookies=cookies, headers=headers, transport=transport,
                                      timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Portal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------------------------------ transport
    def _send(self, path: str, params: dict | None = None):
        if "/iserver" in path:
            raise PortalError(f"refusing {path}: this client is read-only (no brokerage-session routes)")
        for attempt in range(RETRIES + 1):
            self._limit.wait()
            try:
                r = self._http.request("GET", path, params=params)
            except Exception as exc:  # httpx / playwright network errors
                raise PortalError(f"portal unreachable: {type(exc).__name__}: {exc}") from exc
            if r.status_code not in RETRY_STATUSES or attempt == RETRIES:
                break
            retry_after = r.headers.get("retry-after", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else 2.0 * 2 ** attempt)
        if r.status_code == 401:
            raise PortalError(f"not logged in (HTTP 401 on {path}): log in again", 401)
        if r.status_code != 200:
            where = f" → {r.headers.get('location')}" if 300 <= r.status_code < 400 else ""
            raise PortalError(f"GET {path} → HTTP {r.status_code}{where}: {r.text[:160]}", r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:  # 200 OK but not JSON (a login/error web page): say what came back
            raise PortalError(f"GET {path} → HTTP 200 but not JSON ({r.headers.get('content-type', '?')}): "
                              f"{r.text[:160]!r}", NOT_JSON) from None

    def _get(self, route: str, **params):
        return self._send(routes.FUNDAMENTALS_BASE + route, params or None)

    # --------------------------------------------------------------------------------------- fundamentals
    def financials(self, conid: int, statement: str, annual: bool = True):
        return self._get(routes.FINANCIALS.format(conid=conid), annual=str(annual).lower(), type=statement)

    def data_list(self, conids, fields) -> list[dict]:
        """[{conid, field_name, display_value}] for many conids at once (batched)."""
        ids, names, rows = [str(c) for c in conids], ",".join(fields), []
        for i in range(0, len(ids), routes.CONIDS_PER_DATA_LIST):
            chunk = ",".join(ids[i:i + routes.CONIDS_PER_DATA_LIST])
            rows.extend(self._get(routes.DATA_LIST, conids=chunk, field_names=names) or [])
        return rows

    def key_metrics(self, conid: int):
        return self._get(routes.KEY_METRICS.format(conid=conid), show="translations")

    def fin_trends(self, conid: int, search_id, annual: bool = True):
        return self._get(routes.FIN_TRENDS.format(conid=conid), search_id=search_id, annual=str(annual).lower())

    def key_ratios(self, conid: int):
        return self._get(routes.KEY_RATIOS.format(conid=conid))
