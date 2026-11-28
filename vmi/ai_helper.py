"""Optional AI helper: a second opinion on one company's moat, from a LOCAL model (Ollama), at the owner's discretion.

It knows nothing by itself: the prompt carries Adam's rules (his own words from the master documents) and this company's numbers
and the app's at-first-sight signals, and asks for a short opinion. It is a reasoning aid, never a verdict: the answer is shown
with an "AI opinion, minor help" label and is not saved anywhere. Everything stays on this PC (Ollama's default address).
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urlsplit

from vmi import ai_runtime
from vmi.config import get_settings

ADAM = """You are helping a retail investor apply Adam Khoo's Value Momentum Investing moat step (Step 3). His rules:
- Wide moat: about 20 years of protection, no or insignificant competitors, can raise prices every year without losing customers or share, very high profit margins (examples: Visa 78% gross, Microsoft 68%). He buys these most.
- Narrow moat: about 10 years, several significant competitors, limited pricing power, average margins. He buys some.
- No moat: many competitors selling near-identical products, price decides, low margins (example: Singapore Airlines 16% gross). Avoided.
- Five sources, he wants at least 3: brand (or pricing power, same slot), switching costs, network effect, barriers to entry, economies of scale.
- Compare with the closest competitors: invest in the top dog; no clear leader means skip. Trouble signs: customers concentrated in a few buyers, margins falling for years, losing market share.
Use only the facts given. If something is not given, say it is unknown; never invent figures."""


def _ollama() -> dict:
    s = get_settings()
    try:
        with urllib.request.urlopen(f"{s.ai_url}/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        return {"available": True, "model": s.ai_model, "installed": s.ai_model in names or any(n.startswith(s.ai_model.split(":")[0]) for n in names),
                "url": s.ai_url}
    except Exception:
        return {"available": False, "model": s.ai_model, "installed": False, "url": s.ai_url}


def status(*, local_only: bool = False) -> dict:
    """Which backend can answer: an Ollama server that is already running, else the built-in one once downloaded.
    {"available", "backend": "ollama"|"builtin"|None, "model", "builtin": {...download state...}}"""
    b = ai_runtime.status()
    settings = get_settings()
    if local_only and urlsplit(settings.ai_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        o = {"available": False, "installed": False, "url": settings.ai_url}
    else:
        o = _ollama()
    backend = "ollama" if o["available"] and o["installed"] else "builtin" if b["ready"] else None
    return {"available": backend is not None, "backend": backend, "model": o["model"] if backend == "ollama" else b["model"],
            "installed": o["installed"], "url": o["url"], "builtin": b}


def prompt_for(symbol: str, name: str, industry: str, first_sight: dict, peers: dict | None, filing: dict | None) -> str:
    signals = "\n".join(f"- [{s['reading']}] {s['label']}: {s['text']} ({s['source']})" for s in first_sight.get("signals", []))
    comp = (filing or {}).get("competition") or "not found"
    conc = "; ".join((filing or {}).get("customer_concentration") or []) or "none found"
    n_peers = ((peers or {}).get("summary") or {}).get("peers")
    return (f"{ADAM}\n\nCompany: {symbol} ({name}), industry: {industry}.\nSignals from the numbers:\n{signals}\n"
            f"Peers in the comparison: {n_peers if n_peers is not None else 'unknown'}.\nAnnual report, competition passage: {comp[:1500]}\n"
            f"Customer concentration sentences: {conc[:800]}\n\n"
            "Task: in at most 150 words give (1) wide / narrow / no moat at first sight and why, (2) the single biggest doubt, "
            "(3) the two things the investor should check by hand before deciding. Plain language, no hype.")


def plain(text: str) -> str:
    """Strip markdown the page does not render (**bold**, *italic*, `code`, # headings, '* ' bullets)."""
    text = re.sub(r"```[a-z]*\n?|```", "", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?![\w*])", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    text = re.sub(r"^(\s*)[*•]\s+", r"\1- ", text, flags=re.M)
    return text.strip()


def opinion(prompt: str) -> str:
    return plain(_opinion(prompt))


def _opinion(prompt: str) -> str:
    if status()["backend"] == "builtin":
        return ai_runtime.chat(prompt)
    s = get_settings()
    body = json.dumps({"model": s.ai_model, "prompt": prompt, "stream": False, "options": {"temperature": 0.3, "num_ctx": ai_runtime.CTX}}).encode()
    req = urllib.request.Request(f"{s.ai_url}/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=s.ai_timeout) as r:
        text = json.loads(r.read()).get("response", "")
    return text.split("</think>")[-1].strip()           # reasoning models may print their thinking first


def overview_chat(backend: str, messages: list[dict], max_tokens: int, *, timeout: float | None = None) -> str:
    """Tool-free chat on the already selected backend; never silently switches models."""
    if backend == "builtin":
        return ai_runtime.chat_with_tools(messages, [], lambda *_: "", max_rounds=0, max_tokens=max_tokens, timeout=600 if timeout is None else timeout)
    if backend != "ollama":
        raise RuntimeError("No AI model is available. See AI Settings.")
    settings = get_settings()
    body = {"model": settings.ai_model, "messages": messages, "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.3, "num_ctx": ai_runtime.CTX}}
    req = urllib.request.Request(f"{settings.ai_url}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=settings.ai_timeout if timeout is None else min(timeout, settings.ai_timeout)) as response:
        text = json.loads(response.read())["message"]["content"]
    return text.split("</think>")[-1].strip()



def assistant_chat(backend: str, messages: list[dict], tools: list[dict], run_tool) -> str:
    """Run at most three read-only tool rounds, followed by a tool-free answer."""
    if not tools:
        return overview_chat(backend, messages, 650, timeout=90)
    if backend == "builtin":
        return ai_runtime.chat_with_tools(messages, tools, run_tool, max_rounds=3, max_tokens=650, timeout=90)
    if backend != "ollama":
        raise RuntimeError("No local AI model is available.")
    settings = get_settings()
    messages = list(messages)
    for _ in range(3):
        body = {"model": settings.ai_model, "messages": messages, "tools": tools, "stream": False,
                "options": {"num_predict": 650, "temperature": 0.3, "num_ctx": ai_runtime.CTX}}
        req = urllib.request.Request(f"{settings.ai_url}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=min(90, settings.ai_timeout)) as response:
            msg = json.loads(response.read())["message"]
        calls = (msg.get("tool_calls") or [])[:5]
        if not calls:
            return (msg.get("content") or "").split("</think>")[-1].strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            messages.append({"role": "tool", "tool_name": name,
                             "content": run_tool(name, fn.get("arguments", {}))})
    return overview_chat(backend, messages, 650, timeout=90)
