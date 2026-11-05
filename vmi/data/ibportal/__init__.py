"""IBKR fundamentals through the Client Portal Gateway (the backend of IB's free Fundamentals Explorer).

Why this exists: TWS API 10.47 removed `reqFundamentalData`, but IBKR still serves LSEG fundamentals to every
client through its web portal. IB's own Client Portal Gateway forwards `/v1/tws/<route>` to that backend.

Modules (each one has a single job, so a change usually touches one file):
    routes.py   every URL and field name (edit here when IBKR changes something)
    client.py   HTTP to the local gateway, read-only by construction (refuses /iserver routes)
    parse.py    pure functions: JSON → Fundamentals / analyst fields, units and fiscal-year checks
    service.py  cache-aware operations: fundamentals(), estimates(), sync(), check()

Setup (Log.md has the reasoning): run IBKR's Client Portal Gateway, log it in with a DIFFERENT username than
TWS (the paper login works; the gateway opens its own brokerage session), set VMI_IB_CP_URL=https://localhost:5000,
then `python -m vmi.data.ib_fundamentals check AAPL`.
"""
from vmi.data.ibportal.client import Portal, PortalError, base_url
from vmi.data.ibportal.service import (cached_estimates, cached_fundamentals, check, enabled, estimates,
                                       fundamentals, sync)

__all__ = ["Portal", "PortalError", "base_url", "cached_estimates", "cached_fundamentals", "check", "enabled",
           "estimates", "fundamentals", "sync"]
