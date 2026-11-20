"""Research tools the local AI may call while forming a moat opinion: web search, read a page, Wikipedia summary.

Only the search words / the page address leave this PC (public company names, never the owner's data). All fetches are plain
HTTPS GETs with a short timeout and a size cap; private/loopback addresses are refused so a page cannot steer the model
into the owner's own network. Every function returns a short plain-text string (errors included) and never raises.
"""
from __future__ import annotations

import base64
import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MAX_BYTES = 600_000
PAGE_CHARS = 6000

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Use it to find WHY a margin, ROIC or growth figure moved (acquisition, one-off charge, new competitor, "
                       "regulation, product shift) and what competitors or analysts say. Returns titles, links and snippets.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "read_page",
        "description": "Read the text of one web page (a link from web_search, an investor-relations page, an annual-report page, a news "
                       "article). Long pages come in parts: call again with the next offset to keep reading. Also lists the page's links.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "offset": {"type": "integer"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "app_analysis",
        "description": "This app's own analysis of a ticker (the Analysis page): 10-year statement figures, margins, ROE/ROIC, growth, the step "
                       "checks, peers and moat evidence. Cite it as [analysis page].",
        "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}}},
    {"type": "function", "function": {
        "name": "wikipedia",
        "description": "Short Wikipedia summary of a company or industry term (business model, competitors, history).",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}}},
]


def _public(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except OSError:
        return False
    return True


class _PublicOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public(newurl):
            raise urllib.error.URLError("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_PublicOnly)


def _get(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with _opener.open(req, timeout=timeout) as r:
        return r.read(MAX_BYTES).decode("utf-8", "ignore")


def _text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _unwrap(link: str) -> str:
    """Bing result links are redirects carrying the real address base64-encoded in `u=a1...`."""
    link = html.unescape(link)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("u", [""])[0]
    if q.startswith("a1"):
        try:
            return base64.urlsafe_b64decode(q[2:] + "=" * (-len(q[2:]) % 4)).decode()
        except Exception:
            pass
    return link


def web_search(query: str, n: int = 6) -> str:
    try:
        page = _get("https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "setlang": "en", "cc": "us"}))
    except Exception as exc:
        return f"search failed: {exc}"
    out = []
    for b in re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', page, re.S):
        a = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        if a:
            out.append(f"- {_text(a.group(2))[:100]} ({_unwrap(a.group(1))[:140]}): {_text(p.group(1))[:240] if p else ''}")
        if len(out) >= n:
            break
    return "\n".join(out) or "no results"


def read_page(url: str, offset: int = 0) -> str:
    if not _public(url):
        return "refused: only public http(s) pages can be read"
    try:
        raw = _get(url)
    except Exception as exc:
        return f"could not read the page: {exc}"
    text = _text(raw)
    offset = max(0, int(offset or 0))
    part = text[offset:offset + PAGE_CHARS]
    if not part:
        return "no more text on this page"
    more = f"\n[page continues: call read_page with offset={offset + PAGE_CHARS}]" if len(text) > offset + PAGE_CHARS else "\n[end of page]"
    links = []
    if offset == 0:
        for href, label in re.findall(r'<a[^>]+href="(https?://[^"#]+)"[^>]*>(.*?)</a>', raw, re.S)[:200]:
            label = _text(label)[:60]
            if label and len(links) < 25:
                links.append(f"{label}: {href[:150]}")
    return part + more + ("\nLINKS: " + " | ".join(links) if links else "")


def app_analysis(ticker: str) -> str:
    """Summary of the local app's analysis of `ticker` (the same figures the Analysis page shows)."""
    try:
        from vmi.analysis.pipeline import analyse_ticker
        rep = analyse_ticker(ticker.upper(), with_technicals=False)
    except Exception as exc:
        return f"analysis failed: {exc}"
    m = rep.get("metrics") or {}
    keep = {k: m.get(k) for k in ("roe", "roic", "net_margin", "gross_margin", "operating_margin", "basis", "roe_loss_years") if k in m}
    steps = [f"Step {s['step']} {s.get('title','')}: {'pass' if s.get('passed') else 'fail'}; "
             + "; ".join(f"{c['name']}={'ok' if c.get('passed') else 'no' if c.get('passed') is False else '?'} ({c.get('note','')[:90]})"
                         for c in s.get("checks", [])[:8]) for s in rep.get("steps", [])]
    return json.dumps({"ticker": ticker.upper(), "name": rep.get("name"), "industry": rep.get("industry"), "price": rep.get("price"),
                       "metrics": keep, "moat": rep.get("moat")}, default=str)[:1500] + "\n" + "\n".join(steps)[:4500]


def wikipedia(title: str) -> str:
    try:
        q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "redirects": 1,
                                    "generator": "search", "gsrsearch": title, "gsrlimit": 1, "format": "json"})
        pages = json.loads(_get("https://en.wikipedia.org/w/api.php?" + q)).get("query", {}).get("pages", {})
        p = next(iter(pages.values()), None)
        return f"{p['title']}: {p.get('extract', '')[:2500]}" if p else "no Wikipedia page found"
    except Exception as exc:
        return f"wikipedia failed: {exc}"


def make_runner():
    """A `run` for one research session that steers the model away from search loops: a near-repeat of an earlier query is
    refused, and after two searches in a row without opening a page it is told to read the best results first."""
    seen: list[set] = []
    streak = [0]

    def words(q: str) -> set:
        return {w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2}

    def runner(name: str, args: dict) -> str:
        if name == "web_search":
            q = words(str(args.get("query", "")))
            for old in seen:
                if q and len(q & old) / len(q | old) >= 0.6:
                    return ("You already searched almost exactly this. Do not repeat searches: open the most relevant result pages from "
                            "your earlier searches with read_page, or search for a DIFFERENT question.")
            seen.append(q)
            streak[0] += 1
            out = run(name, args)
            if streak[0] >= 2:
                out += ("\nNOTE: you have searched twice without reading anything. Now open the 1-2 most relevant result pages "
                        "above with read_page before searching again; snippets are not evidence.")
            return out
        if name == "read_page":
            streak[0] = 0
        return run(name, args)

    return runner


def run(name: str, args: dict) -> str:
    try:
        if name == "web_search":
            return web_search(str(args.get("query", ""))[:200])
        if name == "read_page":
            return read_page(str(args.get("url", ""))[:500], args.get("offset") or 0)
        if name == "app_analysis":
            return app_analysis(str(args.get("ticker", ""))[:12])
        if name == "wikipedia":
            return wikipedia(str(args.get("title", ""))[:100])
    except Exception as exc:                       # a tool must never break the answer
        return f"tool error: {exc}"
    return f"unknown tool {name}"
