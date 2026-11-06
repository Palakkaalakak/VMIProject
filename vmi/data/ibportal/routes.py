r"""Every IBKR route and field name this package uses. Edit HERE when IBKR changes one.

Where they come from (details and dates in Log.md, 2026-11-05):
  * IBKR's own Client Portal web app (ndcdyn.interactivebrokers.com/portal) calls the Fundamentals Explorer
    backend (LSEG data, free to all IBKR clients) as `/tws.proxy/<route>`. The routes and response shapes
    below were read from that app's public JavaScript.
  * IBKR's Client Portal Gateway (clientportal.gw build a27ed42, disassembled) forwards every path it does not
    recognise, unchanged and with your login cookies, to `proxyRemoteHost` from its config file. Its `TwsService`
    (`/v1/tws/...`) is never registered in this build ("Unknown service tws", confirmed on a real run 2026-11-06).
    The default `root/conf.yaml` points at IB's public Web API host (no fundamentals there: 404, confirmed);
    `root/conf.tws.yaml` points at the portal website host, which serves `/tws.proxy/fundamentals/...`.
    So: run the gateway with the `conf.tws.yaml` profile and ask it for `/tws.proxy/...` directly. NOTE: IBKR's
    `bin\run.bat` never passes its file argument to Java (it only derives the folder), so `run.bat root\conf.tws.yaml`
    silently loads conf.yaml (confirmed on a real run 2026-11-06). Start Java yourself with `--conf conf.tws.yaml`.

READ-ONLY RULE: this package only reads. It never calls /iserver routes (trading/brokerage). `client.Portal`
refuses them, so the rule is enforced in code. Note that the gateway itself opens a brokerage session for
whoever logs into it, so log it in with a DIFFERENT username than TWS (e.g. the paper login).
"""
from __future__ import annotations

# --- gateway services (path prefixes on the gateway) ----------------------------------------------------
# Each group is tried in order; the first base that answers is remembered per gateway (client._working_base).
# With conf.tws.yaml the gateway forwards to the portal website, which does NOT serve /v1/api (404, confirmed
# 2026-11-06); the portal web app reaches the same Web API routes as /portal.proxy/v1/portal/<route>.
WEB_API = "/v1/api"
# "/v1/portal" is the gateway's own portal service (route ^/(v1|…)/(portal|am|api|tws)/(.*) in GatewayHttpProxy,
# forwarded to portalBaseURL "/portal.proxy" in conf.tws.yaml, with the gateway's login cookies).
API_BASES = ("/v1/api", "/v1/portal", "/portal.proxy/v1/portal")  # session + contract routes
FUNDAMENTALS_BASES = ("/tws.proxy", "/v1/portal", "/v1/api")
# Browser login straight on the portal site (browser.py). Verified on a real run 2026-11-06: /tws.proxy answers all
# nine fundamentals routes; PORTAL_BASE_URL in the portal's own config is "/portal.proxy/v1/portal".
DIRECT_FUNDAMENTALS_BASES = ("/tws.proxy",)
DIRECT_API_BASES = ("/portal.proxy/v1/portal",)
GATEWAY_CONFIG_HINT = ("If every route failed, the gateway is on its default conf.yaml (IB's public Web API, no fundamentals). "
                       "IBKR's bin\\run.bat ignores the file name you give it, so start the gateway with this repo's "
                       "launcher instead: tools\\start_cp_gateway.cmd C:\\path\\to\\clientportal.gw  (then log in again)")

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
