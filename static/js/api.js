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
  quote: (s) => request("GET", `/api/quote/${s}`),
  // analysis
  analyse: (s, technicals = true) => request("GET", `/api/analysis/${s}${qs({ technicals })}`),
  override: (s) => request("GET", `/api/analysis/${s}/override`),
  setOverride: (s, body) => request("PUT", `/api/analysis/${s}/override`, body),
  clearOverride: (s, commit = false) => request("DELETE", `/api/analysis/${s}/override${qs({ commit })}`),
  overrideSchema: () => request("GET", "/api/overrides/schema"),
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
  // options
  expirations: (s) => request("GET", `/api/options/${s}/expirations`),
  chain: (s, expiry, width) => request("GET", `/api/options/${s}/chain${qs({ expiry, width })}`),
  suggest: (s, strategy, expiry, watchlist_id) => request("GET", `/api/options/${s}/suggest${qs({ strategy, expiry, watchlist_id })}`),
};
