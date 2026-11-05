"""Editable rule settings: change any value in vmi/rules.py from the UI (Settings screen) without touching code.

Saved changes live in config/rules_settings.json as {section: {key: value}} and are applied at startup and
immediately on save. Only the differences from the defaults are stored, so resetting a key restores the
course default. Help texts come from the comments next to each setting in vmi/rules.py (one source of truth).

How changes take effect immediately: the rule objects in vmi.rules.RULES are shared by every module (many
functions bind e.g. RULES.valuation as a default argument), so the values are updated IN PLACE on those same
objects. That is the one deliberate exception to the dataclasses being frozen, and it lives only here.
Experiments that need a temporary variant use RULES.with_overrides(...) instead (a copy; nothing shared changes).
"""
from __future__ import annotations

import inspect
import json
import re
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any

from vmi import rules as R

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "config" / "rules_settings.json"
_DEFAULTS = R.VMIRules()  # pristine defaults (RULES itself gets updated in place)
BLEND_CHOICES = ("lowest", "second_lowest", "median", "average", "highest")
CHOICES = {("growth", "blend"): BLEND_CHOICES, ("growth", "blend_defensive"): BLEND_CHOICES,
           ("growth", "blend_when_disagree"): BLEND_CHOICES}
_lock = threading.Lock()


def _comments() -> dict[str, dict[str, str]]:
    """{section class name: {field: comment}} parsed from vmi/rules.py (inline + preceding comment lines)."""
    out: dict[str, dict[str, str]] = {}
    for f in fields(R.VMIRules):
        cls = type(getattr(_DEFAULTS, f.name))
        lines = inspect.getsource(cls).splitlines()
        notes, pending = {}, []
        for line in lines[1:]:
            s = line.strip()
            if s.startswith("#"):
                pending.append(s.lstrip("# ").strip())
                continue
            m = re.match(r"(\w+)\s*:\s*[^=]+=\s*.*?(?:#\s*(.*))?$", s)
            if m and not s.startswith(("def ", "@", '"""')):
                notes[m.group(1)] = " ".join(pending + ([m.group(2)] if m.group(2) else [])).strip()
            pending = [] if not s.startswith("#") else pending
        out[f.name] = notes
    return out


def _section_doc(name: str) -> str:
    src = inspect.getsource(type(getattr(_DEFAULTS, name))).splitlines()[0]
    return src.split("#", 1)[1].strip() if "#" in src else ""


def schema() -> list[dict]:
    """Every setting: section, key, type, current value, default, changed flag, help."""
    helps = _comments()
    out = []
    for sec in fields(R.VMIRules):
        cur, dft = getattr(R.RULES, sec.name), getattr(_DEFAULTS, sec.name)
        for f in fields(type(cur)):
            value, default = getattr(cur, f.name), getattr(dft, f.name)
            out.append({"section": sec.name, "section_help": _section_doc(sec.name), "key": f.name,
                        "type": "choice" if (sec.name, f.name) in CHOICES else _kind(default),
                        "choices": list(CHOICES.get((sec.name, f.name), ())), "value": value, "default": default, "changed": value != default,
                        "help": helps.get(sec.name, {}).get(f.name, "")})
    return out


def _kind(v: Any) -> str:
    return ("bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "float" if isinstance(v, float)
            else "text" if isinstance(v, str) else "list")


def _coerce(default: Any, raw: Any) -> Any:
    kind = _kind(default)
    if kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(float(raw))
    if kind == "float":
        return float(raw)
    if kind == "text":
        return str(raw)
    # tuples: list input, or comma-separated text; nested tuples (e.g. beta_table) come as JSON lists
    items = raw if isinstance(raw, (list, tuple)) else json.loads(raw) if str(raw).strip().startswith("[") \
        else [x.strip() for x in str(raw).split(",") if x.strip()]
    sample = default[0] if default else ""
    if isinstance(sample, tuple):
        return tuple(tuple(float(x) for x in row) for row in items)
    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        return tuple(type(sample)(x) for x in items)
    return tuple(str(x) for x in items)


def saved() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, dict)}


def _apply(changes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate everything first, then set the values in place on RULES (all or nothing). Raises ValueError."""
    done: dict[str, dict[str, Any]] = {}
    for section, values in changes.items():
        default = getattr(_DEFAULTS, section, None)
        if default is None:
            raise ValueError(f"unknown settings section '{section}'")
        for key, raw in values.items():
            if not hasattr(default, key):
                raise ValueError(f"unknown setting '{section}.{key}'")
            value = getattr(default, key) if raw is None else _coerce(getattr(default, key), raw)
            if (section, key) in CHOICES and value not in CHOICES[(section, key)]:
                raise ValueError(f"{section}.{key} must be one of {CHOICES[(section, key)]}")
            done.setdefault(section, {})[key] = value
    for section, values in done.items():
        for key, value in values.items():
            object.__setattr__(getattr(R.RULES, section), key, value)  # in place: see module docstring
    return done


def update(changes: dict[str, dict[str, Any]]) -> list[dict]:
    """Apply and persist changes ({section: {key: value}}; value None = back to default)."""
    with _lock:
        applied = _apply(changes)
        data = saved()
        for section, values in applied.items():
            for key, value in values.items():
                if value == getattr(getattr(_DEFAULTS, section), key):
                    data.get(section, {}).pop(key, None)
                else:
                    data.setdefault(section, {})[key] = list(value) if isinstance(value, tuple) else value
        data = {k: v for k, v in data.items() if v}
        SETTINGS_FILE.write_text(json.dumps({"_doc": "Edited from the Settings screen (vmi/settings.py). Only "
                                             "differences from the defaults in vmi/rules.py are stored.", **data},
                                            indent=2, ensure_ascii=False) + "\n")
    return schema()


def reset_all() -> list[dict]:
    return update({sec: {k: None for k in vals} for sec, vals in saved().items()})


def load() -> None:
    """Apply saved settings at startup (bad entries are skipped, never fatal)."""
    for section, values in saved().items():
        for key, value in values.items():
            try:
                _apply({section: {key: value}})
            except (ValueError, TypeError):
                pass
