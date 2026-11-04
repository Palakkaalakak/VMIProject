"""The VMI valuation methods (Lesson 5). Each method is a pure function:

    method(ctx: ValuationContext) -> ValuationResult

so new methods can be registered without touching the selector (see REGISTRY at the bottom).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from vmi.analysis.consistency import series_trend
from vmi.analysis.trends import mean, stdev, trend
from vmi.analysis.valuation.core import (Scenario, ValuationResult, discount_rate, discounted_value,
                                         growth_path)
from vmi.data.models import Estimates, Fundamentals
from vmi.rules import RULES, VMIRules


@dataclass
class ValuationContext:
    fund: Fundamentals
    est: Estimates
    price: float
    history: pd.DataFrame | None = None       # daily OHLCV for historical P/B, P/S
    rules: VMIRules = RULES
    # user overrides (all optional)
    growth_override: float | None = None      # years 1–5
    growth_6_10_override: float | None = None
    growth_11_20_override: float | None = None
    discount_override: float | None = None
    base_cf_override: float | None = None
    notes: list[str] = field(default_factory=list)

    # ----- currency (Lesson 5 §6.1: statement currency vs share-price currency)
    @property
    def statement_currency(self) -> str:
        y = (self.est.extra or {}).get("yahoo") or {}
        return (y.get("financial_currency") or self.fund.currency or "USD").upper()

    @property
    def price_currency(self) -> str:
        y = (self.est.extra or {}).get("yahoo") or {}
        return (y.get("currency") or "USD").upper()

    @property
    def fx(self) -> float:
        """Multiply statement-currency amounts by this to get price-currency amounts."""
        if self.statement_currency == self.price_currency:
            return 1.0
        try:
            from vmi.data.fx import rate
            return rate(self.statement_currency, self.price_currency)
        except Exception:
            self.notes.append(f"FX {self.statement_currency}->{self.price_currency} unavailable; assumed 1.0")
            return 1.0

    def money(self, v: float | None) -> float | None:
        return None if v is None else v * self.fx

    # ----- shared derived inputs (Lesson 5 §4.5)
    @property
    def debt(self) -> float:
        f = self.fund
        return self.fx * (abs(f.latest.get("lt_debt", 0.0)) + abs(f.latest.get("st_debt", 0.0)))

    @property
    def cash(self) -> float:
        f = self.fund
        return self.fx * (f.latest.get("cash", 0.0) + f.latest.get("st_investments", 0.0))

    @property
    def filing_shares(self) -> float | None:
        f = self.fund
        q = f.quarterly.get("shares_diluted")
        if q:
            return q[-1].value
        dil = f.annual.get("shares_diluted")
        if dil:
            return dil[-1].value
        return f.latest.get("shares_outstanding")

    @property
    def shares(self) -> float | None:
        """Shares in *price units*. Normally the latest diluted count; when that disagrees with
        market-cap ÷ price by >25% (ADR ratios, multiple share classes like BRK-B) the price-implied
        count is used so that IV is per traded unit."""
        filing = self.filing_shares
        y = (self.est.extra or {}).get("yahoo") or {}
        mcap = y.get("market_cap")
        implied = mcap / self.price if mcap and self.price else None
        if implied and (not filing or abs(filing / implied - 1) > 0.25):
            if filing:
                self.notes.append(f"share count {filing / 1e6:.0f}M ≠ price-implied {implied / 1e6:.0f}M "
                                  "(ADR ratio / share classes) — using price-implied units")
            return implied
        return filing

    @property
    def beta(self) -> float | None:
        return self.est.beta

    @property
    def rate(self) -> float:
        return self.discount_override or discount_rate(self.beta, self.rules.valuation)

    @property
    def growth_choice(self):
        from vmi.analysis.valuation.growth import choose_growth
        return choose_growth(self.est, self.fund, self.rules)

    @property
    def growth(self) -> float | None:
        if self.growth_override is not None:
            return self.growth_override
        return self.growth_choice.value

    def ttm(self, concept: str) -> float | None:
        """Latest 12-month value converted to price currency."""
        return self.money(self.fund.last(concept))


def _dcf_family(ctx: ValuationContext, method: str, label: str, base: float | None,
                base_desc: str, reasons: list[str]) -> ValuationResult:
    g = ctx.growth
    res = ValuationResult(method, label, applicable=not reasons, reasons=reasons)
    if base is None or base <= 0:
        res.applicable = False
        res.reasons.append(f"{base_desc} not positive")
        return res
    if g is None:
        res.applicable = False
        res.reasons.append("no consensus growth estimate (set an override)")
        return res
    if ctx.base_cf_override is not None:
        base = ctx.base_cf_override
        base_desc += " (user override)"
    rate, shares = ctx.rate, ctx.shares
    path = growth_path(g, g6_10=ctx.growth_6_10_override, g11_20=ctx.growth_11_20_override)
    base_iv = discounted_value(base, path, rate, ctx.debt, ctx.cash, shares, ctx.rules.valuation.horizon_years)
    gc = ctx.growth_choice
    low = min(gc.low if gc.low is not None else g, g)
    cons_path = growth_path(low, g6_10=min(low, ctx.rules.growth.cap_years_6_10) * 0.85)
    cons = discounted_value(base, cons_path, rate, ctx.debt, ctx.cash, shares)
    doom_path = growth_path(low, g6_10=low * ctx.rules.valuation.doomsday_growth_factor,
                            g11_20=ctx.rules.growth.conservative_years_11_20)
    doom = discounted_value(base, doom_path, rate, ctx.debt, ctx.cash, shares)
    hc = 1.0 - ctx.rules.valuation.iv_haircut
    base_iv, cons, doom = (None if v is None else v * hc for v in (base_iv, cons, doom))
    res.intrinsic_value = base_iv
    res.scenarios = [Scenario("base", base_iv, path, "avg of sources; yrs 6–10 capped at 15%; yrs 11–20 4%"),
                     Scenario("conservative", cons, cons_path, "lowest source; yrs 6–10 trimmed"),
                     Scenario("doomsday", doom, doom_path, "lowest source; growth halves after yr 5; 2% terminal")]
    res.inputs = {"base_cash_flow": base, "base_desc": base_desc, "debt": ctx.debt, "cash": ctx.cash,
                  "shares": shares, "beta": ctx.beta, "discount_rate": rate, "growth_1_5": path.g1_5,
                  "growth_6_10": path.g6_10, "growth_11_20": path.g11_20,
                  "growth_sources": ctx.est.sources, "growth_method": gc.method, "growth_notes": gc.notes,
                  "iv_haircut": ctx.rules.valuation.iv_haircut,
                  "statement_currency": ctx.statement_currency, "fx": ctx.fx, "notes": list(ctx.notes)}
    return res


# --------------------------------------------------------------------------------------- DCF (FCF)
def dcf_fcf(ctx: ValuationContext) -> ValuationResult:
    cfo_tr = series_trend(ctx.fund, "cfo", ctx.rules)
    reasons = [] if cfo_tr.consistent else [f"CFO not consistently increasing ({cfo_tr.reason})"]
    return _dcf_family(ctx, "dcf_fcf", "Discounted Free Cash Flow", ctx.ttm("fcf"), "TTM free cash flow", reasons)


def capex_window(fund: Fundamentals, years: int = 5) -> list[float]:
    """The most recent 12-month capex figures: TTM (if newer than the last FY) + preceding fiscal years."""
    annual = [abs(v) for v in fund.series("capex")]
    ttm = fund.ttm.get("capex")
    last_fy = annual[-1] if annual else None
    if ttm is not None and last_fy is not None and abs(abs(ttm) - last_fy) > 0.01 * max(1.0, last_fy):
        return (annual + [abs(ttm)])[-years:]
    return annual[-years:]


def capex_is_lumpy(fund: Fundamentals, rules: VMIRules = RULES) -> bool:
    """Capex 'lumpy' ⇒ normalise. Only when capex is MATERIAL (≥10% of CFO) — tiny capex in asset-light
    names (MA/V) can double without meaning anything — and either the latest 12m capex spiked ≥1.5× the
    prior years' average, or FCF lost its uptrend while CFO kept it."""
    win = capex_window(fund, 6)
    if len(win) < 4:
        return False
    cfo = fund.last("cfo") or 0
    latest, prior = win[-1], mean(win[:-1]) or 0
    if cfo <= 0 or latest < 0.10 * cfo:
        return False
    spike = prior > 0 and latest > rules.valuation.capex_spike_ratio * prior
    fcf_broken = not trend(fund.series("fcf")[-6:]).consistent and series_trend(fund, "cfo", rules).consistent
    return spike or fcf_broken


