"""Negative shareholders' equity assessment (VMI Master Document §3.5 and ROE note in §5.1).

Adam: negative equity is NOT automatically bad. McDonald's, Yum Brands, Domino's (and AutoZone) have negative
equity because years of aggressive buybacks exceed retained earnings — "profit generated from negative equity is
effectively infinity. ROE is infinite, which is very good."

Rule (§3.5) — negative equity is fine, even good, as long as:
  (a) the company is making a lot of money       → TTM/latest net income > 0 and positive in ≥4 of last 5 years
  (b) profits are increasing consistently        → consistency.consistent(net_income)
  (c) free cash flow is increasing consistently  → consistency.consistent(fcf), or a growth-capex dip with
                                                    healthy rising CFO (doc Amazon example / §5.4 Buffett note)
  (d) the cause is buybacks                      → treasury stock ≥ the deficit, OR (for companies that retire
                                                    repurchased shares, e.g. YUM in North Carolina, so there is no
                                                    treasury line) cumulative buybacks over the history ≥ deficit.

Single source of truth: Step 4 (ROE), completeness audit and the API all call `assess`.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

from vmi.analysis.consistency import consistent, growth_capex_dip
from vmi.data.models import Fundamentals


@dataclass
class NegativeEquityAssessment:
    applies: bool                       # equity ≤ 0 right now
    equity: float | None = None
    deficit: float | None = None        # |equity| when negative
    treasury_stock: float | None = None
    cumulative_buybacks: float | None = None
    profitable: bool = False            # (a)
    profits_rising: bool = False        # (b)
    fcf_rising: bool = False            # (c)
    buyback_driven: bool = False        # (d)
    capex_note: str = ""
    passes: bool = False                # all four ⇒ ROE treated as "infinite" (pass)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def current_equity(f: Fundamentals) -> float | None:
    if f.latest.get("equity") is not None:
        return f.latest["equity"]
    s = f.series("equity")
    return s[-1] if s else None


def assess(f: Fundamentals) -> NegativeEquityAssessment:
    eq = current_equity(f)
    if eq is None or eq > 0:
        return NegativeEquityAssessment(applies=False, equity=eq)
    a = NegativeEquityAssessment(applies=True, equity=eq, deficit=abs(eq))

    ni_hist = f.series("net_income")[-5:]
    ni_now = f.ttm.get("net_income", ni_hist[-1] if ni_hist else None)
    a.profitable = bool(ni_now and ni_now > 0 and sum(1 for v in ni_hist if v > 0) >= min(4, len(ni_hist)))
    a.profits_rising = consistent(f, "net_income")
    a.fcf_rising = consistent(f, "fcf")
    if not a.fcf_rising:
        ok, why = growth_capex_dip(f)   # FCF dip from growth capex with healthy CFO (Amazon rule) is acceptable
        a.fcf_rising = ok
        a.capex_note = why

    ts = f.latest.get("treasury_stock")
    if ts is None:
        s = f.series("treasury_stock")
        ts = s[-1] if s else None
    a.treasury_stock = abs(ts) if ts is not None else None
    bb = [abs(v) for v in f.series("buybacks")]
    a.cumulative_buybacks = sum(bb) if bb else None
    a.buyback_driven = bool((a.treasury_stock and a.treasury_stock >= a.deficit)
                            or (a.cumulative_buybacks and a.cumulative_buybacks >= a.deficit))

    for ok, why in ((a.profitable, "(a) makes a lot of money"), (a.profits_rising, "(b) profits rising consistently"),
                    (a.fcf_rising, "(c) FCF rising consistently" + (f" [growth-capex check: {a.capex_note}]" if a.capex_note else "")),
                    (a.buyback_driven, "(d) caused by buybacks (treasury stock / cumulative repurchases ≥ deficit)")):
        a.reasons.append(("✓ " if ok else "✗ ") + why)
    a.passes = a.profitable and a.profits_rising and a.fcf_rising and a.buyback_driven
    return a
