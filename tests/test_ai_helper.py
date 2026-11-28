from vmi import ai_helper


def test_status_is_unavailable_without_a_server(monkeypatch):
    # hermetic: the owner's PC may really have the built-in AI downloaded
    monkeypatch.setattr(ai_helper.ai_runtime, "status", lambda: {"ready": False, "model": "x"})
    assert ai_helper.status()["available"] is False       # nothing listens on the Ollama port in tests


def test_prompt_carries_adams_rules_and_the_facts_only():
    fs = {"signals": [{"reading": "good", "label": "Margin level", "text": "gross margin 70%", "source": "inferred"}]}
    p = ai_helper.prompt_for("ABC", "Abc Inc", "Software", fs, {"summary": {"peers": 4}}, {"competition": "We compete with X.", "customer_concentration": []})
    assert "Wide moat" in p and "gross margin 70%" in p and "We compete with X." in p and "never invent" in p


def test_opinion_strips_reasoning_preamble(monkeypatch):
    import io
    import json
    import urllib.request
    monkeypatch.setattr(ai_helper, "status", lambda: {"backend": "ollama", "model": "x"})     # hermetic: never start the real built-in server
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps({"response": "<think>hmm</think>Narrow moat."}).encode()))
    assert ai_helper.opinion("x") == "Narrow moat."



def test_assistant_resumes_length_limited_markdown(monkeypatch):
    from vmi import ai_helper as h

    monkeypatch.setattr(h.ai_runtime, "ensure_running", lambda: "local")
    replies = iter([
        {"content": "| Stock | P&L |\n| --- | --- |\n| AAA | $13 |", "finish_reason": "length"},
        {"content": "| BBB | $20 |\n\nBBB contributed more.", "finish_reason": "stop"},
    ])
    seen = []
    def reply(base, body, timeout):
        seen.append(body)
        return next(replies)
    monkeypatch.setattr(h.ai_runtime, "_post_chat", reply)
    text = h.assistant_chat("builtin", [{"role": "user", "content": "Compare holdings"}], [], None)
    assert "| AAA | $13 |\n| BBB | $20 |" in text and text.endswith("BBB contributed more.")
    assert "Continue exactly" in seen[1]["messages"][-1]["content"]


def test_assistant_errors_distinguish_current_safety_from_timeout(monkeypatch):
    import pytest
    from vmi import ai_helper as h

    rt = h.ai_runtime
    monkeypatch.setitem(rt._server, "tripped_at", 1)
    monkeypatch.setitem(rt._server, "run_trip_from", 1)
    monkeypatch.setattr(rt, "ensure_running", lambda: "local")
    messages = [{"role": "user", "content": "My question"}]

    def failed(base, body, timeout):
        raise TimeoutError()

    monkeypatch.setattr(rt, "_post_chat", failed)
    with pytest.raises(h.AssistantUnavailable, match="did not respond within 10 minutes"):
        h.assistant_chat("builtin", messages, [], None)
    monkeypatch.setitem(rt._server, "tripped_at", 2)
    monkeypatch.setitem(rt._server, "tripped", "free system RAM is down to 648 MB")
    with pytest.raises(h.AssistantUnavailable, match="stopped for safety.*648 MB"):
        h.assistant_chat("builtin", messages, [], None)


def test_assistant_processes_all_chunks_of_long_input(monkeypatch):
    from vmi import ai_helper as h

    monkeypatch.setattr(h.ai_runtime, "ensure_running", lambda: "local")
    prompts = []

    def reply(base, body, timeout):
        prompts.append(body["messages"][-1]["content"])
        return {"content": f"Pass {len(prompts)}", "finish_reason": "stop"}

    monkeypatch.setattr(h.ai_runtime, "_post_chat", reply)
    text = "FIRST" + "x" * 24999 + "LAST"
    assert h.assistant_chat("builtin", [{"role": "user", "content": text}], [], None) == "Pass 4"
    assert "FIRST" in prompts[0] and "LAST" in prompts[2]
    assert "Pass 2" in prompts[2] and "Pass 3" in prompts[3]


def test_assistant_continues_beyond_previous_context_cutoff(monkeypatch):
    from vmi import ai_helper as h

    monkeypatch.setattr(h.ai_runtime, "ensure_running", lambda: "local")
    chunks = [f"Part {i}. " + str(i) * 8500 + "." for i in range(8)]
    remaining = iter(chunks)
    compacted = []

    def reply(base, body, timeout):
        last = body["messages"][-1]["content"]
        if "Transcript excerpt:" in last:
            compacted.append(last)
            return {"content": "The earlier sections were delivered.", "finish_reason": "stop"}
        if "Continue exactly" in last:
            assert len(body["messages"][-2]["content"]) <= 7000
        chunk = next(remaining)
        return {"content": chunk, "finish_reason": "stop" if chunk == chunks[-1] else "length"}

    monkeypatch.setattr(h.ai_runtime, "_post_chat", reply)
    result = h.assistant_chat("builtin", [{"role": "user", "content": "Give a detailed report"}], [], None)
    assert result == "\n\n".join(chunks)
    assert len(result) > 65_000 and len(compacted) >= 7


def test_assistant_compacts_older_turns_but_preserves_latest_follow_up(monkeypatch):
    from vmi import ai_helper as h

    monkeypatch.setattr(h.ai_runtime, "ensure_running", lambda: "local")

    def reply(base, body, timeout):
        messages = body["messages"]
        if "Transcript excerpt" in messages[-1]["content"]:
            return {"content": "Earlier ticker BBB", "finish_reason": "stop"}
        assert messages[1:3] == [{"role": "user", "content": "Latest prior question"},
                                 {"role": "assistant", "content": "Latest prior answer"}]
        assert "Earlier ticker BBB" in messages[-1]["content"] and messages[-1]["content"].endswith("Current follow-up")
        return {"content": "Follow-up grounded in context", "finish_reason": "stop"}

    monkeypatch.setattr(h.ai_runtime, "_post_chat", reply)
    assert h.assistant_chat("builtin", [
        {"role": "system", "content": "Answer follow-ups"},
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "BBB " + "x" * 20000},
        {"role": "user", "content": "Latest prior question"},
        {"role": "assistant", "content": "Latest prior answer"},
        {"role": "user", "content": "Current follow-up"},
    ], [], None) == "Follow-up grounded in context"