def normalised_fcf(fund: Fundamentals, years: int = 5) -> float | None:
    """Latest 12-month CFO − average capex of the 5 most recent 12-month periods (Lesson 5 §5.2)."""
    cfo = fund.last("cfo")
    capex = capex_window(fund, years)
    if cfo is None or not capex:
        return None
    return cfo - sum(capex) / len(capex)


def dcf_normalized(ctx: ValuationContext) -> ValuationResult:
    cfo_tr = series_trend(ctx.fund, "cfo", ctx.rules)
    reasons = [] if cfo_tr.consistent else [f"CFO not consistently increasing ({cfo_tr.reason})"]
    base = ctx.money(normalised_fcf(ctx.fund, ctx.rules.valuation.capex_normalization_years))
    r = _dcf_family(ctx, "dcf_normalized", "DCF — Normalised capex (CFO − 5y avg capex)", base,
                    "normalised FCF", reasons)
    r.extra["capex_5y"] = capex_window(ctx.fund, ctx.rules.valuation.capex_normalization_years)
    r.extra["lumpy_capex"] = capex_is_lumpy(ctx.fund, ctx.rules)
    return r


def dcf_cfo(ctx: ValuationContext) -> ValuationResult:
    cfo, ni = ctx.ttm("cfo"), ctx.ttm("net_income")
    reasons = []
    cfo_tr = series_trend(ctx.fund, "cfo", ctx.rules)
    if not cfo_tr.consistent:
        reasons.append(f"CFO not consistently increasing ({cfo_tr.reason})")
    if cfo and ni and ni > 0 and cfo > ni * (1 + ctx.rules.valuation.cfo_max_premium_over_ni):
        reasons.append(f"CFO {cfo / ni - 1:.0%} above net income (>20% — use FCF instead)")
    if not ni or ni <= 0:
        reasons.append("net income not positive")
    return _dcf_family(ctx, "dcf_cfo", "Discounted Cash Flow from Operations", cfo, "TTM CFO", reasons)


