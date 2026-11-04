"""The VMI 7-step formula (Part VI) as composable, individually testable checks.

Each step returns a StepResult(passed, score 0..1, checks[], notes[]). Business-type exceptions are
applied inside each step (banks ignore CFO in Step 1, no ROIC for banks/insurers/utilities in Step 4,
CET1 for banks / gearing for REITs in Step 5 …). The moat step (Step 3) is semi-qualitative: we compute
quantitative moat proxies (margins vs peers-free thresholds, margin stability, ROIC persistence, 10-year
chart, pricing power proxy = gross-margin trend, no-moat industry) and let the user record the final
5-source moat verdict per ticker (stored in the DB, see vmi.store) which overrides the proxy.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from vmi.analysis.classify import BizType, is_no_moat_industry
from vmi.analysis.trends import falling_streak, mean, trend
from vmi.data.models import Estimates, Fundamentals
from vmi.rules import RULES, VMIRules


@dataclass
class Check:
    name: str
    passed: bool | None          # None = not applicable / informational
    value: Any = None
    threshold: Any = None
    note: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class StepResult:
    step: int
    title: str
    passed: bool
    score: float
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


def _finish(step: int, title: str, checks: list[Check], notes: list[str] | None = None,
            required: set[str] | None = None) -> StepResult:
    applicable = [c for c in checks if c.passed is not None]
    score = sum(1 for c in applicable if c.passed) / len(applicable) if applicable else 0.0
    req = [c for c in applicable if required is None or c.name in required]
    passed = bool(req) and all(c.passed for c in req)
    return StepResult(step, title, passed, round(score, 3), checks, notes or [])


def _ratio_vals(f: Fundamentals, name: str, n: int = 6) -> list[float]:
    return [p.value for p in f.ratios.get(name, []) if p.end != "TTM"][-n:]


def _ratio_now(f: Fundamentals, name: str) -> float | None:
    pts = f.ratios.get(name, [])
    if not pts:
        return None
    return pts[-1].value


# ------------------------------------------------------------------------------------------ STEP 1
def step1_track_record(f: Fundamentals, biz: BizType, rules: VMIRules = RULES) -> StepResult:
    r = rules.track
    win = r.preferred_years
    checks: list[Check] = []
    notes: list[str] = []
    rev = trend(f.series("revenue")[-win:], r.max_down_years_5y, r.min_years)
    checks.append(Check("revenue_consistent", rev.consistent, rev.cagr, "uptrend ≥5y", rev.reason))
    ni = trend(f.series("net_income")[-win:], r.max_down_years_5y, r.min_years)
    oi = trend(f.series("operating_income")[-win:], r.max_down_years_5y, r.min_years)
    ni_ok = ni.consistent or oi.consistent
    checks.append(Check("earnings_consistent", ni_ok, ni.cagr if ni.consistent else oi.cagr,
                        "NI (or operating income) uptrend",
                        ni.reason if ni.consistent else f"NI: {ni.reason}; operating income: {oi.reason}"))
    ignore_cfo = biz in (BizType.BANK, BizType.CYCLICAL, BizType.INSURANCE, BizType.ASSET_MANAGER)
    cfo = trend(f.series("cfo")[-win:], r.max_down_years_5y, r.min_years)
    checks.append(Check("cfo_consistent", None if ignore_cfo else cfo.consistent, cfo.cagr, "uptrend ≥5y",
                        ("ignored for " + biz.value) if ignore_cfo else cfo.reason))
    # margins
    rev_s = {p.end: p.value for p in f.annual.get("revenue", [])}
    for label, concept in (("gross_margin", "gross_profit"), ("net_margin", "net_income")):
        pts = [(p.end, p.value / rev_s[p.end]) for p in f.annual.get(concept, []) if rev_s.get(p.end)]
        m = [v for _, v in pts][-6:]
        if len(m) < 3:
            checks.append(Check(f"{label}_stable", None, None, "", "not reported (n/a for this business)"))
            continue
        avg5 = mean(m[-6:-1]) or m[-1]
        cur = m[-1]
        streak = falling_streak(m)
        ok = streak < r.reject_if_margin_falls_n_years - 1 and (avg5 <= 0 or cur >= avg5 * (1 - r.margin_tolerance))
        checks.append(Check(f"{label}_stable", ok, round(cur, 4), f"≥ 5y avg {avg5:.1%} (−{r.margin_tolerance:.0%} tol)",
                            f"falling {streak} yrs in a row" if streak >= 2 else ""))
    # Speculative-growth exception (half allocation)
    if biz == BizType.SPECULATIVE:
        q_cfo = [p.value for p in f.quarterly.get("cfo", [])[-2:]]
        q_ni = [p.value for p in f.quarterly.get("net_income", [])[-2:]]
        turned = bool(q_cfo and q_cfo[-1] > 0) and bool(q_ni and q_ni[-1] > 0)
        checks.append(Check("speculative_turned_positive", turned, {"cfo_q": q_cfo, "ni_q": q_ni},
                            "latest quarter CFO & NI > 0", "speculative exception → half allocation"))
        notes.append("Speculative growth exception: needs strong moat; size at ½ normal allocation.")
        return _finish(1, "Consistent track record", checks, notes,
                       required={"revenue_consistent", "speculative_turned_positive"})
    required = {"revenue_consistent", "earnings_consistent", "cfo_consistent", "gross_margin_stable", "net_margin_stable"}
    return _finish(1, "Consistent track record", checks, notes, required)


# ------------------------------------------------------------------------------------------ STEP 2
HIGH_GROWTH_THEMES = {
    "AI & robotics": ("semiconductor", "software", "robot", "artificial intelligence", "cloud", "internet content"),
    "AI energy infrastructure": ("utilities - independent power", "electrical equipment", "nuclear", "renewable",
                                 "power producers"),
    "Healthcare (aging)": ("medical", "health", "biotech", "drug manufacturers", "diagnostics", "healthcare"),
    "Digital payments": ("credit services", "transaction", "payment", "financial data"),
    "Cybersecurity": ("software - infrastructure", "security", "cyber"),
    "New space economy": ("aerospace", "satellite", "space"),
}


def themes_for(industry: str, sector: str = "") -> list[str]:
    blob = f"{industry} {sector}".lower()
    return [t for t, keys in HIGH_GROWTH_THEMES.items() if any(k in blob for k in keys)]


def step2_growth(est: Estimates, f: Fundamentals, rules: VMIRules = RULES) -> StepResult:
    g5, g1 = est.eps_growth_5y, est.eps_growth_next_year
    rg = est.revenue_growth_next_year
    checks = [Check("projected_growth_positive", (g5 if g5 is not None else g1 if g1 is not None else rg or -1) > rules.growth.min_projected_growth,
                    g5 if g5 is not None else g1, "> 0", f"sources: {est.sources}"),
              Check("next_year_growth", None if g1 is None else g1 > 0, g1, "> 0 (informational)")]
    th = themes_for(est.industry or f.industry, est.sector or f.sector)
    notes = [f"High-growth theme(s): {', '.join(th)}"] if th else []
    return _finish(2, "Positive projected growth", checks, notes, {"projected_growth_positive"})


# ------------------------------------------------------------------------------------------ STEP 3
def step3_moat(f: Fundamentals, est: Estimates, ten_year_uptrend: bool | None, biz: BizType,
               manual: dict | None = None, rules: VMIRules = RULES) -> StepResult:
    """Quantitative moat proxies + optional manual 5-source verdict (wins if present)."""
    checks: list[Check] = []
    notes: list[str] = []
    rev = {p.end: p.value for p in f.annual.get("revenue", [])}
    gm = [p.value / rev[p.end] for p in f.annual.get("gross_profit", []) if rev.get(p.end)][-6:]
    nm = [p.value / rev[p.end] for p in f.annual.get("net_income", []) if rev.get(p.end)][-6:]
    roic = _ratio_vals(f, "roic") if biz not in (BizType.BANK, BizType.INSURANCE, BizType.UTILITY) else _ratio_vals(f, "roe")
    no_moat_ind = is_no_moat_industry(est.industry, f.industry, f.sic_description)
    checks.append(Check("not_no_moat_industry", not no_moat_ind, est.industry or f.sic_description,
                        "not commodity/airline/auto/shipping/oil & gas/developer"))
    checks.append(Check("ten_year_uptrend", ten_year_uptrend, None, "10y monthly chart rising (moat proxy)"))
    if gm:
        checks.append(Check("pricing_power_gross_margin", gm[-1] >= (mean(gm[:-1]) or gm[-1]) * 0.97 and gm[-1] > 0.30,
                            round(gm[-1], 3), "GM ≥30% and not eroding (pricing power proxy)"))
    if nm:
        checks.append(Check("high_net_margin", nm[-1] >= 0.10, round(nm[-1], 3), "≥10% (above-average profitability)"))
    if roic:
        persistent = sum(1 for v in roic if v >= rules.profitability.min_roic) >= max(3, len(roic) - 1)
        checks.append(Check("persistent_high_returns", persistent, [round(v, 3) for v in roic], "ROIC/ROE ≥12% most years"))
    proxy_score = sum(1 for c in checks if c.passed) / max(1, sum(1 for c in checks if c.passed is not None))
    grade = "wide" if proxy_score >= 0.8 else "narrow" if proxy_score >= 0.6 else "none"
    if manual and manual.get("sources"):
        n = len(manual["sources"])
        grade = manual.get("grade") or ("wide" if n >= 4 else "narrow" if n >= rules.moat.min_sources else "none")
        checks.append(Check("manual_moat_sources", n >= rules.moat.min_sources, manual["sources"],
                            f"≥{rules.moat.min_sources} of 5 sources", manual.get("note", "")))
        notes.append(f"Manual moat verdict recorded: {grade} ({n}/5 sources)")
        res = _finish(3, "Economic moat", checks, notes, {"manual_moat_sources", "not_no_moat_industry"})
    else:
        notes.append("Moat grade from quantitative proxies — confirm the 5 sources (brand, switching costs, network "
                     "effect, barriers, scale) and the pricing-power test before buying.")
        res = _finish(3, "Economic moat", checks, notes)
        res.passed = grade in ("wide", "narrow") and not no_moat_ind
    res.notes.insert(0, f"moat_grade={grade}")
    return res


def moat_grade(res: StepResult) -> str:
    for n in res.notes:
        if n.startswith("moat_grade="):
            return n.split("=", 1)[1]
    return "none"


# ------------------------------------------------------------------------------------------ STEP 4
def step4_profitability(f: Fundamentals, biz: BizType, rules: VMIRules = RULES) -> StepResult:
    p = rules.profitability
    checks: list[Check] = []
    roe_hist = _ratio_vals(f, "roe")
    roe = _ratio_now(f, "roe")
    if roe is not None:
        avg = mean(roe_hist[:-1]) if len(roe_hist) > 1 else roe
        checks.append(Check("roe", roe >= p.min_roe, round(roe, 4), f"≥{p.min_roe:.0%} (>15% exceptional)",
                            f"5y avg {avg:.1%}" if avg is not None else ""))
        if len(roe_hist) >= 4:
            tr = trend(roe_hist, 3, 3, require_positive_last=False)
            declining = falling_streak(roe_hist) >= 3
            checks.append(Check("roe_not_declining", not declining, [round(v, 3) for v in roe_hist], "not consistently declining"))
    else:
        checks.append(Check("roe", False, None, f"≥{p.min_roe:.0%}", "ROE unavailable"))
    skip_roic = biz in (BizType.BANK, BizType.INSURANCE, BizType.UTILITY)
    roic = _ratio_now(f, "roic")
    checks.append(Check("roic", None if skip_roic else (roic is not None and roic >= p.min_roic),
                        round(roic, 4) if roic is not None else None, f"≥{p.min_roic:.0%}",
                        f"n/a for {biz.value}" if skip_roic else ""))
    # revenue growing faster than receivables
    rev, ar = f.series("revenue"), f.series("receivables")
    if len(rev) >= 4 and len(ar) >= 4 and rev[-4] > 0 and ar[-4] > 0:
        rg, ag = (rev[-1] / rev[-4]) ** (1 / 3) - 1, (ar[-1] / ar[-4]) ** (1 / 3) - 1
        checks.append(Check("revenue_vs_receivables", rg >= ag - 0.02, {"rev_cagr": round(rg, 4), "ar_cagr": round(ag, 4)},
                            "revenue growing ≥ receivables"))
    else:
        checks.append(Check("revenue_vs_receivables", None, None, "", "receivables not reported"))
    ccc = _ratio_vals(f, "ccc")
    if len(ccc) >= 3:
        rising = ccc[-1] - min(ccc[:-1]) > p.ccc_max_increase_days
        checks.append(Check("cash_conversion_cycle", not rising, [round(v, 1) for v in ccc],
                            f"not rising >{p.ccc_max_increase_days:.0f} days (negative = fantastic)"))
    req = {"roe", "roic"}
    return _finish(4, "Profitable & efficient", checks, [], req)


# ------------------------------------------------------------------------------------------ STEP 5
def step5_debt(f: Fundamentals, biz: BizType, est: Estimates | None = None, rules: VMIRules = RULES) -> StepResult:
    d = rules.debt
    checks: list[Check] = []
    if biz == BizType.BANK:
        cet1 = f.meta.get("cet1")
        checks.append(Check("cet1", cet1 is not None and cet1 > d.min_bank_cet1, cet1, f">{d.min_bank_cet1:.0%}",
                            f.meta.get("cet1_source", "")))
        return _finish(5, "Conservative debt", checks, [], {"cet1"})
    if biz == BizType.REIT:
        assets = f.latest.get("total_assets")
        debt = f.latest.get("total_debt") or (f.latest.get("lt_debt", 0) + f.latest.get("st_debt", 0))
        g = debt / assets if assets else None
        checks.append(Check("gearing", g is not None and g <= d.max_reit_gearing, round(g, 4) if g else None,
                            f"≤{d.max_reit_gearing:.0%} (<40% safest)"))
        return _finish(5, "Conservative debt", checks, [], {"gearing"})
    cr = _ratio_now(f, "current_ratio")
    ca, cl = f.latest.get("current_assets"), f.latest.get("current_liabilities")
    if cr is None and ca and cl:
        cr = ca / cl
    deferred_ok = False
    if cr is not None and cr < d.min_current_ratio:
        # subscription / upfront-collection exception: big deferred revenue or very strong FCF
        cfo, cl_v = f.last("cfo"), cl or 0
        deferred_ok = bool(cfo and cl_v and cfo > 0.5 * cl_v)
    checks.append(Check("current_ratio", None if cr is None else (cr > d.min_current_ratio or deferred_ok),
                        round(cr, 3) if cr else None, f">{d.min_current_ratio}",
                        "below 1 but upfront-collection/strong CFO exception" if deferred_ok else ""))
    de = _ratio_now(f, "debt_ebitda")
    debt = abs(f.latest.get("lt_debt", 0.0)) + abs(f.latest.get("st_debt", 0.0))
    ebitda = f.last("ebitda")
    if de is None and ebitda and ebitda > 0:
        de = debt / ebitda
    if debt == 0:
        de = 0.0
    checks.append(Check("debt_to_ebitda", None if de is None else de <= d.max_debt_to_ebitda,
                        round(de, 3) if de is not None else None, f"≤{d.max_debt_to_ebitda}"))
    interest, cfo = f.last("interest_expense"), f.last("cfo")
    interest = abs(interest) if interest else 0.0
    if cfo and cfo > 0:
        dsr = interest / cfo
        checks.append(Check("debt_servicing", dsr < d.max_debt_servicing, round(dsr, 4), f"<{d.max_debt_servicing:.0%}"))
    else:
        checks.append(Check("debt_servicing", None if not interest else False, None, "<30%", "CFO not positive"))
    oi = f.last("operating_income")
    if interest > 0 and oi is not None:
        icr = oi / interest
        checks.append(Check("interest_coverage", icr > d.min_interest_coverage, round(icr, 2), f">{d.min_interest_coverage} (>5 very safe)"))
    else:
        checks.append(Check("interest_coverage", True if interest == 0 else None, None, ">3", "no interest expense"))
    return _finish(5, "Conservative debt", checks, [], {"debt_to_ebitda", "debt_servicing", "current_ratio"})


# ------------------------------------------------------------------------------------------ STEP 6/7
def step6_price(price: float, iv: float | None, conservative: float | None) -> StepResult:
    checks = [Check("below_intrinsic_value", iv is not None and price < iv, round(price, 2),
                    round(iv, 2) if iv else None,
                    f"margin of safety {(iv - price) / iv:.1%}" if iv else "no intrinsic value"),
              Check("below_conservative_value", None if conservative is None else price < conservative,
                    round(price, 2), round(conservative, 2) if conservative else None, "extra safety (informational)")]
    return _finish(6, "Great price (below intrinsic value)", checks, [], {"below_intrinsic_value"})


def step7_entry(tech: dict) -> StepResult:
    checks = [Check("entry_signal", bool(tech.get("entry_ok")), tech.get("scenario"), "wave-down into support",
                    tech.get("entry_reason", "")),
              Check("not_parabolic", not tech.get("signals", {}).get("parabolic_up"), None, "never chase a wave up")]
    return _finish(7, "Great point of entry", checks, [], {"entry_signal", "not_parabolic"})
