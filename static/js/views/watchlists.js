// Watchlists: tracked tickers with intrinsic value + support (buy) levels, distance to next level,
// import (Adam's TICKER|s1,s2|IV format, CSV with header, TradingView lists), auto-fill from the analysis.
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, modal, run, table, toast, signClass } from "../ui.js";
import { METRIC_COLS, loadCols, saveCols, metricColumns, legendHtml } from "./watchlist_cols.js";

export async function render(root, params = {}) {
  root.innerHTML = loading("Loading watchlists…");
  const lists = await api.watchlists();
  const sel = params.id ? +params.id : lists[0]?.id;
  root.innerHTML = `
    <section class="card">
      <div class="tabs">${lists.map((w) => `<a class="tab ${w.id === sel ? "active" : ""}" href="#/watchlists/${w.id}">${esc(w.name)} <span class="muted">${w.count}</span>${w.review_count ? ` <span class="badge" title="stocks in the review queue">${w.review_count} to review</span>` : ""}</a>`).join("")}
        <button id="wl-new" class="secondary">+ New</button></div>
    </section>
    <div id="wl-detail">${sel ? "" : `<div class="card muted">Create a watchlist to start tracking stocks.</div>`}</div>`;
  $("#wl-new", root).addEventListener("click", (e) => run(e.target, async () => {
    const name = prompt("Watchlist name");
    if (!name) return;
    const w = await api.createWatchlist(name);
    location.hash = `#/watchlists/${w.id}`;
  }));
  if (sel) detail($("#wl-detail", root), sel);
}

async function detail(box, id) {
  box.innerHTML = loading();
  const w = await api.watchlist(id);
  box.innerHTML = `
    <section class="card">
      <form id="wl-add" class="inline">
        <input name="symbol" placeholder="Ticker" required>
        <input name="iv" type="number" step="any" placeholder="IV (optional)">
        <input name="supports" placeholder="Supports e.g. 513,466,419">
        <button class="primary">Add / update</button>
        <span class="spacer"></span>
        <button type="button" id="wl-import" class="secondary">Import…</button>
        <button type="button" id="wl-export" class="secondary" title="Download this watchlist as a CSV (symbol, iv, supports) that Import reads back">Export CSV</button>
        <button type="button" id="wl-check" class="secondary">Check prices now</button>
        <button type="button" id="wl-scan" class="secondary">Run VMI scan on list</button>
        <button type="button" id="wl-stats" class="secondary">Watchlist stats</button>
        <button type="button" id="wl-cols" class="secondary" title="Choose extra metric columns for this list">Columns</button>
        <button type="button" id="wl-del" class="danger">Delete list</button>
      </form>
    </section>
    <section id="wl-stats-box"></section>
    <section class="card" id="wl-cols-box" hidden></section>
    <section class="card"><div id="wl-items"></div><div id="wl-legend"></div></section>
    <section class="card" id="wl-review-card" ${(w.items || []).some((i) => i.stage === "review") ? "" : "hidden"}><h3>Review queue <span class="muted small">candidates from the scanner that still need a full review; not counted in sizing, plans, stats or price alerts until promoted</span></h3><div id="wl-review"></div></section>`;
  const review = (w.items || []).filter((i) => i.stage === "review"), watching = (w.items || []).filter((i) => i.stage !== "review");
  $("#wl-review", box).appendChild(table([
    { key: "symbol", label: "Candidate", render: (r) => `<a href="#/analysis/${esc(r.symbol)}"><b>${esc(r.symbol)}</b></a>` },
    { key: "notes", label: "From the scan" },
    { key: "_a", label: "", render: () => `<button class="small primary" data-action="promote">Promote to watchlist</button> <button class="small secondary" data-action="moat">Moat review</button> <button class="small danger" data-action="remove">Remove</button>` },
  ], review, { empty: "Nothing to review.", actions: {
    promote: (r, b) => run(b, async () => { await api.promote(id, r.symbol); toast(`${r.symbol} is in the watchlist`, "ok"); detail(box, id); }),
    moat: (r) => window.open(`#/moat/${r.symbol}`, "_blank"),
    remove: (r, b) => run(b, async () => { await api.removeItem(id, r.symbol); detail(box, id); }) } }));
  // metric columns: chosen per list (saved in this browser), data from GET /metrics (cached analysis) fetched on first use
  let chosen = loadCols(id), metrics = null, loadingMetrics = false;
  const drawItems = () => {
    const extra = metricColumns(chosen, metrics, loadingMetrics);
    const cols = [...COLS.slice(0, -1), ...extra, COLS[COLS.length - 1]];
    const holder = $("#wl-items", box);
    holder.innerHTML = "";
    holder.appendChild(table(cols, watching, {
      empty: "Empty — add tickers or import a list.",
      initialSort: { key: "distance_to_level", desc: false },
      onRow: (r) => { location.hash = `#/analysis/${r.symbol}`; },
      actions: {
        autofill: (r, b) => run(b, async () => { await api.autofill(id, r.symbol); toast(`${r.symbol}: IV + levels filled from analysis`, "ok"); detail(box, id); }),
        remove: (r, b) => run(b, async () => { await api.removeItem(id, r.symbol); detail(box, id); }),
      },
    }));
    $("#wl-legend", box).innerHTML = chosen.length ? legendHtml(metrics, loadingMetrics) : "";
  };
  const ensureMetrics = async () => {
    if (!chosen.length || metrics || loadingMetrics) return drawItems();
    loadingMetrics = true; drawItems();
    try { metrics = await api.watchlistMetrics(id); }
    catch (e) { toast(`Metric columns: ${e.message}`, "error", 7000); metrics = { metrics: {}, rules: {} }; }
    loadingMetrics = false; drawItems();
  };
  const colsPane = $("#wl-cols-box", box);
  colsPane.addEventListener("change", (e) => {
    const key = e.target?.dataset?.col;
    if (!key) return;
    chosen = METRIC_COLS.map((c) => c.key).filter((k) => (k === key ? e.target.checked : chosen.includes(k)));
    saveCols(id, chosen);
    ensureMetrics();
  });
  $("#wl-cols", box).addEventListener("click", () => {
    colsPane.hidden = !colsPane.hidden;
    colsPane.innerHTML = `<h3>Columns <span class="muted small">extra metrics next to the standard ones; saved for this list in this browser</span></h3>
      <div class="inline">${METRIC_COLS.map((c) => `<label class="check"><input type="checkbox" data-col="${c.key}" ${chosen.includes(c.key) ? "checked" : ""}> ${esc(c.label)}</label>`).join("")}</div>`;
  });
  ensureMetrics();
  $("#wl-stats", box).addEventListener("click", (e) => run(e.target, async () => { $("#wl-stats-box", box).innerHTML = statsHtml(await api.watchlistStats(id)); }));
  const refresh = () => detail(box, id);
  $("#wl-add", box).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const supports = String(f.get("supports") || "").split(/[\s,;]+/).filter(Boolean).map(Number).filter((x) => !isNaN(x));
    run(e.submitter, async () => {
      await api.addItem(id, { symbol: String(f.get("symbol")).toUpperCase(), intrinsic_value: f.get("iv") ? +f.get("iv") : null, supports: supports.length ? supports : null });
      refresh();
    });
  });
  $("#wl-import", box).addEventListener("click", () => importDialog(id, refresh));
  $("#wl-export", box).addEventListener("click", async () => {
    const w = await api.watchlist(id);
    const csv = ["symbol,iv,supports", ...(w.items || []).map((i) => `${i.symbol},${i.intrinsic_value ?? ""},${(i.supports || []).join(";")}`)].join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `watchlist-${(w.name || id).toString().replace(/[^\w-]+/g, "_")}.csv`;
    a.click(); URL.revokeObjectURL(a.href);
    toast(`Exported ${(w.items || []).length} symbols`, "ok");
  });
  $("#wl-check", box).addEventListener("click", (e) => run(e.target, async () => { const r = await api.checkAlerts(); toast(`Checked — ${Array.isArray(r) ? r.length : 0} new alert(s)`, "ok"); refresh(); }));
  $("#wl-scan", box).addEventListener("click", (e) => run(e.target, async () => { await api.scanWatchlist(id); location.hash = "#/scanner"; }));
  $("#wl-del", box).addEventListener("click", (e) => confirm(`Delete ${w.name}?`) && run(e.target, async () => { await api.deleteWatchlist(id); location.hash = "#/watchlists"; }));
}

