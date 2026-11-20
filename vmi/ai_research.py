"""Moat opinion by a local AI that researches for itself, cites its sources, and is checked by a second pass.

  1. research  - the model runs its own investigation with web_search / read_page / wikipedia / app_analysis, as many calls as
                 it needs (MAX_ROUNDS only stops a runaway loop), and writes notes where every line names its source.
  2. verdict   - Adam's rules + the evidence + the notes -> grade, reasons, every claim tagged with a source.
  3. review    - the same model re-reads its own verdict once, fixes unsupported claims and present-tense reasoning, and downgrades
                 when unsure. The lower of verdict and review is kept.
  4. checker   - OPTIONAL, run only when the user asks: a separate pass sees only the claims and the sources (the notes and the app's
                 analysis), marks each claim SUPPORTED / UNSUPPORTED / CONTRADICTED, judges whether the grade follows, and may only
                 LOWER the grade.
Owner rule: when two opinions differ, the lower one wins.
"""
from __future__ import annotations

import datetime
import re

from vmi import ai_runtime, ai_tools

MAX_ROUNDS = 40
ORDER = {"NONE": 0, "NARROW": 1, "WIDE": 2}


def _today() -> str:
    return datetime.date.today().isoformat()


RESEARCH_SYSTEM = """You are a careful equity researcher. Today is {today}. Your own memory of companies is OUT OF DATE: do not state any
fact about the company, its rivals or recent events unless a tool result from this session shows it.
Investigate {name} ({ticker}) for a moat assessment. Use the tools as much as you need; search, then OPEN and READ the most relevant
pages with read_page (snippets are not evidence), follow links, and search again only for a NEW question. Cover:
1. The app's own figures: call app_analysis first.
2. Closest competitors and whether {name} is gaining or losing market share (recent years, with numbers where possible).
3. The CAUSE of every weak number in the figures (down year, falling margin, low or negative returns): one-off or structural?
4. Threats over the next 20 years: bigger rivals that bundle the same thing, cheaper substitutes, technology shifts, regulation.
5. Evidence of pricing power (price rises that stuck) and of switching costs or network effects.
6. The latest results and guidance.
When you have enough, reply with NOTES only: one finding per line, each ending with its source in brackets: [url] for web pages or
[analysis page] for app_analysis. Then a line OPEN QUESTIONS: what you could not establish. No grade yet."""

VERDICT_RULES = """Grade {name} ({ticker}) on Adam Khoo's moat scale using ONLY the research notes below (your memory is out of date).
Adam: WIDE = ~20 years of protection, no or insignificant competitors, raises prices every year without losing share, very high margins.
NARROW = ~10 years, several significant competitors, limited pricing power. NONE = commodity-like, price decides, or easily disrupted
and replaced by stronger competitors (no-moat industries: commodities, airlines, autos, oil and gas, shipping, construction,
property developers). He wants at least 3 of 5 sources: brand or pricing power, switching costs, network effect, barriers to entry,
economies of scale.
A MOAT IS ONLY ABOUT THE FUTURE: the question is whether {name} will still be the top dog, protected from competitors, in 10-20
years. "It is wide today" or "justifiable today" means nothing; a business whose protection may erode is NOT wide, whatever its
current numbers. Strong current figures never prove a moat on their own.
Rules: grading higher than deserved is the worst error. If you are unsure, or torn between two grades, ALWAYS give the LOWER one. A weak number with a one-off cause does not count
against the moat; a structural cause does. Every claim must carry its source exactly as in the notes ([url] or [analysis page]).
Output plain text, no markdown:
CLAIMS:
- <claim> [source]
(as many as needed)
REASONING: <at most 100 words>
MOAT VERDICT: WIDE — 8/10   (or NARROW or NONE, your own score)"""

CHECK_RULES = """You are an independent checker. Below are CLAIMS from an analyst with their sources, the SOURCE NOTES they came from,
and the app's own figures. For each claim answer SUPPORTED, UNSUPPORTED (no source says it) or CONTRADICTED (a source says otherwise),
judging only by the sources, not by your memory. Then judge whether the analyst's grade follows from the SUPPORTED claims alone under
these rules: WIDE needs a clear leader with ~20-year protection, >=3 strong sources and no structural threat; NARROW for a limited or
contested edge; NONE for commodity-like or easily disrupted businesses. If torn, the lower grade.
Output plain text:
CHECKS:
- <short claim> -> SUPPORTED | UNSUPPORTED | CONTRADICTED
LOGIC: <one or two sentences>
CHECKER VERDICT: WIDE | NARROW | NONE"""


