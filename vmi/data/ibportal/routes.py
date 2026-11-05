"""Every IBKR route and field name this package uses. Edit HERE when IBKR changes one.

Where they come from (details and dates in Log.md, 2026-11-05):
  * IBKR's own Client Portal web app (ndcdyn.interactivebrokers.com/portal) calls the Fundamentals Explorer
    backend (LSEG data, free to all IBKR clients) as `/tws.proxy/<route>`. The routes and response shapes
    below were read from that app's public JavaScript.
  * IBKR's Client Portal Gateway (clientportal.gw, class TwsService) forwards `<gateway>/v1/tws/<route>` to
    `/tws.proxy/<route>`, and `<gateway>/v1/api/<route>` to the Web API.

READ-ONLY RULE: this package only reads. It never calls /iserver routes (trading/brokerage). `client.Portal`
refuses them, so the rule is enforced in code. Note that the gateway itself opens a brokerage session for
whoever logs into it, so log it in with a DIFFERENT username than TWS (e.g. the paper login).
"""
from __future__ import annotations

# --- gateway services (path prefixes on the gateway) ----------------------------------------------------
WEB_API = "/v1/api"                                  # session + contract routes
FUNDAMENTALS_BASES = ("/v1/tws", "/v1/api/tws.proxy")  # tried in order; the first that answers is remembered

# --- session (Web API) ------------------------------------------------------------------------------------
SESSION_VALIDATE = "/sso/validate"   # GET → 200 + JSON while logged in, 401 otherwise
KEEPALIVE = "/tickle"                # POST → keeps the session alive (sessions idle out after ~5 min)

# --- contracts (Web API) ------------------------------------------------------------------------------------
STOCKS_BY_SYMBOL = "/trsrv/stocks"   # GET ?symbols=AAPL,MSFT → {SYM: [{assetClass, contracts: [{conid, isUS}]}]}
SYMBOLS_PER_REQUEST = 50

# --- fundamentals (served under FUNDAMENTALS_BASES) -------------------------------------------------------
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
# Extra fields only dumped by the `check` command, to confirm names and units before relying on them.
PROBE_FIELDS = ("FIVE_YR_EPS_GROWTH_FIELD", "EPS_GRWTH_5YR", "CONSENSUS_RANK", "PRICE_2_BOOK", "PRICE_2_SALES")
