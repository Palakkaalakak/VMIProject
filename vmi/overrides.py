"""Per-ticker judgement overrides: the human/AI-in-the-loop layer.

Ground rule: distorted data is fixed per ticker with a written reason, never by changing the general
formula. Every overridable input is declared ONCE in FIELDS below. Validation, the API schema, the UI
form and the CLI are all generated from it, so adding an override is one line here plus the line of
code that applies it (search the key name in vmi/analysis/).

Where overrides live (later wins):
    config/judgements.json   committed to git, survives database resets (use for considered judgements)
    database (data/vmi.db)   quick edits from the UI / API

CLI (works for humans and AI agents alike):
    python -m vmi.overrides schema                          # every key, type and meaning
    python -m vmi.overrides show TMO                        # effective overrides for one ticker
    python -m vmi.overrides list                            # every ticker with overrides
    python -m vmi.overrides set TMO growth=0.13 method=dcf_fcf --note "consensus distorted" [--commit]
    python -m vmi.overrides clear TMO [growth method] [--commit]   # remove keys (or all) from DB / judgements
`--commit` writes config/judgements.json instead of the database.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

GROWTH_SOURCES = ("ib", "finviz", "zacks", "yahoo", "stockanalysis")
STEP_CHOICES = ("", "pass", "fail")


@dataclass(frozen=True)
class Field:
    key: str
    kind: str          # number | percent | text | choice | list_number | list_choice | json
    group: str
    label: str
    help: str
    choices: tuple[str, ...] = ()


def _methods() -> tuple[str, ...]:
    from vmi.analysis.valuation.methods import REGISTRY
    return ("",) + tuple(REGISTRY)


def _biz_types() -> tuple[str, ...]:
    from vmi.analysis.classify import BizType
    return ("",) + tuple(b.value for b in BizType)


FIELDS: tuple[Field, ...] = (
    # --- growth --------------------------------------------------------------------------------------
    Field("growth", "percent", "Growth", "Growth yrs 1–5", "Replaces the analyst growth (decimal, 0.13 = 13%)."),
    Field("growth_blend", "choice", "Growth", "Growth blend",
          "How analyst sources are combined when no growth number is set (default: lowest).",
          ("", "lowest", "average", "median")),
    Field("exclude_sources", "list_choice", "Growth", "Ignore growth sources",
          "Analyst sources to ignore for this ticker (e.g. one is stale).", GROWTH_SOURCES),
    Field("growth_6_10", "percent", "Growth", "Growth yrs 6–10", "Default: yrs 1–5 growth capped at 15%."),
    Field("growth_11_20", "percent", "Growth", "Growth yrs 11–20", "Default 4% (Adam's conservative option: 2%)."),
    # --- valuation inputs --------------------------------------------------------------------------------
    Field("method", "choice", "Valuation", "Valuation method", "Force a method instead of the automatic choice.",
          ()),  # choices filled lazily (see schema())
    Field("base_cf", "number", "Valuation", "Base cash flow", "Starting cash flow for DCF/DNI (price currency)."),
    Field("discount_rate", "percent", "Valuation", "Discount rate", "Replaces the beta-table rate."),
    Field("beta", "number", "Valuation", "Beta", "Replaces the data beta (drives the discount rate)."),
    Field("shares", "number", "Valuation", "Shares", "Share count in price units (ADR ratios, share classes)."),
    Field("cash", "number", "Valuation", "Cash", "Cash + short-term investments (price currency)."),
    Field("debt", "number", "Valuation", "Debt", "Total debt (price currency)."),
    Field("iv_haircut", "percent", "Valuation", "IV haircut", "Per-ticker flat haircut on DCF/DNI (0 = none)."),
    Field("iv_override", "number", "Valuation", "Intrinsic value", "Final IV (skips the computed one)."),
    Field("conservative_override", "number", "Valuation", "Conservative value", "Final conservative value."),
    # --- classification ------------------------------------------------------------------------------------
    Field("biz_type", "choice", "Classification", "Business type", "Changes method choice and step exceptions.", ()),
    Field("category", "choice", "Classification", "Category", "Portfolio category (drives allocation).",
          ("", "predictable", "growth", "large_growth", "speculative_growth", "turnaround")),
    # --- moat review (discretionary: the code only gathers evidence, see Step 3) ---------------------------
    Field("moat_grade", "choice", "Moat review", "Moat verdict", "Your verdict after checking the evidence.",
          ("", "wide", "narrow", "none")),
    Field("moat_sources", "list_choice", "Moat review", "Moat sources present",
          "Adam: ≥3 of 5 → invest (4+ wide, 3 narrow if no verdict given).",
          ("brand", "switching_costs", "network_effect", "barriers", "scale")),
    Field("moat_score", "number", "Moat review", "Moat score /10", "AI or human score; Adam wants 7–9 (8+ wide)."),
    # --- verdicts ---------------------------------------------------------------------------------------------
    *(Field(f"step{i}", "choice", "Steps", f"Step {i}", "Force this step's verdict (the reason goes in the note).",
            STEP_CHOICES) for i in range(1, 8)),
    # --- trading -----------------------------------------------------------------------------------------------
    Field("buy_levels", "list_number", "Trading", "Buy levels", "Manual tranche buy prices, e.g. 405, 385, 363."),
    Field("allocation_multiplier", "number", "Trading", "Allocation ×", "Position size multiplier (1 = normal)."),
    Field("scan", "choice", "Trading", "Superscanner", "pin = always deep-analyse; exclude = never show.",
          ("", "pin", "exclude")),
)
BY_KEY = {f.key: f for f in FIELDS}
META_KEYS = ("note", "source")  # stored alongside, not validated as inputs


def schema() -> list[dict]:
    lazy = {"method": _methods(), "biz_type": _biz_types()}
    return [{**asdict(f), "choices": list(lazy.get(f.key, f.choices))} for f in FIELDS]


def validate(data: dict) -> dict:
    """Coerce and check values. Empty values (None, '', []) mean 'remove this key'. Raises ValueError."""
    lazy = {"method": _methods(), "biz_type": _biz_types()}
    out: dict = {}
    for key, raw in data.items():
        if key in META_KEYS:
            continue
        f = BY_KEY.get(key)
        if f is None:
            raise ValueError(f"unknown override '{key}' (see: python -m vmi.overrides schema)")
        if raw in (None, "", [], {}):
            out[key] = None
            continue
        choices = lazy.get(key, f.choices)
        if f.kind in ("number", "percent"):
            v = float(raw)
            if f.kind == "percent" and abs(v) > 1.5:
                raise ValueError(f"{key}: give a decimal (0.13 = 13%), got {raw}")
            out[key] = v
        elif f.kind == "choice":
            if str(raw) not in choices:
                raise ValueError(f"{key}: must be one of {[c for c in choices if c]}")
            out[key] = str(raw)
        elif f.kind == "list_number":
            items = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
            out[key] = sorted((float(x) for x in items if str(x).strip()), reverse=True)
        elif f.kind == "list_choice":
            items = raw if isinstance(raw, list) else str(raw).split(",")
            bad = [x for x in items if x.strip() not in choices]
            if bad:
                raise ValueError(f"{key}: unknown {bad}; choose from {list(choices)}")
            out[key] = [x.strip() for x in items]
        elif f.kind == "json":
            out[key] = raw if isinstance(raw, (dict, list)) else json.loads(raw)
        else:
            out[key] = str(raw)
    return out


def describe(ov: dict) -> list[str]:
    """Human-readable list of the overrides in effect (shown in the analysis report)."""
    return [f"{BY_KEY[k].label}: {v}" for k, v in ov.items() if k in BY_KEY and v not in (None, "", [])]


# ================================================================================================= CLI
def _parse_assignments(items: list[str]) -> dict:
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"expected key=value, got '{item}'")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> None:
    from vmi import store

    ap = argparse.ArgumentParser(prog="python -m vmi.overrides", description="Per-ticker judgement overrides")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema", help="list every override key")
    sub.add_parser("list", help="every ticker with overrides")
    sh = sub.add_parser("show", help="effective overrides for a ticker")
    sh.add_argument("ticker")
    st = sub.add_parser("set", help="set keys (key=value …)")
    st.add_argument("ticker")
    st.add_argument("assignments", nargs="+")
    st.add_argument("--note", default="")
    st.add_argument("--commit", action="store_true", help="write config/judgements.json instead of the DB")
    cl = sub.add_parser("clear", help="remove keys (or every key) for a ticker")
    cl.add_argument("ticker")
    cl.add_argument("keys", nargs="*")
    cl.add_argument("--commit", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "schema":
        for f in schema():
            ch = f" [{', '.join(c for c in f['choices'] if c)}]" if f["choices"] else ""
            print(f"{f['group']:14s} {f['key']:22s} {f['kind']:12s} {f['help']}{ch}")
    elif a.cmd == "list":
        print(json.dumps(store.all_overrides(), indent=2, default=str))
    elif a.cmd == "show":
        print(json.dumps(store.get_override(a.ticker), indent=2, default=str))
    elif a.cmd == "set":
        data = validate(_parse_assignments(a.assignments))
        res = (store.set_judgement if a.commit else store.set_override)(a.ticker, data, a.note)
        print(json.dumps(res, indent=2, default=str))
    elif a.cmd == "clear":
        data = {k: None for k in a.keys} if a.keys else None
        res = (store.set_judgement if a.commit else store.set_override)(a.ticker, data, "", clear_all=not a.keys)
        print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
