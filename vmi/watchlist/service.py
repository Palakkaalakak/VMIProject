"""Tracked watchlists (Lesson 9 §3): great businesses (Steps 1–5 passed) waiting for the right price.

Each item carries an intrinsic value (manual or auto from the valuation engine) and 3–4 buy levels
(manual or auto from technicals). `check_all()` runs while the app is open (background loop in the API)
and raises in-app alerts when BOTH entry conditions are met (Lesson 9 §3.1):
    1. price below intrinsic value, AND
    2. price has waved down to an identified support / buy level.
Also flags: price crossing below IV, and parabolic moves (covered-call opportunity / don't chase).

Import formats accepted:
  * one ticker per line / comma-separated
  * "TICKER|s1,s2,s3|IV"  (same format as Adam's reference list)
  * CSV with columns symbol[,iv][,supports]  (supports separated by ; or space)
  * TradingView / IBKR exports (lines like "NASDAQ:AAPL" — the exchange prefix is stripped)
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from vmi import store
from vmi.data import market
from vmi.rules import RULES

log = logging.getLogger("vmi.watchlist")
_SYM = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _clean_symbol(raw: str) -> str | None:
    s = raw.strip().upper()
    if ":" in s:
        s = s.split(":", 1)[1]
    s = s.replace(" ", "")
    return s if _SYM.match(s) else None


# --------------------------------------------------------------------------------------- CRUD
def create(name: str) -> dict:
    with store.session() as s:
        if s.scalar(select(store.Watchlist).where(store.Watchlist.name == name)):
            raise ValueError(f"watchlist '{name}' exists")
        w = store.Watchlist(name=name)
        s.add(w)
        s.commit()
        return store.to_dict(w)


def list_all() -> list[dict]:
    with store.session() as s:
        out = []
        for w in s.scalars(select(store.Watchlist).order_by(store.Watchlist.id)):
            out.append({**store.to_dict(w), "count": len(w.items)})
        return out


def get(wid: int) -> dict:
    with store.session() as s:
        w = s.get(store.Watchlist, wid)
        if not w:
            raise ValueError("watchlist not found")
        items = [enrich(store.to_dict(i)) for i in w.items]
        return {**store.to_dict(w), "items": sorted(items, key=lambda i: i.get("distance_to_level") or 9e9)}


def delete(wid: int) -> None:
    with store.session() as s:
        w = s.get(store.Watchlist, wid)
        if w:
            s.delete(w)
            s.commit()


def upsert_item(wid: int, symbol: str, intrinsic_value: float | None = None, supports: list[float] | None = None,
                notes: str | None = None, iv_source: str | None = None) -> dict:
    sym = _clean_symbol(symbol)
    if not sym:
        raise ValueError(f"bad symbol '{symbol}'")
    with store.session() as s:
        it = s.scalar(select(store.WatchItem).where(store.WatchItem.watchlist_id == wid, store.WatchItem.symbol == sym))
        if it is None:
            it = store.WatchItem(watchlist_id=wid, symbol=sym, supports=[], triggered=[])
            s.add(it)
        if intrinsic_value is not None:
            it.intrinsic_value = float(intrinsic_value)
            it.iv_source = iv_source or "manual"
        if supports is not None:
            it.supports = sorted({round(float(x), 4) for x in supports if x}, reverse=True)
            it.triggered = []
        if notes is not None:
            it.notes = notes
        s.commit()
        return store.to_dict(it)


def remove_item(wid: int, symbol: str) -> None:
    with store.session() as s:
        it = s.scalar(select(store.WatchItem).where(store.WatchItem.watchlist_id == wid,
                                                    store.WatchItem.symbol == symbol.upper()))
        if it:
            s.delete(it)
            s.commit()


def parse_import(text: str) -> list[dict]:
    """→ [{symbol, iv, supports}] from any supported format."""
    rows: list[dict] = []
    text = text.strip()
    if not text:
        return rows
    first = text.splitlines()[0].lower()
    if "symbol" in first and ("," in first or "\t" in first):
        rdr = csv.DictReader(io.StringIO(text), dialect="excel-tab" if "\t" in first else "excel")
        for r in rdr:
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            sym = _clean_symbol(r.get("symbol") or r.get("ticker") or "")
            if not sym:
                continue
            iv = r.get("iv") or r.get("intrinsic_value") or r.get("intrinsic value")
            sup = re.split(r"[;\s/]+", r.get("supports") or r.get("buy_levels") or "")
            rows.append({"symbol": sym, "iv": float(iv) if iv else None,
                         "supports": [float(x) for x in sup if re.match(r"^\d+(\.\d+)?$", x)]})
        return rows
    for line in text.replace(";", "\n").splitlines():
        line = line.strip().strip('"')
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = line.split("|")
            sym = _clean_symbol(parts[0])
            if not sym:
                continue
            sup = [float(x) for x in (parts[1].split(",") if len(parts) > 1 else []) if x.strip()]
            iv = float(parts[2]) if len(parts) > 2 and parts[2].strip() else None
            rows.append({"symbol": sym, "iv": iv, "supports": sup})
        else:
            for tok in re.split(r"[,\s]+", line):
                sym = _clean_symbol(tok)
                if sym:
                    rows.append({"symbol": sym, "iv": None, "supports": []})
    return rows


def import_text(wid: int, text: str, auto_fill: bool = False) -> dict:
    rows = parse_import(text)
    for r in rows:
        upsert_item(wid, r["symbol"], r["iv"], r["supports"] or None)
    if auto_fill:
        for r in rows:
            if r["iv"] is None or not r["supports"]:
                try:
                    autofill(wid, r["symbol"], only_missing=True)
                except Exception as exc:
                    log.info("autofill %s failed: %s", r["symbol"], exc)
    return {"imported": len(rows), "symbols": [r["symbol"] for r in rows]}


def autofill(wid: int, symbol: str, only_missing: bool = False) -> dict:
    """Fill IV + buy levels from the analysis pipeline (respecting per-ticker overrides)."""
    from vmi.analysis.pipeline import analyse_ticker

    rep = analyse_ticker(symbol, with_technicals=True, overrides=store.get_override(symbol))
    with store.session() as s:
        it = s.scalar(select(store.WatchItem).where(store.WatchItem.watchlist_id == wid,
                                                    store.WatchItem.symbol == symbol.upper()))
        cur_iv = it.intrinsic_value if it else None
        cur_sup = list(it.supports) if it else []
    iv = rep.get("intrinsic_value")
    levels = [b["price"] for b in (rep.get("technicals") or {}).get("buy_levels", [])]
    return upsert_item(wid, symbol,
                       intrinsic_value=None if (only_missing and cur_iv) else iv,
                       supports=None if (only_missing and cur_sup) else (levels or None),
                       iv_source="auto")


# --------------------------------------------------------------------------------------- monitoring
def enrich(item: dict, price: float | None = None) -> dict:
    px = price if price is not None else item.get("last_price")
    iv = item.get("intrinsic_value")
    sup = item.get("supports") or []
    item["price"] = px
    item["margin_of_safety"] = (iv - px) / iv if iv and px else None
    below = [l for l in sup if px and l <= px]
    above = [l for l in sup if px and l > px]
    nxt = max(below) if below else None
    item["next_level"] = nxt
    item["distance_to_level"] = (px - nxt) / px if nxt and px else None
    item["levels_hit"] = len(above)
    item["in_buy_zone"] = bool(px and iv and px < iv and (
        any(abs(px - l) / l <= RULES.technical.near_level_pct for l in sup) or above))
    return item


def check_all() -> list[dict]:
    """Refresh prices for every watched symbol and create alerts for newly triggered conditions."""
    new_alerts: list[dict] = []
    with store.session() as s:
        items = list(s.scalars(select(store.WatchItem)))
        symbols = sorted({i.symbol for i in items})
        prices: dict[str, float | None] = {}
        for sym in symbols:
            try:
                prices[sym] = market.last_price(sym)
            except Exception:
                prices[sym] = None
        tol = RULES.technical.near_level_pct
        for it in items:
            px = prices.get(it.symbol)
            if not px:
                continue
            prev = it.last_price
            it.last_price, it.last_checked = px, datetime.now(timezone.utc)
            iv = it.intrinsic_value
            trig = set(it.triggered or [])
            for lvl in it.supports or []:
                key = f"L{lvl}"
                hit = px <= lvl * (1 + tol)
                if hit and key not in trig and (iv is None or px < iv):
                    msg = (f"{it.symbol} at {px:.2f} reached buy level {lvl:g}"
                           + (f" — {((iv - px) / iv):.0%} below IV {iv:.2f}" if iv else "")
                           + ". Consider a tranche (Step 7).")
                    s.add(store.Alert(symbol=it.symbol, kind="buy_level", message=msg, price=px))
                    new_alerts.append({"symbol": it.symbol, "kind": "buy_level", "message": msg})
                    trig.add(key)
                elif px > lvl * (1 + 3 * tol) and key in trig:
                    trig.discard(key)          # re-arm once price has moved well away
            if iv and prev and prev >= iv > px and "IV" not in trig:
                msg = f"{it.symbol} crossed below intrinsic value {iv:.2f} (now {px:.2f}) — Step 6 satisfied."
                s.add(store.Alert(symbol=it.symbol, kind="below_iv", message=msg, price=px))
                new_alerts.append({"symbol": it.symbol, "kind": "below_iv", "message": msg})
                trig.add("IV")
            elif iv and px > iv * 1.03:
                trig.discard("IV")
            it.triggered = sorted(trig)
        s.commit()
    return new_alerts


def alerts(unseen_only: bool = False, limit: int = 100) -> list[dict]:
    with store.session() as s:
        q = select(store.Alert).order_by(store.Alert.id.desc()).limit(limit)
        if unseen_only:
            q = select(store.Alert).where(store.Alert.seen.is_(False)).order_by(store.Alert.id.desc()).limit(limit)
        return [store.to_dict(a) for a in s.scalars(q)]


def mark_seen(ids: list[int] | None = None) -> None:
    with store.session() as s:
        q = select(store.Alert).where(store.Alert.seen.is_(False))
        for a in s.scalars(q):
            if ids is None or a.id in ids:
                a.seen = True
        s.commit()
