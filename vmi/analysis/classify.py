"""Company-type classification → drives which VMI exceptions and valuation method apply.

Business types (Lesson 5 decision table + Step 1/4/5 exceptions + Lesson 8 categories):
  bank, insurance, asset_manager (finance: brokers/asset managers/finance cos), reit,
  utility, cyclical (deep cyclicals / commodities / property developers / shipping / airlines…),
  speculative (unprofitable hyper-growth), normal.

Primary signal = SEC SIC code (official, free, available for all filers); secondary = sector/industry
strings from market data providers. User overrides always win (stored per ticker).
"""
from __future__ import annotations

from enum import Enum

from vmi.rules import RULES


class BizType(str, Enum):
    NORMAL = "normal"
    BANK = "bank"
    INSURANCE = "insurance"
    ASSET_MANAGER = "asset_manager"
    REIT = "reit"
    UTILITY = "utility"
    CYCLICAL = "cyclical"
    SPECULATIVE = "speculative"


# SIC ranges (inclusive) → type. Source: SEC SIC code list.
_SIC_RULES: list[tuple[int, int, BizType]] = [
    (6020, 6036, BizType.BANK),          # commercial banks, savings institutions
    (6000, 6019, BizType.BANK),
    (6111, 6163, BizType.ASSET_MANAGER),  # credit agencies, mortgage bankers, loan brokers
    (6172, 6172, BizType.ASSET_MANAGER),
    (6199, 6199, BizType.ASSET_MANAGER),  # finance services
    (6200, 6299, BizType.ASSET_MANAGER),  # brokers, dealers, exchanges, investment advice
    (6300, 6411, BizType.INSURANCE),
    (6798, 6798, BizType.REIT),
    (6500, 6553, BizType.CYCLICAL),       # real estate operators / developers
    (4900, 4991, BizType.UTILITY),
    (1000, 1499, BizType.CYCLICAL),       # mining, oil & gas extraction
    (1500, 1799, BizType.CYCLICAL),       # construction
    (2900, 2999, BizType.CYCLICAL),       # petroleum refining
    (3310, 3399, BizType.CYCLICAL),       # primary metals
    (3711, 3716, BizType.CYCLICAL),       # motor vehicles
    (4400, 4499, BizType.CYCLICAL),       # water transportation / shipping
    (4512, 4522, BizType.CYCLICAL),       # airlines
    (2800, 2821, BizType.CYCLICAL),       # basic chemicals
]

_TEXT_RULES: list[tuple[tuple[str, ...], BizType]] = [
    (("reit",), BizType.REIT),
    (("bank", "savings institution"), BizType.BANK),
    (("insurance",), BizType.INSURANCE),
    # NB: "Credit Services" (V, MA, AXP-style networks) and "Financial Data & Stock Exchanges" (SPGI, MCO)
    # are deliberately NOT here — Adam values card networks / ratings agencies with DCF like normal companies.
    (("asset management", "capital markets", "brokerage", "investment banking", "mortgage finance"),
     BizType.ASSET_MANAGER),
    (("utilities", "utility"), BizType.UTILITY),
]


def from_sic(sic: int | None) -> BizType | None:
    if not sic:
        return None
    for lo, hi, t in _SIC_RULES:
        if lo <= sic <= hi:
            return t
    return None


def from_text(*texts: str) -> BizType | None:
    blob = " ".join(t.lower() for t in texts if t)
    if not blob:
        return None
    for keys, t in _TEXT_RULES:
        if any(k in blob for k in keys):
            return t
    if any(k in blob for k in RULES.moat.no_moat_industries):
        return BizType.CYCLICAL
    return None


def is_no_moat_industry(*texts: str) -> bool:
    blob = " ".join(t.lower() for t in texts if t)
    return any(k in blob for k in RULES.moat.no_moat_industries)


def classify(sic: int | None, sic_desc: str = "", sector: str = "", industry: str = "",
             revenue_growth: float | None = None, profitable_years: int | None = None,
             override: str | None = None) -> BizType:
    if override:
        try:
            return BizType(override)
        except ValueError:
            pass
    t = from_text(industry) or from_sic(sic) or from_text(sic_desc, sector)
    if t:
        return t
    # Speculative growth: very high revenue growth and not yet consistently profitable (<5 yrs)
    if (revenue_growth is not None and revenue_growth >= RULES.speculative.min_revenue_growth
            and (profitable_years or 0) < RULES.speculative.upgrade_after_years):
        return BizType.SPECULATIVE
    return BizType.NORMAL


# Sector buckets for portfolio construction (Lesson 8: 3 defensive, 5 cyclical, 3 growth sectors)
DEFENSIVE_SECTORS = {"healthcare", "health care", "consumer staples", "consumer defensive", "utilities"}
CYCLICAL_SECTORS = {"energy", "basic materials", "materials", "financials", "financial services",
                    "financial", "real estate", "industrials"}
GROWTH_SECTORS = {"technology", "information technology", "consumer discretionary", "consumer cyclical",
                  "communication services"}


def sector_bucket(sector: str) -> str:
    s = (sector or "").lower()
    if s in DEFENSIVE_SECTORS:
        return "defensive"
    if s in CYCLICAL_SECTORS:
        return "cyclical"
    if s in GROWTH_SECTORS:
        return "growth"
    return "unknown"
