"""Fundamental review mode: default off, persisted, pauses IB and the sign-in autosync."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from vmi.data import mode


def test_default_off_and_persisted():
    assert mode.fundamental_review() is False
    mode.set_fundamental_review(True)
    assert mode.fundamental_review() is True
    mode.set_fundamental_review(False)
    assert mode.fundamental_review() is False


def test_autosync_is_skipped_in_review_mode(monkeypatch):
    from vmi.data.ibportal import job

    monkeypatch.setattr(job, "stale", lambda: True)
    started = []
    monkeypatch.setattr(job, "start", lambda tickers=None: started.append(1) or True)
    monkeypatch.setattr(job.get_settings(), "ib_portal_autosync", True)
    mode.set_fundamental_review(True)
    assert not job.autosync() and not started
    mode.set_fundamental_review(False)
    assert job.autosync() and started


def test_gateway_watchdog_does_not_connect_while_paused(monkeypatch):
    from vmi.data.ib import IBGateway

    gw = IBGateway()
    calls = []

    class FakeIB:
        def isConnected(self): return False
        def disconnect(self): pass
    gw.ib = FakeIB()

    async def fake_connect():
        calls.append(1)
        return False
    monkeypatch.setattr(gw, "_connect_any", fake_connect)
    mode.set_fundamental_review(True)

    async def run():
        t = asyncio.create_task(gw._watchdog())
        await asyncio.sleep(0.3)
        t.cancel()
    asyncio.run(run())
    assert not calls and gw.status == "paused" and gw.info()["paused"]


def test_api_toggle(temp_db):
    from vmi.api import app as appmod

    c = TestClient(appmod.app)
    assert c.get("/api/mode").json() == {"fundamental_review": False}
    assert c.put("/api/mode", json={"fundamental_review": True}).json()["fundamental_review"] is True
    assert c.get("/api/health").json()["fundamental_review"] is True
