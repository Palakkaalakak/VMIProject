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

def _course() -> str:
    """Adam's own words on the moat: vmi/data/adam_moat.md, verbatim extracts of the owner's course master document. It is the owner's
    copy of paid course material, so it is kept out of git; build it with tools/make_adam_moat.py. Without it the AI works from the
    summary below."""
    from pathlib import Path
    try:
        return (Path(__file__).parent / "data" / "adam_moat.md").read_text(encoding="utf-8")
    except OSError:
        return ""


NUANCES = """OTHER LESSONS OF THE COURSE AND HOW TO READ EVIDENCE (summarised from the course unless marked otherwise):
- Negative shareholders' equity caused by years of share buybacks (large treasury stock) is not a weakness: ROE is effectively
  infinite, not negative. Check the cause before reading ROE or debt ratios.
- A current ratio below 1 can be deliberate (stretching supplier payments) or come from subscription deferred revenue; not a red flag
  on its own. Never read one ratio in isolation.
- Lumpy net income from one-off items: judge operating income instead. Falling free cash flow from a temporary capex surge (e.g. data
  centres) while operating cash flow rises is fine and strengthens the future moat.
- Slow growth is not a weak moat. "Boring" predictable businesses (5-10% growth, products that never go obsolete such as food, drinks,
  everyday consumer brands) are typically large WIDE-moat companies: few new rivals want to enter, sales and profits are consistent.
  Moat width is about protection from competition, not growth speed.
- Asset-light brand owners (franchise models, outsourced manufacturing, the company owns the brand, recipes or designs) are a
  strength: low input costs, inflation passed on through price rises.
- A great brand having a bad patch (a poor CEO, a strategy mistake, a scandal, a lawsuit, a weak region, profits down for a year or
  two) is a temporary problem with the moat intact, as long as customers still default to the brand; Adam buys these as turnarounds.
- A global brand that people everywhere default to out of habit (top-of-mind recall, part of daily life) is a brand monopoly even when
  rivals exist and growth is slow; that is the classic wide moat.
- Top dog in a duopoly: when two or three leaders share an industry that newcomers cannot enter (payment networks, credit ratings,
  stock exchanges, index providers: "toll-booth" businesses, monopolistic, little or no competition), EACH leader is WIDE; Adam grades
  both card networks wide. The top-dog test fails only when a rival is STRONGER, or there is no clear leader among many.
- The app's figures include rough automatic proxies (e.g. a "pricing power" check that only compares margins in the 2021-23 cost
  shock, an "at first sight" label, "unreviewed" moat status). They are hints to verify, not verdicts: a small margin dip in an
  inflation shock does not prove a brand lacks pricing power. Look for real evidence (price rises that stuck, customers staying), and
  never score a source low on one proxy alone. "unreviewed" only means nobody has graded it yet.
- A strong brand that must keep spending heavily just to keep its customers (e.g. producing its own content, which is hit-and-miss)
  is less predictable: Adam calls such a business "good, not great"; that points to NARROW even when the brand is famous.
- Network effects can be regional: the platform you "have to be on" to buy or sell in a region (a country or continent) has a moat
  there, even if it is small elsewhere; judge it inside its home market.
- "We face intense / aggressive competition" appears in EVERY annual report; it is boilerplate, not evidence of a weak moat. Evidence
  of erosion is specific and recent: the leader losing share two years running, the leader forced to cut prices to keep customers,
  customers visibly switching. A named bigger rival existing (e.g. Microsoft in security) is not erosion either: Adam rates Amazon,
  Google and Microsoft wide although they compete with each other.
- Discounting to clear excess stock, a reorganisation, a new CEO, a weak quarter or a strategy mistake is a temporary problem; only
  discounting that is needed to keep customers year after year is lost pricing power.
- Never cite the app's automatic "pricing power" check (it only compares margins in the 2021-23 cost shock) as evidence; margins can
  dip in an inflation shock for a brand that still raises prices. Use sourced price rises and customer behaviour instead.
- WEIGH EVERY RIVAL, never just name it. Ask three things and write the answers in your reasoning: (1) OVERLAP: what share of THIS
  company's revenue does the rival actually compete for? A rival that overlaps one small segment is a small threat; one that overlaps
  nearly everything is a big one. (2) FOCUS: is the product a core business for the rival or a bundled side line? A specialist for whom
  the product is the whole company (it invests, innovates and sells in it full time) usually keeps an edge against a giant that treats
  it as a side line, although the giant can win on price by bundling. (3) EVIDENCE: do the notes show customers, deals or share
  actually going to the rival, or price cuts forced by it? Only sourced evidence of that counts as erosion. "Competes in some
  segments", "is a big company" and "could bundle" are not evidence.
  Competition itself is NOT a problem. A company that keeps beating its rivals (growing faster than them, winning their customers,
  taking share, keeping or raising prices and margins) has a moat BECAUSE of the competition it wins: Adam rates Google, Amazon
  and Microsoft wide although they fight each other. Grade the track record against the rivals: who is winning, who is gaining share?
  Better still is little or no competition at all: Adam wants "monopolistic businesses with ideally little or no competition";
  "wide-moat companies have no competitors or insignificant competition"; Pillar 5 is "weak competition" (few competitors, with very
  small market share and a weaker competitive position). Barriers to entry (regulation, patents, IP, security clearances) are what
  keep new rivals out, and in "boring" industries few new competitors want to enter at all.
- MISSING EVIDENCE IS NOT NEGATIVE EVIDENCE: if the notes do not cover rivals or a threat, do not lower the grade for it; judge from what is
  known with Adam's framework. Lower only for sourced negatives from credible sources (company filings, major news or finance outlets,
  official data); a single unknown blog or report site is weak evidence.
- DISCOUNTS: Adam's erosion test is discounting needed to KEEP customers year after year. Discounts offered to WIN customers away from
  rivals, or to sell a bigger bundle of the company's own products, are expansion, not lost pricing power; discounts to clear stock or
  a one-off are temporary. Classify every discount before using it as evidence.
- DECISION RULE (Adam: "at least 3 of the 5 sources"): score the five sources honestly 0-10 the way Adam does (Meta 9,9,8,10,9; Zoom
  6,5,6,6,5). A clear leader with sticky customers (enterprise integration, ecosystem, recurring revenue, a regulated or licensed
  position, a brand people default to) normally scores 7+ on at least three sources, and then the grade is WIDE unless the notes show
  specific, recent structural erosion. Two strong sources, or a leader without sticky customers, is NARROW. One or none, or a business
  that a much bigger rival can copy and bundle, is NONE.
- Industries he bans (commodities, airlines, autos, property, construction, shipping, oil and gas) stay NONE or at most NARROW even
  with big, profitable companies; key-man dependence and forced price cuts are red flags."""

