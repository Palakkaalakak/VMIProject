r"""Every IBKR route and field name this package uses. Edit HERE when IBKR changes one.

Source (details and dates in Log.md, 2026-11-05/06): IBKR's own Client Portal web app calls the Fundamentals Explorer
backend (LSEG/Refinitiv data, free to all IBKR clients) as `<SITE>/tws.proxy/<route>` (portal config:
TWS_BASE_URL "/tws.proxy"). Routes and response shapes below were read from that app's public JavaScript and confirmed
on real runs (2026-11-06, AAPL + MSFT). The Client Portal Gateway cannot carry them (its catch-all route redirects
unknown paths to the portal site; disassembly + real runs, Log.md 2026-11-06), so we log in in a browser instead.

READ-ONLY RULE: this package only reads. `client.Portal` refuses any /iserver path (trading/brokerage).
"""
from __future__ import annotations

SITE = "https://ndcdyn.interactivebrokers.com"
LOGIN = SITE + "/sso/Login?forwardTo=22&RL=1&ip2loc=US"
FUNDAMENTALS_BASE = "/tws.proxy"

# --- fundamentals (served under FUNDAMENTALS_BASE) -------------------------------------------------------
FINANCIALS = "/fundamentals/financials/{conid}"
#   GET ?annual=true|false&type=income|balance|cash →
#   {"generalInfo": [...], "table": {"columns": [{"name", "value"}],
#                                    "rows": [{"metric_name", "metric_name_tag", "search_id", "hasEsimates",
#                                              "<column name>": value, "trend": [...], "change": pct}]}}
STATEMENTS = ("income", "balance", "cash")

DATA_LIST = "/fundamentals/data_list"
#   GET ?conids=1,2,3&field_names=A,B → [{"conid", "field_name", "display_value"}]  (many conids per call)
CONIDS_PER_DATA_LIST = 50

KEY_METRICS = "/fundamentals/data/predefined/nextg_qd/{conid}"  # GET ?show=translations → [{field_name, display_value}]
KEY_RATIOS = "/fundamentals/key_ratios/{conid}"                 # GET → {"tables": [{"rows": [...]}]}
FIN_TRENDS = "/fundamentals/fin_trends/{conid}"
#   GET ?search_id=<row search_id>&annual=true → {"periods"|"values": [{"year"|"title", "actual", "estimate"}]}
#   Not used yet: extension point for analyst EPS/revenue estimates per future year.

# --- data_list fields → our estimate keys ------------------------------------------------------------------
# (IBKR field name, our key, unit). "pct" values arrive in percent ("9.07" = 9.07 %) and are stored as decimals.
ANALYST_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("LONG_TERM_GROWTH", "eps_growth_5y", "pct"),  # analyst consensus long-term EPS growth (the DCF growth input)
    ("BETA", "beta", "x"),
)
# key_metrics fields → our estimate keys. EPSTRENDGR ("9.85%"): meaning NOT documented in the portal JS (UNVERIFIED);
# cross-checked 2026-11-06 against the I/B/E/S consensus pretax-income CAGR in fin_trends: AAPL 9.85 % vs 10.1 % (to FY2029),
# MSFT 17.38 % vs 18.5 % (to FY2030), i.e. a forward consensus growth rate. Exclude per stock with the `exclude_sources` override.
KEY_METRIC_FIELDS: tuple[tuple[str, str, str], ...] = (("EPSTRENDGR", "eps_growth_5y", "pct"),)
# Extra fields only dumped by the `check` command, to confirm names and units before relying on them.
PROBE_FIELDS = ("FIVE_YR_EPS_GROWTH_FIELD", "EPS_GRWTH_5YR", "CONSENSUS_RANK", "PRICE_2_BOOK", "PRICE_2_SALES")
