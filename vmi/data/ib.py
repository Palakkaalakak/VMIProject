"""Interactive Brokers gateway (TWS / IB Gateway) via ib_async — market data ONLY.

Design notes (researched best practices):
  * ib_async (maintained successor of ib_insync) runs an asyncio event loop. FastAPI also runs an
    asyncio loop, so we run IB on its OWN dedicated thread + loop and marshal calls with
    `asyncio.run_coroutine_threadsafe`. This avoids the classic "This event loop is already running"
    problems and keeps the web server responsive while IB streams.
  * Auto-reconnect watchdog: if TWS restarts / disconnects, a background task retries forever with
    backoff. Everything else in the app degrades gracefully to Yahoo data meanwhile.
  * Option chains: reqSecDefOptParams (one call, all expiries/strikes) → qualify a strike window →
    reqMktData streaming with generic tick 106 (IV) + model greeks. Tickers are kept subscribed in a
    pool so re-opening a chain is instant and values never "disappear" between refreshes. Pacing:
    IB allows ~100 simultaneous lines by default, so the pool is LRU-capped.
  * NO orders are ever sent to IB. Paper trading is fully internal (vmi.paper).
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import OrderedDict
from typing import Any

from vmi.config import get_settings
from vmi.data import market_hours
from vmi.data.models import OptionQuote, Quote

log = logging.getLogger("vmi.ib")


def _clean(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or f < 0 and f != -1 and False:
        return None
    if f == -1.0:  # IB uses -1 for "no data"
        return None
    return f


AUTO_PORTS = (7496, 7497, 4001, 4002)  # TWS live, TWS paper, IB Gateway live, IB Gateway paper


def candidate_ports(configured: int) -> tuple[int, ...]:
    """Ports to try, in order: the configured one, or (0 = auto) the usual TWS / IB Gateway ports."""
    return (configured,) if configured else AUTO_PORTS


class IBGateway:
    def __init__(self):
        self.settings = get_settings()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.ib = None
        self.status = "disabled" if not self.settings.ib_enabled else "starting"
        self.last_error = ""
        self._tickers: OrderedDict[int, Any] = OrderedDict()  # conId → Ticker (streaming pool)
        self.port = self.settings.ib_port or AUTO_PORTS[0]  # the port actually connected to (or last tried)
        self._max_lines = 90
        self._contract_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self.settings.ib_enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="ib-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            from ib_async import IB
        except Exception as exc:  # pragma: no cover
            self.status, self.last_error = "unavailable", f"ib_async import failed: {exc}"
            return
        self.ib = IB()
        self.ib.errorEvent += self._on_error
        self._loop.create_task(self._watchdog())
        self._loop.run_forever()

    def _on_error(self, reqId, errorCode, errorString, contract=None):
        # 2104/2106/2158 are informational "data farm OK" messages
        if errorCode in (2104, 2106, 2107, 2108, 2119, 2158, 10167, 10168):
            return
        self.last_error = f"{errorCode}: {errorString}"
        log.debug("IB error %s %s", errorCode, errorString)

    async def _watchdog(self) -> None:
        delay = 2.0
        while True:
            if not self.ib.isConnected():
                self.status = "connecting"
                if await self._connect_any():
                    self.ib.reqMarketDataType(self.settings.ib_market_data_type)
                    self.status = "connected"
                    self._tickers.clear()
                    delay = 2.0
                else:
                    self.status = "disconnected"
                    delay = min(60.0, delay * 1.5)
            await asyncio.sleep(delay if not self.ib.isConnected() else 5.0)

    async def _connect_any(self) -> bool:
        """Try each candidate port until one accepts the (read-only) connection; remember which one worked."""
        for port in candidate_ports(self.settings.ib_port):
            try:
                await self.ib.connectAsync(self.settings.ib_host, port, clientId=self.settings.ib_client_id,
                                           timeout=self.settings.ib_connect_timeout, readonly=True)
                self.port = port
                return True
            except Exception as exc:
                self.last_error = f"connect {port}: {exc!s}"[:200]
        return False

    @property
    def connected(self) -> bool:
        return bool(self.ib and self.ib.isConnected())

    def call(self, coro_factory, timeout: float = 30.0):
        """Run a coroutine on the IB loop from any thread and wait for the result."""
        if not self.connected or not self._loop:
            raise RuntimeError("IB not connected")
        fut = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return fut.result(timeout)

    def info(self) -> dict:
        return {"status": self.status, "connected": self.connected, "host": self.settings.ib_host,
                "port": self.port, "tried_ports": list(candidate_ports(self.settings.ib_port)), "client_id": self.settings.ib_client_id,
                "last_error": self.last_error, "streaming_lines": len(self._tickers)}

    # ------------------------------------------------------------------ helpers (IB-loop side)
    async def _stock(self, symbol: str):
        from ib_async import Stock

        key = f"STK:{symbol}"
        if key not in self._contract_cache:
            c = Stock(symbol.replace("-", " ").replace(".", " "), "SMART", "USD")
            q = await self.ib.qualifyContractsAsync(c)
            if not q:
                raise ValueError(f"IB could not qualify {symbol}")
            self._contract_cache[key] = q[0]
        return self._contract_cache[key]

    def _subscribe(self, contract, generic: str = ""):
        cid = contract.conId
        if cid in self._tickers:
            self._tickers.move_to_end(cid)
            return self._tickers[cid]
        while len(self._tickers) >= self._max_lines:
            old_id, old = self._tickers.popitem(last=False)
            try:
                self.ib.cancelMktData(old.contract)
            except Exception:
                pass
        t = self.ib.reqMktData(contract, generic, False, False)
        self._tickers[cid] = t
        return t

    # ------------------------------------------------------------------ public API (any thread)
    def conid(self, symbol: str) -> int:
        """IB contract id of a US stock (qualified on SMART)."""
        return int(self.call(lambda: self._stock(symbol)).conId)

    def quote(self, symbol: str, wait: float = 2.0) -> Quote:
        async def run():
            c = await self._stock(symbol)
            t = self._subscribe(c)
            end = time.time() + wait
            while time.time() < end and not (_clean(t.bid) and _clean(t.ask)) and not _clean(t.last):
                await asyncio.sleep(0.1)
            return Quote(symbol=symbol, last=_clean(t.last), bid=_clean(t.bid), ask=_clean(t.ask),
                         close=_clean(t.close), volume=_clean(t.volume), ts=time.time(), source="ib",
                         session=market_hours.session_now())
        return self.call(run, timeout=wait + 10)

    def history(self, symbol: str, duration: str = "10 Y", bar: str = "1 day") -> list[dict]:
        async def run():
            c = await self._stock(symbol)
            bars = await self.ib.reqHistoricalDataAsync(c, endDateTime="", durationStr=duration,
                                                        barSizeSetting=bar, whatToShow="TRADES",
                                                        useRTH=True, formatDate=1)
            return [{"date": str(b.date)[:10], "open": b.open, "high": b.high, "low": b.low,
                     "close": b.close, "volume": b.volume} for b in bars]
        return self.call(run, timeout=60)

    def option_params(self, symbol: str) -> dict:
        async def run():
            c = await self._stock(symbol)
            params = await self.ib.reqSecDefOptParamsAsync(c.symbol, "", c.secType, c.conId)
            smart = [p for p in params if p.exchange == "SMART"] or params
            if not smart:
                return {"expirations": [], "strikes": [], "trading_class": "", "multiplier": "100"}
            # choose the trading class with the most expirations (standard monthly+weekly)
            best = max(smart, key=lambda p: len(p.expirations))
            return {"expirations": sorted(best.expirations), "strikes": sorted(best.strikes),
                    "trading_class": best.tradingClass, "multiplier": best.multiplier}
        return self.call(run, timeout=30)

    def option_chain(self, symbol: str, expiry: str, strikes: list[float], rights=("C", "P"),
                     wait: float = 6.0) -> list[OptionQuote]:
        async def run():
            from ib_async import Option

            und = await self._stock(symbol)
            ut = self._subscribe(und)
            contracts = [Option(und.symbol, expiry, k, r, "SMART", currency="USD")
                         for k in strikes for r in rights]
            qualified = []
            # qualify in batches (pacing-friendly)
            for i in range(0, len(contracts), 50):
                q = await self.ib.qualifyContractsAsync(*contracts[i:i + 50])
                qualified.extend([x for x in q if x and getattr(x, "conId", 0)])
            tickers = [self._subscribe(c, "100,101,106") for c in qualified]
            end = time.time() + wait
            while time.time() < end:
                ready = sum(1 for t in tickers if _clean(t.bid) is not None or _clean(t.last) is not None)
                if tickers and ready >= 0.9 * len(tickers):
                    break
                await asyncio.sleep(0.2)
            und_px = _clean(ut.marketPrice()) if hasattr(ut, "marketPrice") else None
            out = []
            for t in tickers:
                g = t.modelGreeks or t.lastGreeks or t.bidGreeks
                c = t.contract
                out.append(OptionQuote(
                    symbol=symbol, expiry=c.lastTradeDateOrContractMonth, strike=c.strike, right=c.right,
                    bid=_clean(t.bid), ask=_clean(t.ask), last=_clean(t.last), volume=_clean(t.volume),
                    open_interest=_clean(t.callOpenInterest if c.right == "C" else t.putOpenInterest),
                    iv=_clean(g.impliedVol) if g else _clean(getattr(t, "impliedVolatility", None)),
                    delta=_clean(g.delta) if g else None, gamma=_clean(g.gamma) if g else None,
                    theta=_clean(g.theta) if g else None, vega=_clean(g.vega) if g else None,
                    und_price=und_px, con_id=c.conId))
            return out
        return self.call(run, timeout=wait + 60)


_gateway: IBGateway | None = None


def gateway() -> IBGateway:
    global _gateway
    if _gateway is None:
        _gateway = IBGateway()
    return _gateway
