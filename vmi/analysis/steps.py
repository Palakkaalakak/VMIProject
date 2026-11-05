"""The VMI 7-step formula (Part VI) as composable, individually testable checks.

Each step returns a StepResult(passed, score 0..1, checks[], notes[]). Business-type exceptions are
applied inside each step (banks ignore CFO in Step 1, no ROIC for banks/insurers/utilities in Step 4,
CET1 for banks / gearing for REITs in Step 5 …). The moat (Step 3) is a discretionary judgement: the code
gathers the evidence Adam's grade table looks at and a reviewer checklist; the verdict is recorded by a person
or an AI via the overrides moat_grade / moat_sources / moat_score (vmi/overrides.py). Until then the step shows
a clearly labelled data hint, and the final "VMI buy" signal requires a reviewed moat.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from vmi.analysis.classify import BizType, is_no_moat_industry
from vmi.analysis.consistency import series_trend
from vmi.analysis import negative_equity
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
    extra: dict = field(default_factory=dict)  # step-specific structured data (e.g. the moat review)

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
    checks: list[Check] = []
    notes: list[str] = []
    rev = series_trend(f, "revenue", rules)
    checks.append(Check("revenue_consistent", rev.consistent, rev.cagr, "uptrend ≥5y", rev.reason))
    ni = series_trend(f, "net_income", rules)
    oi = series_trend(f, "operating_income", rules)
    ni_ok = ni.consistent or oi.consistent
    checks.append(Check("earnings_consistent", ni_ok, ni.cagr if ni.consistent else oi.cagr,
                        "NI (or operating income) uptrend",
                        ni.reason if ni.consistent else f"NI: {ni.reason}; operating income: {oi.reason}"))
    ignore_cfo = biz in (BizType.BANK, BizType.CYCLICAL, BizType.INSURANCE, BizType.ASSET_MANAGER)
    cfo = series_trend(f, "cfo", rules)
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
MOAT_SOURCES = {
    "brand": "Strong brand / brand monopoly: first name people think of; loyal even when pricier",
    "switching_costs": "High switching costs: costly or risky to leave (ecosystems, embedded enterprise software)",
    "network_effect": "Network effect: more users make it better for every user (marketplaces, social, payments)",
    "barriers": "High barriers to entry: regulation, licences, patents, security clearances",
    "scale": "Economies of scale: so big that competing is almost impossible",
}
MOAT_QUESTIONS = (
    "Pricing power test: can it raise prices every year without losing market share? (yes → wide)",
    "Are the closest competitors clearly weaker? Is this the top dog of its industry?",
    "Could a bigger competitor disrupt it within 1–3 years (no moat) or beyond 10 years (narrow)?",
    "Score each of the five sources /10 (an AI can do this); Adam wants ≥3 of 5 sources and an overall 7–9/10.",
)


def _margins(f: Fundamentals, concept: str) -> list[float]:
    rev = {p.end: p.value for p in f.annual.get("revenue", [])}
    return [p.value / rev[p.end] for p in f.annual.get(concept, []) if rev.get(p.end)][-10:]


def _describe(xs: list[float]) -> str:
    if len(xs) < 2:
        return ""
    avg = mean(xs)
    sd = (sum((x - avg) ** 2 for x in xs) / len(xs)) ** 0.5
    drift = xs[-1] - mean(xs[:-1])
    direction = "rising" if drift > 0.01 else "eroding" if drift < -0.01 else "stable"
    return f"{len(xs)}y avg {avg:.1%}, range {min(xs):.1%}–{max(xs):.1%}, σ {sd:.1%}, {direction}"


def moat_verdict(review: dict | None, rules: VMIRules = RULES) -> dict | None:
    """Reviewer verdict from the overrides (moat_grade / moat_sources / moat_score, or the legacy `moat` dict)."""
    r = dict(review or {})
    legacy = r.get("moat") if isinstance(r.get("moat"), dict) else {}
    grade = r.get("moat_grade") or legacy.get("grade")
    sources = r.get("moat_sources") or legacy.get("sources") or []
    score = r.get("moat_score")
    if not (grade or sources or score is not None):
        return None
    if not grade and sources:
        grade = "wide" if len(sources) >= 4 else "narrow" if len(sources) >= rules.moat.min_sources else "none"
    if not grade and score is not None:
        grade = "wide" if score >= 8 else "narrow" if score >= rules.moat.min_ai_score else "none"
    return {"grade": grade, "sources": list(sources), "score": score}


def step3_moat(f: Fundamentals, est: Estimates, ten_year_uptrend: bool | None, biz: BizType,
               review: dict | None = None, rules: VMIRules = RULES,
               ten_year_return: float | None = None) -> StepResult:
    """Evidence for the reviewer (Adam's grade table: margins, consistency, pricing power, 10-year chart) plus
    the reviewer's verdict. Every check is evidence; only the verdict decides. Without a verdict, a data hint
    (share of supportive signals) stands in provisionally and the step is marked unreviewed."""
    gm, nm, om, fm = (_margins(f, c) for c in ("gross_profit", "net_income", "operating_income", "fcf"))
    roic_name = "roe" if biz in (BizType.BANK, BizType.INSURANCE, BizType.UTILITY) else "roic"
    roic = _ratio_vals(f, roic_name, 10)
    no_moat_ind = is_no_moat_industry(est.industry, f.industry, f.sic_description)
    rev, ni, cfo = (series_trend(f, c, rules) for c in ("revenue", "net_income", "cfo"))
    rv = f.series("revenue")
    cagr = (rv[-1] / rv[-6]) ** 0.2 - 1 if len(rv) >= 6 and rv[-6] > 0 and rv[-1] > 0 else None
    gm_sd = (sum((x - mean(gm)) ** 2 for x in gm) / len(gm)) ** 0.5 if len(gm) >= 3 else None
    mcap = ((est.extra or {}).get("yahoo") or {}).get("market_cap")

    checks = [
        Check("industry_structure", not no_moat_ind, est.industry or f.industry or f.sic_description,
              "not a typical no-moat industry (commodities, airlines, autos, shipping, developers)"),
        Check("ten_year_chart", ten_year_uptrend, None if ten_year_return is None else round(ten_year_return, 3),
              "clear 10-year uptrend (Adam's visual moat proxy)", "value = 10-year price return"),
        Check("gross_margin", None if not gm else gm[-1] >= 0.40, round(gm[-1], 3) if gm else None,
              "high and not eroding (pricing power)", _describe(gm)),
        Check("gross_margin_stability", None if gm_sd is None else gm_sd <= 0.03, round(gm_sd, 4) if gm_sd is not None else None,
              "σ ≤ 3 pts: prices held through cycles", ""),
        Check("operating_margin", None if not om else om[-1] >= 0.20, round(om[-1], 3) if om else None,
              "≥20% suggests an advantage", _describe(om)),
        Check("net_margin", None if not nm else nm[-1] >= 0.10, round(nm[-1], 3) if nm else None,
              "wide: very high · narrow: average · none: low", _describe(nm)),
        Check("fcf_margin", None if not fm else fm[-1] >= 0.10, round(fm[-1], 3) if fm else None,
              "≥10% of sales turns into free cash", _describe(fm)),
        Check(f"{roic_name}_persistence", None if not roic else
              sum(v >= rules.profitability.min_roic for v in roic) >= max(3, len(roic) - 1),
              [round(v, 3) for v in roic], f"{roic_name.upper()} ≥{rules.profitability.min_roic:.0%} nearly every year",
              "competition normally erodes high returns; persistence means something protects them"),
        Check("revenue_consistency", rev.consistent, None if cagr is None else round(cagr, 3),
              "sales rising consistently (value = 5y CAGR)", rev.reason),
        Check("profit_and_cash_consistency", ni.consistent and cfo.consistent, None,
              "net income and operating cash flow rising consistently", f"NI: {ni.reason}; CFO: {cfo.reason}"),
        Check("scale", None, {"revenue": f.last("revenue"), "market_cap": mcap}, "evidence for economies of scale",
              "compare with the closest competitors"),
    ]
    signals = [c for c in checks if c.passed is not None]
    support = sum(c.passed for c in signals) / len(signals) if signals else 0.0
    hint = "none" if no_moat_ind else "wide" if support >= 0.8 else "narrow" if support >= 0.6 else "none"

    verdict = moat_verdict(review, rules)
    extra = {"reviewed": verdict is not None, "hint": hint, "support": round(support, 3),
             "sources": MOAT_SOURCES, "questions": list(MOAT_QUESTIONS), "verdict": verdict}
    if verdict:
        grade = verdict["grade"]
        checks.append(Check("reviewer_verdict", grade in ("wide", "narrow"), grade,
                            f"≥{rules.moat.min_sources} of 5 sources / score ≥{rules.moat.min_ai_score}",
                            f"sources: {', '.join(verdict['sources']) or '—'}; score: {verdict['score'] if verdict['score'] is not None else '—'}"))
        notes = [f"Moat reviewed: {grade}."]
    else:
        grade = hint
        notes = [f"UNREVIEWED — data hint '{hint}' ({support:.0%} of signals supportive). Record a verdict "
                 "(moat_grade / moat_sources / moat_score) after checking the five sources; a VMI buy needs it."]
    res = StepResult(3, "Economic moat", grade in ("wide", "narrow"), round(support, 3), checks, notes, extra)
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
        ne = negative_equity.assess(f)
        if ne.applies:
            # Doc §5.1: ROE from negative (buyback-driven) equity is "effectively infinite" → pass if §3.5 holds
            checks.append(Check("roe", ne.passes, "∞ (negative equity)", f"≥{p.min_roe:.0%}",
                                "negative equity — " + "; ".join(ne.reasons)))
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
