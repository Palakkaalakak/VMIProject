# Engineering log

**For every future change (AI or human):** add an entry at the top of "Entries" (newest first) with what
changed, why, the files touched, how it was verified, and what is left open. Update "Current state" when an
entry changes it. Keep the evidence (links, versions, dates) for any claim about an outside system, because
those claims go stale and the next person has to be able to re-check them.

Related docs: `README.md` (overview, architecture, recipes), `docs/GROUND_RULES.md` (owner's rules),
`docs/CALIBRATION.md` (intrinsic-value calibration against Adam's numbers).

---

## Current state (2026-11-05)

- Offline test suite: `python3 -m pytest -q tests`, 66 passing.
- Fundamentals: SEC EDGAR → stockanalysis → Yahoo, merged in `vmi/data/fundamentals.py`. IB is tried first:
  TWS XML (works only if IB still permits it for your login), then the Client Portal Gateway
  (`vmi/data/ibportal/`). **The gateway path is implemented and offline-tested, but it has not been run
  against a real logged-in gateway yet.** The first live run is the `check` command below.
- Open items: a live gateway check on the owner's PC; full-market scanner benchmark; judgement-only
  calibration cases (BKNG/UNH growth input, NKE/LVMUY on P/S); companies with a short history.

### Where to change what

| To change… | Edit |
|---|---|
| an IB route, gateway path or IB field name | `vmi/data/ibportal/routes.py` (only there) |
| how an IB row label maps to our concepts | `LABELS` in `vmi/data/ibportal/parse.py` |
| IB cache keys / TTL / sync behaviour | `vmi/data/ibportal/service.py`, `ttl_ib_portal` in `vmi/config.py` |
| the order IB sources are tried, breaker pauses | `vmi/data/ib_fundamentals.py` |
| a VMI threshold | `vmi/rules.py` |
| a data provider or the merge order | `vmi/data/<provider>.py`, `vmi/data/fundamentals.py` |
| business-type classification | `vmi/analysis/classify.py` |

---

## Entries

### 2026-11-05 — IB fundamentals through the Client Portal Gateway (read-only), replacing the guessed version

**Problem.** The owner wants fundamentals from IBKR. `reqFundamentalData` no longer works in TWS, the earlier
attempt (`vmi/data/ib_portal.py`, same day) used guessed routes, and the owner can't run two sessions on one
username.

**Research (evidence, all checked 2026-11-05):**
1. *TWS API.* The TWS API 10.47 release notes list `reqFundamentalData`, its callbacks and tick type 47 as
   removed ("De-Supported Fundamentals Data Request"):
   https://www.ibkrguides.com/releasenotes/prod-2026.htm. Current builds are Stable 10.50.1f (2026-10-05) and
   Latest 10.51.1e (2026-10-26), per IB's `download2.interactivebrokers.com/installers/{tws,ibgateway}/{stable,latest}-standalone/version.json`.
2. *Where the refusal happens.* The ibx project's gateway investigation found that 10.51 refuses fundamentals
   **locally** with error 10358 unless the login's feature list contains `ALLOW_FNDT_SOMEAPI` ("Nothing is sent
   to the farm"). An older 10.40 still forwarded the request and received ratios on a paper account on
   2026-10-07: https://github.com/deepentropy/ibx/issues/639, /674, /634. So the old README line "IB servers
   refuse older clients" was wrong: the gate is per login and sits in new builds. Running an outdated build to
   get around an entitlement check is fragile and against IB's intent, so it is **not** used.
3. *IB still serves fundamentals.* The Fundamentals Explorer "provides comprehensive, worldwide fundamentals
   data to all IBKR clients, at no cost" (LSEG data): https://www.interactivebrokers.com/en/trading/fundamentals-explorer.php
4. *Exact routes and response shapes.* These were read from IB's own portal JavaScript (public files under
   https://ndcdyn.interactivebrokers.com/portal/: `index.js`, `part.5012.js` financials, `part.2663.js` key
   metrics, `part.9665.js` key ratios, `part.7109.js` data_list). The portal calls `/tws.proxy/fundamentals/…`.
   They are recorded with their shapes in `vmi/data/ibportal/routes.py`. IB's field dictionary includes
   `LONG_TERM_GROWTH` ("Long Term Growth"), the analyst consensus input Adam's DCF needs.
5. *How the gateway reaches them.* IB's Client Portal Gateway (`clientportal.gw.zip`, disassembled with
   `javap`) routes `^/(v1|…)/(portal|am|api|tws)/(.*)`. Its `TwsService` rewrites `/v1/tws/<route>` to
   `/tws.proxy/<route>` (`twsBaseURL`). So the local URL is `https://localhost:5000/v1/tws/fundamentals/…`.
   The `PossibleIBFundamentalFix` note's claims (that TWS has a local REST server, and the `/mofw/` route) are
   wrong.
6. *Sessions.* One brokerage session per username across TWS, Client Portal and Mobile, and a second username
   is the documented fix: https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions.md.
   The gateway itself opens a brokerage session after login (`ClientPortalService`: `iserver/auth/ssodh/init`,
   "iserver init"). Therefore **the gateway must use a different username than TWS.** Paper usernames are
   valid gateway logins: https://interactivebrokers.com/docs/web-api/authentication/paper.md.