def discounted_net_income(ctx: ValuationContext) -> ValuationResult:
    ni_tr = series_trend(ctx.fund, "net_income", ctx.rules)
    reasons = [] if ni_tr.consistent else [f"net income not consistently increasing ({ni_tr.reason})"]
    return _dcf_family(ctx, "dni", "Discounted Net Income", ctx.ttm("net_income"), "TTM net income", reasons)


# --------------------------------------------------------------------------------------- multiples
def _year_end_prices(ctx: ValuationContext, ends: list[str]) -> dict[str, float]:
    h = ctx.history
    if h is None or h.empty:
        return {}
    out = {}
    for e in ends:
        ts = pd.Timestamp(e)
        sub = h.loc[:ts]
        if not sub.empty and (ts - sub.index[-1]).days < 10:
            out[e] = float(sub["close"].iloc[-1])
    return out


def historical_multiple(ctx: ValuationContext, concept: str, per_share_den: bool = True,
                        years: int = 5) -> tuple[list[float], float | None]:
    """Year-end price ÷ (concept per share) for the last `years` fiscal years, plus current."""
    pts = ctx.fund.annual.get(concept, [])[-years:]
    shares = {p.end: p.value for p in ctx.fund.annual.get("shares_diluted", [])}
    prices = _year_end_prices(ctx, [p.end for p in pts])
    ratios = []
    for p in pts:
        sh = shares.get(p.end) or ctx.shares
        if p.end in prices and sh and p.value > 0:
            ratios.append(prices[p.end] / (p.value / sh))
    cur_val = ctx.ttm(concept) if concept in ctx.fund.ttm else ctx.fund.latest.get(concept)
    cur = (ctx.price / (cur_val / ctx.shares)) if cur_val and cur_val > 0 and ctx.shares else None
    return ratios, cur


def tangible_book(fund: Fundamentals) -> float | None:
    eq = fund.latest.get("equity")
    if eq is None:
        return None
    return eq - fund.latest.get("goodwill", 0.0) - fund.latest.get("intangibles", 0.0)


