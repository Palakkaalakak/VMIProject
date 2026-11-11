"""Persistence (SQLite via SQLAlchemy 2.0). Portfolios, positions, trades, watchlists, alerts,
per-ticker valuation overrides and scan results. One module = one schema; business logic lives elsewhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from vmi.config import get_settings


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    style: Mapped[str] = mapped_column(String(30), default="balanced")   # growth|defensive|balanced|dividend|speculative
    cash: Mapped[float] = mapped_column(Float, default=100_000.0)
    starting_cash: Mapped[float] = mapped_column(Float, default=100_000.0)
    target_positions: Mapped[int] = mapped_column(Integer, default=20)
    # sizing_mode: "target" (equity ÷ target_positions) | "watchlist" (equity ÷ size of `watchlist_id`) | "manual"
    # (`manual_allocation` $ per stock); tranches; auto_trade (tranche plans fill without a click); market_hours_only.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    positions: Mapped[list["Position"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    trades: Mapped[list["Trade"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    key: Mapped[str] = mapped_column(String(80))            # "AAPL" or "AAPL 20261218 250 P"
    symbol: Mapped[str] = mapped_column(String(20))
    sec_type: Mapped[str] = mapped_column(String(5), default="STK")   # STK | OPT
    expiry: Mapped[str | None] = mapped_column(String(8), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    right: Mapped[str | None] = mapped_column(String(1), nullable=True)
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    qty: Mapped[float] = mapped_column(Float, default=0.0)          # negative = short (options)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)     # per share / per option share
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    tranches_filled: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)          # category, IV at entry, plan …
    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    key: Mapped[str] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(20))
    sec_type: Mapped[str] = mapped_column(String(5), default="STK")
    side: Mapped[str] = mapped_column(String(4))                    # BUY | SELL
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)                     # fill price per share
    mid: Mapped[float] = mapped_column(Float)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)     # $ total
    liquidity: Mapped[str] = mapped_column(String(10), default="liquid")
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, default="")
    # --- journal / audit (the Trade table is the ledger: positions and cash can be rebuilt from it, vmi/paper/ledger.py)
    kind: Mapped[str] = mapped_column(String(12), default="fill")      # fill | assignment | expiry | adjustment
    source: Mapped[str] = mapped_column(String(10), default="paper")   # paper | admin
    fees: Mapped[float] = mapped_column(Float, default=0.0)            # $ total, reduces cash
    tags: Mapped[str] = mapped_column(String(200), default="")         # comma separated, free vocabulary
    thesis: Mapped[str] = mapped_column(Text, default="")              # why the trade was made (reviewed later)
    context: Mapped[dict] = mapped_column(JSON, default=dict)          # snapshot at the time: IV, MOS, steps, plan, …
    edited: Mapped[bool] = mapped_column(Boolean, default=False)       # changed by an admin edit after creation
    portfolio: Mapped[Portfolio] = relationship(back_populates="trades")


class TradeAudit(Base):
    """Every admin change to the ledger, with the full before/after row, so nothing is ever silently rewritten."""
    __tablename__ = "trade_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(12))                    # add | update | delete | rebuild
    reason: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class OptionSnapshot(Base):
    """Saved option payoff profile: the inputs (legs, spot, IV, rate, date) plus the computed curves and scenario grid,
    so the position can be analysed later without IBKR or a live quote."""
    __tablename__ = "option_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    portfolio_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    reason: Mapped[str] = mapped_column(String(20), default="manual")  # manual | trade | daily
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class TranchePlan(Base):
    """Buy (and optional sell) levels for one stock in one portfolio. The automation loop (vmi/paper/autotrade.py)
    fills a level when the price reaches it (or only alerts, when auto is off). Every fill links back here."""
    __tablename__ = "tranche_plans"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="active")   # active | paused | done | cancelled
    auto: Mapped[bool | None] = mapped_column(Boolean, nullable=True)    # None = follow the portfolio setting
    intrinsic_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    require_below_iv: Mapped[bool] = mapped_column(Boolean, default=True)
    allocation: Mapped[float | None] = mapped_column(Float, nullable=True)  # $ full allocation override (else sizing mode)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)          # category multiplier (½ speculative …)
    # [{"price": 180.0, "fraction": 0.25, "status": "pending|filled|skipped", "trade_id": None, "filled_at": None,
    #   "note": ""}] buy levels high → low; sell levels: {"price" | "over_iv": 0.5, "fraction": 0.33, …}
    buy_levels: Mapped[list] = mapped_column(JSON, default=list)
    sell_levels: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="manual")      # manual | watchlist | analysis
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    history: Mapped[list] = mapped_column(JSON, default=list)              # every change / trigger, for review
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # backfill start


class DailyMark(Base):
    """One row per portfolio per day (key="__portfolio__") and per held/planned instrument: the raw material for equity
    curves and later what-if studies (price, value, IV, MOS, option implied vol, trend …)."""
    __tablename__ = "daily_marks"
    __table_args__ = (UniqueConstraint("day", "portfolio_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)               # YYYY-MM-DD
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    items: Mapped[list["WatchItem"]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchItem(Base):
    __tablename__ = "watch_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    intrinsic_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv_source: Mapped[str] = mapped_column(String(20), default="manual")   # manual | auto
    supports: Mapped[list] = mapped_column(JSON, default=list)             # buy levels, high → low
    notes: Mapped[str] = mapped_column(Text, default="")
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered: Mapped[list] = mapped_column(JSON, default=list)            # levels already alerted
    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    symbol: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(30))       # buy_level | below_iv | parabolic | exit_rule
    message: Mapped[str] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    seen: Mapped[bool] = mapped_column(Boolean, default=False)


class Override(Base):
    """Per-ticker human-in-the-loop valuation overrides (growth, method, biz type, moat, IV …)."""
    __tablename__ = "overrides"
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    universe: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    funnel: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="running")
    results: Mapped[list] = mapped_column(JSON, default=list)


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(get_settings().database_url, future=True,
                                connect_args={"check_same_thread": False, "timeout": 30})
        Base.metadata.create_all(_engine)
        _add_missing_columns(_engine)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _add_missing_columns(eng) -> None:
    """create_all never alters existing tables: add columns introduced after a database was first created."""
    from sqlalchemy import inspect, text

    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                kind = col.type.compile(dialect=eng.dialect)
                arg = getattr(col.default, "arg", None)
                if isinstance(arg, bool):
                    default = "1" if arg else "0"
                elif isinstance(arg, (int, float)):
                    default = repr(arg)
                elif isinstance(arg, str):
                    default = "'" + arg.replace("'", "''") + "'"
                else:                                  # callables (dict/list factories) and no default
                    default = {"JSON": "'{}'", "String": "''", "Text": "''"}.get(type(col.type).__name__, "NULL")
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {kind} DEFAULT {default}'))


def session() -> Session:
    engine()
    assert _Session is not None
    return _Session()


# ------------------------------------------------------------------------------------- overrides
JUDGEMENTS_FILE = Path(__file__).resolve().parents[1] / "config" / "judgements.json"


def judgements() -> dict[str, dict]:
    """Committed per-ticker judgement overrides (config/judgements.json) — survive DB wipes."""
    try:
        raw = json.loads(JUDGEMENTS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return {k.upper(): v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def get_override(symbol: str) -> dict:
    """Effective overrides = committed judgement (if any) ⊕ DB override (DB wins). `note` explains provenance."""
    j = dict(judgements().get(symbol.upper(), {}))
    with session() as s:
        o = s.get(Override, symbol.upper())
        db = dict(o.data) if o else {}
        if o and o.note:
            db["note"] = o.note
    out = {**j, **db}
    if out:
        out["source"] = "db" if db and not j else "judgement" if j and not db else "judgement+db" if out else ""
    return out


def _stamped(data: dict | None) -> dict | None:
    from vmi.overrides import stamp_review  # local import: vmi.overrides imports nothing from the store at load time
    return stamp_review(data) if data else data


def _merge(current: dict, changes: dict | None, clear_all: bool) -> dict:
    """Apply changes to stored overrides: a None value removes that key; clear_all empties everything."""
    out = {} if clear_all else dict(current)
    for k, v in (changes or {}).items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def set_override(symbol: str, data: dict | None, note: str = "", clear_all: bool = False) -> dict:
    """Merge validated changes into the DB override for one ticker (see vmi.overrides.validate)."""
    with session() as s:
        o = s.get(Override, symbol.upper())
        merged = _merge(dict(o.data) if o else {}, _stamped(data), clear_all)
        if o is None:
            o = Override(symbol=symbol.upper(), data=merged, note=note)
            s.add(o)
        else:
            o.data, o.note = merged, ("" if clear_all else note or o.note)
        if not o.data and not o.note:
            s.delete(o)
        s.commit()
    return get_override(symbol)


def set_judgement(symbol: str, data: dict | None, note: str = "", clear_all: bool = False) -> dict:
    """Same as set_override, but writes the committed config/judgements.json (survives DB resets)."""
    try:
        raw = json.loads(JUDGEMENTS_FILE.read_text())
    except (OSError, ValueError):
        raw = {}
    sym = symbol.upper()
    entry = _merge({k: v for k, v in raw.get(sym, {}).items() if k != "note"}, _stamped(data), clear_all)
    note = "" if clear_all else (note or raw.get(sym, {}).get("note", ""))
    if entry or note:
        raw[sym] = {**entry, **({"note": note} if note else {})}
    else:
        raw.pop(sym, None)
    JUDGEMENTS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    return get_override(symbol)


def all_overrides() -> dict[str, dict]:
    out = {k: {"data": {x: y for x, y in v.items() if x != "note"}, "note": v.get("note", ""), "source": "judgement"}
           for k, v in judgements().items()}
    with session() as s:
        for o in s.scalars(select(Override)):
            out[o.symbol] = {"data": {**out.get(o.symbol, {}).get("data", {}), **o.data}, "note": o.note, "source": "db"}
    return out


def add_alert(symbol: str, kind: str, message: str, price: float | None = None) -> None:
    with session() as s:
        s.add(Alert(symbol=symbol, kind=kind, message=message, price=price))
        s.commit()


def to_dict(obj: Any) -> dict:
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, datetime) else v
    return out
