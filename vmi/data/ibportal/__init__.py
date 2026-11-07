"""IBKR fundamentals from the portal site (the backend of IB's free Fundamentals Explorer, LSEG/Refinitiv data).

Why this exists: TWS API 10.47 removed `reqFundamentalData`, but IBKR still serves the same data to every client in
its web portal. IB's Client Portal Gateway cannot carry those routes (Log.md, 2026-11-06), so `sync` logs in in a
browser window (PAPER username) and reads them on that session, in parallel when the portal accepts the copied cookies.

Modules (each one has a single job, so a change usually touches one file):
    routes.py   every URL and field name (edit here when IBKR changes something)
    browser.py  the browser login; hands back a Portal (fast httpx mode, or the browser itself as fallback)
    client.py   HTTP to the portal, read-only by construction (refuses /iserver), rate-limited, thread-safe
    parse.py    pure functions: JSON → Fundamentals / analyst fields, units and fiscal-year checks
    service.py  cache reads for the app, sync(), check(), contract ids via the TWS API

Use: `python -m vmi.data.ib_fundamentals sync --sp500` (IB Gateway on the live login must run for new contract ids).
"""
from vmi.data.ibportal.client import Portal, PortalError
from vmi.data.ibportal.service import cached_estimates, cached_fundamentals, check, login_and_sync, prefetch_conids, sync

__all__ = ["Portal", "PortalError", "cached_estimates", "cached_fundamentals", "check", "login_and_sync", "prefetch_conids", "sync"]
