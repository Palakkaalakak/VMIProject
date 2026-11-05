"""Judgement override layer (vmi/overrides.py + vmi/store.py): validation, storage, application."""
import json

import pytest

from vmi import overrides as O
from vmi import store
from vmi.config import get_settings


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Empty database and an empty judgements file for one test."""
    monkeypatch.setattr(get_settings(), "db_url", f"sqlite:///{tmp_path / 'vmi.db'}")
    monkeypatch.setattr(store, "_engine", None)
    monkeypatch.setattr(store, "_Session", None)
    jf = tmp_path / "judgements.json"
    jf.write_text(json.dumps({"_doc": "keep me"}))
    monkeypatch.setattr(store, "JUDGEMENTS_FILE", jf)
    return jf


def test_schema_covers_every_field_and_fills_choices():
    sch = {f["key"]: f for f in O.schema()}
    assert {"growth", "growth_blend", "exclude_sources", "beta", "step6", "buy_levels", "scan"} <= set(sch)
    assert "dcf_fcf" in sch["method"]["choices"] and "bank" in sch["biz_type"]["choices"]


def test_validate_coerces_and_rejects():
    v = O.validate({"growth": "0.13", "buy_levels": "363, 405;385", "exclude_sources": "zacks",
                    "step6": "pass", "method": "", "note": "ignored here"})
    assert v == {"growth": 0.13, "buy_levels": [405.0, 385.0, 363.0], "exclude_sources": ["zacks"],
                 "step6": "pass", "method": None}
    for bad in ({"growth": "13"}, {"nope": 1}, {"step1": "maybe"}, {"exclude_sources": "bloomberg"}):
        with pytest.raises(ValueError):
            O.validate(bad)


def test_db_overrides_merge_remove_and_clear(tmp_store):
    store.set_override("tmo", {"growth": 0.13, "method": "dcf_fcf"}, "consensus distorted")
    store.set_override("TMO", {"beta": 0.8, "method": None})            # merge + remove one key
    o = store.get_override("TMO")
    assert o["growth"] == 0.13 and o["beta"] == 0.8 and "method" not in o and o["note"] == "consensus distorted"
    assert store.set_override("TMO", None, clear_all=True) == {}


def test_committed_judgements_round_trip(tmp_store):
    store.set_judgement("asml", {"growth": 0.2}, "cycle peak")
    raw = json.loads(tmp_store.read_text())
    assert raw["_doc"] == "keep me" and raw["ASML"] == {"growth": 0.2, "note": "cycle peak"}
    store.set_override("ASML", {"beta": 1.1})                           # DB layers on top of the file
    assert store.get_override("ASML")["source"] == "judgement+db"
    store.set_judgement("ASML", None, clear_all=True)
    assert "ASML" not in json.loads(tmp_store.read_text())


def test_cli_set_show_clear(tmp_store, capsys):
    O.main(["set", "NKE", "growth_blend=average", "step1=pass", "--note", "temporary dip"])
    capsys.readouterr()
    O.main(["show", "NKE"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["growth_blend"] == "average" and shown["step1"] == "pass" and shown["note"] == "temporary dip"
    O.main(["clear", "NKE"])
    assert store.get_override("NKE") == {}


def test_step_verdicts_can_be_forced():
    from vmi.analysis.pipeline import _apply_step_overrides
    from vmi.analysis.steps import StepResult

    steps = [StepResult(i, f"s{i}", passed=(i != 1), score=0.0) for i in range(1, 8)]
    out = _apply_step_overrides(steps, {"step1": "pass", "step6": "fail", "note": "temporary dip"})
    assert out[0].passed and not out[5].passed and "temporary dip" in out[0].notes[0]
    assert out[1].passed  # untouched steps keep their verdict


def test_scanner_pins_only_for_number_changing_judgements():
    assert O.pins_in_scanner({"growth": 0.13}) and O.pins_in_scanner({"scan": "pin"})
    assert not O.pins_in_scanner({"moat_grade": "wide", "moat_score": 9})
    assert not O.pins_in_scanner({"growth": 0.13, "scan": "exclude"})


def test_turnaround_exception_only_needs_the_reviewed_moat_intact():
    from vmi.analysis.pipeline import _turnaround_exception
    from vmi.analysis.steps import Check, StepResult

    def s1():
        return StepResult(1, "track", False, 0.5, [Check("revenue_consistent", False), Check("earnings_consistent", False)])

    intact = StepResult(3, "moat", True, 1.0, extra={"verdict": {"grade": "wide", "passes": True}})
    broken = StepResult(3, "moat", False, 0.0, extra={"verdict": {"grade": "none", "passes": False}})
    unreviewed = StepResult(3, "moat", True, 1.0, extra={"verdict": None})
    for moat, cat, want in ((intact, "turnaround", True), (broken, "turnaround", False),
                            (unreviewed, "turnaround", False), (intact, "growth", False)):
        step1 = s1()
        _turnaround_exception(step1, moat, cat)
        assert step1.passed is want
