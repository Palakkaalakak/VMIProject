"""Pure parsers: watchlist import formats, JS-object tokenizer, JSON-safe API encoder."""
import math

import numpy as np

from vmi.api.jsonsafe import clean
from vmi.data.jsobj import balanced, parse
from vmi.watchlist.service import parse_import


def test_import_adam_pipe_format():
    rows = parse_import("MSFT|513,466,419|570.31\nNKE|41|43.84")
    assert rows[0] == {"symbol": "MSFT", "iv": 570.31, "supports": [513, 466, 419]}
    assert rows[1]["symbol"] == "NKE"


def test_import_csv_with_header():
    rows = parse_import("symbol,iv,supports\nAAPL,270.77,261;246\n")
    assert rows == [{"symbol": "AAPL", "iv": 270.77, "supports": [261, 246]}]


def test_import_tradingview_list():
    assert [r["symbol"] for r in parse_import("NASDAQ:MSFT, NYSE:V,AAPL")] == ["MSFT", "V", "AAPL"]


def test_jsobj_unquoted_keys_and_balanced():
    src = '{datekey:["2024","2025"],revenue:[1.5,2],name:"a}b"}'
    assert parse(src) == {"datekey": ["2024", "2025"], "revenue": [1.5, 2], "name": "a}b"}
    assert balanced("x={a:{b:1}} tail", 2) == "{a:{b:1}}"


def test_jsonsafe_numpy_and_nan():
    out = clean({"b": np.bool_(True), "f": np.float64(1.5), "n": float("nan"), "arr": np.array([1, 2]),
                 "inf": math.inf})
    assert out == {"b": True, "f": 1.5, "n": None, "arr": [1, 2], "inf": None}


def test_fdic_holding_name_matching():
    from vmi.data.fdic import _norm, _score

    assert _norm("PNC Financial Services Group, Inc.") == _norm("PNC FINL SERVICES GROUP INC") == "PNC"
    assert _norm("U.S. Bancorp") == _norm("U S BCORP") == "US"
    assert _norm("Bank of New York Mellon Corporation") == _norm("BANK OF NY MELLON CORP THE")
    assert _score(_norm("U.S. Bancorp"), _norm("US METRO BCORP")) == 0  # single token must match exactly
    assert _score(_norm("Cullen/Frost Bankers, Inc."), _norm("CULLEN FROST BANKERS INC")) == 3
