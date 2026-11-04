"""Shared HTTP plumbing: per-host rate limiting + retries with exponential backoff."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class RateLimiter:
    """Simple thread-safe minimum-interval limiter."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


_limiters: dict[str, RateLimiter] = {}
_limiters_lock = threading.Lock()
_DEFAULT_RPS = {"data.sec.gov": 8.0, "www.sec.gov": 8.0, "finviz.com": 1.5, "api.nasdaq.com": 2.0,
                "stockanalysis.com": 4.0, "www.zacks.com": 2.0, "api.fdic.gov": 4.0, "en.wikipedia.org": 2.0}

_client: httpx.Client | None = None


def _limiter_for(host: str) -> RateLimiter:
    with _limiters_lock:
        if host not in _limiters:
            _limiters[host] = RateLimiter(_DEFAULT_RPS.get(host, 5.0))
        return _limiters[host]


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"Accept-Encoding": "gzip, deflate"},
        )
    return _client


class HttpError(RuntimeError):
    pass


def get(url: str, *, headers: dict | None = None, params: dict | None = None, retries: int = 3,
        expect_json: bool = True):
    host = urlparse(url).netloc
    limiter = _limiter_for(host)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        limiter.wait()
        try:
            r = client().get(url, headers=headers or {"User-Agent": BROWSER_UA}, params=params)
            if r.status_code == 404:
                raise HttpError(f"404 {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json() if expect_json else r.text
        except HttpError:
            raise
        except Exception as exc:  # network / transient
            last_exc = exc
            time.sleep(min(8.0, 0.75 * 2 ** attempt))
    raise HttpError(f"GET failed {url}: {last_exc}")