FRAMEWORK_QUICK = """ADAM KHOO'S MOAT FRAMEWORK, CONDENSED (from his course):
- A moat protects the business from competition so rivals cannot easily take its customers or market share; the company keeps pricing
  power (raises prices without losing customers or share) and grows sales, profit and cash flow for the next 10-20 years. It is the
  most important step.
- WIDE: a very strong advantage we are pretty certain cannot easily be disrupted for 20 years; monopolistic, no or insignificant
  competition; raises prices without hurting demand; high margins. NARROW: some advantage probably lasting ~10 years; several
  significant competitors; limited pricing power (Tesla must keep cutting prices). NONE: may be growing now but can easily be disrupted
  or replaced by a bigger rival within 1-3 years; many rivals selling near-identical products; price decides (Zoom, PayPal and Beyond
  Meat were avoided). Commodities, airlines, autos, property, construction, shipping, oil and gas are mostly NONE.
- Five sources, at least 3 wanted: (1) brand monopoly / pricing power: the first name people think of (Google, Microsoft Office,
  McDonald's, Meta); (2) high switching costs (Apple ecosystem, enterprise software such as ServiceNow, security vendors such as Palo
  Alto, CrowdStrike, Fortinet, AWS); (3) network effect (Meta, Amazon, Google, Alibaba, Tencent, Mercado Libre); (4) barriers to entry
  (patents, regulation, security clearances: Palantir, Lockheed); (5) economies of scale (Amazon, Walmart, Costco). Score each 0-10 as he
  does (Meta 9,9,8,10,9; Zoom 6,5,6,6,5): 7-9 overall gives confidence, 6 is "not strong enough".
- Top dog: he invests in the strongest business of its industry; the closest rivals must be weaker; no clear leader means forget it.
  Wide examples he names: Meta, Amazon, S&P Global, Alphabet, Netflix, Nvidia, Mastercard, Visa, Apple, Microsoft. Narrow: Cisco,
  FedEx, Expedia, Dow, Alcoa, Chevron, Schlumberger, Tesla, Exxon, Shell.
- Tests: can it raise prices every year without losing share? could a bigger rival replicate it within 1-3 years? is it losing share
  or discounting? one-trick pony, customer concentration, key-man risk?
- Erosion: margins falling 2-3 years because it must discount; share lost two years straight; customers visibly switching. A bad year,
  bad CEO, scandal, lawsuit or capex surge is temporary; disruption, a permanent change in what customers want, or a rival taking share
  year after year is structural. A clear 10-year share-price uptrend is a clue to a wide moat."""

