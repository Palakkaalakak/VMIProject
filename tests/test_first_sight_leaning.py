"""First-sight leaning: strengths must be able to outweigh a couple of warnings (MSFT: 4 good, 2 bad was labelled weak)."""
from vmi.analysis import first_sight as FS


def _assess_with(signals, monkeypatch, no_moat=False):
    it = iter(signals + [{"label": "x", "reading": "unknown", "text": "x", "source": "adam"}] * 6)
    monkeypatch.setattr(FS, "_margin_level", lambda f: next(it))
    monkeypatch.setattr(FS, "_margin_trend", lambda f: next(it))
    monkeypatch.setattr(FS, "_vs_peers", lambda p: [next(it), next(it)])
    monkeypatch.setattr(FS, "_pricing", lambda f: next(it))
    monkeypatch.setattr(FS, "_record", lambda s: next(it))
    return FS.assess(None, [], None, no_moat)["leaning"]


def _s(reading):
    return {"label": "s", "reading": reading, "text": reading, "source": "adam"}


def test_four_good_two_bad_is_not_weak(monkeypatch):
    sig = [_s("good"), _s("bad"), _s("good"), _s("good"), _s("good"), _s("bad")]
    assert _assess_with(sig, monkeypatch) == "narrow-looking"


def test_more_bad_than_good_is_weak(monkeypatch):
    sig = [_s("bad"), _s("bad"), _s("bad"), _s("good"), _s("unknown"), _s("unknown")]
    assert _assess_with(sig, monkeypatch) == "weak"


def test_one_bad_and_little_good_is_weak(monkeypatch):
    assert _assess_with([_s("bad"), _s("good"), _s("unknown")], monkeypatch) == "weak"


def test_no_moat_industry_is_weak_whatever_the_signals(monkeypatch):
    assert _assess_with([_s("good")] * 5, monkeypatch, no_moat=True) == "weak"
