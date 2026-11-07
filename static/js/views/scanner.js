// Superscanner view: start a funnel run (broad/cheap filters first), live funnel progress, sortable results.
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, run, table, toast, signClass } from "../ui.js";
import { applyFilters, filterPanel, loadSaved, readFilters, save, setForm } from "./scanner_filters.js";

let poll = null;

export function render(root) {
  root.innerHTML = `
    <section class="card">
      <h3>Superscanner</h3>
      <form id="scan-form" class="grid">
        <label>Universe <select name="universe"><option value="sp500">S&amp;P 500</option><option value="us">Full US market</option><option value="list">Custom list</option></select></label>
        <label class="wide">Symbols (custom list) <input name="symbols" placeholder="AAPL, MSFT, AZO …"></label>
        <label>Min market cap ($B) <input name="min_market_cap" type="number" step="0.5" value="2"></label>
        <label>Min price <input name="min_price" type="number" step="1" value="5"></label>
        <label>Min ROE <input name="min_roe" type="number" step="0.01" value="0.12"></label>
        <label>Deep-analysis limit <input name="deep_limit" type="number" value="400"></label>
        <label class="check"><input type="checkbox" name="require_ten_year_uptrend" checked> require 10y uptrend</label>
        <button class="primary">Start scan</button>
      </form>
    </section>
    <section id="scan-status" class="card"></section>
    <section class="card">
      <div class="toolbar inline">
        <h3>Results</h3>
        <button id="scan-dropped" class="secondary">Why dropped?</button>
      </div>
      <div id="scan-filter-box"></div>
      <div id="scan-results">${loading()}</div>
    </section>`;
  $("#scan-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      universe: f.get("universe"),
      symbols: String(f.get("symbols") || "").split(/[\s,;]+/).filter(Boolean).map((s) => s.toUpperCase()),
      min_market_cap: parseFloat(f.get("min_market_cap")) * 1e9,
      min_price: parseFloat(f.get("min_price")),
      min_roe: parseFloat(f.get("min_roe")),
      deep_limit: parseInt(f.get("deep_limit"), 10),
      require_ten_year_uptrend: f.get("require_ten_year_uptrend") === "on",
    };
    run(e.submitter, async () => { await api.scanStart(body); toast("Scan started", "ok"); startPolling(root); });
  });
  $("#scan-dropped", root).addEventListener("click", (e) => run(e.target, () => showDropped(root)));
  startPolling(root);
  loadResults(root);
}

export function destroy() { clearInterval(poll); poll = null; }

function startPolling(root) {
  clearInterval(poll);
  const tick = async () => {
    const st = await api.scanStatus().catch(() => null);
    if (!st || !document.body.contains(root)) return destroy();
    $("#scan-status", root).innerHTML = statusHtml(st);
    if (!st.running) { clearInterval(poll); poll = null; if (st.n_results) loadResults(root); }
  };
  tick();
  poll = setInterval(tick, 2000);
}

const statusHtml = (st) => `
  <div class="inline"><b>${st.running ? "Running" : "Idle"}</b> · stage <b>${esc(st.stage)}</b> · ${esc(st.message || "")}
    · ${fmt.num(st.elapsed, 0)}s ${st.error ? `<span class="neg">${esc(st.error)}</span>` : ""}</div>
  <div class="progress"><div style="width:${Math.round((st.progress || 0) * 100)}%"></div></div>
  <ol class="funnel">${(st.funnel || []).map((f) => `<li><b>${esc(f.stage)}</b> ${fmt.num(f.count, 0)} <span class="muted small">${esc(f.note || "")}</span></li>`).join("")}</ol>`;

let allRows = [];

async function loadResults(root) {
  const box = $("#scan-results", root);
  try {
    allRows = (await api.scanResults({})).results || [];
    const fb = $("#scan-filter-box", root);
    const wasOpen = fb.querySelector("details")?.open;
    fb.innerHTML = filterPanel(allRows);
    const form = fb.querySelector("form");
    setForm(form, loadSaved());
    if (wasOpen) fb.querySelector("details").open = true;
    const redraw = () => { save(readFilters(form)); drawRows(root); };
    form.addEventListener("input", redraw);
    $("#scan-reset", root).addEventListener("click", () => { form.reset(); redraw(); });
    drawRows(root);
  } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

function drawRows(root) {
  const box = $("#scan-results", root);
  const rows = applyFilters(allRows, readFilters($("#scan-filter-box form", root)));
  $("#scan-count", root).textContent = `${rows.length} of ${allRows.length} shown`;
  box.innerHTML = "";
  box.appendChild(table(COLUMNS, rows, {
    empty: allRows.length ? "No stock matches these filters." : "No results yet — start a scan.",
    initialSort: { key: "margin_of_safety", desc: true },
    onRow: (r) => { location.hash = `#/analysis/${r.symbol}`; },
  }));
}

const COLUMNS = [
  { key: "symbol", label: "Ticker", render: (r) => `<b>${esc(r.symbol)}</b>${r.pinned ? ` <span class="badge na" title="${esc(r.pinned)}">judged</span>` : ""}<div class="small muted">${esc(r.name || "")}</div>` },
  { key: "sector", label: "Sector" },
  { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
  { key: "intrinsic_value", label: "IV", cls: "num", render: (r) => `${fmt.money(r.intrinsic_value)}${r.iv_low_confidence ? ` <span class="badge na" title="${esc(r.iv_note)}">⚠ low confidence</span>` : ""}` },
  { key: "margin_of_safety", label: "MOS", cls: "num", render: (r) => `<span class="${signClass(r.margin_of_safety)}">${fmt.pct(r.margin_of_safety)}</span>` },
  { key: "growth", label: "Growth", cls: "num", render: (r) => fmt.pct(r.growth) },
  { key: "roe", label: "ROE", cls: "num", render: (r) => fmt.pct(r.roe) },
  { key: "roic", label: "ROIC", cls: "num", render: (r) => fmt.pct(r.roic) },
  { key: "net_margin", label: "Net margin", cls: "num", render: (r) => fmt.pct(r.net_margin) },
  { key: "peg", label: "PEG", cls: "num", render: (r) => fmt.num(r.peg) },
  { key: "market_cap", label: "Mkt cap", cls: "num", render: (r) => fmt.big(r.market_cap) },
  { key: "method", label: "Method" },
  { key: "moat", label: "Moat", render: (r) => `${esc(r.moat ?? "")}${r.moat_reviewed ? "" : " ?"}` },
  { key: "style", label: "Style" },
  { key: "steps_passed", label: "Steps", cls: "num", render: (r) => `${r.steps_passed}/7` },
  { key: "trend", label: "Trend" },
  { key: "vmi_pass", label: "Buy?", render: (r) => badge(r.vmi_pass, "BUY", "—") },
];

async function showDropped(root) {
  const d = await api.scanDropped();
  const entries = Object.entries(d.dropped || d || {});
  const counts = {};
  entries.forEach(([, why]) => { const k = String(why).split(":")[0]; counts[k] = (counts[k] || 0) + 1; });
  const { modal } = await import("../ui.js");
  modal("Dropped candidates", `<p>${Object.entries(counts).map(([k, n]) => `<b>${esc(k)}</b>: ${n}`).join(" · ")}</p>
    <table class="compact"><tbody>${entries.slice(0, 1000).map(([s, w]) => `<tr><td><a href="#/analysis/${esc(s)}">${esc(s)}</a></td><td class="small">${esc(w)}</td></tr>`).join("")}</tbody></table>`);
}