OWNER_QUICK = """THE OWNER'S GUIDANCE (the owner's own reasoning, not Adam's words; follow it):
- "Intense competition" in an annual report is boilerplate; a bigger rival merely existing is not erosion. Weigh each rival by OVERLAP
  (share of this company's revenue it contests), FOCUS (core business or side line for the rival) and EVIDENCE (customers or share
  actually lost). A company that keeps beating its rivals has a moat because of the competition it wins.
- Classify every discount: to KEEP customers = lost pricing power; to WIN customers from rivals or sell bigger bundles = expansion;
  to clear stock or a one-off = temporary.
- Never use the app's automatic "pricing power" check as evidence. Negative equity from buybacks, current ratio below 1, lumpy income,
  capex-driven free-cash-flow dips and slow growth of a predictable brand are not weaknesses. A great brand's bad patch is temporary.
  Toll-booth duopolies (ratings, card networks, exchanges) are WIDE for each leader. Network effects can be regional.
- MISSING EVIDENCE IS NOT NEGATIVE EVIDENCE: if the notes do not cover rivals or a threat, do not lower the grade for it; judge from what is
  known with Adam's framework. Lower only for sourced negatives from credible sources; one weak source alone is not enough.
- DECISION RULE: a clear leader with sticky customers normally scores 7+ on at least three sources: WIDE unless the notes show specific,
  recent structural erosion; two strong sources: NARROW; one or none, or easily copied or bundled by a much bigger rival: NONE.
  Grading too high is the worst error; lower only for specific sourced doubt."""

CHECKLIST_QUICK = """NUANCE CHECKLIST: answer EVERY item with a reason of at most 8 words. YES = the requirement is met; NO = it is not met (say why);
NA = the notes do not cover it. NA and missing information NEVER lower the grade: only a sourced negative from a credible source does.
1 FUTURE: judged on the next 10-20 years, not today's numbers?
2 SOURCES: five sources scored 0-10 on sourced evidence; grade fits 3-of-5?
3 TOP DOG: closest rivals named and compared with a source?
4 RIVALS WEIGHED: each threat rival's overlap, focus and evidence stated?
5 COMPETITION WON: is it beating its rivals?
6 EROSION: every signal specific, recent, from a credible source (filings, major news or finance outlets, official data; one unknown blog or report site is weak) and not boilerplate or "a rival exists"?
7 DISCOUNTS: each classed keep / win / clear?
8 SETBACKS: each weak number sourced and classed temporary or structural?
9 FIGURES: buyback equity, current ratio, lumpy income, capex dips, slow growth, app proxy: none misused?
10 RED FLAGS: one-trick pony, concentration, key-man, hit-and-miss spend checked?
11 BANNED INDUSTRY: commodity, airline, auto, property, construction, shipping, oil and gas?
12 NOT OVER-GRADED: supported by sourced evidence?
13 NOT UNDER-GRADED: lowered only for specific sourced doubt?
14 SOURCES: every claim's source really says it?"""

