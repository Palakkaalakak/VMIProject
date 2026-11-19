"""The "at first sight" read of a company's moat: a few quick signals and one short paragraph, to disqualify fast.

It is NOT the verdict (Adam: the moat is a judgement, Step 3). Every signal says where it comes from:
  adam      a test or comparison Adam states (margins at or above the closest competitors, margins steady or rising 5 years,
            pricing power held, a consistent 5-10 year record)
  inferred  Adam gives no bar, so the band is read off his own examples: Visa 78% gross / 67% operating / 49% net and
            Microsoft 68% / 46% / 39% are his "very high margins" (wide); Singapore Airlines 16% gross / 9.6% net is "low" (no moat)
The bands are the constants below so they are easy to change.
"""
from __future__ import annotations

from vmi.analysis import moat_evidence as ME
from vmi.analysis.trends import falling_streak

# Inferred from Adam's examples (see the module note). Gross margin is the main measure; operating margin when no gross profit is reported.
HIGH_GROSS, LOW_GROSS = 0.60, 0.25       # Visa 78%, Microsoft 68%  |  Singapore Airlines 16%
HIGH_OPERATING, LOW_OPERATING = 0.30, 0.10   # Visa 67%, Microsoft 46%  |  (airline net 9.6%)
FRAGMENTED_SHARE = 0.10                  # a leader under 10% of its peer group's sales is not "the" top dog


def _signal(label: str, reading: str, text: str, source: str) -> dict:
    return {"label": label, "reading": reading, "text": text, "source": source}      # reading: good | bad | unknown


def _margin_level(f) -> dict:
    hist = ME.margin_history(f, 10)
    for name, high, low in (("gross margin", HIGH_GROSS, LOW_GROSS), ("operating margin", HIGH_OPERATING, LOW_OPERATING)):
        series = hist.get(name) or hist.get(name.replace(" margin", ""))
        if series:
            v = series[max(series)]
            if v >= high:
                return _signal("Margin level", "good", f"{name} {v:.0%}: very high (Adam's wide examples: Visa 78% gross, Microsoft 68%)", "inferred")
            if v < low:
                return _signal("Margin level", "bad", f"{name} {v:.0%}: low (his no-moat example: Singapore Airlines 16% gross)", "inferred")
            return _signal("Margin level", "unknown", f"{name} {v:.0%}: in between (average = narrow at best)", "inferred")
    return _signal("Margin level", "unknown", "no margin data", "inferred")


def _margin_trend(f) -> dict:
    hist = ME.margin_history(f, 6)
    series = hist.get("gross margin") or hist.get("operating margin") or hist.get("gross") or hist.get("operating")
    if not series or len(series) < 4:
        return _signal("Margin trend (5 years)", "unknown", "not enough margin history", "adam")
    vals = [series[y] for y in sorted(series)]
    streak = falling_streak(vals)
    if streak >= 2:
        return _signal("Margin trend (5 years)", "bad", f"margin has fallen {streak} years in a row (Adam: a falling margin is a bad sign)", "adam")
    avg = sum(vals[:-1]) / len(vals[:-1])
    ok = vals[-1] >= avg * 0.97
    return _signal("Margin trend (5 years)", "good" if ok else "bad",
                   f"latest {vals[-1]:.1%} vs earlier average {avg:.1%}: {'steady or rising' if ok else 'below its own average'}", "adam")


def _vs_peers(peers: dict | None) -> list[dict]:
    if not peers or not peers.get("rows"):
        return [_signal("Versus competitors", "unknown", "no peer table (list peers in the overrides for a non-S&P 500 company)", "adam")]
    s = peers.get("summary") or {}
    ranks, n = s.get("ranks") or {}, (s.get("peers") or 0) + 1
    out = []
    if ranks.get("operating_margin"):
        top = ranks["operating_margin"] <= max(1, n // 3)
        out.append(_signal("Versus competitors", "good" if top else "bad" if ranks["operating_margin"] > n * 2 / 3 else "unknown",
                           f"operating-margin rank {ranks['operating_margin']} of {n} (Adam: margins should match or beat the closest competitors)", "adam"))
    share = s.get("share")
    if share is not None:
        if s.get("top_dog_hint"):
            out.append(_signal("Industry position", "good", f"looks like the industry leader ({share:.0%} of the group's sales)", "adam"))
        elif share < FRAGMENTED_SHARE and n >= 6:
            out.append(_signal("Industry position", "bad", f"only {share:.0%} of the group's sales among {n} companies: competition looks fragmented", "inferred"))
        else:
            out.append(_signal("Industry position", "unknown", f"{share:.0%} of the group's sales, {n} companies", "inferred"))
    return out


def _pricing(f) -> dict:
    p = ME.pricing_power(f)
    if p["held"] is None:
        return _signal("Pricing power", "unknown", "not enough history for the 2018-20 vs 2021-23 margin test", "adam")
    return _signal("Pricing power", "good" if p["held"] else "bad",
                   f"{p['measure']} {'held up' if p['held'] else 'fell'} through the 2021-23 cost shock (baseline {p['baseline']:.1%}, worst {p['stress_min']:.1%})", "adam")


def _record(steps: list[dict]) -> dict:
    s1 = next((s for s in steps if s["step"] == 1), None)
    if s1 is None:
        return _signal("Track record", "unknown", "no Step 1 result", "adam")
    return _signal("Track record", "good" if s1["passed"] else "bad",
                   "sales, earnings and cash flow rising consistently" if s1["passed"] else "Step 1 fails: earnings or margins not consistently rising", "adam")


def assess(f, steps: list[dict], peers: dict | None = None, no_moat_industry: bool = False) -> dict:
    """{"leaning", "signals": [...], "paragraph"} from the statements (f), the 7 step results and the optional peer table."""
    signals = [_margin_level(f), _margin_trend(f), *_vs_peers(peers), _pricing(f), _record(steps)]
    good = sum(s["reading"] == "good" for s in signals)
    bad = sum(s["reading"] == "bad" for s in signals)
    if no_moat_industry:
        leaning, head = "weak", "Adam's no-moat industry list (commodities, airlines, autos ...)"
    elif (bad >= 2 and bad >= good) or (bad and good < 2):
        leaning, head = "weak", "more warning signs than strengths"
    elif good >= 4 and not bad:
        leaning, head = "wide-looking", "strong on every signal that can be checked from data"
    elif good > bad:
        leaning, head = "narrow-looking", "decent but not clearly dominant"
    else:
        leaning, head = "unclear", "not enough evidence either way"
    goods = "; ".join(s["text"] for s in signals if s["reading"] == "good")
    bads = "; ".join(s["text"] for s in signals if s["reading"] == "bad")
    para = f"At first sight: {leaning} ({head})." + (f" For: {goods}." if goods else "") + (f" Against: {bads}." if bads else "") \
        + " This is a quick screen from numbers, not a moat verdict: the customer test, the five sources and the competitors still need your judgement."
    return {"leaning": leaning, "signals": signals, "paragraph": para, "good": good, "bad": bad}