function importDialog(id, done) {
  const m = modal("Import watchlist", `
    <p class="small muted">Formats: <code>MSFT|513,466,419|570.31</code> (Adam's), CSV/TSV with a <code>symbol</code> header
      (optional <code>iv</code>, <code>supports</code>), or a TradingView export / plain list (<code>NASDAQ:MSFT, AAPL …</code>).</p>
    <textarea id="imp-text" rows="12" placeholder="Paste here"></textarea>
    <label class="check"><input type="checkbox" id="imp-auto" checked> auto-fill missing IV / levels from analysis (slower)</label>
    <button id="imp-go" class="primary">Import</button>`);
  $("#imp-go", m.el).addEventListener("click", (e) => run(e.target, async () => {
    const r = await api.importList(id, $("#imp-text", m.el).value, $("#imp-auto", m.el).checked);
    toast(`Imported ${r.imported} symbols`, "ok"); m.close(); done();
  }));
}

const COLS = [
  { key: "symbol", label: "Ticker", render: (r) => `<b>${esc(r.symbol)}</b>${r.notes ? `<div class="small muted">${esc(r.notes)}</div>` : ""}` },
  { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
  { key: "intrinsic_value", label: "IV", cls: "num", render: (r) => `${fmt.money(r.intrinsic_value)} <span class="small muted">${esc(r.iv_source || "")}</span>` },
  { key: "margin_of_safety", label: "Price vs IV", cls: "num", render: (r) => `<span class="${signClass(r.margin_of_safety)}" title="Price versus intrinsic value: −20% = price 20% below IV (undervalued); +20% = 20% above IV (overvalued)">${fmt.gap(r.margin_of_safety)}</span>` },
  { key: "supports", label: "Supports", render: (r) => (r.supports || []).map((s) => `<span class="chip ${r.price && s >= r.price ? "hit" : ""}">${fmt.num(s)}</span>`).join(" ") },
  { key: "next_level", label: "Next level", cls: "num", render: (r) => fmt.money(r.next_level) },
  { key: "distance_to_level", label: "Distance", cls: "num", render: (r) => fmt.pct(r.distance_to_level) },
  { key: "levels_hit", label: "Hit", cls: "num" },
  { key: "in_buy_zone", label: "Buy zone", render: (r) => badge(r.in_buy_zone, "BUY ZONE", "—") },
  { key: "_a", label: "", render: () => `<button class="small secondary" data-action="autofill">Auto-fill</button> <button class="small danger" data-action="remove">✕</button>` },
];

const P = (v, d = 1) => (v == null ? "—" : fmt.pct(v, d));
const STEP = ["Track record", "Growth", "Moat (provisional)", "Profitability", "Debt", "Price < IV", "Chart entry"];

function statsHtml(s) {
  const g = s.growth_spread, n = s.numbers, f = s.flags;
  const row = (k, pct = true) => `<tr><td>${esc(n[k].label)}</td><td class="num">${pct ? P(n[k].mean) : fmt.num(n[k].mean)}</td><td class="num">${pct ? P(n[k].median) : fmt.num(n[k].median)}</td>
    <td class="num">${pct ? P(n[k].min) : fmt.num(n[k].min)}</td><td class="num">${pct ? P(n[k].max) : fmt.num(n[k].max)}</td><td class="num">${n[k].n}</td></tr>`;
  const mix = (o) => Object.entries(o).map(([k, v]) => `${esc(k)} <b>${v}</b>`).join(" · ") || "—";
  return `<section class="card"><h3>Stats: ${esc(s.watchlist)} <span class="muted small">${s.n_analysed} of ${s.n_stocks} analysed · equal weight</span></h3>
    ${s.errors.length ? `<p class="note neg small">Not analysed: ${s.errors.map((e) => `${esc(e.symbol)} (${esc(e.error)})`).join("; ")}</p>` : ""}
    ${s.fails_great_business.length ? `<p class="note"><b>${s.fails_great_business.length} fail the great-business check (steps 1-5):</b> ${s.fails_great_business.map((x) => `<a href="#/analysis/${esc(x.symbol)}">${esc(x.symbol)}</a> (step ${x.first_failed_step ?? "?"})`).join(", ")}</p>` : `<p class="note">✔ Every stock passes steps 1-5 (moat is only provisional).</p>`}
    <div class="kpis"><div class="kpi"><span>Avg of LOWEST growth estimates</span><b>${P(g.avg_of_lowest)}</b></div>
      <div class="kpi"><span>Avg of AVERAGE estimates</span><b>${P(g.avg_of_average)}</b></div>
      <div class="kpi"><span>Avg of HIGHEST estimates</span><b>${P(g.avg_of_highest)}</b></div>
      <div class="kpi"><span>Growth ≥ ${P(g.threshold, 0)} by lowest / avg / highest</span><b>${g.n_growth_by_lowest} / ${g.n_growth_by_average} / ${g.n_growth_by_highest}</b></div>
      <div class="kpi"><span>Great business · below IV · entry OK</span><b>${f.great_business} · ${f.below_iv} · ${f.entry_ok}</b></div>
      <div class="kpi"><span>Moat reviewed · IV low-confidence</span><b>${f.moat_reviewed} · ${f.iv_low_confidence}</b></div></div>
    <table class="compact"><thead><tr><th></th><th>Mean</th><th>Median</th><th>Min</th><th>Max</th><th>n</th></tr></thead><tbody>
      ${["growth_low", "growth_avg", "growth_high", "growth", "roe", "roic", "net_margin", "margin_of_safety", "dividend_yield"].map((k) => row(k)).join("")}
      ${["pe", "peg", "beta", "steps_passed"].map((k) => row(k, false)).join("")}</tbody></table>
    <p class="small"><b>Steps passed (of ${s.n_analysed}):</b> ${Object.entries(s.step_pass_counts).map(([k, v]) => `${esc(STEP[k - 1])} ${v}`).join(" · ")}</p>
    <p class="small"><b>Sector:</b> ${mix(s.mix.sector)}</p><p class="small"><b>Industry:</b> ${mix(s.mix.industry)}</p>
    <p class="small"><b>Style:</b> ${mix(s.mix.style)} · <b>Category:</b> ${mix(s.mix.category)} · <b>Moat:</b> ${mix(s.mix.moat)} · <b>Method:</b> ${mix(s.mix.method)}</p>
    <p class="small muted">Largest sector share ${P(s.concentration.top_sector_share, 0)} (${esc(s.concentration.top_sector || "—")}); market cap ${fmt.big(s.concentration.smallest_cap)} to ${fmt.big(s.concentration.largest_cap)}. Growth uses each stock's lowest, average and highest usable 5-year analyst estimate; single-source stocks count the same value three times.</p></section>`;
}