CHECKLIST = """NUANCE CHECKLIST: answer EVERY item with YES, NO or NA and one short sourced reason. YES = the requirement is met; NO = it is not met
(say why); NA = the notes do not cover it. NA and missing information NEVER lower the grade: only a sourced negative from a credible source
does. A wrong answer here is the usual way a grade goes wrong.
1. FUTURE: is the grade about the next 10-20 years of protection, not how good the numbers are today?
2. SOURCES: are all five sources scored 0-10 on sourced evidence (not on a guess), and is the grade consistent with the 3-of-5 decision rule?
3. TOP DOG: are the closest competitors named and compared (clearly weaker / equal / stronger), with a source? Equal strength in a toll-booth duopoly is still WIDE for each.
4. RIVALS WEIGHED: for each rival named as a threat, did you state OVERLAP (share of this company's revenue it contests), FOCUS (core business or bundled side line for the rival) and EVIDENCE (customers, deals or share actually lost to it)?
5. COMPETITION WON: is the company beating its rivals (faster growth, share gains, price and margins held)? Competition it wins is not a weakness.
6. EROSION EVIDENCE: is every erosion signal specific, recent and from a credible source (company filings, major news or finance outlets, official data; a single unknown blog or report site is weak evidence) and (the leader losing share two years running, forced discounting to KEEP customers, customers switching)? "Intense competition" boilerplate, "a bigger rival exists" and "could bundle" do not count.
7. DISCOUNTS CLASSIFIED: is each discount or price cut classed as (a) to keep existing customers = lost pricing power, (b) to win customers from rivals or sell bigger bundles = expansion, or (c) to clear stock or a one-off = temporary?
8. TEMPORARY OR STRUCTURAL: is every weak number or setback (down year, margin dip, bad CEO, strategy mistake, scandal, lawsuit, capex surge) traced to a sourced cause and classed temporary or structural? A global brand people default to is not weakened by a bad patch.
9. FIGURES READ RIGHT: negative equity from buybacks, current ratio below 1, lumpy net income, falling free cash flow from a capex surge, slow growth of a boring predictable brand: none was wrongly held against the moat, and the app's automatic "pricing power" check was NOT used as evidence.
10. BUSINESS-MODEL RED FLAGS: one-trick pony, customer concentration, key-man or unique-talent dependence, a brand that must keep spending heavily on hit-and-miss output: each checked.
11. BANNED INDUSTRY: is it in commodities, airlines, autos, property, construction, shipping, oil and gas? Then never above NARROW, usually NONE.
12. NOT OVER-GRADED: grading too HIGH is the worst error; is the grade supported by sourced evidence, not hope?
13. NOT UNDER-GRADED: was the grade lowered only for specific sourced doubt, not because of general unease, a rival merely existing, or "when unsure" used as a default?
14. SOURCES CHECKED: does every claim carry a source that really says it?"""

VERDICT_BODY = """Grade {name} ({ticker}) with this framework, using ONLY the research notes below for facts about the company (your memory of it is
out of date; general knowledge of how moats work is fine).
A moat is about the FUTURE: will {name} still be the protected top dog in 10-20 years? Current numbers alone never prove a moat, and
"wide today" means nothing. Judge with the tests above.
Rules: grading higher than deserved is the worst error, so when the sourced evidence leaves real doubt (the notes show share loss, forced
discounting, a much stronger rival replicating it, a commodity product), give the LOWER grade. Do NOT downgrade a brand monopoly or
dominant platform merely because rivals exist or some theoretical risk is imaginable; downgrade for threats the notes actually show.
A weak number with a one-off cause does not count against the moat; a structural cause does. Missing information is not a negative: if the
notes do not cover something, judge from what is known.
Every claim must carry its source exactly as in the notes ([url] or [analysis page]).
Output plain text, no markdown:
CLAIMS:
- <claim> [source]
(the 6-8 most decisive claims only)
SOURCES (0-10 each, Adam's scale): brand/pricing power=?, switching costs=?, network effect=?, barriers to entry=?, economies of scale=?
CHECKLIST: (all 14 items, one line each of at most 12 words: "n. YES|NO|NA - reason [source]")
REASONING: <at most 100 words: the strong sources, top dog or not, the tests, the biggest doubt>
MOAT VERDICT: WIDE — 8/10   (or NARROW or NONE, your own overall score on Adam's scale: about 8-10 wide, 6-7 narrow, 5 or less none)"""

ADAM = (_course() + "\n\n" + NUANCES) if _course() else (FRAMEWORK_QUICK + "\n\n" + NUANCES)      # the deepest framework text
VERDICT_RULES = ADAM + "\n\n" + VERDICT_BODY

CHECK_RULES = """You are an independent checker. Below are CLAIMS from an analyst with their sources, the SOURCE NOTES they came from,
and the app's own figures. For each claim answer SUPPORTED, UNSUPPORTED (no source says it) or CONTRADICTED (a source says otherwise),
judging only by the sources, not by your memory. Then judge whether the analyst's grade follows from the SUPPORTED claims alone under
Adam Khoo's framework: WIDE = brand monopoly / dominant leader, ~20-year protection, >=3 strong sources, no threat shown in the sources;
NARROW = limited or contested edge, ~10 years; NONE = easily copied or replaced by much bigger rivals, or commodity-like. If torn, the lower grade.
FIRST, independently of the analyst, answer the NUANCE CHECKLIST (below) yourself from the sources only. THEN compare with the analyst's
CHECKLIST answers and flag every item where they differ and who is right. Your grade follows from your own checklist answers.
Output plain text:
MY CHECKLIST: (14 lines of at most 12 words: "n. YES|NO|NA - reason [source]")
DIFFERENCES: <items where you disagree with the analyst, with reasons, or "none">
CHECKS:
- <short claim> -> SUPPORTED | UNSUPPORTED | CONTRADICTED
LOGIC: <one or two sentences>
CHECKER VERDICT: WIDE | NARROW | NONE"""


