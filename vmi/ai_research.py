"""Moat opinion by a local AI that researches for itself, cites its sources, and is checked by a second pass.

  1. research  - the model runs its own investigation with web_search / read_page / wikipedia / app_analysis, as many calls as
                 it needs (MAX_ROUNDS only stops a runaway loop), and writes notes where every line names its source.
  2. verdict   - Adam's rules + the evidence + the notes -> grade, reasons, every claim tagged with a source.
  3. review    - the same model re-reads its own verdict once, fixes unsupported claims and present-tense reasoning, and downgrades
                 when unsure. The lower of verdict and review is kept.
  4. checker   - OPTIONAL, run only when the user asks: a separate pass sees only the claims and the sources (the notes and the app's
                 analysis), marks each claim SUPPORTED / UNSUPPORTED / CONTRADICTED, judges whether the grade follows, and gives the
                 grade the sourced claims support: it may raise or lower the opinion's grade.
Owner rule: when two opinions differ, the lower one wins.
"""
from __future__ import annotations

import datetime
import re

from vmi import ai_runtime, ai_tools

MAX_ROUNDS = 50
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
BUDGET: you have {budget} tool calls in total. Every tool result tells you how many are left. Plan for it: cover all six points
before the budget runs out, and stop calling tools and write your NOTES when about 5 calls are left (or earlier if you have enough).
When you have enough, reply with NOTES only: one finding per line, each ending with its source in brackets: [url] for web pages or
[analysis page] for app_analysis. Then a line OPEN QUESTIONS: what you could not establish. No grade yet."""

ADAM = """ADAM KHOO'S MOAT FRAMEWORK (from his course; apply it as written):
- A moat protects the business from competition so competitors cannot easily take its customers or market share, letting it keep
  growing sales, profit and cash flow for the next 10 to 20 years. With a strong moat it keeps pricing power: it raises prices
  consistently without losing customers or share.
- WIDE: a very strong, sustainable advantage we are pretty certain cannot easily be disrupted for the next 20 years; a very
  monopolistic business with no competitors or only insignificant ones; can raise prices without hurting demand; very high profit
  margins and consistent growth. Typical: a BRAND MONOPOLY (the first name people think of for the product; part of everyday
  vocabulary), a dominant platform with a strong network effect, an ecosystem with very high switching costs, huge economies of scale.
  Having rivals does not stop a business being WIDE when the rivals are far smaller or cannot take its customers.
- NARROW: some advantage probably sustainable for ~10 years, beyond that not sure; several significant competitors; limited pricing
  power (raise prices too much and customers leave, e.g. a carmaker that must keep cutting prices against many rivals); average margins.
- NONE: it may be growing and profitable now, but it can easily be disrupted, replicated or replaced by a much bigger or stronger
  competitor within a few years; many competitors selling near-identical products; price decides. Typical pattern: a popular, fast-
  growing app or payments/communication service that larger platforms can copy and bundle. Also most commodity companies, airlines,
  auto makers, property developers, construction, shipping, oil and gas.
- Sources (he wants at least 3 of 5): (1) strong brand / brand monopoly or pricing power, (2) high switching costs, (3) network effect,
  (4) high barriers to entry (patents, regulation, security clearances), (5) economies of scale.
- Signs of erosion: margins falling for 2-3 years because it has to discount, rising costs squeezing margins, market share falling for
  two years straight, customers visibly switching to competitors.
- Tests: Can it raise prices every year without losing share? Could a much bigger competitor replicate it and take its customers
  within 1-3 years? Is it the top dog of its industry, with the closest competitors clearly weaker? Is it losing share or discounting?"""

VERDICT_RULES = ADAM + """

