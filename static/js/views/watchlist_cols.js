// Metric columns of the watchlist page: the choosable columns, the per-list choice (localStorage) and the colour legend.
// Values and green / yellow / red flags come from GET /api/watchlists/{id}/metrics (flags decided by vmi/watchlist/flags.py).
import { esc, fmt } from "../ui.js";

const pct = (v) => fmt.pct(v, 1), num = (v) => fmt.num(v, 2);
export const METRIC_COLS = [
  { key: "growth", label: "Growth", fmt: pct }, { key: "roe", label: "ROE", fmt: pct }, { key: "roic", label: "ROIC", fmt: pct },
  { key: "net_margin", label: "Net margin", fmt: pct }, { key: "margin_of_safety", label: "Price vs IV (VMI IV)", fmt: (v) => fmt.gap(v, 1) },
  { key: "peg", label: "PEG", fmt: num }, { key: "pe", label: "P/E", fmt: num }, { key: "dividend_yield", label: "Div. yield", fmt: pct },
  { key: "steps_passed", label: "Steps", fmt: (v) => (v == null ? "—" : `${v}/7`) }, { key: "moat", label: "Moat", fmt: (v) => v || "—" },
  { key: "distance_to_level", label: "Dist. (flagged)", fmt: pct },
  { key: "market_cap", label: "Mkt cap", fmt: fmt.big }, { key: "beta", label: "Beta", fmt: num }, { key: "sector", label: "Sector", fmt: (v) => v || "—" },
];

const storeKey = (id) => `vmi.wl.cols.${id}`;
export function loadCols(id) {
  try {
    const v = JSON.parse(localStorage.getItem(storeKey(id)) || "[]");
    return Array.isArray(v) ? v.filter((k) => METRIC_COLS.some((c) => c.key === k)) : [];
  } catch { return []; }
}
export function saveCols(id, cols) {
  try { localStorage.setItem(storeKey(id), JSON.stringify(cols)); } catch { /* private mode: the choice just is not remembered */ }
}

/** Table columns for the chosen metrics; `data` is the /metrics payload (null while loading). */
export function metricColumns(chosen, data, loading) {
  return chosen.map((k) => METRIC_COLS.find((c) => c.key === k)).filter(Boolean).map((c) => ({
    key: `m_${c.key}`, label: c.label, cls: ["sector", "moat"].includes(c.key) ? "" : "num",
    sort: (r) => data?.metrics?.[r.symbol]?.[c.key] ?? null,
    render: (r) => {
      const m = data?.metrics?.[r.symbol];
      if (!m) return loading ? `<span class="muted">…</span>` : "—";
      if (m.error) return `<span class="muted" title="${esc(m.error)}">—</span>`;
      const text = esc(c.fmt(m[c.key])), flag = m.flags?.[c.key];
      return flag ? `<span class="flag ${flag}">${text}</span>` : text;
    },
  }));
}

export function legendHtml(data, loading) {
  if (loading) return `<p class="small muted">Analysing the list (cached for 6 hours)…</p>`;
  const rl = data?.rules || {}, p = (v) => (v == null ? "?" : `${(v * 100).toFixed(0)}%`);
  const errs = Object.values(data?.metrics || {}).filter((m) => m.error);
  return `<p class="small muted"><span class="flag green">green</span> good · <span class="flag yellow">yellow</span> borderline · <span class="flag red">red</span> fails the rule · no colour = no rule.
    Thresholds are the app's own rules: ROE / ROIC green ≥ ${p(rl.excellent_roe)}, yellow ≥ ${p(rl.min_roe)}; PEG green ≤ ${rl.peg_attractive ?? "?"}, yellow ≤ ${rl.peg_screen ?? "?"};
    margin of safety green when price is below IV; steps green ≥ 5 of 7; growth green ≥ ${p(rl.growth_threshold)}, yellow when positive;
    dividend yield green ≥ ${p(rl.min_yield)}, yellow ≥ ${p(rl.screen_yield)}; distance green within ${p(rl.near_level_pct)} of a buy level,
    yellow within ${p(3 * rl.near_level_pct)}; wide moat green, narrow yellow.</p>
    ${errs.length ? `<p class="small neg">Not analysed: ${errs.map((m) => `${esc(m.symbol)} (${esc(m.error)})`).join("; ")}</p>` : ""}`;
}
