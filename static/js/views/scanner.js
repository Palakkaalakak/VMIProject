// Superscanner view: start a funnel run (broad/cheap filters first), live funnel progress, sortable results.
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, run, table, toast, signClass } from "../ui.js";
import { ruleGroups } from "../rule_fields.js";
import { addIndustryStats, applyFilters, filterPanel, loadSaved, readFilters, save, setForm } from "./scanner_filters.js";

let poll = null;

const OPEN = ["track", "profitability", "debt"];
let presetData = null;

/** Rule values a preset starts from: course defaults when the preset says so, else the Settings page, plus its own rules. */
function baseRules(preset) {
  const base = {};
  for (const r of presetData.schema) (base[r.section] ||= {})[r.key] = preset.course_defaults ? r.default : r.value;
  for (const [sec, vals] of Object.entries(preset.rules || {})) Object.assign(base[sec] ||= {}, vals);
  return base;
}

function drawPreset(root, id) {
  const preset = presetData.presets[id];
  const pm = preset.params || {};
  const f = $("#scan-form", root);
  $("#scan-preset-note", root).textContent = preset.note;
  const set = (name, v) => { if (v !== undefined) { const el = f.elements[name]; el.type === "checkbox" ? (el.checked = !!v) : (el.value = v); } };
  set("min_market_cap", pm.min_market_cap !== undefined ? pm.min_market_cap / 1e9 : 2);
  set("require_ten_year_uptrend", pm.require_ten_year_uptrend ?? true);
  set("include_speculative", pm.include_speculative ?? true);
  set("require_steps", !!(pm.require_steps && pm.require_steps.length));
  $("#scan-rules", root).innerHTML = ruleGroups(presetData.schema, baseRules(preset), OPEN);
  root._base = baseRules(preset);
}

export async function render(root) {
  root.innerHTML = `
    <section class="card">
      <h3>Superscanner</h3>
      <form id="scan-form" class="grid">
        <label>Preset <select name="preset" id="scan-preset"></select></label>
        <p class="small muted wide" style="grid-column:1/-1" id="scan-preset-note"></p>
        <label>Universe <select name="universe"><option value="sp500">S&amp;P 500</option><option value="us">Full US market</option><option value="list">Custom list</option></select></label>
        <label class="wide">Symbols (custom list) <input name="symbols" placeholder="AAPL, MSFT, AZO …"></label>
        <label>Min market cap ($B) <input name="min_market_cap" type="number" step="0.5" value="2"></label>
        <label>Min price <input name="min_price" type="number" step="1" value="5"></label>
        <label>10y chart: min total return <input name="ten_year_min_return" type="number" step="0.1" value="0.5"></label>
        <label>Deep-analysis limit <input name="deep_limit" type="number" value="400"></label>
        <label class="check"><input type="checkbox" name="require_ten_year_uptrend" checked> require 10y uptrend</label>
        <label class="check"><input type="checkbox" name="require_steps"> drop stocks failing steps 1, 2, 4, 5 (the checks the scan can verify from data)</label>
        <label class="check"><input type="checkbox" name="include_speculative" checked> keep speculative growth (50%+ revenue growth)</label>
        <details class="wide" style="grid-column:1/-1"><summary><b>Every rule for this scan</b> <span class="muted small">(edit any; applies to this scan only, nothing is saved to Settings; changed values are sent as overrides)</span></summary>
          <div id="scan-rules"></div></details>
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
  const sel = $("#scan-preset", root);
  sel.innerHTML = Object.entries(presetData.presets).map(([k, p]) => `<option value="${k}">${esc(p.label)}</option>`).join("");
  sel.addEventListener("change", () => drawPreset(root, sel.value));
  drawPreset(root, sel.value);
  $("#scan-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const rules = {};                      // only what differs from the preset's starting values
    for (const r of presetData.schema) {
      const el = e.target.elements[`${r.section}.${r.key}`];
      if (!el) continue;
      const was = root._base[r.section]?.[r.key];
      const now = r.type === "bool" ? el.value === "true" : el.value;
      const same = r.type === "bool" ? now === was : r.type === "int" || r.type === "float" ? Number(now) === Number(was) : String(now) === (Array.isArray(was) ? JSON.stringify(was) : String(was));
      if (!same) (rules[r.section] ||= {})[r.key] = now;
    }
    const body = {
      preset: f.get("preset"), rules,
      universe: f.get("universe"),
      symbols: String(f.get("symbols") || "").split(/[\s,;]+/).filter(Boolean).map((s) => s.toUpperCase()),
      min_market_cap: parseFloat(f.get("min_market_cap")) * 1e9,
      min_price: parseFloat(f.get("min_price")),
      ten_year_min_return: parseFloat(f.get("ten_year_min_return")),
      deep_limit: parseInt(f.get("deep_limit"), 10),
      require_ten_year_uptrend: f.get("require_ten_year_uptrend") === "on",
      include_speculative: f.get("include_speculative") === "on",
      require_steps: f.get("require_steps") === "on" ? [1, 2, 4, 5] : [],
    };
    run(e.submitter, async () => { await api.scanStart(body); toast(`Scan started (${presetData.presets[body.preset].label}${Object.keys(rules).length ? ", with your rule edits" : ""})`, "ok"); startPolling(root); });
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
