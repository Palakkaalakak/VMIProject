// Single HTTP client for the FastAPI backend. Every view imports from here — never calls fetch directly.
async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "content-type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const msg = (data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText;
    throw new Error(msg);
  }
  return data;
}

const qs = (params = {}) => {
  const p = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + new URLSearchParams(p).toString() : "";
};

export const api = {
  health: () => request("GET", "/api/health"),
  ibSync: () => request("GET", "/api/ib/sync"),
  startIbSync: () => request("POST", "/api/ib/sync"),
  quote: (s) => request("GET", `/api/quote/${s}`),
  // analysis
  analyse: (s, technicals = true) => request("GET", `/api/analysis/${s}${qs({ technicals })}`),
  override: (s) => request("GET", `/api/analysis/${s}/override`),
  setOverride: (s, body) => request("PUT", `/api/analysis/${s}/override`, body),
  clearOverride: (s, commit = false) => request("DELETE", `/api/analysis/${s}/override${qs({ commit })}`),
  moatEvidence: (s) => request("GET", `/api/analysis/${s}/moat-evidence`),
  overrideSchema: () => request("GET", "/api/overrides/schema"),
  overridesAll: () => request("GET", "/api/overrides"),
  // settings (vmi/rules.py values, editable)
  settings: () => request("GET", "/api/settings"),
  saveSettings: (changes) => request("PUT", "/api/settings", { changes }),
  resetSettings: () => request("DELETE", "/api/settings"),
  size: (s, portfolio_id, multiplier) => request("GET", `/api/analysis/${s}/size${qs({ portfolio_id, multiplier })}`),
  // scanner
  scanStart: (body) => request("POST", "/api/scan/start", body),
  scanStatus: () => request("GET", "/api/scan/status"),
  scanResults: (params) => request("GET", `/api/scan/results${qs(params)}`),
  scanDropped: () => request("GET", "/api/scan/dropped"),
  // portfolios
  portfolios: () => request("GET", "/api/portfolios"),
  portfolio: (id) => request("GET", `/api/portfolios/${id}`),
  createPortfolio: (body) => request("POST", "/api/portfolios", body),
  deletePortfolio: (id) => request("DELETE", `/api/portfolios/${id}`),
  resetPortfolio: (id) => request("POST", `/api/portfolios/${id}/reset`),
  trades: (id) => request("GET", `/api/portfolios/${id}/trades`),
  stockOrder: (id, body) => request("POST", `/api/portfolios/${id}/orders/stock`, body),
  optionOrder: (id, body) => request("POST", `/api/portfolios/${id}/orders/option`, body),
  // watchlists
  watchlists: () => request("GET", "/api/watchlists"),
  watchlist: (id) => request("GET", `/api/watchlists/${id}`),
  createWatchlist: (name) => request("POST", "/api/watchlists", { name }),
  deleteWatchlist: (id) => request("DELETE", `/api/watchlists/${id}`),
  addItem: (id, body) => request("POST", `/api/watchlists/${id}/items`, body),
  removeItem: (id, s) => request("DELETE", `/api/watchlists/${id}/items/${s}`),
  autofill: (id, s) => request("POST", `/api/watchlists/${id}/items/${s}/autofill`),
  importList: (id, text, auto_fill) => request("POST", `/api/watchlists/${id}/import`, { text, auto_fill }),
  scanWatchlist: (id) => request("POST", `/api/watchlists/${id}/scan`),
  // alerts
  alerts: () => request("GET", "/api/alerts"),
  markSeen: (ids) => request("POST", "/api/alerts/seen", ids ?? null),
  checkAlerts: () => request("POST", "/api/alerts/check"),
  // ledger (admin edits), journal, review, automation, option book
  ledger: (id) => request("GET", `/api/portfolios/${id}/ledger`),
  ledgerAdd: (id, body) => request("POST", `/api/portfolios/${id}/ledger`, body),
  ledgerUpdate: (tid, body) => request("PUT", `/api/ledger/${tid}`, body),
  ledgerDelete: (tid, body) => request("POST", `/api/ledger/${tid}/delete`, body),
  verify: (id) => request("GET", `/api/portfolios/${id}/verify`),
  rebuild: (id, reason) => request("POST", `/api/portfolios/${id}/rebuild`, { reason }),
  audit: (id) => request("GET", `/api/portfolios/${id}/audit`),
  exportAll: (id) => request("GET", `/api/portfolios/${id}/export`),
  recordMarks: (id) => request("POST", `/api/portfolios/${id}/marks`),
  review: (id) => request("GET", `/api/portfolios/${id}/review`),
  whatIf: (id, name, params) => request("GET", `/api/portfolios/${id}/review/what-if/${name}${qs(params)}`),
  equityCurve: (id) => request("GET", `/api/portfolios/${id}/equity-curve`),
  pfSettings: (id) => request("GET", `/api/portfolios/${id}/settings`),
  savePfSettings: (id, changes) => request("PUT", `/api/portfolios/${id}/settings`, { changes }),
  plans: (id) => request("GET", `/api/portfolios/${id}/plans`),
  savePlan: (id, body) => request("PUT", `/api/portfolios/${id}/plans`, body),
  deletePlan: (id, symbol) => request("DELETE", `/api/portfolios/${id}/plans/${symbol}`),
  plansFromWatchlist: (id, wid, overwrite = false) => request("POST", `/api/portfolios/${id}/plans/from-watchlist/${wid}${qs({ overwrite })}`),
  runPlans: (id) => request("POST", `/api/portfolios/${id}/plans/run`),
  snapshots: (params) => request("GET", `/api/optionbook/snapshots${qs(params)}`),
  snapshot: (sid) => request("GET", `/api/optionbook/snapshots/${sid}`),
  createSnapshot: (body) => request("POST", "/api/optionbook/snapshots", body),
  recompute: (sid, body) => request("POST", `/api/optionbook/snapshots/${sid}/recompute`, body),
  deleteSnapshot: (sid) => request("DELETE", `/api/optionbook/snapshots/${sid}`),
  // options
  expirations: (s) => request("GET", `/api/options/${s}/expirations`),
  chain: (s, expiry, width) => request("GET", `/api/options/${s}/chain${qs({ expiry, width })}`),
  suggest: (s, strategy, expiry, watchlist_id) => request("GET", `/api/options/${s}/suggest${qs({ strategy, expiry, watchlist_id })}`),
};