Grade {name} ({ticker}) with this framework, using ONLY the research notes below for facts about the company (your memory of it is
out of date; general knowledge of how moats work is fine).
A moat is about the FUTURE: will {name} still be the protected top dog in 10-20 years? Current numbers alone never prove a moat, and
"wide today" means nothing. Judge with the tests above.
Rules: grading higher than deserved is the worst error, so when the evidence leaves real doubt (the notes show share loss, forced
discounting, a much stronger rival replicating it, a commodity product), give the LOWER grade. Do NOT downgrade a brand monopoly or
dominant platform merely because rivals exist or some theoretical risk is imaginable; downgrade for threats the notes actually show.
A weak number with a one-off cause does not count against the moat; a structural cause does.
Every claim must carry its source exactly as in the notes ([url] or [analysis page]).
Output plain text, no markdown:
CLAIMS:
- <claim> [source]
(as many as needed)
REASONING: <at most 100 words: which of the 5 sources are strong, the tests, the biggest doubt>
MOAT VERDICT: WIDE — 8/10   (or NARROW or NONE, your own score)"""

CHECK_RULES = """You are an independent checker. Below are CLAIMS from an analyst with their sources, the SOURCE NOTES they came from,
and the app's own figures. For each claim answer SUPPORTED, UNSUPPORTED (no source says it) or CONTRADICTED (a source says otherwise),
judging only by the sources, not by your memory. Then judge whether the analyst's grade follows from the SUPPORTED claims alone under
Adam Khoo's framework: WIDE = brand monopoly / dominant leader, ~20-year protection, >=3 strong sources, no threat shown in the sources;
NARROW = limited or contested edge, ~10 years; NONE = easily copied or replaced by much bigger rivals, or commodity-like. If torn, the lower grade.
Output plain text:
CHECKS:
- <short claim> -> SUPPORTED | UNSUPPORTED | CONTRADICTED
LOGIC: <one or two sentences>
CHECKER VERDICT: WIDE | NARROW | NONE"""


def _grade(text: str, label: str) -> str | None:
    m = re.search(label + r":\s*\**\s*(WIDE|NARROW|NONE|NO MOAT)", text or "", re.I)
    return None if not m else ("NONE" if m.group(1).upper().startswith("NO") else m.group(1).upper())


def research(ticker: str, name: str, base_url: str | None = None, on_tool=None, max_rounds: int = MAX_ROUNDS) -> str:
    msgs = [{"role": "system", "content": RESEARCH_SYSTEM.format(today=_today(), name=name, ticker=ticker, budget=max_rounds)},
            {"role": "user", "content": f"Research {name} ({ticker}) now. Start with app_analysis."}]
    inner, used = ai_tools.make_runner(), [0]

    def counted(tool: str, args: dict) -> str:
        used[0] += 1
        left = max_rounds - used[0]
        note = (f"\n[tool call {used[0]} of {max_rounds}: {left} left]" if left > 5 else
                f"\n[tool call {used[0]} of {max_rounds}: only {left} left. Stop researching and write your NOTES now.]")
        return inner(tool, args) + note

    return ai_runtime.chat_with_tools(msgs, ai_tools.TOOLS, counted, max_rounds=max_rounds, max_tokens=1500,
                                      require_first_tool=True, base_url=base_url, on_tool=on_tool, timeout=600)


def _chat(base_url: str | None, messages: list[dict], max_tokens: int = 1200) -> str:
    return ai_runtime.chat_with_tools(messages, [], lambda n, a: "", max_rounds=0, max_tokens=max_tokens, base_url=base_url, timeout=600)


def verdict(ticker: str, name: str, notes: str, evidence: str = "", base_url: str | None = None) -> str:
    msgs = [{"role": "system", "content": VERDICT_RULES.format(name=name, ticker=ticker)},
            {"role": "user", "content": (f"EVIDENCE CARD:\n{evidence}\n\n" if evidence else "") + f"RESEARCH NOTES:\n{notes}"}]
    return _chat(base_url, msgs)


REVIEW_RULES = ADAM + """

Re-read the moat verdict you wrote below, as a strict reviewer of your own work, before it goes to anyone. Fix it if:
- a claim has no source, or the source in the notes does not actually say it -> drop the claim and re-judge;
- the reasoning argues from the present ("today", "currently") instead of the next 10-20 years -> judge the future;
- the grade is WIDE although the notes show a real threat (share loss, forced discounting, a much stronger rival replicating it, a
  commodity product) -> lower it; the grade is above NONE although the business can easily be copied or replaced by much bigger
  competitors -> NONE;
- you were genuinely unsure between two grades -> the LOWER one.
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
    if not _grade(v, "MOAT VERDICT"):                  # forgot the grade line: ask once more
        v = verdict(ticker, name, notes + "\n\nREMEMBER: end with the line MOAT VERDICT: WIDE|NARROW|NONE — n/10", evidence, base_url=base_url)
    rv = review(v, notes, base_url=base_url)
    g1, g2 = _grade(v, "MOAT VERDICT"), _grade(rv, "MOAT VERDICT")
    # owner rule: the lower of the two wins; no readable grade at all counts as NONE (an opinion without a grade is not a moat)
    final = _lowest(g1, g2) or "NONE"
    out = {"notes": notes, "verdict": v, "review": rv, "verdict_grade": g1, "review_grade": g2, "final": final}
    if run_checker:
        out.update(run_check(out, ticker, evidence, base_url=base_url))
    return out


def run_check(result: dict, ticker: str, evidence: str = "", base_url: str | None = None) -> dict:
    """Optional independent checker on a finished opinion. Run only when the user asks; its grade replaces the opinion's grade
    (it may raise or lower it), because it judged every claim against the sources."""
    figures = evidence or ai_tools.app_analysis(ticker)
    c = check(result.get("review") or result["verdict"], result["notes"], figures, base_url=base_url)
    g = _grade(c, "CHECKER VERDICT")
    return {"check": c, "checker_grade": g, "final_checked": g or result.get("final")}
