"""Single-ticker VMI analysis: data → classification → Steps 1–5 → valuation (Step 6) → technicals (Step 7).

The one function the API, scanner deep-pass, watchlists and calibration all call, so behaviour is identical
everywhere. Per-ticker judgement overrides come in `overrides`; every key is declared in vmi/overrides.py.
"""
from __future__ import annotations

from typing import Any

from vmi.analysis import steps as S
from vmi.analysis import technicals as T
from vmi.analysis.classify import BizType, classify, sector_bucket
from vmi.analysis.valuation.growth import GrowthControls
from vmi.analysis.valuation.methods import ValuationContext
from vmi.analysis.valuation.selector import value_company
from vmi.data import market
from vmi.data.estimates import get_estimates
from vmi.data.fundamentals import resolve
from vmi.overrides import describe
from vmi.rules import RULES, VMIRules


def growth_rate(f, est) -> float | None:
    """Growth used for portfolio buckets: consensus 5y EPS growth, else revenue CAGR."""
    if est.eps_growth_5y is not None:
        return est.eps_growth_5y
    rev = f.series("revenue")[-6:]
    if len(rev) >= 3 and rev[0] > 0 and rev[-1] > 0:
        return (rev[-1] / rev[0]) ** (1 / (len(rev) - 1)) - 1
    return None


def category(biz: BizType, growth: float | None, f, rules: VMIRules = RULES) -> str:
    """Lesson 8 portfolio categories."""
    if biz == BizType.SPECULATIVE:
        return "speculative_growth"
    if biz == BizType.REIT:
        return "dividend"
    if biz == BizType.CYCLICAL:
        return "deep_cyclical"
    ni = f.series("net_income")
    if len(ni) >= 3 and ni[-2] > 0 and (ni[-1] < ni[-2] * (1 - rules.turnaround.profit_drop_one_year)
                                        or ni[-1] < ni[-2] < ni[-3]):
        return "turnaround"
    if growth is not None and growth >= rules.growth.large_growth_threshold:
        return "large_growth"
    if growth is not None and growth >= rules.growth.growth_stock_threshold:
        return "growth"
    return "predictable"


