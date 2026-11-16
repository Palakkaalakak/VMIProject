// Superscanner view: start a funnel run (broad/cheap filters first), live funnel progress, sortable results.
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, run, table, toast, signClass } from "../ui.js";
import { badgeFor, ruleInput } from "../rule_fields.js";
import { addIndustryStats, applyFilters, filterPanel, loadSaved, readFilters, save, setForm } from "./scanner_filters.js";

let poll = null;

let presetData = null;
let added = {};          // key -> {def, el}: filters the owner chose to set (everything else uses the preset's values)

/** Scan options (not rules). `value(preset)` = the preset's default shown when the filter is added. */
const SCAN_OPTIONS = {
  "scan.min_market_cap": { label: "Min market cap ($B)", help: "Full-market scan only (S&P 500 and custom lists ignore it)", type: "float", param: "min_market_cap",
    value: (p) => (p.params.min_market_cap ?? 2e9) / 1e9, send: (v) => parseFloat(v) * 1e9 },
  "scan.min_price": { label: "Min price", help: "Full-market scan only", type: "float", param: "min_price", value: () => 5, send: parseFloat },
  "scan.ten_year_min_return": { label: "10-year chart: min total return", help: "0.5 = +50% over ten years (and an upward trend)", type: "float", param: "ten_year_min_return", value: () => 0.5, send: parseFloat },
  "scan.require_ten_year_uptrend": { label: "Require 10-year uptrend", help: "Adam's long-term chart filter", type: "bool", param: "require_ten_year_uptrend", value: (p) => p.params.require_ten_year_uptrend ?? true, send: (v) => v === "true" },
  "scan.include_speculative": { label: "Keep speculative growth (50%+ revenue growth)", help: "Young companies whose profits are not consistent yet", type: "bool", param: "include_speculative", value: (p) => p.params.include_speculative ?? true, send: (v) => v === "true" },
  "scan.require_steps": { label: "Drop stocks failing steps 1, 2, 4, 5", help: "The steps the scan can verify 100% from data", type: "bool", param: "require_steps", value: (p) => !!(p.params.require_steps || []).length, send: (v) => (v === "true" ? [1, 2, 4, 5] : []) },
  "scan.deep_limit": { label: "Deep-analysis limit", help: "Safety cap on how many stocks get the full analysis", type: "int", param: "deep_limit", value: () => 400, send: (v) => parseInt(v, 10) },
};

/** Rule values a preset starts from: course defaults when the preset says so, else the Settings page, plus its own rules. */
function baseRules(preset) {
  const base = {};
  for (const r of presetData.schema) (base[r.section] ||= {})[r.key] = preset.course_defaults ? r.default : r.value;
  for (const [sec, vals] of Object.entries(preset.rules || {})) Object.assign(base[sec] ||= {}, vals);
  return base;
}

const defOf = (key, preset) => {
  if (SCAN_OPTIONS[key]) return SCAN_OPTIONS[key].value(preset);
  const [sec, k] = key.split(".");
  return baseRules(preset)[sec]?.[k];
};

function input(key, value) {
  const o = SCAN_OPTIONS[key];
  const name = `name="${esc(key)}"`;
  if (o) {
    if (o.type === "bool") return `<select ${name}><option value="true" ${value ? "selected" : ""}>yes</option><option value="false" ${value ? "" : "selected"}>no</option></select>`;
    return `<input ${name} type="number" step="any" value="${esc(value)}">`;
  }
  return ruleInput(presetData.schema.find((r) => `${r.section}.${r.key}` === key), value);
}

function drawAdded(root) {
  const preset = presetData.presets[$("#scan-preset", root).value];
  const box = $("#scan-added", root);
  const keys = Object.keys(added);
  box.innerHTML = keys.length ? `<table class="compact"><tbody>${keys.map((k) => {
    const o = SCAN_OPTIONS[k], r = o ? null : presetData.schema.find((x) => `${x.section}.${x.key}` === k);
    const cur = added[k].touched ? added[k].value : defOf(k, preset);
    return `<tr data-key="${esc(k)}"><td><b>${esc(o ? o.label : k)}</b> ${r ? badgeFor(r) : ""}<div class="small muted">${esc(o ? o.help : r.help || r.source_note)}</div></td>
      <td>${input(k, cur)}</td><td class="small muted">preset: ${esc(String(defOf(k, preset)))}</td><td><button type="button" class="small danger" data-remove="${esc(k)}" title="Back to the preset's value">✕</button></td></tr>`;
  }).join("")}</tbody></table>` : `<p class="small muted">No filters added: this scan uses the preset's values.</p>`;
  box.querySelectorAll("[name]").forEach((el) => el.addEventListener("input", () => { added[el.name].touched = true; added[el.name].value = el.type === "checkbox" ? el.checked : el.value; }));
  box.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => { delete added[b.dataset.remove]; drawAdded(root); }));
}

