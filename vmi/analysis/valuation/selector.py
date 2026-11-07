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
from vmi.analysis.consistency import consistent, is_turnaround
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


# Cash flow distorted by customer funds / lending (marketplace float, fintech): Adam values "finance companies,
# insurance companies, brokers and asset management companies" by discounted net income because "their cash flow is
# affected by loans they give and loans redeemed, or customers putting cash into the funds" (Master doc l.1568).
# Measured as the share of CFO that is working-capital movement rather than earnings (MELI's Mercado Pago).
WC_DISTORTION = 0.5


def working_capital_share(f) -> float | None:
    """(CFO − NI − D&A − SBC) / CFO: how much of operating cash flow is working-capital movement, not earnings."""
    cfo, ni = f.last("cfo"), f.last("net_income")
    if not cfo or cfo <= 0 or ni is None:
        return None
    da, sbc = f.last("d_and_a") or 0.0, f.last("sbc") or 0.0
    return (cfo - ni - da - sbc) / cfo


# Turnaround (Adam's Category 7, l.2898): a great business whose profits fell temporarily. Valued by his default DCF on the
# normal base. (An earlier version averaged the last 4 years citing l.2502; fed Adam's own growth, the plain TTM base fits his
# turnarounds - UNH 1.07, NKE 1.18 of his IV - while the 4-year average overshoots them 1.47 / 2.32, so it was dropped.)
TURNAROUND = ("Turnaround (profits fell >25% or 2 years in a row) → Discounted Free Cash Flow; consistency checks are waived "
              "(Adam: a great business with a temporary profit drop)")

# Neither CFO nor net income consistent: the company fails Step 1 ("he won't buy it; it wouldn't pass the first five
# steps", Master doc l.2258). Any value is for reference only, and the one method Adam names for a business with
# inconsistent profits is Price-to-Sales ("if forced to value Singapore Airlines, the only method he could use is the
# price to sales ratio method", l.1510).
REFERENCE_ONLY = ("Neither CFO nor net income consistent → fails Step 1 (do not buy); Price-to-Sales shown for reference "
                  "(Adam: the only method for inconsistent profits)")


def candidate_methods(ctx: ValuationContext, biz: BizType) -> tuple[list[str], str]:
    f = ctx.fund
    cfo_ok = consistent(f, "cfo", ctx.rules)
    ni_ok = consistent(f, "net_income", ctx.rules)
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
        fcf_ttm = f.last("fcf")
        if ni_ttm > 0 and (cfo_ttm or 0) > 0 and (fcf_ttm or 0) > 0:
            # Adam values speculative growth with P/S or PSG only when there are no consistent profits and cash flow
            # (l.2264, l.2858). Already profitable with positive cash flow → his default DCF; the category (½ position,
            # upgrade after 5 years) is unchanged.
            return (["dcf_fcf", "dcf_normalized", "psg", "ps_mean"],
                    "Speculative growth but already profitable with positive cash flow → Discounted Free Cash Flow "
                    "(Adam: P/S growth only without consistent profits and cash flow)")
        return ["psg", "ps_mean", "dcf_fcf"], "Speculative growth (unprofitable, revenue ≥50%) → Price-to-Sales-Growth"
    if ni_ttm < 0 and not cfo_ok:
        return ["pb_distressed", "ps_mean", "psg"], "Loss-making → Price-to-Book (≤0.5× liquidation value)"
    if biz in (BizType.CYCLICAL, BizType.UTILITY) and not (cfo_ok and ni_ok):
        return ["ps_mean", "pb_distressed", "dcf_normalized"], "Cyclical with inconsistent profits → mean Price-to-Sales"
    wc = working_capital_share(f)
    if cfo_ok and ni_ok and wc is not None and wc > WC_DISTORTION:
        return (["dni", "dcf_normalized", "dcf_fcf"],
                f"{wc:.0%} of operating cash flow is customer funds / working capital, not earnings → Discounted Net "
                "Income (Adam: cash flow distorted by loans and customer funds, as for finance companies)")
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
    # Neither consistent: reference value only. Distressed P/B is reserved for genuinely loss-making
    # companies (handled above) — never applied to a profitable business as a fallback.
    if is_turnaround(f, ctx.rules):
        return ["dcf_fcf", "dni", "ps_mean"], TURNAROUND
    return ["ps_mean", "dni", "dcf_fcf"], REFERENCE_ONLY


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
    elif reason == TURNAROUND:  # consistency preconditions are waived by definition: first method with a value
        selected = next((m for m in order if results.get(m) and (results[m].intrinsic_value or 0) > 0), None)
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