def analyse_ticker(ticker: str, *, with_technicals: bool = True, overrides: dict | None = None,
                   rules: VMIRules = RULES) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    ov = overrides or {}
    f = resolve(ticker)
    if f is None:
        raise ValueError(f"No fundamentals found for {ticker} from any source")
    est = get_estimates(ticker)
    price = market.last_price(ticker) or 0.0
    hist = market.history(ticker, "10y")  # always: historical P/B, P/S valuations need it (cached)

    rev = f.series("revenue")
    rg = (rev[-1] / rev[-2] - 1) if len(rev) >= 2 and rev[-2] > 0 else None
    prof = sum(1 for v in f.series("net_income")[-5:] if v > 0)
    biz = classify(f.sic, f.sic_description, est.sector or f.sector, est.industry or f.industry, rg, prof,
                   override=ov.get("biz_type"))

    ten_up = T.ten_year_uptrend(hist) if hist is not None and not hist.empty else None

    s1 = S.step1_track_record(f, biz, rules)
    s2 = S.step2_growth(est, f, rules)
    s3 = S.step3_moat(f, est, ten_up, biz, ov, rules, ten_year_return=_ten_year_return(hist))
    s4 = S.step4_profitability(f, biz, rules)
    s5 = S.step5_debt(f, biz, est, rules)

    ctx = ValuationContext(f, est, price, hist, rules,
                           growth_override=ov.get("growth"), growth_controls=growth_controls(ov),
                           growth_6_10_override=ov.get("growth_6_10"),
                           growth_11_20_override=ov.get("growth_11_20"), discount_override=ov.get("discount_rate"),
                           base_cf_override=ov.get("base_cf"), base_period=ov.get("base_period"),
                           beta_override=ov.get("beta"), shares_override=ov.get("shares"),
                           cash_override=ov.get("cash"), debt_override=ov.get("debt"),
                           haircut_override=ov.get("iv_haircut"))
    val = value_company(ctx, biz, ov.get("method"))
    iv = ov.get("iv_override") or val.intrinsic_value
    if ov.get("conservative_override"):
        val.conservative_value = ov["conservative_override"]
    s6 = S.step6_price(price, iv, val.conservative_value)

    tech_dict = None
    if with_technicals and hist is not None and not hist.empty:
        tech = T.analyse(hist, intrinsic_value=iv)   # buy levels must sit below IV
        tech_dict = tech.to_dict()
        tech_dict.pop("levels", None)
        if ov.get("buy_levels"):
            tech_dict["buy_levels"] = [{"tranche": i, "price": p, "source": "judgement override", "touches": None,
                                        "confirmed": True} for i, p in enumerate(ov["buy_levels"], 1)]
    s7 = S.step7_entry(tech_dict or {})
    g = growth_rate(f, est)
    cat = ov.get("category") or category(biz, g, f, rules)
    s1.notes += [w for w in f.warnings if w.startswith("revenue restated")]  # evidence for the reviewer
    _turnaround_exception(s1, s3, cat)
    steps = _apply_step_overrides([s1, s2, s3, s4, s5, s6, s7], ov)
    s1, s2, s3, s4, s5, s6, s7 = steps

    great = all(s.passed for s in (s1, s2, s3, s4, s5))
    moat_reviewed = bool(s3.extra.get("reviewed")) or ov.get("step3") in ("pass", "fail")
    moat = S.moat_grade(s3)
    alloc = 1.0
    if cat in ("speculative_growth", "turnaround"):
        alloc = rules.portfolio.speculative_multiplier
    elif moat == "narrow":
        alloc = rules.portfolio.narrow_moat_multiplier
    if ov.get("allocation_multiplier") is not None:
        alloc = ov["allocation_multiplier"]
    roe, roic = f.ratios.get("roe", []), f.ratios.get("roic", [])
    metrics = {
        "growth": g, "eps_growth_5y": est.eps_growth_5y, "revenue_cagr": s1.checks[0].value,
        "roe": roe[-1].value if roe else None, "roic": roic[-1].value if roic else None,
        "pe": est.pe, "peg": est.peg, "dividend_yield": est.dividend_yield, "beta": est.beta,
        "margin_of_safety": (iv - price) / iv if iv and price else None,
        "net_margin": (f.last("net_income") / f.last("revenue")) if f.last("revenue") else None,
        "market_cap": (est.extra.get("yahoo") or {}).get("market_cap"),
    }
    return {
        "ticker": ticker, "name": f.name or (est.extra.get("yahoo") or {}).get("name", ""), "price": price,
        "sector": est.sector or f.sector, "industry": est.industry or f.industry,
        "sector_bucket": sector_bucket(est.sector or f.sector), "biz_type": biz.value, "category": cat,
        "style": "growth" if (g or 0) >= rules.growth.growth_stock_threshold else "defensive",
        "moat": moat, "allocation_multiplier": alloc,
        "great_business": great, "undervalued": s6.passed, "entry_ok": s7.passed,
        # the moat is discretionary: a buy signal needs a reviewed moat (verdict or forced step-3 verdict)
        "moat_reviewed": moat_reviewed, "moat_hint": s3.extra.get("hint"),
        "vmi_pass": great and s6.passed and s7.passed and moat_reviewed,
        "watchlist_candidate": great and not s6.passed,
        "steps": [s.to_dict() for s in (s1, s2, s3, s4, s5, s6, s7)],
        "valuation": val.to_dict(), "intrinsic_value": iv, "technicals": tech_dict, "metrics": metrics,
        "estimates": {k: v for k, v in est.to_dict().items() if k != "extra"},
        "data": {"provenance": f.provenance, "completeness": f.meta.get("completeness"), "warnings": f.warnings,
                 "latest_date": f.latest_date, "currency": f.currency},
        "overrides": ov,
        "overrides_applied": describe(ov),
    }


def growth_controls(ov: dict) -> GrowthControls:
    """Per-ticker growth-input choices from the overrides (vmi/overrides.py: Growth group)."""
    return GrowthControls(source=ov.get("growth_source") or None, blend=ov.get("growth_blend") or None,
                          exclude=tuple(ov.get("exclude_sources") or ()), extra=dict(ov.get("extra_sources") or {}))


def _turnaround_exception(s1, s3, cat: str) -> None:
    """Adam's Category 7: a great business hit by temporary bad news, so profits fall while the moat stays
    intact. Step 1 then passes, but only when a reviewer confirmed the moat and sales are still rising
    (the dip is in profits, not in the business). The category's ½ position size applies separately."""
    if s1.passed or cat != "turnaround":
        return
    moat_ok = ((s3.extra.get("verdict") or {}).get("grade")) in ("wide", "narrow")
    sales_ok = any(c.name == "revenue_consistent" and c.passed for c in s1.checks)
    if moat_ok and sales_ok:
        s1.passed = True
        s1.notes.append("Turnaround exception (Adam, Category 7): profits fell temporarily, sales still rising and "
                        "the reviewed moat is intact; buy at ½–⅓ of a normal position only.")


def _ten_year_return(hist) -> float | None:
    if hist is None or hist.empty:
        return None
    close = hist["close"].dropna()
    if len(close) < 2 or (close.index[-1] - close.index[0]).days < 9 * 365 or close.iloc[0] <= 0:
        return None
    return float(close.iloc[-1] / close.iloc[0] - 1)


def _apply_step_overrides(steps: list, ov: dict) -> list:
    """`stepN: pass|fail` overrides force a step's verdict; the reason lives in the override note."""
    for s in steps:
        forced = ov.get(f"step{s.step}")
        if forced in ("pass", "fail"):
            s.passed = forced == "pass"
            s.notes.append(f"verdict forced to {forced.upper()} by judgement override"
                           + (f": {ov['note']}" if ov.get("note") else ""))
    return steps