function drawPreset(root, id, apply = false) {
  const preset = presetData.presets[id];
  $("#scan-preset-note", root).textContent = preset.note;
  if (apply) {            // the preset's results filters (growth profile, yield, category ...) replace the saved ones
    save(preset.filters || {});
    const form = $("#scan-filter-box form", root);
    if (form) { setForm(form, preset.filters || {}); drawRows(root); }
  }
  drawAdded(root);          // untouched rows follow the new preset's defaults
}

function pickerOptions() {
  const ruleOpts = presetData.schema.map((r) => `<option value="${esc(r.section)}.${esc(r.key)}" label="${esc((r.help || r.source_note || "").slice(0, 110))}"></option>`);
  const scanOpts = Object.entries(SCAN_OPTIONS).map(([k, o]) => `<option value="${esc(k)}" label="${esc(o.label)}"></option>`);
  return scanOpts.join("") + ruleOpts.join("");
}

export async function render(root) {
  root.innerHTML = `
    <section class="card">
      <h3>Superscanner</h3>
      <form id="scan-form" class="grid">
        <label>Preset <select name="preset" id="scan-preset"></select></label>
        <label>Universe <select name="universe"><option value="sp500">S&amp;P 500</option><option value="us">Full US market</option><option value="list">Custom list</option></select></label>
        <label class="wide">Symbols (custom list) <input name="symbols" placeholder="AAPL, MSFT, AZO …"></label>
        <p class="small muted wide" style="grid-column:1/-1" id="scan-preset-note"></p>
        <div class="wide" style="grid-column:1/-1">
          <label>Add a filter (type to search every scan option and every rule, e.g. roic, current ratio, margin)
            <input id="scan-pick" list="scan-pick-list" placeholder="search filters…" autocomplete="off" style="width:min(32rem,100%)"></label>
          <datalist id="scan-pick-list"></datalist>
          <div id="scan-added"></div>
        </div>
        <button class="primary">Start scan</button>
      </form>
    </section>
    <section id="scan-status" class="card"></section>
    <section class="card">
      <div class="toolbar inline">
        <h3>Results</h3>
        <button id="scan-dropped" class="secondary">Why dropped?</button>
        <button id="scan-save" class="secondary">Save shown list as a watchlist</button>
        <span class="spacer"></span>
        <label class="small">Add to review queue of <select id="scan-review-wl"></select></label>
      </div>
      <div id="scan-filter-box"></div>
      <div id="scan-results">${loading()}</div>
    </section>`;
  presetData = await api.scanPresets();
  added = {};
  const sel = $("#scan-preset", root);
  sel.innerHTML = Object.entries(presetData.presets).map(([k, p]) => `<option value="${k}">${esc(p.label)}</option>`).join("");
  $("#scan-pick-list", root).innerHTML = pickerOptions();
  sel.addEventListener("change", () => drawPreset(root, sel.value, true));
  $("#scan-pick", root).addEventListener("change", (e) => {
    const key = e.target.value.trim();
    const known = SCAN_OPTIONS[key] || presetData.schema.some((r) => `${r.section}.${r.key}` === key);
    if (!known) { if (key) toast(`No filter called “${key}”: pick one from the list`, "error"); return; }
    added[key] ||= { touched: false, value: null };
    e.target.value = "";
    drawAdded(root);
  });
  drawPreset(root, sel.value);
  $("#scan-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const preset = presetData.presets[f.get("preset")];
    const body = { preset: f.get("preset"), universe: f.get("universe"), rules: {},
      symbols: String(f.get("symbols") || "").split(/[\s,;]+/).filter(Boolean).map((s) => s.toUpperCase()) };
    for (const key of Object.keys(added)) {                       // only the filters the owner added; the rest = preset values
      const el = e.target.elements[key];
      if (!el) continue;
      if (SCAN_OPTIONS[key]) body[SCAN_OPTIONS[key].param] = SCAN_OPTIONS[key].send(el.value);
      else { const [sec, k] = key.split("."); (body.rules[sec] ||= {})[k] = el.value; }
    }
    const n = Object.keys(added).length;
    run(e.submitter, async () => { await api.scanStart(body); toast(`Scan started (${preset.label}${n ? `, ${n} filter${n > 1 ? "s" : ""} set by you` : ""})`, "ok"); startPolling(root); });
  });
  $("#scan-save", root).addEventListener("click", (e) => run(e.target, async () => {
    const rows = applyFilters(allRows, readFilters($("#scan-filter-box form", root)));
    if (!rows.length) return toast("Nothing is shown", "error");
    const name = prompt(`Watchlist name (${rows.length} stocks currently shown; all scan results stay saved)`, "Scan " + new Date().toISOString().slice(0, 10));
    if (!name) return;
    const w = await api.createWatchlist(name);
    await api.importList(w.id, rows.map((r) => r.symbol).join(", "), false);
    toast(`Saved ${rows.length} stocks to “${name}”`, "ok");
  }));
  $("#scan-dropped", root).addEventListener("click", (e) => run(e.target, () => showDropped(root)));
  startPolling(root);
  loadResults(root);
  fillReviewTargets(root);
}

