from vmi import ai_helper


def test_status_is_unavailable_without_a_server():
    assert ai_helper.status()["available"] is False       # nothing listens on the Ollama port in tests


def test_prompt_carries_adams_rules_and_the_facts_only():
    fs = {"signals": [{"reading": "good", "label": "Margin level", "text": "gross margin 70%", "source": "inferred"}]}
    p = ai_helper.prompt_for("ABC", "Abc Inc", "Software", fs, {"summary": {"peers": 4}}, {"competition": "We compete with X.", "customer_concentration": []})
    assert "Wide moat" in p and "gross margin 70%" in p and "We compete with X." in p and "never invent" in p


def test_opinion_strips_reasoning_preamble(monkeypatch):
    import io
    import json
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps({"response": "<think>hmm</think>Narrow moat."}).encode()))
    assert ai_helper.opinion("x") == "Narrow moat."
