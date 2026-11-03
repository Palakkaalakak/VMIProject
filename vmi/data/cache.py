"""Tiny persistent TTL cache (SQLite, thread-safe). Used by every data provider.

Values are JSON-serialised. Keys are namespaced ("sec:facts:320193"). A stale value can still be
read with `allow_stale=True`, which lets the UI keep showing data when a provider is down.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(
                "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts REAL NOT NULL)"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, timeout=30, check_same_thread=False)
            self._local.conn = conn
        return conn

    def get(self, key: str, ttl: float | None = None, allow_stale: bool = False) -> Any | None:
        row = self._conn().execute("SELECT v, ts FROM kv WHERE k=?", (key,)).fetchone()
        if not row:
            return None
        value, ts = row
        if ttl is not None and not allow_stale and time.time() - ts > ttl:
            return None
        return json.loads(value)

    def age(self, key: str) -> float | None:
        row = self._conn().execute("SELECT ts FROM kv WHERE k=?", (key,)).fetchone()
        return None if not row else time.time() - row[0]

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, default=str, separators=(",", ":"))
        with self._lock:
            c = self._conn()
            c.execute("REPLACE INTO kv (k, v, ts) VALUES (?, ?, ?)", (key, payload, time.time()))
            c.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            c = self._conn()
            c.execute("DELETE FROM kv WHERE k=?", (key,))
            c.commit()

    def get_or_set(self, key: str, ttl: float, factory: Callable[[], T]) -> T:
        """Return cached value if fresh; otherwise compute. On failure fall back to stale data."""
        cached = self.get(key, ttl)
        if cached is not None:
            return cached
        try:
            value = factory()
        except Exception:
            stale = self.get(key, allow_stale=True)
            if stale is not None:
                return stale
            raise
        if value is not None:
            self.set(key, value)
        return value


_cache: TTLCache | None = None


def get_cache() -> TTLCache:
    global _cache
    if _cache is None:
        from vmi.config import get_settings

        _cache = TTLCache(get_settings().cache_dir / "cache.sqlite")
    return _cache
