"""Consensus growth for years 1–5 from the available analyst 5-year EPS growth estimates (FinViz, Zacks,
Yahoo LTG, IB/LSEG when it answers).

How the sources are combined is rules.growth.blend, overridable per ticker:
  * "lowest"  (default since 2026-11-05, owner directive): the most conservative source
  * "average" Adam's literal rule (Lesson 5 §4.6) — he averages FactSet, FinViz and Zacks
  * "median"

Only data hygiene is applied — no fitted adjustments:
  * impossible values (< −20% or > 100%) are discarded as bad data
  * hard sanity cap rules.growth.max_years_1_5
  * fallbacks when no 5-year estimate exists: median next-year EPS growth, then 5y revenue CAGR
No fitted adjustments: conservatism comes from the blend choice (and the optional flat
rules.valuation.iv_haircut), never from reshaping the growth input.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from vmi.data.models import Estimates, Fundamentals
from vmi.rules import RULES, VMIRules


@dataclass
class GrowthChoice:
    value: float | None
    method: str
    sources: dict[str, float] = field(default_factory=dict)
    low: float | None = None
    high: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _cagr(vals: list[float]) -> float | None:
    if len(vals) >= 3 and vals[0] > 0 and vals[-1] > 0:
        return (vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1
    return None


BLENDS = {
    "lowest": lambda vals: vals[0],
    "second_lowest": lambda vals: vals[min(1, len(vals) - 1)],
    "median": lambda vals: (vals[(len(vals) - 1) // 2] + vals[len(vals) // 2]) / 2,
    "average": lambda vals: sum(vals) / len(vals),
    "highest": lambda vals: vals[-1],
}


@dataclass(frozen=True)
class GrowthControls:
    """Per-ticker choices for the years 1–5 growth input (all optional; see vmi/overrides.py).

    source   use exactly this source (a data source name or one of `extra`) instead of a blend
    blend    blend name (BLENDS); None = the rules' automatic choice
    exclude  sources to ignore
    extra    additional sources supplied by a person or an AI, e.g. {"factset": 0.15}; they join the blend
    """
    source: str | None = None
    blend: str | None = None
    exclude: tuple[str, ...] = ()
    extra: dict[str, float] = field(default_factory=dict)


def collect_sources(est: Estimates, controls: GrowthControls) -> dict[str, float]:
    """Usable 5-year EPS growth estimates: data sources + extra ones, minus excluded; impossible values dropped."""
    raw = {k: v.get("eps_growth_5y") for k, v in (est.sources or {}).items()}
    raw.update(controls.extra or {})
    return {k: float(v) for k, v in raw.items()
            if k not in controls.exclude and v is not None and -0.20 < float(v) < 1.0}


def choose_growth(est: Estimates, f: Fundamentals | None = None, rules: VMIRules = RULES,
                  controls: GrowthControls | None = None) -> GrowthChoice:
    """Years 1–5 growth. Order: a chosen single source → a chosen blend → the rules' automatic blend
    (lowest; median for defensives or when sources disagree) → fallbacks when no 5-year estimate exists."""
    c = controls or GrowthControls()
    cap = rules.growth.max_years_1_5
    srcs = collect_sources(est, c)
    if srcs:
        vals = sorted(srcs.values())
        notes: list[str] = []
        if c.source:
            if c.source not in srcs:
                notes.append(f"chosen source '{c.source}' has no estimate — fell back to the blend")
            else:
                g = srcs[c.source]
                return GrowthChoice(min(g, cap), f"source:{c.source}", srcs, vals[0], vals[-1],
                                    notes + ([f"capped at {cap:.0%}"] if g > cap else []))
        blend = c.blend if c.blend in BLENDS else _auto_blend(vals, rules, notes)
        g = BLENDS[blend](vals)
        notes += [f"capped at {cap:.0%}"] if g > cap else []
        return GrowthChoice(min(g, cap), blend, srcs, vals[0], vals[-1], notes)
    nxt = sorted(float(v["eps_growth_next_year"]) for k, v in (est.sources or {}).items() if k not in c.exclude
                 if v.get("eps_growth_next_year") is not None and -0.5 < v["eps_growth_next_year"] < 1.0)
    if nxt:
        return GrowthChoice(min(nxt[len(nxt) // 2], cap), "next_year_median",
                            notes=["no 5-year estimates — used median next-year EPS growth"])
    if f is not None:
        rc = _cagr(f.series("revenue")[-6:])
        if rc is not None:
            return GrowthChoice(min(rc, cap), "historical_revenue",
                                notes=["no estimates — used 5y historical revenue CAGR"])
    return GrowthChoice(None, "none", notes=["no growth data"])


def _auto_blend(vals: list[float], rules: VMIRules, notes: list[str]) -> str:
    """rules.growth: lowest by default; blend_defensive below the growth-stock line; blend_when_disagree when
    the sources differ by ≥ disagreement_ratio (checked last, so it wins)."""
    g = rules.growth
    blend = g.blend
    if BLENDS["median"](vals) < g.growth_stock_threshold:
        blend = g.blend_defensive
        notes.append(f"defensive (median source {BLENDS['median'](vals):.1%}) → {blend}")
    if vals[0] > 0 and vals[-1] / vals[0] >= g.disagreement_ratio:
        blend = g.blend_when_disagree
        notes.append(f"sources disagree ({vals[0]:.1%}–{vals[-1]:.1%}) → {blend}")
    return blend
