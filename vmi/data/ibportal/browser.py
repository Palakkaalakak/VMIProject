"""Log in to IBKR's portal site in a real browser window and hand back a `Portal` on that session.

    with login() as p:                  # opens Edge/Chrome, waits for you to log in (PAPER username)
        ibportal.sync([...], portal=p)

Fast mode: after the login, the browser's cookies and user agent are copied into an httpx client, which is checked
with one real request. If the portal accepts it, `sync` runs many requests in parallel; if not, the browser itself
sends every request (one at a time, slower). Either way the browser window stays open until the work is done.

Needs `pip install playwright`: it drives the Edge or Chrome already installed (Playwright's own Chromium if you ran
`python -m playwright install chromium`). Read-only: Portal refuses /iserver.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from vmi.data.ibportal import routes
from vmi.data.ibportal.client import Portal, PortalError

PROBE_CONID = 265598  # AAPL: a cheap call that only answers with JSON when logged in
BROWSERS = ("msedge", "chrome", None)  # None = Playwright's bundled Chromium


class _Response:
    """The few httpx.Response attributes Portal._send reads."""

    def __init__(self, r):
        self.status_code = r.status
        self.headers = {k.lower(): v for k, v in r.headers.items()}
        self.content = r.body()
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)


class BrowserHttp:
    """Duck-types httpx.Client.request over a Playwright browser context (cookies, redirects, TLS: the browser's)."""

    def __init__(self, context, base: str = routes.SITE, timeout: float = 20.0):
        self.context, self.base, self.timeout = context, base, timeout

    def request(self, method: str, path: str, params: dict | None = None) -> _Response:
        r = self.context.request.fetch(self.base + path, method=method, params=params or None, max_redirects=5,
                                       fail_on_status_code=False, timeout=self.timeout * 1000)
        return _Response(r)

    def close(self) -> None:  # the context belongs to login()
        pass


def _launch(pw):
    errors = []
    for channel in BROWSERS:
        try:
            return pw.chromium.launch(headless=False, **({"channel": channel} if channel else {}))
        except Exception as exc:
            errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0][:100]}")
    raise PortalError("no browser could be started (" + "; ".join(errors) + "). Install Edge/Chrome or run: "
                      "python -m playwright install chromium")


def _answers(p: Portal) -> bool:
    try:
        return p.data_list([PROBE_CONID], ["BETA"]) is not None
    except PortalError:
        return False


def _cookie_portal(context, page) -> Portal:
    """An httpx Portal carrying the browser's cookies and user agent."""
    import httpx

    jar = httpx.Cookies()
    for c in context.cookies():
        jar.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
    headers = {"User-Agent": page.evaluate("navigator.userAgent"), "Accept": "application/json, text/plain, */*",
               "Referer": routes.SITE + "/portal/"}
    return Portal(cookies=jar, headers=headers)


@contextmanager
def login(login_timeout: float = 600.0, say: Callable[[str], None] = print) -> Iterator[Portal]:
    """Open a browser at the IBKR login, wait until the fundamentals routes answer, yield the fastest working Portal."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortalError("playwright is not installed: pip install playwright") from exc
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(routes.LOGIN)
            slow = Portal(http=BrowserHttp(context))
            say("A browser window opened: log in with your PAPER username (not the live one). Waiting for the login ...")
            deadline = time.monotonic() + login_timeout
            while not _answers(slow):
                if time.monotonic() > deadline:
                    raise PortalError(f"not logged in within {login_timeout:.0f}s")
                time.sleep(2)
            fast = _cookie_portal(context, page)
            if _answers(fast):
                say("Logged in. Fast mode: parallel requests with the browser's login cookies.")
                with fast:
                    yield fast
            else:
                say("Logged in. Fast mode refused by the portal: the browser sends every request (slower).")
                yield slow
        finally:
            browser.close()
