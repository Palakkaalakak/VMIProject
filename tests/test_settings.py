"""Editable rule settings (vmi/settings.py): validation, in-place apply, persistence of differences only."""
import json

import pytest

from vmi import settings
from vmi.rules import RULES


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "rules_settings.json")
    yield tmp_path / "rules_settings.json"
    settings._apply({sec: {k: None for k in v} for sec, v in {"valuation": {"uncertainty_haircut": 0},
                                                              "growth": {"blend": 0}}.items()})


def test_schema_lists_every_rule_with_help():
    s = {(x["section"], x["key"]): x for x in settings.schema()}
    assert s[("growth", "blend")]["type"] == "choice" and "lowest" in s[("growth", "blend")]["choices"]
    assert "haircut" in s[("valuation", "uncertainty_haircut")]["help"].lower()
    assert s[("valuation", "beta_table")]["type"] == "list"


def test_update_applies_in_place_and_stores_only_differences(tmp_settings):
    from vmi.analysis.valuation import core  # binds RULES.valuation as a default argument at import time

    shared = core.discount_rate.__defaults__[0]
    settings.update({"valuation": {"uncertainty_haircut": "0.1"}, "growth": {"blend": "median"}})
    assert RULES.valuation.uncertainty_haircut == 0.1 and shared.uncertainty_haircut == 0.1  # same object
    saved = json.loads(tmp_settings.read_text())
    assert saved["valuation"] == {"uncertainty_haircut": 0.1} and saved["growth"] == {"blend": "median"}
    settings.update({"growth": {"blend": None}})  # back to default → removed from the file
    assert "growth" not in json.loads(tmp_settings.read_text()) and RULES.growth.blend == "lowest"


def test_invalid_values_are_rejected(tmp_settings):
    for bad in ({"growth": {"blend": "max"}}, {"nope": {"x": 1}}, {"growth": {"nope": 1}},
                {"valuation": {"iv_haircut": "abc"}}):
        with pytest.raises((ValueError, TypeError)):
            settings.update(bad)
