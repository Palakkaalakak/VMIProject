"""Direct access to IBKR's portal site through a real browser window (no Client Portal Gateway).

Why: the gateway only forwards /v1/api and /v1/portal; for every other path it answers 302 to the portal site, and
those two services 404 on the Fundamentals routes (confirmed on a real run 2026-11-06). The portal site itself serves
/tws.proxy/fundamentals/... to a logged-in browser, so we log in in a browser and send our GETs through its cookies.

    with browser_portal() as p:          # opens Edge/Chrome, waits for you to log in (paper username)
        ibportal.sync([...], portal=p)   # same Portal API as the gateway client

Needs `pip install playwright` only: it drives the Edge or Chrome that is already installed (falls back to
Playwright's own Chromium if you ran `playwright install chromium`). Read-only: Portal still refuses /iserver.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from vmi.data.ibportal.client import Portal, PortalError

SITE = "https://ndcdyn.interactivebrokers.com"
LOGIN = SITE + "/sso/Login?forwardTo=22&RL=1&ip2loc=US"
LOGIN_PROBE_CONID = 265598  # AAPL: a cheap fundamentals call that only answers with JSON when logged in
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

    def __init__(self, context, base: str = SITE, timeout: float = 20.0):
        self.context, self.base, self.timeout = context, base, timeout

    def request(self, method: str, path: str, params: dict | None = None) -> _Response:
        try:
            r = self.context.request.fetch(self.base + path, method=method, params=params or None,
                                           max_redirects=5, fail_on_status_code=False,
                                           timeout=self.timeout * 1000)
        except Exception as exc:  # playwright raises its own Error type
            raise PortalError(f"browser request failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        return _Response(r)

    def close(self) -> None:  # the context belongs to browser_portal
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


@contextmanager
def browser_portal(login_timeout: float = 600.0, say: Callable[[str], None] = print) -> Iterator[Portal]:
    """Open a browser at the IBKR login, wait until the fundamentals routes answer, yield a Portal on it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise PortalError("playwright is not installed: pip install playwright") from exc
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            context = browser.new_context()
            context.new_page().goto(LOGIN)
            portal = Portal(http=BrowserHttp(context))
            say("A browser window opened: log in with your PAPER username (not the live one). Waiting for the login ...")
            deadline, last = time.monotonic() + login_timeout, ""
            while True:
                try:
                    if portal.data_list([LOGIN_PROBE_CONID], ["BETA"]) is not None:
                        break
                except PortalError as exc:
                    last = str(exc)
                if time.monotonic() > deadline:
                    raise PortalError(f"not logged in within {login_timeout:.0f}s; last answer: {last[:300]}")
                time.sleep(3)
            say("Logged in: fundamentals routes answer.")
            yield portal
        finally:
            browser.close()
