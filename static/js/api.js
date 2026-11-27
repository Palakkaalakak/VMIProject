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
  setMode: (fundamental_review) => request("PUT", "/api/mode", { fundamental_review }),
  ibSync: () => request("GET", "/api/ib/sync"),
  startIbSync: () => request("POST", "/api/ib/sync"),
  quote: (s) => request("GET", `/api/quote/${s}`),
  // analysis
  analyse: (s, technicals = true, mode = {}) => request("GET", `/api/analysis/${s}${qs({ technicals, ...mode })}`),
  override: (s) => request("GET", `/api/analysis/${s}/override`),
  setOverride: (s, body) => request("PUT", `/api/analysis/${s}/override`, body),
  clearOverride: (s, commit = false) => request("DELETE", `/api/analysis/${s}/override${qs({ commit })}`),
  // "More detailed overview" tab (vmi/analysis/overview.py)
  ovStatements: (s, period = "annual") => request("GET", `/api/analysis/${s}/statements${qs({ period })}`),
  ovTrends: (s, period = "annual") => request("GET", `/api/analysis/${s}/trends${qs({ period })}`),
  ovMetrics: (s) => request("GET", `/api/analysis/${s}/metrics`),
  ovSnapshot: (s) => request("GET", `/api/analysis/${s}/snapshot`),
  ovValuationPreview: (s, body) => request("POST", `/api/analysis/${s}/valuation/preview`, body),
  ovDividends: (s) => request("GET", `/api/analysis/${s}/dividends`),
  ovEarnings: (s) => request("GET", `/api/analysis/${s}/earnings`),
  moatEvidence: (s) => request("GET", `/api/analysis/${s}/moat-evidence`),
  overrideSchema: () => request("GET", "/api/overrides/schema"),
  overridesAll: () => request("GET", "/api/overrides"),
  // settings (vmi/rules.py values, editable)
  settings: () => request("GET", "/api/settings"),
  saveSettings: (changes) => request("PUT", "/api/settings", { changes }),
  resetSettings: () => request("DELETE", "/api/settings"),
  size: (s, portfolio_id, multiplier, price) => request("GET", `/api/analysis/${s}/size${qs({ portfolio_id, multiplier, price })}`),
  // scanner
  scanPresets: () => request("GET", "/api/scan/presets"),
  scanStart: (body) => request("POST", "/api/scan/start", body),
  scanStatus: () => request("GET", "/api/scan/status"),
  scanResults: (params) => request("GET", `/api/scan/results${qs(params)}`),
  bars: (s, interval = "1d") => request("GET", `/api/bars/${s}${qs({ interval })}`),
  aiStatus: () => request("GET", "/api/ai/status"),
  aiSettings: () => request("GET", "/api/ai/settings"),
  saveAiSettings: (settings) => request("PUT", "/api/ai/settings", settings),
  aiExplain: (s, level, fresh, mode = {}) => request("POST", `/api/analysis/${s}/ai-explain${qs({ level, fresh, ...mode })}`),
  aiDownload: () => request("POST", "/api/ai/download"),
  aiRemove: () => request("DELETE", "/api/ai/model"),
  aiOpinion: (s, level = "quick", checker = false) => request("POST", `/api/analysis/${s}/ai-opinion?level=${level}&checker=${checker}`),
  aiCheck: (s) => request("POST", `/api/analysis/${s}/ai-check`),
  touches: () => request("GET", "/api/touches"),
  touchPrompts: () => request("GET", "/api/touches/prompts"),
  touchAnswer: (id, waiting) => request("POST", `/api/touches/${id}/answer`, { waiting }),
  touchStats: () => request("GET", "/api/touches/stats"),
  scanSaved: () => request("GET", "/api/scan/saved"),
  scanSave: (id, name) => request("POST", `/api/scan/runs/${id}/save`, { name }),
  scanUnsave: (id) => request("DELETE", `/api/scan/runs/${id}/save`),
  scanDropped: () => request("GET", "/api/scan/dropped"),
  // portfolios
  portfolios: () => request("GET", "/api/portfolios"),
  portfolio: (id) => request("GET", `/api/portfolios/${id}`),
  createPortfolio: (body) => request("POST", "/api/portfolios", body),
  deletePortfolio: (id) => request("DELETE", `/api/portfolios/${id}`),
  resetPortfolio: (id) => request("POST", `/api/portfolios/${id}/reset`),
  breakdown: (id, by) => request("GET", `/api/portfolios/${id}/breakdown${qs({ by })}`),
  setTag: (id, symbol, tag) => request("POST", `/api/portfolios/${id}/tags`, { symbol, tag }),
  heatmap: (metric) => request("GET", `/api/heatmap${qs({ metric })}`),
  premarket: (id) => request("GET", `/api/portfolios/${id}/premarket`),
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
  addReview: (id, s, notes) => request("POST", `/api/watchlists/${id}/review/${s}`, { notes }),
  promote: (id, s) => request("POST", `/api/watchlists/${id}/items/${s}/promote`),
  autofill: (id, s) => request("POST", `/api/watchlists/${id}/items/${s}/autofill`),
  importList: (id, text, auto_fill) => request("POST", `/api/watchlists/${id}/import`, { text, auto_fill }),
  watchlistStats: (id, threshold) => request("GET", `/api/watchlists/${id}/stats${qs({ threshold })}`),
  watchlistMetrics: (id) => request("GET", `/api/watchlists/${id}/metrics`),
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
  runPlans: (id, backdate_days) => request("POST", `/api/portfolios/${id}/plans/run${qs({ backdate_days })}`),
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
