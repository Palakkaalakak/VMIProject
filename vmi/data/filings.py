"""Annual-report (10-K) excerpts for the moat review: the competition passage and customer-concentration sentences.

Extraction is plain text matching on the filing's own words and every excerpt is shown verbatim with its filing
date, so the reviewer reads the company's statements, not our interpretation. Results are cached per filing.
"""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from vmi.config import get_settings
from vmi.data import http, sec
from vmi.data.cache import get_cache

COMPETITION_HEADINGS = ("competition", "competitors", "competitive conditions", "competition and competitive conditions",
                        "competitive landscape", "competitive environment")
CONCENTRATION = re.compile(r"[^.]{0,200}\b(?:customers?|distributors?|resellers?|channel partners?)\b[^.]{0,160}"
                           r"\baccounted for\b[^.]{0,120}\d+(?:\.\d+)?\s?%[^.]{0,80}\.", re.I)
MAX_PASSAGE = 1600


def latest_10k(cik: int) -> dict | None:
    """{accession, document, filed, url} for the most recent annual report, from SEC's submissions index."""
    def fetch():
        raw = http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=sec._headers())
        recent = raw.get("filings", {}).get("recent", {})
        for i, form in enumerate(recent.get("form", [])):
            if form in ("10-K", "10-K/A", "20-F", "40-F"):
                acc = recent["accessionNumber"][i]
                doc = recent["primaryDocument"][i]
                return {"accession": acc, "document": doc, "filed": recent["filingDate"][i], "form": form,
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"}
        return None

    return get_cache().get_or_set(f"filings:latest:{cik}", 7 * 24 * 3600, fetch)


def annual_reports(cik: int) -> list[dict]:
    """Original annual reports (no amendments), newest first: [{accession, form, filed, period, url}]."""
    def fetch():
        raw = http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=sec._headers())
        recent = raw.get("filings", {}).get("recent", {})
        return [{"accession": recent["accessionNumber"][i], "form": form, "filed": recent["filingDate"][i],
                 "period": recent["reportDate"][i],
                 "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{recent['accessionNumber'][i].replace('-', '')}/{recent['primaryDocument'][i]}"}
                for i, form in enumerate(recent.get("form", [])) if form in ("10-K", "20-F", "40-F")]

    return get_cache().get_or_set(f"filings:annual:{cik}", 7 * 24 * 3600, fetch) or []


# (start heading, end heading) of the business description and of management's discussion (MD&A)
SECTION_MARKS = {
    "10-K": {"business": (r"item\s*1\s*[.:\-—–]?\s*(?:description\s+of\s+)?business", r"item\s*1a\s*[.:\-—–]?\s*risk\s+factors"),
             "mdna": (r"item\s*7\s*[.:\-—–]?\s*management.{0,3}s\s+discussion",
                      r"item\s*7a\s*[.:\-—–]?\s*quantitative|item\s*8\s*[.:\-—–]?\s*(?:consolidated\s+)?financial\s+statements")},
    "20-F": {"business": (r"item\s*4\s*[.:\-—–]?\s*information\s+on\s+the\s+company", r"item\s*4a\b|item\s*5\s*[.:\-—–]?\s*operating"),
             "mdna": (r"item\s*5\s*[.:\-—–]?\s*operating\s+and\s+financial\s+review", r"item\s*6\s*[.:\-—–]?\s*directors")},
}


def _split_ok(pattern: str) -> str:
    """Let heading words match when the filing's HTML splits them ("MAN AGEMENT", "S UPPLEMENTARY")."""
    return re.sub(r"(?<![\\a-z])[a-z]{4,}", lambda m: r"\s?".join(m.group(0)), pattern)


def section_text(text: str, start: str, end: str) -> str:
    """The longest stretch from a `start` heading to the next `end` heading (so table-of-contents entries lose)."""
    best, start, end = "", _split_ok(start), _split_ok(end)
    for m in re.finditer(start, text, re.I):
        if text[:m.start()].rstrip()[-1:] in ('"', "\u201c") or text[m.end():m.end() + 1] in ("\u2014", "\u201d", '"'):
            continue                                   # a quoted cross-reference ("see Item 1. Business\u2014..."), not the heading
        stop = re.compile(end, re.I).search(text, m.end())
        if stop and stop.start() - m.start() > len(best):
            best = text[m.start():stop.start()]
    return best if len(best) > 1500 else ""


def report_sections(filing: dict) -> dict:
    """{business, mdna} plain text of one annual report; '' when a heading is not found (cached per filing)."""
    def fetch():
        html = http.get(filing["url"], headers=sec._headers(), expect_json=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
            text = BeautifulSoup(html, "lxml").get_text("\n")
        text = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", text))
        marks = SECTION_MARKS.get(filing.get("form"), SECTION_MARKS["10-K"])
        return {k: section_text(text, *v)[:200_000] for k, v in marks.items()}

    return get_cache().get_or_set(f"filings:sections:v5:{filing['accession']}", 365 * 24 * 3600, fetch)


def competition_passage(text: str) -> str:
    """The paragraph(s) under a 'Competition' heading (first heading that is followed by real prose)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.lower().rstrip(".:") in COMPETITION_HEADINGS:
            body = ""
            for nxt in lines[i + 1:i + 12]:
                if len(nxt) < 40 and nxt.istitle() and body:  # next heading
                    break
                body += nxt + " "
                if len(body) >= MAX_PASSAGE:
                    break
            if len(body) > 200:
                return body.strip()[:MAX_PASSAGE]
    return ""


GEOGRAPHY = re.compile(r"outside (?:of )?the united states|headquartered|located in|geographic", re.I)


def concentration_sentences(text: str, limit: int = 3) -> list[str]:
    """Sentences like "One customer accounted for 17% of revenue" (geography splits are not concentration)."""
    flat = re.sub(r"\s+", " ", text)
    seen: list[str] = []
    for m in CONCENTRATION.finditer(flat):
        sentence = m.group(0).strip()
        if GEOGRAPHY.search(sentence):
            continue
        if sentence not in seen:
            seen.append(sentence)
        if len(seen) >= limit:
            break
    return seen


def excerpts(cik: int) -> dict:
    """{filed, form, url, competition, customer_concentration} for the latest annual report (cached)."""
    filing = latest_10k(cik)
    if not filing:
        return {}

    def fetch():
        html = http.get(filing["url"], headers=sec._headers(), expect_json=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)  # EDGAR serves inline-XBRL XHTML
            text = BeautifulSoup(html, "lxml").get_text("\n")
        return {**filing, "competition": competition_passage(text),
                "customer_concentration": concentration_sentences(text)}

    return get_cache().get_or_set(f"filings:excerpts:{filing['accession']}", 365 * 24 * 3600, fetch)


def recent_8k(cik: int) -> list[dict]:
    """Recent 8-K filings from SEC's submissions index, newest first: [{form, accession, document, filed, items}].
    `items` is SEC's own list of item numbers, e.g. "2.02,9.01" (2.02 = results of operations = the earnings release)."""
    def fetch():
        raw = http.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=sec._headers())
        recent = raw.get("filings", {}).get("recent", {})
        items = recent.get("items", [])
        return [{"form": form, "accession": recent["accessionNumber"][i], "document": recent["primaryDocument"][i],
                 "filed": recent["filingDate"][i], "items": items[i] if i < len(items) else ""}
                for i, form in enumerate(recent.get("form", [])) if form.startswith("8-K")]

    try:
        return get_cache().get_or_set(f"filings:8k:{cik}", 24 * 3600, fetch) or []
    except http.HttpError:
        return []