7. *Paper/live market data.* IB's FAQ "Market data considerations for the paper trading account"
   (https://www.interactivebrokers.com/lib/cstools/faq/content/1136176599, rendered with Playwright) says:
   - With sharing on, a paper session gets live data alongside the live session only when both run on the
     same device. Otherwise the paper session shows "No Data".
   - The live session always keeps real-time data.

   This is an exchange-licensing rule about market data. Fundamentals are not exchange market data.
   https://www.interactivebrokers.com/docs/tws-api/doc/connectivity/logging-into-multiple-applications.md adds
   that a username used in Client Portal while TWS runs stops TWS auto-reconnecting after the next reset.

**Decision (recommended setup on the owner's PC):**
- TWS (or IB Gateway) on the **live** login, `VMI_IB_PORT=7496` (IB Gateway: 4001), with TWS → Global
  Configuration → API → Settings → **Read-Only API** ticked. The app only reads market data and connects with
  `readonly=True`; its paper trading is simulated locally.
- IBKR **Client Portal Gateway** on the **paper** login, `VMI_IB_CP_URL=https://localhost:5000`. That's a
  different username, so it doesn't compete with TWS, and it only reads fundamentals.
- Fallback if the paper login cannot read fundamentals: one login at a time. Log the gateway in (with any
  login) while TWS is closed, run `sync`, and the cache serves the app for 14 days (`ttl_ib_portal`).

**What was built:**
- `vmi/data/ibportal/` package:
  - `routes.py`: all URLs and fields.
  - `client.py`: HTTP. Refuses any `/iserver` path, rate-limited (`ib_cp_max_rps`), and remembers which
    fundamentals base answers.
  - `parse.py`: pure functions. Exact table schema, with a generic fallback. Estimate columns ("2025E") never
    become history. `harmonize()` snaps units to SEC by a power of 1000 and fills fiscal-year ends.
  - `service.py`: cache-first `fundamentals()` and `estimates()`, bulk `sync()` (analyst fields 50 conids
    per call), and `check()` diagnostics.
- `vmi/data/breaker.py`: shared circuit breaker, replacing ad-hoc dicts.
- `vmi/data/ib_fundamentals.py`: coordinator (TWS XML, then gateway) and the CLI. A per-security 430 no longer
  pauses the TWS path; only 10358/"not allowed"/timeouts do.
- `vmi/data/fundamentals.py`: `MERGED_KEY` and `invalidate()`, which sync calls so merged data picks up IB.
- `vmi/config.py`: `ib_cp_max_rps`, `ttl_ib_portal`; `ib_cp_url` is now the gateway root.
- Tests: `tests/test_ibportal.py`, with a mock gateway. It proves no `/iserver` call is ever made.
  `tests/conftest.py` gives every test an isolated cache. Removed: `vmi/data/ib_portal.py`,
  `tests/test_ib_portal.py`.

**How to use (owner's PC):**
```bash
python3 -m vmi.data.ib_fundamentals check AAPL MSFT    # TWS probe + every gateway route; raw JSON → data/ib_portal_samples/
python3 -m vmi.data.ib_fundamentals sync --sp500       # fill the IB cache (add --no-statements for analyst growth only)
```

**Verified:** offline tests (66 pass). Probing IB's endpoints from the cloud sandbox was blocked, correctly,
so nothing here has seen a real IB response yet.

**Unverified, to be settled by the first `check` run:**
- `/v1/tws/fundamentals/*` answers through the gateway. The code falls back to `/v1/api/tws.proxy`.
- The paper login can read fundamentals.
- Exact `metric_name` strings and number formats. If `parsed_annual` is sparse, extend `LABELS` from the
  saved JSON.
- The `LONG_TERM_GROWTH` units.

### 2026-11-05 — Managed care (SIC 6324) classified as normal companies
- `vmi/analysis/classify.py`: SIC 6324 and text "healthcare plans"/"managed care" map to `normal` (DCF), not
  `insurance`. The master doc files managed care under Healthcare. Test in `tests/test_valuation_rules.py`.
- Effect: UNH is now DCF IV 638 vs Adam 438 (ratio 1.46; it was 1.35 on P/B). The gap is the growth input
  (13–18% rebound consensus vs ~6% implied by Adam). This is a judgement case; details in `docs/CALIBRATION.md`.
  BKNG was re-checked the same way: the data matches filings and the gap is Adam's growth.

### 2026-11-05 — FDIC CET1 holding-company matching
- `vmi/data/fdic.py`:
  - Canonical tokens on both sides (FINL/SVC/BCORP/NY abbreviations, split initials "U S" → "US").
  - Exact holding matches rank above bank-name matches.
  - Single-token keys must match exactly.
  - Fallback to the bank's own name for banks without a holding company (Zions).
- Verified live against api.fdic.gov with the final code: 25 large bank holding companies resolve to their
  main bank (JPM, USB, MTB, BK, FCNCA, ZION, WFC, PNC, EWBC, C, BAC, GS, MS, SCHW, WAL, CFR, KEY, TFC, FITB,
  HBAN, CFG, RF, COF, STT, NTRS). A name search finds no active FDIC bank for Comerica or Webster, so they
  return none rather than a wrong bank. Test in `tests/test_parsing.py`.

### 2026-11-05 — First Client Portal provider (superseded the same day)
- `vmi/data/ib_portal.py` implemented the `PossibleIBFundamentalFix` idea with guessed routes and a
  schema-agnostic parser. It was replaced by the `vmi/data/ibportal/` entry above once the real routes were
  found in IB's code.

### Before 2026-11-05
See `git log`, `docs/CALIBRATION.md` (valuation calibration history) and `docs/GROUND_RULES.md`.