def _grade(text: str, label: str) -> str | None:
    m = re.search(label + r":\s*\**\s*(WIDE|NARROW|NONE|NO MOAT)", text or "", re.I)
    return None if not m else ("NONE" if m.group(1).upper().startswith("NO") else m.group(1).upper())


def research_agent(ticker: str, name: str, base_url: str | None = None, on_tool=None, max_rounds: int = MAX_ROUNDS) -> str:
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


def research(ticker: str, name: str, base_url: str | None = None, on_tool=None, level: str | None = None) -> str:
    """Code-driven research (vmi.ai_pipeline): the code searches and reads, the model plans and extracts. The older free-roaming
    agent is kept as research_agent()."""
    from vmi import ai_pipeline
    lv = _level(level)
    return ai_pipeline.research(ticker, name, lambda msgs, mt: _chat(base_url, msgs, mt), on_tool=on_tool,
                                questions=lv["questions"], pages=lv["pages"], followups=lv["followups"], plan=lv["plan"])


def verdict(ticker: str, name: str, notes: str, evidence: str = "", base_url: str | None = None, level: str | None = None) -> str:
    lv = _level(level)
    system = lv["adam"] + "\n\n" + _fit(VERDICT_BODY, lv).format(name=name, ticker=ticker) + "\n\n" + lv["checklist"]
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": (f"EVIDENCE CARD:\n{evidence}\n\n" if evidence else "") + f"RESEARCH NOTES:\n{notes}"}]
    return _chat(base_url, msgs)


REVIEW_BODY = """Re-read the moat verdict you wrote below, as a strict reviewer of your own work, before it goes to anyone. Fix it if:
- a claim has no source, or the source in the notes does not actually say it -> drop the claim and re-judge;
- the reasoning argues from the present ("today", "currently") instead of the next 10-20 years -> judge the future;
- the grade is WIDE although the notes show a real threat (share loss, forced discounting, a much stronger rival replicating it, a
  commodity product) -> lower it; the grade is above NONE although the business can easily be copied or replaced by much bigger
  competitors -> NONE;
- you were genuinely torn between two grades because of conflicting SOURCED evidence -> the LOWER one; but missing information in the notes is never a reason to lower, and a lowered grade needs a sourced negative.
INDEPENDENT RE-VERIFICATION: before you answer, go through the NUANCE CHECKLIST below yourself, item by item, against the research
notes (do not just trust the analyst's answers). Where an answer is wrong, unsupported or missing, fix it; a fixed answer may change the grade
in either direction, but a grade change needs a sourced reason.
Output only (do not repeat the claims):
CHECKLIST REVIEW: <"all 14 confirmed" or the numbers you changed with the corrected answer, in at most 40 words>
FIXES: <what you changed in the verdict and why in at most 40 words, or "none">
SOURCES (0-10 each, Adam's scale): brand/pricing power=?, switching costs=?, network effect=?, barriers to entry=?, economies of scale=?
REASONING: <at most 80 words>
MOAT VERDICT: WIDE — 8/10   (or NARROW or NONE)"""
REVIEW_RULES = ADAM + "\n\n" + REVIEW_BODY

# Three depths. quick = condensed framework + short checklist, fewest searches (fast); standard = fuller course nuances;
# deep = Adam's own words (needs the local course extract) + everything. Each is larger, deeper and slower than the one before.
LEVELS = {
    "quick": {"adam": FRAMEWORK_QUICK + "\n\n" + OWNER_QUICK, "checklist": CHECKLIST_QUICK, "questions": 4, "pages": 2, "followups": 0, "plan": False,
              "claims": "the 4 most decisive claims only", "reasoning": "at most 60 words", "item": "at most 8 words"},
    "standard": {"adam": FRAMEWORK_QUICK + "\n\n" + NUANCES, "checklist": CHECKLIST, "questions": 6, "pages": 3, "followups": 2, "plan": True,
                 "claims": "the 6 most decisive claims only", "reasoning": "at most 100 words", "item": "at most 12 words"},
    "deep": {"adam": ADAM, "checklist": CHECKLIST, "questions": 6, "pages": 3, "followups": 3, "plan": True,
             "claims": "the 6-8 most decisive claims", "reasoning": "at most 100 words", "item": "at most 12 words"},
}
DEFAULT_LEVEL = "quick"


