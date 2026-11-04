"""Automatic valuation-method selection — Adam's decision sequence (Lesson 5 §11 / §14).

    bank                       → P/B (5y avg × BVPS)
    REIT                       → P/NAV + yield
    insurance / asset manager  → Discounted Net Income
    speculative growth         → PSG (and mean P/S)
    cyclical / inconsistent    → mean P/S   (P/B ≤0.5 if loss-making)
    normal:
        CFO consistent & capex lumpy        → DCF normalised capex   (hyperscalers)
        CFO consistent                      → DCF on FCF (default); DCF on CFO allowed if CFO ≤1.2×NI
        CFO inconsistent, NI consistent     → Discounted Net Income
        neither                             → fails Step 1; mean P/S shown for reference
        loss-making                         → P/B distressed

Every candidate is computed and returned so a human reviewer can override the pick
(e.g. force `dcf_normalized` when news says a company is in a capex super-cycle).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from vmi.analysis.classify import BizType
from vmi.analysis.trends import trend
from vmi.analysis.valuation.core import ValuationResult
from vmi.analysis.valuation.methods import REGISTRY, ValuationContext, capex_is_lumpy


@dataclass
class ValuationReport:
    biz_type: str
    selected: str
    selection_reason: str
    intrinsic_value: float | None
    conservative_value: float | None
    price: float
    margin_of_safety: float | None          # (IV − price) / IV
    methods: dict[str, ValuationResult] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["methods"] = {k: v.to_dict() for k, v in self.methods.items()}
        return d


def candidate_methods(ctx: ValuationContext, biz: BizType) -> tuple[list[str], str]:
    f = ctx.fund
    cfo_ok = trend(f.series("cfo")[-6:]).consistent
    ni_ok = trend(f.series("net_income")[-6:]).consistent
    ni_ttm = f.last("net_income") or 0
    cfo_ttm, ni = f.last("cfo"), f.last("net_income")

    if biz == BizType.BANK:
        return ["pb_bank", "dni", "yield"], "Bank → Price-to-Book (banks are never valued by DCF)"
    if biz == BizType.REIT:
        return ["pnav_reit", "yield", "dcf_cfo"], "REIT → Price-to-NAV/Book + dividend yield"
    if biz in (BizType.INSURANCE, BizType.ASSET_MANAGER):
        order = ["dni", "pb_bank", "dcf_fcf"] if ni_ok else ["pb_bank", "dni"]
        return order, "Finance/insurance/asset manager → Discounted Net Income (cash flow distorted by flows)"
    if biz == BizType.SPECULATIVE:
        return ["psg", "ps_mean", "dcf_fcf"], "Speculative growth (unprofitable, revenue ≥50%) → Price-to-Sales-Growth"
    if ni_ttm < 0 and not cfo_ok:
        return ["pb_distressed", "ps_mean", "psg"], "Loss-making → Price-to-Book (≤0.5× liquidation value)"
    if biz in (BizType.CYCLICAL, BizType.UTILITY) and not (cfo_ok and ni_ok):
        return ["ps_mean", "pb_distressed", "dcf_normalized"], "Cyclical with inconsistent profits → mean Price-to-Sales"
    if cfo_ok:
        if capex_is_lumpy(f, ctx.rules):
            return (["dcf_normalized", "dcf_fcf", "dcf_cfo", "dni"],
                    "CFO consistent but capex lumpy/spiking → DCF with normalised capex (CFO − 5y avg capex)")
        cfo_close = bool(cfo_ttm and ni and ni > 0
                         and cfo_ttm <= ni * (1 + ctx.rules.valuation.cfo_max_premium_over_ni))
        return (["dcf_fcf", "dcf_cfo", "dcf_normalized", "dni"],
                "CFO consistently increasing → Discounted Free Cash Flow (default)"
                + ("; CFO within 20% of NI so DCF-on-CFO also allowed" if cfo_close else ""))
    if ni_ok:
        return ["dni", "ps_mean"], "CFO inconsistent but net income consistent → Discounted Net Income"
    return ["ps_mean", "pb_distressed"], ("Neither CFO nor net income consistent → fails Step 1 (do not buy); "
                                          "mean P/S shown for reference only")


def value_company(ctx: ValuationContext, biz: BizType, force_method: str | None = None) -> ValuationReport:
    order, reason = candidate_methods(ctx, biz)
    to_run = list(dict.fromkeys(order + ["peg", "yield"] + ([force_method] if force_method else [])))
    results: dict[str, ValuationResult] = {}
    for m in to_run:
        fn = REGISTRY.get(m)
        if not fn:
            continue
        try:
            results[m] = fn(ctx)
        except Exception as exc:  # one bad method must never break the report
            results[m] = ValuationResult(m, m, False, reasons=[f"error: {exc}"])

    selected = None
    if force_method and force_method in results and results[force_method].intrinsic_value:
        selected, reason = force_method, f"User override → {results[force_method].label}"
    else:
        for m in order:
            r = results.get(m)
            if r and r.applicable and r.intrinsic_value and r.intrinsic_value > 0:
                selected = m
                break
        if selected is None:
            for m in order:
                r = results.get(m)
                if r and r.intrinsic_value and r.intrinsic_value > 0 and m not in ("peg", "yield"):
                    selected = m
                    reason += f" | preconditions not fully met — showing {r.label} for reference"
                    break
    iv = results[selected].intrinsic_value if selected else None
    cons = results[selected].conservative if selected else None
    mos = (iv - ctx.price) / iv if iv and iv > 0 and ctx.price else None
    return ValuationReport(biz_type=biz.value, selected=selected or "", selection_reason=reason,
                           intrinsic_value=iv, conservative_value=cons, price=ctx.price, margin_of_safety=mos,
                           methods=results, candidates=order, notes=list(ctx.notes))
