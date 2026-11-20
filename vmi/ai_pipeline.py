"""Code-driven company research for the moat AI: the code searches, opens and reads; the model plans, extracts and judges.

Small local models are bad at driving open-ended tool loops (they repeat searches and never open pages), so the loop lives here:
  1. plan     - the model turns Adam's moat tests into 6-8 concrete questions about this company.
  2. sources  - the company's latest annual report (SEC 10-K / 20-F: the Competition section and competition-related risk factors)
                and this app's own analysis are always included.
  3. search   - for each question the code searches (DuckDuckGo, Bing fallback), ranks results (primary sources first, spam last),
                opens the top pages, extracts the main text (trafilatura) and keeps only the passages relevant to the question.
  4. extract  - the model writes findings from those passages only, each with its URL; UNKNOWN when the passages do not say.
  5. reflect  - the model lists what is still unknown; one more round of steps 3-4 on those gaps.
Searches and pages are cached for a few days, so re-running a ticker is fast and does not hammer the search engines.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import json
import re
import urllib.parse

from vmi import ai_tools

PAGE_TTL = 3 * 24 * 3600
PASSAGE_CHARS = 1800
PAGES_PER_QUESTION = 3
WORKERS = 3

GOOD_DOMAINS = {"sec.gov": 4, "wikipedia.org": 2, "reuters.com": 3, "bloomberg.com": 2, "ft.com": 2, "wsj.com": 2, "cnbc.com": 2,
                "morningstar.com": 3, "fool.com": 1, "seekingalpha.com": 1, "statista.com": 2, "marketwatch.com": 1, "barrons.com": 2,
                "investopedia.com": 1, "economist.com": 2, "forbes.com": 1, "businesswire.com": 2, "prnewswire.com": 2, "gartner.com": 2,
                "idc.com": 2, "macrotrends.net": 1, "stockanalysis.com": 1}
BAD_DOMAINS = ("youtube.com", "pinterest.", "facebook.com", "instagram.com", "tiktok.com", "quora.com", "x.com", "twitter.com",
               "linkedin.com", "amazon.com/dp", "ebay.")

DEFAULT_QUESTIONS = [
    "Who are {name}'s closest competitors in each main business, and what are the market shares? Is {name} gaining or losing share?",
    "Has {name} raised prices in recent years, and did customers or volumes hold up afterwards?",
    "How hard or costly is it for {name}'s customers to switch to a competitor (switching costs, contracts, integration, ecosystem)?",
    "Does {name} benefit from a network effect, high barriers to entry (regulation, patents, licences) or economies of scale?",
    "What threats could erode {name}'s position over the next 10-20 years (bigger rivals bundling, cheaper substitutes, technology, regulation)?",
    "What explains any recent decline in {name}'s profits, margins or growth: a one-off or a structural cause?",
    "What did {name} report in its latest annual or quarterly results and guidance?",
]

PLAN_PROMPT = """You plan research for a moat assessment of {name} ({ticker}) using Adam Khoo's framework (brand monopoly / pricing power,
switching costs, network effect, barriers to entry, economies of scale; top dog vs closest competitors; can a much bigger rival copy it;
signs of erosion: discounting, share loss, customers switching; temporary vs structural problems).
App figures for context:
{figures}
Write 6 to 8 specific research questions that, once answered from current web sources, would settle the grade. Make them concrete for
this company (name its businesses, the weak numbers above, its likely rivals as things to CHECK, not facts).
Reply with a JSON list of strings only."""

EXTRACT_PROMPT = """QUESTION: {question}
Below are passages fetched today from web pages about {name}. Using ONLY these passages (your memory is out of date), write 1 to 5
short findings that answer the question, each ending with the source URL in brackets, e.g. "... [https://...]". Quote numbers exactly.
If the passages do not answer it, write exactly: UNKNOWN: <what is missing>.
PASSAGES:
{passages}"""

REFLECT_PROMPT = """Research notes so far on {name} ({ticker}) for a moat assessment:
{notes}
List at most 4 follow-up questions for the most important things still UNKNOWN or contradictory (rivals and market share, pricing power
evidence, switching costs, threats, causes of weak numbers). Reply with a JSON list of strings only; [] if nothing important is missing."""


def _cached(key: str, fn, ttl: int = PAGE_TTL):
    try:
        from vmi.data.cache import get_cache
        return get_cache().get_or_set(key, ttl, fn)
    except Exception:
        return fn()


def _domain(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _score(url: str, name: str, ticker: str) -> int:
    d, u = _domain(url), url.lower()
    if any(b in u for b in BAD_DOMAINS) or u.endswith(".pdf"):
        return -10
    s = max((v for k, v in GOOD_DOMAINS.items() if d == k or d.endswith("." + k)), default=0)
    first = re.sub(r"[^a-z0-9]", "", name.lower().split()[0]) if name else ""
    if first and first in d.replace("-", "").replace(".", ""):          # the company's own site / investor relations
        s += 4
    if "investor" in u or "/ir" in u or "annual-report" in u:
        s += 1
    return s


def search(query: str, name: str, ticker: str) -> list[tuple[str, str, str]]:
    """[(title, url, snippet)] ranked: primary sources first, junk dropped. Cached."""
    def go():
        for engine in (ai_tools._ddg, ai_tools._bing):
            try:
                res = ai_tools._relevant(query, engine(query))
            except Exception:
                continue
            if len(res) >= 2:
                return [list(r) for r in res]
        return []
    res = _cached("ai:search:" + query.lower(), go)
    res = [tuple(r) for r in res if _score(r[1], name, ticker) > -10]
    return sorted(res, key=lambda r: -_score(r[1], name, ticker))


def page_text(url: str) -> str:
    """Main text of a page (trafilatura; plain-text fallback). Cached; '' when it cannot be read."""
    def go():
        if not ai_tools._public(url):
            return ""
        try:
            raw = ai_tools._get(url, timeout=15)
        except Exception:
            return ""
        try:
            import trafilatura
            txt = trafilatura.extract(raw, include_comments=False, include_tables=True, favor_recall=True) or ""
        except Exception:
            txt = ""
        return (txt or ai_tools._text(raw))[:60000]
    return _cached("ai:page:" + url, go)


def passages(text: str, question: str, name: str, limit: int = PASSAGE_CHARS) -> str:
    """The paragraphs of `text` that best match the question (word overlap), best first, up to `limit` characters."""
    q = {w for w in re.findall(r"[a-z0-9]+", (question + " " + name).lower()) if len(w) > 3}
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-Z])", text) if len(p.strip()) > 60]
    if len(paras) <= 1:
        paras = [text[i:i + 600] for i in range(0, min(len(text), 30000), 600)]
    scored = sorted(paras, key=lambda p: -len(q & set(re.findall(r"[a-z0-9]+", p.lower()))))
    out = ""
    for p in scored:
        if len(out) + len(p) > limit:
            p = p[:max(0, limit - len(out))]
        out += p + "\n"
        if len(out) >= limit:
            break
    return out.strip()


def sec_annual_report(ticker: str) -> str:
    """Competition section + competition-related risk factors from the latest 10-K / 20-F, with its URL. '' if not found."""
    try:
        from vmi.data import filings
        from vmi.data.fundamentals import resolve
        f = resolve(ticker)
        cik = getattr(f, "cik", None)
        if not cik:
            return ""
        filing = filings.latest_10k(cik)
        if not filing:
            return ""
    except Exception:
        return ""

    def go():
        from bs4 import BeautifulSoup
        from vmi.data import http, sec
        html = http.get(filing["url"], headers=sec._headers(), expect_json=False)
        text = BeautifulSoup(html, "lxml").get_text("\n")
        comp = filings.competition_passage(text)
        risk_kw = re.compile(r"compet|market share|pricing pressure|customers may|switch|disrupt|new entrants|substitut", re.I)
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 120 and risk_kw.search(ln)]
        risks = " ".join(lines[:8])[:3000]
        return {"competition": comp, "risks": risks, "conc": filings.concentration_sentences(text)}
    try:
        d = _cached(f"ai:sec:{filing['accession']}", go, 365 * 24 * 3600)
    except Exception:
        return ""
    src = f"[{filing['url']}]"
    parts = [f"ANNUAL REPORT ({filing.get('form', '10-K')}, filed {filing.get('filed')}) {src}"]
    if d.get("competition"):
        parts.append("Company's own Competition section: " + d["competition"] + " " + src)
    if d.get("risks"):
        parts.append("Company's own competition-related risk factors: " + d["risks"] + " " + src)
    if d.get("conc"):
        parts.append("Customer concentration: " + "; ".join(d["conc"]) + " " + src)
    return "\n".join(parts) if len(parts) > 1 else ""


def _json_list(text: str) -> list[str]:
    m = re.search(r"\[.*\]", text or "", re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            return [str(x).strip() for x in v if str(x).strip()]
        except ValueError:
            pass
    return [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", ln).strip() for ln in (text or "").splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s", ln)]


def _search_query(question: str, name: str) -> str:
    q = re.sub(r"[?\"']", " ", question)
    q = re.sub(r"\b(what|which|who|how|does|did|is|are|has|have|the|and|or|of|in|its|any|over|next|years?|a|an|to|for|with|from|that|this)\b",
               " ", q, flags=re.I)
    q = " ".join(q.split())
    if name.split()[0].lower() not in q.lower():
        q = f"{name} {q}"
    return q[:150] + f" {datetime.date.today().year}"


def answer(question: str, name: str, ticker: str, chat, on_tool=None) -> str:
    """Search, open the best pages, keep the relevant passages and let the model write sourced findings."""
    q = _search_query(question, name)
    if on_tool:
        on_tool("web_search", {"query": q})
    results = search(q, name, ticker)
    texts = []
    for title, url, snippet in results[:PAGES_PER_QUESTION + 2]:
        if len(texts) >= PAGES_PER_QUESTION:
            break
        if on_tool:
            on_tool("read_page", {"url": url})
        t = page_text(url)
        if len(t) > 300:
            texts.append(f"[{url}] {title}\n" + passages(t, question, name))
        elif snippet:
            texts.append(f"[{url}] {title} (snippet only)\n{snippet}")
    if not texts:
        return f"- UNKNOWN: no usable web pages found for: {question}"
    out = chat([{"role": "user", "content": EXTRACT_PROMPT.format(question=question, name=name, passages="\n\n".join(texts))}], 700)
    return out.strip()


def research(ticker: str, name: str, chat, on_tool=None, figures: str | None = None) -> str:
    """Full code-driven research; returns notes where every line names its source. `chat(messages, max_tokens) -> str`."""
    figures = figures if figures is not None else ai_tools.app_analysis(ticker)
    if on_tool:
        on_tool("app_analysis", {"ticker": ticker})
    qs = _json_list(chat([{"role": "user", "content": PLAN_PROMPT.format(name=name, ticker=ticker, figures=figures[:3500])}], 600))
    qs = [q for q in qs if len(q) > 15][:8] or [q.format(name=name) for q in DEFAULT_QUESTIONS]
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        sec_future = ex.submit(sec_annual_report, ticker)
        found = list(ex.map(lambda q: f"Q: {q}\n" + answer(q, name, ticker, chat, on_tool), qs))
        annual = sec_future.result()
    notes = "\n\n".join(found)
    gaps = _json_list(chat([{"role": "user", "content": REFLECT_PROMPT.format(name=name, ticker=ticker, notes=notes[:9000])}], 400))[:4]
    if gaps:
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            notes += "\n\n" + "\n\n".join(ex.map(lambda q: f"Q (follow-up): {q}\n" + answer(q, name, ticker, chat, on_tool), gaps))
    head = f"APP FIGURES [analysis page]:\n{figures[:2500]}"
    return "\n\n".join(p for p in (head, annual, notes) if p)