def _level(level: str | None) -> dict:
    return LEVELS.get(level or DEFAULT_LEVEL) or LEVELS[DEFAULT_LEVEL]


def _fit(body: str, lv: dict) -> str:
    """Scale the output-length instructions of a prompt body to the level."""
    return (body.replace("the 6-8 most decisive claims only", lv["claims"]).replace("at most 100 words: the strong", lv["reasoning"] + ": the strong")
            .replace("at most 12 words", lv["item"]).replace("<at most 80 words>", "<" + lv["reasoning"] + ">"))


def review(verdict_text: str, notes: str, base_url: str | None = None, level: str | None = None) -> str:
    lv = _level(level)
    msgs = [{"role": "system", "content": lv["adam"] + "\n\n" + _fit(REVIEW_BODY, lv) + "\n\n" + lv["checklist"]},
            {"role": "user", "content": f"YOUR VERDICT:\n{verdict_text}\n\nRESEARCH NOTES IT WAS BASED ON:\n{notes}"}]
    return _chat(base_url, msgs)


def check(verdict_text: str, notes: str, figures: str, base_url: str | None = None, level: str | None = None) -> str:
    lv = _level(level)
    claims = verdict_text.split("REASONING:")[0]
    grade = _grade(verdict_text, "MOAT VERDICT") or "?"
    msgs = [{"role": "system", "content": _fit(CHECK_RULES, lv) + "\n\n" + lv["checklist"]},
            {"role": "user", "content": f"ANALYST GRADE: {grade}\n\n{claims}\n\nSOURCE NOTES:\n{notes}\n\nAPP FIGURES [analysis page]:\n{figures}"}]
    return _chat(base_url, msgs, max_tokens=1000)


def final_text(result: dict) -> str:
    """The opinion as one text: the first verdict's sourced claims, then the self-review (fixes, sources, reasoning, grade)."""
    claims = (result.get("verdict") or "").split("REASONING:")[0].strip()      # claims, sources and the analyst's checklist
    review = (result.get("review") or "").strip()
    return (claims + "\n\n" + review).strip() if review else (result.get("verdict") or "")


def _lowest(*grades):
    gs = [g for g in grades if g]
    return min(gs, key=ORDER.get) if gs else None


def opinion(ticker: str, name: str, evidence: str = "", base_url: str | None = None, on_tool=None, run_checker: bool = False,
            level: str | None = None) -> dict:
    """Research -> verdict -> self-review (always); the checker only when run_checker (the user asks for it).
    `level` is "quick" (default), "standard" or "deep": larger prompts, more research, slower."""
    level = level if level in LEVELS else DEFAULT_LEVEL
    notes = research(ticker, name, base_url=base_url, on_tool=on_tool, level=level)
    v = verdict(ticker, name, notes, evidence, base_url=base_url, level=level)
    if not _grade(v, "MOAT VERDICT"):                  # forgot the grade line: ask once more
        v = verdict(ticker, name, notes + "\n\nREMEMBER: end with the line MOAT VERDICT: WIDE|NARROW|NONE — n/10", evidence, base_url=base_url, level=level)
    rv = review(v, notes, base_url=base_url, level=level)
    g1, g2 = _grade(v, "MOAT VERDICT"), _grade(rv, "MOAT VERDICT")
    # owner rule: the lower of the two wins; no readable grade at all counts as NONE (an opinion without a grade is not a moat)
    final = _lowest(g1, g2) or "NONE"
    out = {"notes": notes, "verdict": v, "review": rv, "verdict_grade": g1, "review_grade": g2, "final": final, "level": level}
    if run_checker:
        out.update(run_check(out, ticker, evidence, base_url=base_url))
    return out


def run_check(result: dict, ticker: str, evidence: str = "", base_url: str | None = None, level: str | None = None) -> dict:
    """Optional independent checker on a finished opinion. Run only when the user asks; its grade replaces the opinion's grade
    (it may raise or lower it), because it judged every claim against the sources."""
    figures = evidence or ai_tools.app_analysis(ticker)
    c = check(final_text(result), result["notes"], figures, base_url=base_url, level=level or result.get("level"))
    g = _grade(c, "CHECKER VERDICT")
    return {"check": c, "checker_grade": g, "final_checked": g or result.get("final")}
