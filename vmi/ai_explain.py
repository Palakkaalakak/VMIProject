"""AI company explainer: a plain-language read of what a company is, how it makes money, and WHY each of its numbers is what it is.

Built on the same research helpers as the moat AI (vmi.ai_pipeline: the code searches and reads pages, the model extracts and writes) but with
a different job: teach the owner the company, not grade its moat. Output sections (fixed order):
  Overview, How it makes money, Industry and competitors, History, Management and capital use, What moves the business,
  Recent events and risks, one paragraph per metric group (returns, margins, growth, balance sheet, cash and efficiency, valuation),
  Glossary, Further reading.
Rules baked into every prompt: the APP FIGURES are facts (never recomputed or contradicted); every cause names its source URL or is
marked UNKNOWN / (general knowledge); no buy/sell advice. Results are cached 3 days. Never feeds a step or a verdict.
Nothing here runs without the owner pressing the button (the model is a local one, see vmi.ai_runtime).
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import re
from typing import Callable

from vmi import ai_pipeline as P

CACHE_TTL = 3 * 24 * 3600
WORKERS = 3

# (key, title, search words, question)
CONTEXT = [
    ("overview", "How it makes money", "{name} business overview segments revenue breakdown how it makes money",
     "What does {name} sell, to whom, and which segments earn how much of revenue and profit?"),
    ("industry", "Industry and competitors", "{name} industry competitors market share position",
     "How does {name}'s industry work, who are its main competitors and where does {name} rank?"),
    ("history", "History", "{name} company history acquisitions spin-off milestones",
     "How did {name} get here: founding, key acquisitions, spin-offs, crises and turning points?"),
    ("management", "Management and capital use", "{name} capital allocation buybacks dividends debt CEO strategy",
     "How does {name}'s management use cash (buybacks, dividends, acquisitions, debt) and what is its strategy?"),
    ("drivers", "What moves the business", "{name} what drives revenue growth cyclical interest rates costs regulation",
     "What drives {name}'s sales and profits: cycles, rates, regulation, input costs, customers?"),
    ("recent", "Recent events and risks", "{name} latest results risks outlook",
     "What are {name}'s latest results, recent news and its main risks?"),
]

# metric group -> (title, search words, the app's checks / metrics belonging to it)
GROUPS = {
    "returns": ("Returns: ROE and ROIC", "{name} return on equity ROIC drivers profitability segments", ("roe", "roic", "roe_not_declining")),
    "margins": ("Margins", "{name} gross margin operating margin net margin drivers pricing costs", ("gross_margin_stable", "net_margin_stable")),
    "growth": ("Growth and consistency", "{name} revenue growth earnings growth drivers outlook",
               ("revenue_consistent", "earnings_consistent", "cfo_consistent")),
    "balance": ("Debt and balance sheet", "{name} debt leverage balance sheet interest coverage liquidity",
                ("current_ratio", "debt_to_ebitda", "debt_servicing", "interest_coverage", "core_ratios")),
    "cash": ("Cash flow and efficiency", "{name} free cash flow capital expenditure working capital receivables",
             ("revenue_vs_receivables", "cash_conversion_cycle")),
    "valuation": ("Valuation", "{name} valuation price earnings growth analysts expectations", ()),
}

SECTION_PROMPT = """You are explaining {name} ({ticker}) to an investor who knows nothing about it yet. Write the section "{title}" in plain,
friendly language (at most {words} words, short paragraphs, no jargon without a quick definition, no markdown symbols).
APP FIGURES are facts from the investor's app: never recompute or contradict them.
Use ONLY the NOTES (fetched today, each ends with its source URL) for facts about the company. Cite a URL in brackets after each factual claim.
If the notes do not say something, write "not found in the sources" instead of guessing. General background that is not company-specific
(what a margin is, what is usual for the industry) is allowed if you label it "(general knowledge)". No buy or sell advice.
{extra}
APP FIGURES:
{figures}
NOTES:
{notes}"""

METRIC_EXTRA = """For EACH figure above say, in this order: (1) what it measures in one plain sentence, (2) why it is at THIS level for this
company: which business, segment or trait of the company causes it, (3) how it compares with the company's own 5-year average and what is
usual for this kind of company and why, (4) if it is below its usual level, the reasons found in the sources (temporary or structural?)."""

GLOSSARY_PROMPT = """From the text below, list at most 8 finance or industry terms a beginner may not know, each with a one-sentence plain definition.
Format: "term: definition" one per line. Text:
{text}"""


def _words(level: str) -> int:
    return 180 if level == "deep" else 120


def metric_facts(rep: dict, margins: dict | None = None) -> dict[str, str]:
    """{group key: text of the app's own figures for that group}: values, rules and verdicts from the analysis report, so the model explains
    numbers it was GIVEN. `margins` = moat_evidence.margin_history output (optional)."""
    checks = {c["name"]: c for s in rep.get("steps", []) if s["step"] in (1, 4, 5) for c in s.get("checks", [])}
    m = rep.get("metrics", {})
    basis = (m.get("basis") or {}).get("label", "latest fiscal year")

    def pct(v):
        return f"{v:.1%}" if isinstance(v, (int, float)) and abs(v) < 5 else str(v)

    def line(name):
        c = checks.get(name)
        if not c or c.get("passed") is None and c.get("value") is None:
            return ""
        v = c.get("value")
        shown = ", ".join(pct(x) for x in v) if isinstance(v, list) else pct(v) if isinstance(v, (int, float)) else str(v)
        verdict = "PASS" if c.get("passed") else "FAIL" if c.get("passed") is False else "info"
        return f"- {name.replace('_', ' ')}: {shown} [{verdict}; rule: {c.get('threshold') or 'n/a'}{'; ' + c['note'] if c.get('note') else ''}]"

    out: dict[str, str] = {}
    for key, (_, _, names) in GROUPS.items():
        lines = [x for x in (line(n) for n in names) if x]
        if key == "returns":
            lines = [f"- ROE judged on the {basis}: {pct(m.get('roe'))} (latest fiscal year {pct(m.get('roe_latest'))}, 5-year average {pct(m.get('roe_avg5'))}, "
                     f"{m.get('roe_loss_years') or 0} loss year(s) of the last 5)", f"- ROIC: {pct(m.get('roic'))}"] + lines
        if key == "margins" and margins:
            lines += [f"- {k} by year: " + ", ".join(f"{y} {pct(v)}" for y, v in sorted(series.items())[-6:]) for k, series in margins.items()
                      if k in ("gross margin", "operating margin", "net margin")]
        if key == "growth":
            lines = [f"- analyst growth used for valuation: {pct(m.get('growth'))}; revenue CAGR {pct(m.get('revenue_cagr'))}"] + lines
        if key == "valuation":
            lines = [f"- price {rep.get('price')}, intrinsic value {rep.get('intrinsic_value')}, margin of safety {pct(m.get('margin_of_safety'))}, "
                     f"P/E {m.get('pe')}, PEG {m.get('peg')}, dividend yield {pct(m.get('dividend_yield'))}, beta {m.get('beta')}"]
        out[key] = "\n".join(lines) or "- no figures available"
    return out


def _links(text: str) -> list[str]:
    seen, out = set(), []
    for u in re.findall(r"https?://[^\s\]\)>\"']+", text or ""):
        u = u.rstrip(".,;")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _clean(text: str) -> str:
    from vmi.ai_helper import plain
    return plain(text)


def explain(ticker: str, name: str, rep: dict, chat: Callable[[list[dict], int], str], margins: dict | None = None, level: str = "quick",
            on_tool=None, cik: int | str | None = None, use_cache: bool = True) -> dict:
    """The full explainer. `chat(messages, max_tokens) -> str` is the local model; `rep` is the app's analysis report for the ticker."""
    ticker = ticker.upper()
    level = "deep" if level == "deep" else "quick"
    key = f"ai:explain:{level}:{ticker}:{datetime.date.today().isoformat()}"
    if use_cache:
        try:
            from vmi.data.cache import get_cache
            hit = get_cache().get(key, CACHE_TTL)
            if hit:
                return {**hit, "cached": True}
        except Exception:
            pass
    pages = 3 if level == "deep" else 2
    facts = metric_facts(rep, margins)
    app_text = "\n".join(f"{GROUPS[k][0]}:\n{v}" for k, v in facts.items())

    def research(question: str, words: str) -> str:
        return P.answer(question.format(name=name), name, ticker, chat, on_tool, pages, words.format(name=name))

    jobs = [(k, t, w, q) for k, t, w, q in CONTEXT] + [(f"m_{k}", g[0], g[1], f"Why are {{name}}'s {g[0].lower()} what they are?") for k, g in GROUPS.items()]
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        annual = ex.submit(P.sec_annual_report, ticker)
        notes = dict(zip([j[0] for j in jobs], ex.map(lambda j: research(j[3], j[2]), jobs)))
        report_text = annual.result()
    recent_extra = f"\nANNUAL REPORT EXTRACTS:\n{report_text[:2500]}" if report_text else ""

    sections = []
    for k, title, _, _ in CONTEXT:
        extra = "Start with a 3-sentence overview a teenager could follow." if k == "overview" else ""
        n = notes[k] + (recent_extra if k in ("industry", "recent") else "")
        text = chat([{"role": "user", "content": SECTION_PROMPT.format(name=name, ticker=ticker, title=title, words=_words(level), extra=extra,
                                                                      figures=app_text[:1500], notes=n[:5000])}], 520)
        sections.append({"key": k, "title": title, "text": _clean(text), "links": _links(n + " " + text)})
    for k, (title, _, _) in GROUPS.items():
        text = chat([{"role": "user", "content": SECTION_PROMPT.format(name=name, ticker=ticker, title=title, words=_words(level) + 60, extra=METRIC_EXTRA,
                                                                      figures=facts[k], notes=notes[f"m_{k}"][:4500])}], 620)
        sections.append({"key": f"m_{k}", "title": title, "text": _clean(text), "links": _links(notes[f"m_{k}"] + " " + text), "figures": facts[k]})
    gl = chat([{"role": "user", "content": GLOSSARY_PROMPT.format(text="\n".join(s["text"] for s in sections)[:6000])}], 400)
    sections.append({"key": "glossary", "title": "Glossary", "text": _clean(gl), "links": []})
    further = [u for s in sections for u in s["links"]]
    if cik:
        further.append(f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K&dateb=&owner=include&count=10")
    further.append(f"https://en.wikipedia.org/wiki/Special:Search?search={name.replace(' ', '+')}")
    result = {"ticker": ticker, "name": name, "level": level, "generated": datetime.datetime.now().isoformat(timespec="minutes"),
              "sections": sections, "further_reading": list(dict.fromkeys(further)), "cached": False}
    if use_cache:
        try:
            from vmi.data.cache import get_cache
            get_cache().set(key, result)
        except Exception:
            pass
    return result
