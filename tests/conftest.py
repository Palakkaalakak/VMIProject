"""Shared offline fixtures. Tests never touch the network: they build Fundamentals objects directly."""
from __future__ import annotations

import pytest

from vmi.data.models import Fundamentals, Point


def make_fund(ticker: str = "TEST", years: tuple[int, ...] = tuple(range(2016, 2026)), ttm: dict | None = None,
              latest: dict | None = None, **series: list[float]) -> Fundamentals:
    """Build a Fundamentals with annual series aligned to `years` (oldest → newest)."""
    f = Fundamentals(ticker=ticker)
    for concept, vals in series.items():
        ys = years[-len(vals):]
        f.annual[concept] = [Point(end=f"{y}-12-31", value=float(v), fy=y) for y, v in zip(ys, vals)]
    f.ttm = dict(ttm or {})
    f.latest = dict(latest or {})
    return f


@pytest.fixture
def fund_factory():
    return make_fund
