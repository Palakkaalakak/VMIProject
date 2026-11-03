"""Provider-agnostic data models. Analysis code depends ONLY on these, never on a provider."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Point:
    end: str          # ISO date the period ends (or instant date)
    value: float
    fy: int | None = None


@dataclass
class Fundamentals:
    """Normalised financial history for one company. Money values in reporting currency units."""

    ticker: str
    cik: int | None = None
    name: str = ""
    currency: str = "USD"
    sic: int | None = None
    sic_description: str = ""
    sector: str = ""
    industry: str = ""
    # concept -> ordered (oldest→newest) list of fiscal-year values
    annual: dict[str, list[Point]] = field(default_factory=dict)
    # concept -> ordered list of single-quarter values (derived where needed)
    quarterly: dict[str, list[Point]] = field(default_factory=dict)
    # concept -> trailing-twelve-month value (flows only)
    ttm: dict[str, float] = field(default_factory=dict)
    # concept -> latest balance-sheet value (instants)
    latest: dict[str, float] = field(default_factory=dict)
    latest_date: str = ""
    source: str = "sec"
    warnings: list[str] = field(default_factory=list)

    def series(self, concept: str) -> list[float]:
        return [p.value for p in self.annual.get(concept, [])]

    def years(self, concept: str) -> list[str]:
        return [p.end for p in self.annual.get(concept, [])]

    def last(self, concept: str, default: float | None = None) -> float | None:
        if concept in self.ttm:
            return self.ttm[concept]
        if concept in self.latest:
            return self.latest[concept]
        s = self.annual.get(concept)
        return s[-1].value if s else default

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fundamentals":
        d = dict(d)
        d["annual"] = {k: [Point(**p) for p in v] for k, v in d.get("annual", {}).items()}
        d["quarterly"] = {k: [Point(**p) for p in v] for k, v in d.get("quarterly", {}).items()}
        return cls(**d)


@dataclass
class Estimates:
    """Forward-looking consensus (FactSet substitute: averaged across free sources)."""

    ticker: str
    eps_growth_5y: float | None = None          # blended long-term EPS growth (decimal)
    eps_growth_next_year: float | None = None
    revenue_growth_next_year: float | None = None
    long_term_growth: float | None = None       # conservative/long-term figure if available
    sources: dict[str, dict[str, float | None]] = field(default_factory=dict)
    beta: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    dividend_yield: float | None = None
    dividend_per_share: float | None = None
    payout_ratio: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    book_value_per_share: float | None = None
    sector: str = ""
    industry: str = ""
    earnings_date: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Quote:
    symbol: str
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    close: float | None = None
    volume: float | None = None
    avg_volume: float | None = None
    ts: float = 0.0
    source: str = ""

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.bid > 0 and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return self.last or self.close

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mid"] = self.mid
        return d


@dataclass
class OptionQuote:
    symbol: str          # underlying
    expiry: str          # YYYYMMDD
    strike: float
    right: str           # "C" / "P"
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    und_price: float | None = None
    con_id: int | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask > 0 and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return self.last

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mid"] = self.mid
        return d
