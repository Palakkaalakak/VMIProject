"""Entry timing: is it better to buy ON the touch of a support, or to wait for confirmation? (owner 2026-11-25; evidence for the owner,
not an Adam rule, nothing here changes any trading rule.)

Every touch of a buy level becomes a `SupportTouch` (created where touches are already detected: the watchlist check and the tranche
plans). The owner is asked "waiting for confirmation?" at most once every `ASK_EVERY_DAYS` while the touch is live (asking is recorded when
the prompt is SHOWN); no answer means "assumed waiting" until a buy is linked. Every BUY carries an entry type: on_touch, special or
confirmed (automatic plan fills are on_touch). `stats()` then compares the groups on what was paid versus the touch price, the forward
return, how many touches broke down (price fell more than `BREAKDOWN_PCT` below the level) and how many rallies were missed while waiting.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd
from sqlalchemy import select

from vmi import store
from vmi.rules import RULES

ASK_EVERY_DAYS = 2
LAPSE_DAYS = 42                    # about 30 trading days without a buy: the touch is over
BREAKDOWN_PCT = 0.05               # "broke down" = fell this far below the level within the window (owner-adjustable constant)
WINDOW_BARS = 20
LONG_BARS = 60
MIN_FOR_VERDICT = 10
ENTRY_TYPES = ("on_touch", "special", "confirmed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(ts) -> pd.Timestamp:
    """Calendar day of a timestamp as a tz-naive Timestamp (bars are indexed that way)."""
    t = pd.Timestamp(ts)
    return (t.tz_convert(None) if t.tzinfo else t).normalize()


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------ recording
def record_touch(symbol: str, level: float, price: float, source: str = "watchlist") -> dict | None:
    """Open a touch for (symbol, level) unless one is already open. Returns the new row (dict) or None."""
    symbol = symbol.upper()
    with store.session() as s:
        have = s.scalar(select(store.SupportTouch).where(
            store.SupportTouch.symbol == symbol, store.SupportTouch.status == "open",
            store.SupportTouch.level.between(level * 0.995, level * 1.005)))
        if have is not None:
            return None
        t = store.SupportTouch(symbol=symbol, level=float(level), touch_price=float(price), source=source)
        s.add(t)
        s.commit()
        return store.to_dict(t)


def on_price(symbol: str, price: float) -> None:
    """Close open touches whose price has moved well above the level (the same re-arm distance the alerts use) or that are too old."""
    symbol = symbol.upper()
    away = 1 + 3 * RULES.technical.near_level_pct
    now = _now()
    with store.session() as s:
        for t in s.scalars(select(store.SupportTouch).where(store.SupportTouch.symbol == symbol, store.SupportTouch.status == "open")):
            if price > t.level * away or now - _aware(t.touched_at) > timedelta(days=LAPSE_DAYS):
                t.status, t.closed_at = "lapsed", now
        s.commit()


def link_entry(symbol: str, trade_id: int, price: float, entry_type: str | None, when: datetime | None = None) -> dict | None:
    """A BUY happened: attach it to the open touch of this symbol (newest first), or record a touch-less entry so its type still counts."""
    if entry_type is not None and entry_type not in ENTRY_TYPES:
        raise ValueError(f"entry_type must be one of {ENTRY_TYPES}")
    symbol, when = symbol.upper(), when or _now()
    with store.session() as s:
        t = s.scalar(select(store.SupportTouch).where(store.SupportTouch.symbol == symbol, store.SupportTouch.status == "open")
                     .order_by(store.SupportTouch.touched_at.desc()))
        if t is None:
            t = store.SupportTouch(symbol=symbol, level=float(price), touch_price=float(price), touched_at=when, source="manual")
            s.add(t)
        t.status, t.entry_type, t.trade_id, t.entry_price, t.entered_at, t.closed_at = "entered", entry_type, trade_id, float(price), when, when
        s.commit()
        return store.to_dict(t)


# ------------------------------------------------------------------------------------------------ asking
def _prompt_due(t, now: datetime) -> bool:
    if t.status != "open" or t.waiting is False:
        return False
    return t.last_asked_at is None or now - _aware(t.last_asked_at) >= timedelta(days=ASK_EVERY_DAYS)


def open_touches() -> list[dict]:
    """Open touches with `effective_waiting` (no answer counts as waiting) and `ask_due`. Read-only: does not mark anything as asked."""
    now = _now()
    with store.session() as s:
        rows = s.scalars(select(store.SupportTouch).where(store.SupportTouch.status == "open").order_by(store.SupportTouch.touched_at.desc())).all()
        return [{**store.to_dict(t), "effective_waiting": t.waiting is not False, "assumed": t.waiting is None, "ask_due": _prompt_due(t, now)} for t in rows]


def prompts() -> list[dict]:
    """The touches to ask about NOW. Showing them counts as asking: the same touch is not offered again for ASK_EVERY_DAYS
    (and an unanswered one stays 'assumed waiting')."""
    now = _now()
    out = []
    with store.session() as s:
        for t in s.scalars(select(store.SupportTouch).where(store.SupportTouch.status == "open")):
            if _prompt_due(t, now):
                out.append(store.to_dict(t))
                t.last_asked_at = now
        s.commit()
    return out


def answer(touch_id: int, waiting: bool) -> dict:
    with store.session() as s:
        t = s.get(store.SupportTouch, touch_id)
        if t is None:
            raise ValueError(f"no touch {touch_id}")
        now = _now()
        t.waiting, t.last_asked_at = bool(waiting), now
        t.answers = [*(t.answers or []), {"at": now.isoformat(), "waiting": bool(waiting)}]
        s.commit()
        return store.to_dict(t)


# ------------------------------------------------------------------------------------------------ the evidence
def _outcome(t: dict, bars: pd.DataFrame) -> dict:
    """What the price did after one touch: forward returns from the price actually paid (or the touch price when nothing was bought),
    whether it broke down below the level, whether a rally was missed."""
    day = _day(t["touched_at"])
    after = bars[bars.index >= day]
    base = t["entry_price"] or t["touch_price"]
    out = {"cost_vs_touch": ((t["entry_price"] / t["touch_price"]) - 1) if t["entry_price"] else None, "ret20": None, "ret60": None,
           "broke_down": None, "missed_rally": None}
    if len(after) > 1:
        w = after.iloc[1:WINDOW_BARS + 1]
        if len(after) > WINDOW_BARS:
            out["ret20"] = float(after["close"].iloc[WINDOW_BARS] / base - 1)
        if len(after) > LONG_BARS:
            out["ret60"] = float(after["close"].iloc[LONG_BARS] / base - 1)
        if len(w) >= 5:
            out["broke_down"] = bool(w["low"].min() < t["level"] * (1 - BREAKDOWN_PCT))
            out["missed_rally"] = bool(t["status"] != "entered" and w["high"].max() > t["level"] * (1 + BREAKDOWN_PCT))
    return out


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def stats(history_fn: Callable[[str], pd.DataFrame] | None = None) -> dict:
    """Groups (on_touch / special / confirmed / waited_no_entry) with count, average cost vs the touch price, average 20- and 60-bar
    return, breakdown rate and missed-rally rate, plus a one-line verdict once there are MIN_FOR_VERDICT outcomes."""
    if history_fn is None:
        from vmi.data import market
        history_fn = lambda sym: market.history(sym, "2y")      # noqa: E731
    with store.session() as s:
        touches = [store.to_dict(t) for t in s.scalars(select(store.SupportTouch).order_by(store.SupportTouch.touched_at))]
    cache: dict[str, pd.DataFrame] = {}
    groups: dict[str, list[dict]] = {k: [] for k in (*ENTRY_TYPES, "untyped", "waited_no_entry")}
    for t in touches:
        if t["status"] == "open" and not t["entry_price"]:
            continue                                            # still live: no outcome yet
        if t["symbol"] not in cache:
            try:
                b = history_fn(t["symbol"])
                b = b.copy()
                b.index = [_day(i) for i in b.index]
                cache[t["symbol"]] = b
            except Exception:
                cache[t["symbol"]] = pd.DataFrame(columns=["open", "high", "low", "close"])
        o = _outcome(t, cache[t["symbol"]]) if not cache[t["symbol"]].empty else {}
        key = (t["entry_type"] or "untyped") if t["status"] == "entered" else "waited_no_entry"
        groups[key].append({**t, **o})
    table = {}
    for k, rows in groups.items():
        n = len(rows)
        bd = [r.get("broke_down") for r in rows if r.get("broke_down") is not None]
        mr = [r.get("missed_rally") for r in rows if r.get("missed_rally") is not None]
        table[k] = {"n": n, "avg_cost_vs_touch": _mean([r.get("cost_vs_touch") for r in rows]),
                    "avg_ret20": _mean([r.get("ret20") for r in rows]), "avg_ret60": _mean([r.get("ret60") for r in rows]),
                    "breakdown_rate": (sum(bd) / len(bd)) if bd else None, "missed_rate": (sum(mr) / len(mr)) if mr else None,
                    "symbols": sorted({r["symbol"] for r in rows})[:12]}
    return {"groups": table, "verdict": _verdict(table), "n_touches": len(touches),
            "open_now": sum(1 for t in touches if t["status"] == "open" and not t["entry_price"]),
            "definitions": {"on_touch": "bought as price touched the level", "confirmed": "bought after price confirmed the level held",
                            "special": "bought for another reason (gap, news ...)", "waited_no_entry": "touch ended without a buy",
                            "breakdown": f"price fell more than {BREAKDOWN_PCT:.0%} below the level within {WINDOW_BARS} bars"}}


def _verdict(table: dict) -> str:
    on, conf = table["on_touch"], table["confirmed"]
    if on["n"] + conf["n"] + table["waited_no_entry"]["n"] < MIN_FOR_VERDICT:
        return f"Not enough data yet ({on['n'] + conf['n'] + table['waited_no_entry']['n']} finished touches; a verdict needs {MIN_FOR_VERDICT})."
    if not on["n"] or not conf["n"]:
        return "Both on-touch and confirmed entries are needed to compare them."
    parts = []
    if on["avg_cost_vs_touch"] is not None and conf["avg_cost_vs_touch"] is not None:
        parts.append(f"confirmed entries paid {conf['avg_cost_vs_touch'] - on['avg_cost_vs_touch']:+.1%} versus on-touch entries")
    if on["avg_ret20"] is not None and conf["avg_ret20"] is not None:
        parts.append(f"20-bar return {conf['avg_ret20']:+.1%} (confirmed, n={conf['n']}) vs {on['avg_ret20']:+.1%} (on touch, n={on['n']})")
    if on["breakdown_rate"] is not None:
        parts.append(f"{on['breakdown_rate']:.0%} of touches broke down")
    if table["waited_no_entry"]["missed_rate"] is not None:
        parts.append(f"{table['waited_no_entry']['missed_rate']:.0%} of unbought touches then rallied")
    return "; ".join(parts) + "." if parts else "No outcome data yet."