async function fillReviewTargets(root) {
  const sel = $("#scan-review-wl", root);
  const lists = await api.watchlists().catch(() => []);
  let want = null;
  try { want = localStorage.getItem("vmi.scanner.reviewWl"); } catch { /* private window */ }
  sel.innerHTML = lists.length ? lists.map((w) => `<option value="${w.id}" ${String(w.id) === want ? "selected" : ""}>${esc(w.name)}</option>`).join("") : `<option value="">(create a watchlist first)</option>`;
  sel.addEventListener("change", () => { try { localStorage.setItem("vmi.scanner.reviewWl", sel.value); } catch { /* ignore */ } });
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
    allRows = addIndustryStats((await api.scanResults({})).results || []);
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
    actions: { review: (r, b) => addToReview(root, r, b) },
  }));
}

function addToReview(root, r, btn) {
  const wid = $("#scan-review-wl", root).value;
  if (!wid) return toast("Pick a watchlist first (corner of the results)", "error");
  const note = `scanner ${r.steps_passed}/7${r.great_business ? "" : ", not a great business yet"}; growth ${fmt.pct(r.growth_low ?? r.growth, 0)}-${fmt.pct(r.growth_high ?? r.growth, 0)}; ${r.industry || r.sector || ""} (${new Date().toISOString().slice(0, 10)})`;
  run(btn, async () => {
    const res = await api.addReview(wid, r.symbol, note);
    const name = $("#scan-review-wl", root).selectedOptions[0].textContent;
    toast(res.already ? `${r.symbol} is already in “${name}” (${res.already})` : `${r.symbol} added to the review queue of “${name}”`, res.already ? "info" : "ok");
  });
}

const COLUMNS = [
  { key: "symbol", label: "Ticker", render: (r) => `<b>${esc(r.symbol)}</b>${r.pinned ? ` <span class="badge na" title="${esc(r.pinned)}">judged</span>` : ""}<div class="small muted">${esc(r.name || "")}</div>` },
  { key: "sector", label: "Sector" },
  { key: "industry", label: "Industry", render: (r) => `${esc(r.industry || "")}<div class="small muted">#${r.industry_rank ?? "—"} of ${r.industry_n ?? "—"} · ${fmt.pct(r.industry_share, 0)} of its cap</div>` },
  { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
  { key: "intrinsic_value", label: "IV", cls: "num", render: (r) => `${fmt.money(r.intrinsic_value)}${r.iv_low_confidence ? ` <span class="badge na" title="${esc(r.iv_note)}">IV may be high</span>` : ""}` },
  { key: "margin_of_safety", label: "MOS", cls: "num", render: (r) => `<span class="${signClass(r.margin_of_safety)}">${fmt.pct(r.margin_of_safety)}</span>` },
  { key: "growth", label: "Growth (low / avg / high)", cls: "num", render: (r) => `${fmt.pct(r.growth)}<div class="small muted" title="${esc(Object.entries(r.growth_sources || {}).map(([k, v]) => `${k} ${fmt.pct(v)}`).join(", "))}">${r.growth_low != null ? `${fmt.pct(r.growth_low, 0)} / ${fmt.pct(r.growth_avg, 0)} / ${fmt.pct(r.growth_high, 0)}` : ""}</div>` },
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
  { key: "_review", label: "", render: () => `<button class="small secondary" data-action="review" title="Add to the review queue of the chosen watchlist">+ Review</button>` },
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