def _pb_core(ctx: ValuationContext, method: str, label: str, tangible: bool) -> ValuationResult:
    res = ValuationResult(method, label, applicable=True)
    shares = ctx.shares
    book = ctx.money(tangible_book(ctx.fund) if tangible else ctx.fund.latest.get("equity"))
    if not book or not shares or book <= 0:
        res.applicable = False
        res.reasons.append("book value not positive")
        return res
    bvps = book / shares
    eq_hist = ctx.fund.annual.get("equity", [])[-5:]
    prices = _year_end_prices(ctx, [p.end for p in eq_hist])
    sh = {p.end: p.value for p in ctx.fund.annual.get("shares_diluted", [])}
    hist = [prices[p.end] / (p.value / (sh.get(p.end) or shares)) for p in eq_hist
            if p.end in prices and p.value > 0]
    cur_pb = ctx.price / bvps
    avg = mean(hist)
    sd = stdev(hist)
    res.inputs = {"book_value_per_share": bvps, "current_pb": cur_pb, "pb_history": hist,
                  "avg_pb_5y": avg, "tangible": tangible}
    if avg:
        res.intrinsic_value = avg * bvps
        res.extra["plus_1sd"] = (avg + sd) * bvps if sd else None
        res.extra["minus_1sd"] = (avg - sd) * bvps if sd else None
    return res, bvps, cur_pb  # type: ignore[return-value]


def price_to_book_bank(ctx: ValuationContext) -> ValuationResult:
    out = _pb_core(ctx, "pb_bank", "Price-to-Book (bank: 5y avg P/B × BVPS)", tangible=False)
    if isinstance(out, ValuationResult):
        return out
    res, bvps, cur = out
    v = ctx.rules.valuation
    if res.intrinsic_value is None:  # fall back to the 1.2–1.4 fair band
        res.intrinsic_value = v.bank_pb_fair_low * bvps
        res.reasons.append("no P/B history — used 1.2× BVPS (low end of fair band)")
    res.scenarios = [Scenario("base", res.intrinsic_value), Scenario("conservative", min(res.intrinsic_value, v.bank_pb_fair_low * bvps), note="≤1.2× book"),
                     Scenario("cheap", 1.0 * bvps, note="1.0× book = really undervalued")]
    dps = ctx.est.dividend_per_share
    if dps:
        res.extra["max_price_for_yield"] = dps / v.bank_min_yield
    res.extra["verdict"] = ("really undervalued (<1.0×)" if cur < 1 else "cheap (<1.2×)" if cur < v.bank_pb_fair_low
                            else "fair (1.2–1.4×)" if cur <= v.bank_pb_fair_high else "expensive (>1.4×)")
    return res


def price_to_book_distressed(ctx: ValuationContext) -> ValuationResult:
    out = _pb_core(ctx, "pb_distressed", "Price-to-Book (loss-making / distressed: ≤0.5× liquidation value)", tangible=True)
    if isinstance(out, ValuationResult):
        return out
    res, bvps, cur = out
    res.intrinsic_value = bvps  # liquidation value per share
    res.scenarios = [Scenario("base", bvps, note="tangible book = liquidation value"),
                     Scenario("conservative", bvps * ctx.rules.valuation.distressed_pb_max, note="buy ≤0.5× book")]
    res.extra["buy_below"] = bvps * ctx.rules.valuation.distressed_pb_max
    return res


def price_to_nav_reit(ctx: ValuationContext) -> ValuationResult:
    out = _pb_core(ctx, "pnav_reit", "Price-to-NAV/Book (REIT) + yield check", tangible=False)
    if isinstance(out, ValuationResult):
        return out
    res, bvps, cur = out
    v = ctx.rules.valuation
    cap = v.reit_pnav_max * bvps
    if res.intrinsic_value is None:
        res.intrinsic_value = cap
        res.reasons.append("no P/B history — used 1.2× NAV cap")
    res.scenarios = [Scenario("base", res.intrinsic_value), Scenario("conservative", min(res.intrinsic_value, cap), note="≤1.2× NAV rule")]
    dps = ctx.est.dividend_per_share or (ctx.fund.series("dps")[-1] if ctx.fund.series("dps") else None)
    if dps:
        res.extra["max_price_for_yield"] = dps / v.reit_min_yield
        res.extra["yield_at_price"] = dps / ctx.price if ctx.price else None
    res.reasons.append("US REIT book value is historical cost (not marked to market) — treat P/B with care; "
                       "the yield test is the more reliable gate for US REITs")
    return res


