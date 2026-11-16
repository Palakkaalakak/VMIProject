"""Scanner presets. A preset = scan options + rule overrides that apply to ONE scan only (nothing is saved).

  current          whatever is on the Settings page (default)
  adam             Adam's course rules: every rule back to its course default (the Settings page is ignored for this
                   scan), 10-year uptrend required, large caps (>= $10B, his personal preference, l.235)
  adam_excellent   as `adam` with his "excellent" bars: ROE and ROIC >= 15% (l.1237)
  adam_speculative Adam's speculative-growth entry (l.2095): revenue growth >= 50%, profits may be missing, the long
                   uptrend filter is dropped because such companies are young
  custom           the owner edits any scan option and ANY rule on the scanner page; those values ride in `rules`

Per-scan overrides typed on the scanner page (`rules`) are applied on top of the preset.
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "current": {"label": "Current settings", "note": "Uses the rules as set on the Settings page.",
                "params": {}, "rules": {}, "course_defaults": False},
    "adam": {"label": "Adam: great business (steps 1-5)",
             "note": "All rules at Adam's course defaults, 10-year uptrend required, market cap >= $10B (his personal preference).",
             "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False},
             "rules": {}, "course_defaults": True},
    "adam_excellent": {"label": "Adam: excellent (ROE and ROIC >= 15%)",
                       "note": "As above with his 'excellent' profitability bars.",
                       "params": {"min_market_cap": 10e9, "require_ten_year_uptrend": True, "include_speculative": False},
                       "rules": {"profitability": {"min_roe": 0.15, "min_roic": 0.15}}, "course_defaults": True},
    "adam_speculative": {"label": "Adam: speculative growth",
                         "note": "Revenue growing >= 50%, profits not required yet, no 10-year chart filter (young companies); half allocation.",
                         "params": {"include_speculative": True, "require_ten_year_uptrend": False, "min_market_cap": 1e9},
                         "rules": {}, "course_defaults": True},
    "custom": {"label": "Custom", "note": "Edit any scan option and any rule below; nothing is saved to Settings.",
               "params": {}, "rules": {}, "course_defaults": False},
}


def rule_changes(preset: str, extra: dict | None) -> tuple[dict, bool]:
    """(rule overrides for this scan, apply course defaults first?) for a preset plus the owner's per-scan edits."""
    pr = PRESETS.get(preset or "current")
    if pr is None:
        raise ValueError(f"unknown preset '{preset}'; choose from {sorted(PRESETS)}")
    merged = {sec: dict(v) for sec, v in pr["rules"].items()}
    for sec, vals in (extra or {}).items():
        merged.setdefault(sec, {}).update(vals)
    return merged, bool(pr["course_defaults"])


def resolved_params(preset: str, overrides: dict | None = None) -> dict:
    pr = PRESETS[preset]
    return {**pr["params"], **(overrides or {})}
