"""The app's IB sync: one background job that opens the IBKR login window and refreshes the IB cache.

    start()    begin a sync (S&P 500) unless one is running          → bool
    status()   {state, message, report, last_sync, stale, autosync}   → dict (the Settings card and /api/ib/sync)
    autosync() called once at app start: starts a sync when the IB data is older than ttl_ib_portal

The window opens on the machine that runs the app (this is a local app). Sync = contract ids via the app's own
IB Gateway connection, then the browser login, then the parallel fetch (service.sync).
"""
from __future__ import annotations

import threading
import time

from vmi.config import get_settings
from vmi.data.cache import get_cache

KEY_LAST = "ibportal:last_sync"
_lock = threading.Lock()
_state: dict = {"state": "idle", "message": "", "report": None, "started": None}


def last_sync() -> float | None:
    return get_cache().get(KEY_LAST)


def stale() -> bool:
    ts = last_sync()
    return ts is None or time.time() - ts > get_settings().ttl_ib_portal


def status() -> dict:
    with _lock:
        return {**_state, "last_sync": last_sync(), "stale": stale(), "autosync": get_settings().ib_portal_autosync}


def _say(msg: str) -> None:
    with _lock:
        _state["message"] = msg


def _work(tickers: list[str]) -> dict:
    from vmi.data.ibportal.service import login_and_sync

    return login_and_sync(tickers, say=_say)


def _run(tickers: list[str] | None) -> None:
    try:
        if tickers is None:
            from vmi.data.universe import sp500

            _say("Loading the S&P 500 list ...")
            tickers = [r["symbol"] for r in sp500()]
        report = _work(tickers)
        if report.get("statements"):
            get_cache().set(KEY_LAST, time.time())
        with _lock:
            _state.update(state="done", report=report, message=(
                f"{report.get('statements', 0)}/{report.get('tickers', 0)} stocks in {report.get('seconds', '?')} s"
                + (f" — stopped: {report['stopped']}" if report.get("stopped") else "")))
    except Exception as exc:  # shown in the UI; never kills the app
        with _lock:
            _state.update(state="error", message=f"{type(exc).__name__}: {exc}"[:300])


def start(tickers: list[str] | None = None) -> bool:
    with _lock:
        if _state["state"] == "running":
            return False
        _state.update(state="running", message="Starting ...", report=None, started=time.time())
    threading.Thread(target=_run, args=(tickers,), name="ib-sync", daemon=True).start()
    return True


def autosync() -> bool:
    """At app start: refresh when the IB data is stale (never synced, or older than ttl_ib_portal)."""
    return get_settings().ib_portal_autosync and stale() and start()