def _grade(text: str, label: str) -> str | None:
    m = re.search(label + r":\s*\**\s*(WIDE|NARROW|NONE|NO MOAT)", text or "", re.I)
    return None if not m else ("NONE" if m.group(1).upper().startswith("NO") else m.group(1).upper())


def research(ticker: str, name: str, base_url: str | None = None, on_tool=None, max_rounds: int = MAX_ROUNDS) -> str:
    msgs = [{"role": "system", "content": RESEARCH_SYSTEM.format(today=_today(), name=name, ticker=ticker)},
            {"role": "user", "content": f"Research {name} ({ticker}) now. Start with app_analysis."}]
    return ai_runtime.chat_with_tools(msgs, ai_tools.TOOLS, ai_tools.make_runner(), max_rounds=max_rounds, max_tokens=1500,
                                      require_first_tool=True, base_url=base_url, on_tool=on_tool, timeout=600)


def _chat(base_url: str | None, messages: list[dict], max_tokens: int = 1200) -> str:
    return ai_runtime.chat_with_tools(messages, [], lambda n, a: "", max_rounds=0, max_tokens=max_tokens, base_url=base_url, timeout=600)


def verdict(ticker: str, name: str, notes: str, evidence: str = "", base_url: str | None = None) -> str:
    msgs = [{"role": "system", "content": VERDICT_RULES.format(name=name, ticker=ticker)},
            {"role": "user", "content": (f"EVIDENCE CARD:\n{evidence}\n\n" if evidence else "") + f"RESEARCH NOTES:\n{notes}"}]
    return _chat(base_url, msgs)


REVIEW_RULES = """Re-read the moat verdict you wrote below, as a strict reviewer of your own work, before it goes to anyone.
Fix it if any of these is true, and downgrade when in doubt:
- a claim has no source, or the source in the notes does not actually say it -> drop the claim;
- the reasoning argues from the present ("today", "currently", "for now") instead of the next 10-20 years -> judge the future;
- the reasoning itself names a serious threat, erosion or doubt, yet the grade is WIDE -> it is not WIDE;
- you were unsure or torn -> the LOWER grade.
Output the corrected verdict in the same format (CLAIMS, REASONING, MOAT VERDICT). If nothing needs fixing, repeat it unchanged."""


def review(verdict_text: str, notes: str, base_url: str | None = None) -> str:
    msgs = [{"role": "system", "content": REVIEW_RULES},
            {"role": "user", "content": f"YOUR VERDICT:\n{verdict_text}\n\nRESEARCH NOTES IT WAS BASED ON:\n{notes}"}]
    return _chat(base_url, msgs)


def check(verdict_text: str, notes: str, figures: str, base_url: str | None = None) -> str:
    claims = verdict_text.split("REASONING:")[0]
    grade = _grade(verdict_text, "MOAT VERDICT") or "?"
    msgs = [{"role": "system", "content": CHECK_RULES},
            {"role": "user", "content": f"ANALYST GRADE: {grade}\n\n{claims}\n\nSOURCE NOTES:\n{notes}\n\nAPP FIGURES [analysis page]:\n{figures}"}]
    return _chat(base_url, msgs, max_tokens=1000)


def _lowest(*grades):
    gs = [g for g in grades if g]
    return min(gs, key=ORDER.get) if gs else None


def opinion(ticker: str, name: str, evidence: str = "", base_url: str | None = None, on_tool=None, run_checker: bool = False) -> dict:
    """Research -> verdict -> self-review (always); the checker only when run_checker (the user asks for it)."""
    notes = research(ticker, name, base_url=base_url, on_tool=on_tool)
    v = verdict(ticker, name, notes, evidence, base_url=base_url)
    rv = review(v, notes, base_url=base_url)
    g1, g2 = _grade(v, "MOAT VERDICT"), _grade(rv, "MOAT VERDICT")
    out = {"notes": notes, "verdict": v, "review": rv, "verdict_grade": g1, "review_grade": g2, "final": _lowest(g1, g2)}
    if run_checker:
        out.update(run_check(out, ticker, evidence, base_url=base_url))
    return out


def run_check(result: dict, ticker: str, evidence: str = "", base_url: str | None = None) -> dict:
    """Optional independent checker on a finished opinion; it can only lower the grade."""
    figures = evidence or ai_tools.app_analysis(ticker)
    c = check(result.get("review") or result["verdict"], result["notes"], figures, base_url=base_url)
    g = _grade(c, "CHECKER VERDICT")
    return {"check": c, "checker_grade": g, "final_checked": _lowest(result.get("final"), g)}
