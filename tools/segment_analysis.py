"""Does the conservatism we need depend on the TYPE of company? (owner request 2026-11-05)

Every ticker in Adam's reference table is valued with the current rules ("auto") and with each fixed growth
blend, then grouped by every structural feature we know: style (growth/defensive), category, business type,
moat, sector bucket, valuation method, discount-rate band, number of analyst sources and their agreement.
For each group: n, median ours/Adam, over-valuations (>1.10), under-valuations (<0.75) and the flat change
that would move the median to 0.95 (positive = haircut needed, negative = we are too low).

A pattern only becomes a rule when (1) the group is big enough to mean something (n ≥ 5), (2) the bias is
large (median outside 0.80–1.05) and (3) there is a structural reason for it. Everything else stays a
per-ticker judgement. Results feed docs/CALIBRATION.md.

    PYTHONPATH=. python tools/segment_analysis.py            # → table + data/segment_analysis.json
"""
from __future__ import annotations

import json
import statistics

from vmi.analysis.calibrate import load_reference
from vmi.analysis.pipeline import analyse_ticker
from vmi.config import get_settings

VARIANTS = {"auto": {}, "lowest": {"growth_blend": "lowest"}, "median": {"growth_blend": "median"}}
TARGET = 0.95
MIN_N = 5


def _sources(r: dict) -> list[float]:
    return sorted(s["eps_growth_5y"] for s in r["estimates"]["sources"].values() if s.get("eps_growth_5y"))


def collect() -> list[dict]:
    rows = []
    for sym, ref in load_reference().items():
        if not ref["iv"] or not sym.isalpha():
            continue
        row: dict = {"symbol": sym, "adam_iv": ref["iv"]}
        try:
            for name, ov in VARIANTS.items():
                r = analyse_ticker(sym, with_technicals=False, overrides=ov or None)
                row[name] = (r["intrinsic_value"] or 0) / ref["iv"] or None
                if name == "auto":
                    v = r["valuation"]
                    inputs = (v["methods"].get(v["selected"]) or {}).get("inputs") or {}
                    src = _sources(r)
                    row.update(style=r["style"], category=r["category"], biz_type=r["biz_type"], moat=r["moat"],
                               sector=r["sector_bucket"], method=v["selected"], rate=inputs.get("discount_rate"),
                               growth=inputs.get("growth_1_5"), n_sources=len(src),
                               dispersion=(src[-1] / src[0]) if src and src[0] > 0 else None)
        except Exception as exc:  # one failing ticker must not stop the study
            row["error"] = str(exc)
        rows.append(row)
    return rows


FEATURES = {
    "style": lambda r: r.get("style"),
    "category": lambda r: r.get("category"),
    "biz_type": lambda r: r.get("biz_type"),
    "moat": lambda r: r.get("moat"),
    "sector bucket": lambda r: r.get("sector"),
    "method": lambda r: r.get("method"),
    "method family": lambda r: ("discounted (DCF/DNI)" if r.get("method") in ("dcf_fcf", "dcf_normalized", "dcf_cfo", "dni")
                                else "multiples (P/B, P/S, PSG)" if r.get("method") else None),
    "discount rate": lambda r: None if r.get("rate") is None else "≤6.0% (low beta)" if r["rate"] <= 0.06
                     else "6.0–7.0%" if r["rate"] <= 0.07 else ">7.0%",
    "growth input": lambda r: None if r.get("growth") is None else "<8%" if r["growth"] < 0.08
                    else "8–15%" if r["growth"] < 0.15 else "15–25%" if r["growth"] < 0.25 else "≥25%",
    "analyst sources": lambda r: {0: "none", 1: "one"}.get(r.get("n_sources"), "two or more"),
    "source agreement": lambda r: None if r.get("dispersion") is None or r.get("n_sources", 0) < 2
                        else "agree (<1.5×)" if r["dispersion"] < 1.5 else "disagree (≥1.5×)",
}


def stats(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x)
    if not xs:
        return {"n": 0}
    med = statistics.median(xs)
    return {"n": len(xs), "median": round(med, 3), "above110": sum(x > 1.10 for x in xs),
            "below075": sum(x < 0.75 for x in xs), "change_to_0.95": round(1 - TARGET / med, 3)}


def main() -> None:
    rows = collect()
    out: dict = {"rows": rows, "features": {}}
    print("overall:", {k: stats([r.get(k) for r in rows]) for k in VARIANTS})
    for feat, key in FEATURES.items():
        groups: dict[str, list[dict]] = {}
        for r in rows:
            if (g := key(r)) is not None and r.get("auto"):
                groups.setdefault(str(g), []).append(r)
        out["features"][feat] = {}
        print(f"\n{feat}")
        for g, rs in sorted(groups.items()):
            st = {k: stats([r.get(k) for r in rs]) for k in VARIANTS}
            out["features"][feat][g] = st
            a = st["auto"]
            flag = "  ◀ bias" if a["n"] >= MIN_N and not 0.80 <= a["median"] <= 1.05 else ""
            print(f"  {g:28s} n={a['n']:2d} auto={a['median']:.2f} lowest={st['lowest'].get('median', 0):.2f} "
                  f"median-blend={st['median'].get('median', 0):.2f} >1.10:{a['above110']} <0.75:{a['below075']} "
                  f"change→0.95 {a['change_to_0.95']:+.2f}{flag}  [{', '.join(r['symbol'] for r in rs)}]")
    (get_settings().data_dir / "segment_analysis.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
