"""VMI rulebook — every numeric threshold taught in the course, in ONE place.

Every constant here is traceable to docs/VMI_MASTER_DOCUMENT.pdf (section noted in the comment).
Nothing else in the codebase should hard-code a VMI threshold: import it from here so that the
methodology can be tuned (or a "strict"/"lenient" profile created) without touching logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, replace
from typing import Any


@dataclass(frozen=True)
class TrackRecordRules:  # Step 1 (Part VI)
    min_years: int = 5                     # "at least the last 5 years, better 10"
    preferred_years: int = 10
    max_down_years_5y: int = 2             # "one or two years of decline is fine"
    min_trend_r2: float = 0.0              # optional extra strictness (log-linear fit); 0 = off
    margin_tolerance: float = 0.15         # current margin may be up to 15% (relative) below 5y avg
    reject_if_margin_falls_n_years: int = 5  # "margins falling for five straight years → avoid"


@dataclass(frozen=True)
class SpeculativeRules:  # Step 1 exception + Lesson 8 category 4
    min_revenue_growth: float = 0.50       # "revenue growing 50–100%"
    positive_quarters_required: int = 1    # Palantir case: first positive quarter of CFO
    allocation_multiplier: float = 0.5     # "half of my normal investment allocation"
    upgrade_after_years: int = 5


@dataclass(frozen=True)
class GrowthRules:  # Step 2 + Lesson 5 §4.6
    min_projected_growth: float = 0.0      # positive is the bar
    cap_years_6_10: float = 0.15           # "cap at a maximum of 15%"
    years_11_20: float = 0.04              # "default 4%"
    conservative_years_11_20: float = 0.02  # "you may use a lower figure (e.g. 2%)"
    max_years_1_5: float = 0.40            # sanity cap on analyst estimates (not in course; guards outliers)
    growth_stock_threshold: float = 0.15   # user rule: growth ≥15%, defensive <15%
    large_growth_threshold: float = 0.20   # Lesson 8 "cheetah": growing above 20–25%
    # How the analyst 5-year EPS growth sources are combined for years 1–5 (owner directive 2026-11-05):
    # "lowest" (default, conservative) · "average" (Adam's literal rule) · "median". Per-ticker override:
    # key `growth_blend` in config/judgements.json or the UI's Judgement override card.
    blend: str = "lowest"
    # Defensive stocks (median of the sources < growth_stock_threshold) use this blend instead. Reason: analyst
    # long-term forecasts are systematically over-optimistic mainly for fast growers (Chan, Karceski & Lakonishok
    # 2003), so "lowest" offsets a real bias there, while for slow, stable compounders it only adds downside
    # noise (segment study 2026-11-05: defensive median ours/Adam 0.79 with lowest). Set to "lowest" to apply
    # the lowest source everywhere.
    blend_defensive: str = "median"
    # When the sources disagree this much (max/min), the lowest is usually a stale outlier rather than a
    # conservative estimate, so the default switches to the median (tools/segment_analysis.py, 2026-11-05).
    # Not applied when the blend is set per ticker.
    disagreement_ratio: float = 1.5
    blend_when_disagree: str = "median"    # blend used when the sources disagree (see disagreement_ratio)


@dataclass(frozen=True)
class MoatRules:  # Step 3
    min_sources: int = 3                   # "at least THREE out of these FIVE"
    min_ai_score: int = 7                  # "7, 8 or 9 out of 10 gives me more confidence"
    no_moat_industries: tuple[str, ...] = (
        "airline", "oil & gas", "oil and gas", "crude", "petroleum", "shipping", "marine",
        "auto manufacturer", "automobile", "motor vehicle", "construction", "homebuild",
        "property developer", "real estate develop", "steel", "metal mining", "gold", "silver",
        "copper", "coal", "aluminum", "commodity", "drilling",
    )


@dataclass(frozen=True)
class ProfitabilityRules:  # Step 4
    min_roe: float = 0.12
    excellent_roe: float = 0.15
    min_roic: float = 0.12
    excellent_roic: float = 0.15
    ccc_max_increase_days: float = 30.0    # "must not be increasing too much"


@dataclass(frozen=True)
class DebtRules:  # Step 5
    min_current_ratio: float = 1.0
    max_debt_to_ebitda: float = 3.0
    max_debt_servicing: float = 0.30       # interest / CFO
    min_interest_coverage: float = 3.0
    safe_interest_coverage: float = 5.0
    min_bank_cet1: float = 0.10
    max_reit_gearing: float = 0.45
    safe_reit_gearing: float = 0.40


@dataclass(frozen=True)
class ValuationRules:  # Lesson 5
    horizon_years: int = 20
    peg_attractive: float = 1.5
    peg_screen: float = 2.0
    cfo_max_premium_over_ni: float = 0.20  # CFO method allowed if CFO ≤ NI × 1.2
    capex_normalization_years: int = 5
    capex_spike_ratio: float = 1.5         # latest capex > 1.5× prior-4y avg ⇒ "lumpy" ⇒ normalise
    # Adam's cash-flow normalisation (MSFT/AMZN case study): sudden big jump in the last 12 months → don't use it,
    # use the prior fiscal year; sudden big plunge → use the average of the last few years.
    base_jump_ratio: float = 1.30          # TTM > 1.3× last FY ⇒ "sudden big jump"
    base_plunge_ratio: float = 0.70        # TTM < 0.7× last FY ⇒ "sudden big plunge"
    base_avg_years: int = 4
    bank_pb_fair_low: float = 1.2
    bank_pb_fair_high: float = 1.4
    distressed_pb_max: float = 0.5
    reit_pnav_max: float = 1.2
    reit_pnav_max_high_growth: float = 1.5
    reit_min_yield: float = 0.05
    bank_min_yield: float = 0.045
    psg_undervalued: float = 0.2
    psg_fair: float = 0.3
    # Adam's beta → discount-rate lookup (observed rows; interpolated in between).
    beta_table: tuple[tuple[float, float], ...] = (
        (0.28, 0.058), (0.83, 0.061), (1.10, 0.066), (1.40, 0.074), (1.49, 0.077),
    )
    min_discount_rate: float = 0.058       # "lowest rate in the table"
    max_discount_rate: float = 0.11        # extrapolation guard for very high betas
    doomsday_growth_factor: float = 0.5    # "growth halves after yr 5"
    # Optional flat conservatism haircut on discounted-stream valuations (DCF/DNI). It was 0.10 while growth
    # used the AVERAGE of sources. Since 2026-11-05 growth uses the LOWEST source (rules.growth.blend), which
    # already lands the median ours/Adam ratio at ~0.89, so the haircut is 0: one conservatism knob, not two.
    # Per-ticker: override `iv_haircut`. See docs/CALIBRATION.md.
    iv_haircut: float = 0.0
    # Extra flat haircut where the growth input is structurally less reliable: growth stocks (yrs 1–5 growth
    # ≥ rules.growth.growth_stock_threshold, i.e. Adam's own 15% growth/defensive line: long-term analyst
    # forecasts are most over-optimistic for fast growers and DCF compounds the error over 20 years) and
    # single-source estimates (no cross-check). Not applied to human growth overrides. 5% gave the tightest
    # spread vs Adam's IVs in tools/segment_analysis.py; larger values did not reduce over-valuations further.
    uncertainty_haircut: float = 0.05
    # Alternative single knob: relative cut on consensus growth (years 1–5) BEFORE the DCF. Experiments
    # (docs/CALIBRATION.md) show 10% here ≈ 10% on IV at the median, with marginally tighter tails.
    # Keep ONE of the two non-zero; both 0 = pure Adam.
    growth_haircut: float = 0.0


@dataclass(frozen=True)
class TechnicalRules:  # Lesson 6 + Step 7
    sma_periods: tuple[int, ...] = (50, 100, 150, 200)
    ema_periods: tuple[int, ...] = (20, 40)
    trend_slope_lookback: int = 20         # bars used to measure MA slope
    support_tolerance: float = 0.02        # S/R is a zone — 2% buffer
    min_touches_potential: int = 2
    min_touches_confirmed: int = 3
    swing_window: int = 5
    parabolic_dist_from_50: float = 0.25   # >25% above 50SMA = stretched/parabolic
    parabolic_drop_pct: float = 0.15       # ≥15% fall in ≤10 bars = "90-degree drop"
    double_bottom_reclaim_bars: int = 3
    n_buy_levels: int = 4                  # "three or four buy levels"
    near_level_pct: float = 0.03           # price within 3% of a buy level ⇒ "at support"


@dataclass(frozen=True)
class PortfolioRules:  # Lesson 8
    min_stocks: int = 8
    max_stocks: int = 60
    default_target_stocks: int = 20
    tranches: int = 4                      # "three to four tranches"
    speculative_multiplier: float = 0.5
    turnaround_multiplier: float = 0.5
    narrow_moat_multiplier: float = 0.75   # "smaller positions, especially initially"
    max_sector_weight: float = 0.30        # soft warning (Adam's biggest sector is 27%)


@dataclass(frozen=True)
class DividendRules:  # Lesson 8 §8.1
    min_yield: float = 0.05
    us_min_yield_screen: float = 0.03
    min_dps_growth_years: int = 5
    payout_min: float = 0.20
    payout_max: float = 1.00


@dataclass(frozen=True)
class TurnaroundRules:  # Lesson 8 §8.7
    profit_drop_one_year: float = 0.25
    consecutive_decline_years: int = 2


@dataclass(frozen=True)
class ExecutionRules:
    """Paper-trading fill model (user spec: instant fill at mid + flat slippage; illiquid ⇒ mid debuff).

    Research basis: US equity slippage typically 5–20 bps per trade depending on cap/size; large liquid
    names at the low end. Retail option fills usually land between mid and the touch.
    """
    stock_slippage_bps: float = 5.0
    option_slippage_per_share: float = 0.01   # $1 per contract
    illiquid_spread_pct: float = 0.005        # spread > 0.5% of mid ⇒ illiquid (stocks)
    illiquid_option_spread_pct: float = 0.10  # spread > 10% of mid ⇒ illiquid (options)
    illiquid_min_volume: int = 200_000        # avg daily shares
    illiquid_debuff_frac: float = 0.5         # fill at mid ± 50% of half-spread when illiquid
    no_quote_spread_pct: float = 0.002        # synthetic spread if only last price is known
    commission_per_share: float = 0.0         # user: nothing but slippage
    default_cash: float = 100_000.0


@dataclass(frozen=True)
class VMIRules:
    track: TrackRecordRules = field(default_factory=TrackRecordRules)
    speculative: SpeculativeRules = field(default_factory=SpeculativeRules)
    growth: GrowthRules = field(default_factory=GrowthRules)
    moat: MoatRules = field(default_factory=MoatRules)
    profitability: ProfitabilityRules = field(default_factory=ProfitabilityRules)
    debt: DebtRules = field(default_factory=DebtRules)
    valuation: ValuationRules = field(default_factory=ValuationRules)
    technical: TechnicalRules = field(default_factory=TechnicalRules)
    portfolio: PortfolioRules = field(default_factory=PortfolioRules)
    dividend: DividendRules = field(default_factory=DividendRules)
    turnaround: TurnaroundRules = field(default_factory=TurnaroundRules)
    execution: ExecutionRules = field(default_factory=ExecutionRules)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_overrides(self, overrides: dict[str, dict[str, Any]] | None) -> "VMIRules":
        """Return a copy with e.g. {"profitability": {"min_roe": 0.15}} applied."""
        if not overrides:
            return self
        new = self
        for section, values in overrides.items():
            current = getattr(new, section, None)
            if current is None or not isinstance(values, dict):
                continue
            valid = {k: v for k, v in values.items() if hasattr(current, k)}
            new = replace(new, **{section: replace(current, **valid)})
        return new


RULES = VMIRules()


def _load_saved_settings() -> None:
    """Values edited on the Settings screen (config/rules_settings.json) apply to every entry point."""
    from vmi import settings
    settings.load()


_load_saved_settings()
