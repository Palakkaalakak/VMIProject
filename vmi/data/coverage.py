"""Coverage audit: proves every company in a universe has every input the VMI checks need.

For each ticker: resolve fundamentals (SEC → stockanalysis → Yahoo → derived → FDIC) + estimates
(FinViz/Zacks/Yahoo/stockanalysis forecast). Any gap is re-fetched with `force=True` once; whatever
remains is written to data/coverage_<universe>.json with the exact missing fields, so gaps are visible
and fixable, never silently skipped.

Run:  python -m vmi.data.coverage sp500  [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from vmi.config import get_settings
from vmi.data import universe
from vmi.data.estimates import get_estimates
from vmi.data.fundamentals import completeness, resolve


def audit_one(sym: str) -> dict:
    t0 = time.time()
    rec: dict = {"symbol": sym}
    try:
        f = resolve(sym)
        if f is None:
            return {**rec, "ok": False, "fatal": "no fundamentals from any source"}
        comp = completeness(f, f.meta.get("biz", "normal"))
        if not comp["ok"]:  # one forced refresh across all sources
            f = resolve(sym, force=True) or f
            comp = completeness(f, f.meta.get("biz", "normal"))
        est = get_estimates(sym)
        growth_ok = est.eps_growth_5y is not None or est.eps_growth_next_year is not None \
            or est.revenue_growth_next_year is not None
        est_missing = [] if growth_ok else ["growth estimate"]
        if est.beta is None:
            est_missing.append("beta")
        rec.update({"ok": comp["ok"] and not est_missing, "biz": comp["biz"], "missing": comp["missing"] + est_missing,
                    "optional_missing": comp["optional_missing"], "latest_date": f.latest_date,
                    "provenance": sorted(set(v.split("+")[0] for v in f.provenance.values())),
                    "growth_sources": {k: v.get("eps_growth_5y") for k, v in est.sources.items()},
                    "secs": round(time.time() - t0, 1)})
    except Exception as exc:
        rec.update({"ok": False, "fatal": f"{type(exc).__name__}: {exc}"[:300]})
    return rec


def run(universe_name: str = "sp500", workers: int = 4, symbols: list[str] | None = None) -> dict:
    if symbols is None:
        symbols = [r["symbol"] for r in (universe.sp500() if universe_name == "sp500" else universe.us_market())]
    out_path = get_settings().data_dir / f"coverage_{universe_name}.json"
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(audit_one, s): s for s in symbols}
        for i, fut in enumerate(as_completed(futs), 1):
            results.append(fut.result())
            if i % 25 == 0 or i == len(symbols):
                summary = _summary(results, len(symbols))
                out_path.write_text(json.dumps({"summary": summary, "results": sorted(results, key=lambda r: r["symbol"])},
                                               indent=1, default=str))
                print(f"[{i}/{len(symbols)}] ok={summary['ok']} gaps={summary['gaps']}", flush=True)
    return _summary(results, len(symbols))


def _summary(results: list[dict], total: int) -> dict:
    ok = sum(1 for r in results if r.get("ok"))
    from collections import Counter

    field_gaps = Counter(m.split(" (")[0] for r in results for m in r.get("missing", []))
    return {"total": total, "done": len(results), "ok": ok, "gaps": len(results) - ok,
            "gap_fields": dict(field_gaps.most_common()),
            "gap_symbols": sorted(r["symbol"] for r in results if not r.get("ok"))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("universe", nargs="?", default="sp500")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--symbols", nargs="*")
    a = ap.parse_args()
    print(json.dumps(run(a.universe, a.workers, a.symbols), indent=1))