def mean_price_to_sales(ctx: ValuationContext) -> ValuationResult:
    res = ValuationResult("ps_mean", "Mean Price-to-Sales (5y avg P/S × revenue/share)", applicable=True)
    hist, cur = historical_multiple(ctx, "revenue")
    rev = ctx.ttm("revenue")
    if not rev or not ctx.shares or not hist:
        res.applicable = False
        res.reasons.append("insufficient revenue / price history")
        return res
    rps = rev / ctx.shares
    avg, sd = mean(hist), stdev(hist)
    res.intrinsic_value = avg * rps
    res.scenarios = [Scenario("base", res.intrinsic_value),
                     Scenario("conservative", (avg - sd) * rps if sd and avg - sd > 0 else res.intrinsic_value * 0.85)]
    res.inputs = {"revenue_per_share": rps, "ps_history": hist, "avg_ps_5y": avg, "current_ps": cur}
    return res


def psg(ctx: ValuationContext) -> ValuationResult:
    """Price-to-Sales-Growth for unprofitable hyper-growth (0.2–0.3 fair)."""
    res = ValuationResult("psg", "Price-to-Sales-Growth (speculative growth)", applicable=True)
    rev = ctx.ttm("revenue")
    g = ctx.est.revenue_growth_next_year
    if g is None:
        series = ctx.fund.series("revenue")
        if len(series) >= 2 and series[-2] > 0:
            g = series[-1] / series[-2] - 1
            res.reasons.append("no projected revenue growth — used last year's actual growth")
    if not rev or not ctx.shares or not g or g <= 0:
        res.applicable = False
        res.reasons.append("needs positive revenue and revenue growth")
        return res
    ps = ctx.price / (rev / ctx.shares)
    ratio = ps / (g * 100)
    fair_ps = ctx.rules.valuation.psg_fair * g * 100
    res.intrinsic_value = fair_ps * rev / ctx.shares     # price at which PSG = 0.3
    res.scenarios = [Scenario("base", res.intrinsic_value, note="price where PSG = 0.3"),
                     Scenario("conservative", ctx.rules.valuation.psg_undervalued * g * 100 * rev / ctx.shares,
                              note="price where PSG = 0.2")]
    res.inputs = {"ps": ps, "revenue_growth": g, "psg": ratio}
    res.extra["verdict"] = ("undervalued" if ratio < 0.2 else "fair" if ratio <= 0.3 else "overvalued")
    return res


def peg_check(ctx: ValuationContext) -> ValuationResult:
    """Screening only — never the final valuation (Lesson 5 §3)."""
    res = ValuationResult("peg", "PEG quick check (screening only)", applicable=False)
    eps = ctx.fund.series("eps_diluted")
    g = ctx.growth
    pe = ctx.est.pe
    if pe is None and eps and eps[-1] > 0:
        pe = ctx.price / eps[-1]
    if pe and g and g > 0:
        peg = pe / (g * 100)
        res.inputs = {"pe": pe, "growth": g, "peg": peg}
        res.extra["verdict"] = "attractive (≤1.5)" if peg <= ctx.rules.valuation.peg_attractive else "expensive (>1.5)"
    return res


def dividend_yield_check(ctx: ValuationContext) -> ValuationResult:
    res = ValuationResult("yield", "Dividend yield hurdle", applicable=False)
    dps = ctx.est.dividend_per_share or (ctx.fund.series("dps")[-1] if ctx.fund.series("dps") else None)
    if dps and ctx.price:
        res.inputs = {"dps": dps, "yield": dps / ctx.price}
        res.extra["max_price_5pct"] = dps / ctx.rules.dividend.min_yield
    return res


REGISTRY: dict[str, Callable[[ValuationContext], ValuationResult]] = {
    "dcf_fcf": dcf_fcf,
    "dcf_normalized": dcf_normalized,
    "dcf_cfo": dcf_cfo,
    "dni": discounted_net_income,
    "pb_bank": price_to_book_bank,
    "pb_distressed": price_to_book_distressed,
    "pnav_reit": price_to_nav_reit,
    "ps_mean": mean_price_to_sales,
    "psg": psg,
    "peg": peg_check,
    "yield": dividend_yield_check,
}
