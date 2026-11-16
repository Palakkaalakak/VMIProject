// Watchlists: tracked tickers with intrinsic value + support (buy) levels, distance to next level,
// import (Adam's TICKER|s1,s2|IV format, CSV with header, TradingView lists), auto-fill from the analysis.
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, modal, run, table, toast, signClass } from "../ui.js";

export async function render(root, params = {}) {
  root.innerHTML = loading("Loading watchlists…");
  const lists = await api.watchlists();
  const sel = params.id ? +params.id : lists[0]?.id;
  root.innerHTML = `
    <section class="card">
      <div class="tabs">${lists.map((w) => `<a class="tab ${w.id === sel ? "active" : ""}" href="#/watchlists/${w.id}">${esc(w.name)} <span class="muted">${w.count}</span></a>`).join("")}
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
        <button type="button" id="wl-check" class="secondary">Check prices now</button>
        <button type="button" id="wl-scan" class="secondary">Run VMI scan on list</button>
        <button type="button" id="wl-stats" class="secondary">Watchlist stats</button>
        <button type="button" id="wl-del" class="danger">Delete list</button>
      </form>
    </section>
    <section id="wl-stats-box"></section>
    <section class="card"><div id="wl-items"></div></section>`;
  $("#wl-items", box).appendChild(table(COLS, w.items || [], {
    empty: "Empty — add tickers or import a list.",
    initialSort: { key: "distance_to_level", desc: false },
    onRow: (r) => { location.hash = `#/analysis/${r.symbol}`; },
    actions: {
      autofill: (r, b) => run(b, async () => { await api.autofill(id, r.symbol); toast(`${r.symbol}: IV + levels filled from analysis`, "ok"); detail(box, id); }),
      remove: (r, b) => run(b, async () => { await api.removeItem(id, r.symbol); detail(box, id); }),
    },
  }));
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
  { key: "margin_of_safety", label: "MOS", cls: "num", render: (r) => `<span class="${signClass(r.margin_of_safety)}">${fmt.pct(r.margin_of_safety)}</span>` },
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
