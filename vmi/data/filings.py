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
