// Analysis view: full 7-step VMI report for one ticker + valuation methods, technical buy levels,
// judgement overrides and one-click paper trading (tranche sizing).
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, run, toast, signClass } from "../ui.js";
import { sizeSelect } from "../sizes.js";
import { stepsCard } from "../steps_view.js";
import { state } from "../state.js";
import { mountChart } from "../chart_view.js";

let SCHEMA = null; // override fields, from GET /api/overrides/schema (declared once in vmi/overrides.py)

/** personality = {"daily sma50": bounces, …}: show the moving average the stock respects most. */
function personality(p) {
  const best = Object.entries(p || {}).sort((a, b) => b[1] - a[1])[0];
  return best ? `${best[0]} (${best[1]} bounces)` : "—";
}

export function render(root, params = {}) {
  root.innerHTML = `
    <section class="toolbar">
      <form id="analysis-form" class="inline">
        <input id="analysis-symbol" placeholder="Ticker (e.g. MSFT)" value="${esc(params.symbol || "")}" autocomplete="off" required>
        <label class="check"><input type="checkbox" id="analysis-tech" checked> technicals</label>
        <label class="check" title="Judge this stock on a 10-year record only (instead of allowing 5 or 10). Only this analysis; Settings are untouched."><input type="checkbox" id="analysis-ten"> 10-year record only</label>
        <label class="check" title="Use multi-year averages (see Settings → Normalise for the years) for this stock only, even if Settings has it off"><input type="checkbox" id="analysis-norm"> normalised (this stock)</label>
        <button class="primary">Analyse</button>
      </form>
    </section>
    <div id="analysis-out"></div>`;
  $("#analysis-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const s = $("#analysis-symbol", root).value.trim().toUpperCase();
    if (s) location.hash = `#/analysis/${s}`;
  });
  if (params.symbol) {
    const m = loadMode(params.symbol.toUpperCase());       // the two switches are remembered per stock in this browser
    $("#analysis-ten", root).checked = m.ten_year_only;
    $("#analysis-norm", root).checked = m.normalise === true;
    load(root, params.symbol.toUpperCase());
  }
  for (const id of ["analysis-ten", "analysis-norm"]) {
    $(`#${id}`, root).addEventListener("change", () => {
      const s = $("#analysis-symbol", root).value.trim().toUpperCase();
      if (!s) return;
      saveMode(s, readMode(root));
      load(root, s);
    });
  }
}

const MODE_KEY = (s) => `vmi.analysis.mode.${s}`;
const loadMode = (s) => { try { return { ten_year_only: false, normalise: null, ...JSON.parse(localStorage.getItem(MODE_KEY(s)) || "{}") }; } catch { return { ten_year_only: false, normalise: null }; } };
const saveMode = (s, m) => { try { localStorage.setItem(MODE_KEY(s), JSON.stringify(m)); } catch { /* private window */ } };
/** normalise is sent only when ticked (null = whatever Settings says), so an unticked box never switches Settings' normalise off. */
const readMode = (root) => ({ ten_year_only: $("#analysis-ten", root).checked, normalise: $("#analysis-norm", root).checked ? true : null });

async function load(root, symbol) {
  const out = $("#analysis-out", root);
  out.innerHTML = loading(`Analysing ${symbol} (fundamentals, estimates, 10y chart)…`);
  try {
    const mode = readMode(root);
    const r = await api.analyse(symbol, $("#analysis-tech", root).checked, { ten_year_only: mode.ten_year_only, normalise: mode.normalise ?? undefined });
    out.innerHTML = view(r);
    bind(out, r);
  } catch (e) {
    out.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
  }
}

const verdict = (r) => [
  ["Great business", r.great_business], ["Moat reviewed", r.moat_reviewed], ["Undervalued", r.undervalued],
  ["Entry signal", r.entry_ok], ["VMI buy", r.vmi_pass],
].map(([l, v]) => `<div class="kpi"><span>${l}</span>${badge(v, "YES", "NO")}</div>`).join("");

function header(r) {
  const v = r.valuation || {};
  return `<div class="card head">
    <div><h2>${esc(r.ticker)} <small>${esc(r.name || "")}</small></h2>
      <p class="muted">${esc(r.sector || "")} · ${esc(r.industry || "")} · type <b>${esc(r.biz_type)}</b> · ${esc(r.category || "")} · ${esc(r.style || "")} · moat <b>${esc(r.moat)}</b>${r.moat_reviewed ? "" : ' <span class="muted">(unreviewed)</span>'} · <a href="#/settings" class="small" title="Settings → normalise">normalise: ${r.normalised?.enabled ? `<b>ON (${r.normalised.years}y)</b>` : "off"}</a> · ROE, ROIC and margins judged on the <b>${esc(r.metrics?.basis?.label || "latest fiscal year")}</b>${r.mode?.ten_year_only ? ' · <b class="badge na" title="Track record judged on a 10-year record only">10-YEAR ONLY</b>' : ""}</p></div>
    <div class="kpis">
      <div class="kpi"><span>Price</span><b>${fmt.money(r.price)}</b></div>
      <div class="kpi"><span>Intrinsic value</span><b>${fmt.money(r.intrinsic_value)}</b></div>
      <div class="kpi"><span>Margin of safety</span><b class="${signClass(v.margin_of_safety)}">${fmt.pct(v.margin_of_safety)}</b></div>
      <div class="kpi"><span>Conservative</span><b>${fmt.money(v.conservative_value)}</b></div>
      ${verdict(r)}
    </div>
    ${r.normalised?.enabled ? `<p class="note"><b>(NORMALISED)</b> Steps 1, 4 and 5 use the average of the last ${r.normalised.years} fiscal years instead of the latest year (Settings → normalise). Margins, ROE, ROIC, current ratio, debt/EBITDA, debt servicing and interest coverage below are averages.</p>` : ""}
    ${(r.overrides_applied || []).length ? `<p class="note">Judgement overrides (${esc(r.overrides.source || "")}): ${esc(r.overrides_applied.join(" · "))}${r.overrides.note ? ` — ${esc(r.overrides.note)}` : ""}</p>` : ""}
  </div>`;
}

const steps = (r) => stepsCard(r, moatChecklist);

/** Step 3 summary + the button to the dedicated Moat evaluation page (views/moat.js), opened in its own tab. */
function moatChecklist(x, ticker) {
  const v = x.verdict, due = x.review?.due;
  return `<div class="moat-review"><p><b>Moat review</b> — ${v ? `verdict <b>${esc(v.grade)}</b>${v.score != null ? ` · score ${esc(v.score)}/10` : ""}${x.review?.reviewed_on ? ` · reviewed ${esc(x.review.reviewed_on)}` : ""}`
    : "not reviewed yet (provisional result from Adam's two shortcuts only)"}</p>
    ${due ? `<p class="note"><b>Moat review due:</b> ${esc(x.review.reasons.join("; "))}</p>` : ""}
    <a class="button" href="#/moat/${esc(ticker)}" target="_blank" rel="noopener">Open Moat evaluation ↗</a></div>`;
}

function valuation(r) {
  const v = r.valuation || {};
  const rows = Object.values(v.methods || {}).map((m) => `<tr class="${m.method === v.selected ? "selected" : ""}">
    <td>${m.method === v.selected ? "★ " : ""}${esc(m.label)}</td><td>${fmt.money(m.intrinsic_value)}</td>
    <td>${badge(m.applicable, "OK", "caveat")}</td><td class="small muted">${esc((m.reasons || []).join("; "))}</td></tr>`).join("");
  const sel = (v.methods || {})[v.selected] || {};
  const inp = sel.inputs || {};
  const scen = (sel.scenarios || []).map((s) => `<tr><td>${esc(s.name)}</td><td>${fmt.money(s.value)}</td>
    <td>${s.growth ? `${fmt.pct(s.growth.g1_5)} / ${fmt.pct(s.growth.g6_10)} / ${fmt.pct(s.growth.g11_20)}` : ""}</td><td class="small muted">${esc(s.note || "")}</td></tr>`).join("");
  return `<div class="card"><h3>Valuation — ${esc(sel.label || v.selected || "none")}</h3>
    <p class="muted small">${esc(v.selection_reason || "")}</p>
    ${(r.iv_confidence?.reasons || []).map((n) => `<p class="note"><b>Low confidence:</b> ${esc(n)}</p>`).join("")}
    ${(inp.growth_notes || []).filter((n) => n.includes("CAPPED")).map((n) => `<p class="note"><b>${esc(n)}</b> The cap can be switched off in Settings (growth.cap_years_1_5).</p>`).join("")}
    ${inp.base_cash_flow != null ? `<p class="small">Base: <b>${fmt.big(inp.base_cash_flow)}</b> (${esc(inp.base_desc)}) · debt ${fmt.big(inp.debt)} · cash ${fmt.big(inp.cash)} · shares ${fmt.big(inp.shares)} · β ${fmt.num(inp.beta)} → rate ${fmt.pct(inp.discount_rate)} · IV haircut ${fmt.pct(inp.iv_haircut, 0)}${inp.statement_currency && inp.statement_currency !== "USD" ? ` · ${esc(inp.statement_currency)}→USD ${fmt.num(inp.fx, 4)}` : ""}</p>` : ""}
    ${scen ? `<table class="compact"><thead><tr><th>Scenario</th><th>IV</th><th>growth 1–5 / 6–10 / 11–20</th><th></th></tr></thead><tbody>${scen}</tbody></table>` : ""}
    <details><summary>All methods</summary><table class="compact"><tbody>${rows}</tbody></table></details>
    ${(v.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
  </div>`;
}

function volatility(r) {
  const v = r.volatility;
  if (!v) return "";
  const pct = (x) => (x == null ? "—" : (x * 100).toFixed(1) + "%");
  return `<div class="card"><h3>Volatility <span class="muted small">defensive or growth?</span></h3>
    <div class="kpis"><div class="kpi" title="Standard deviation of daily returns, annualised, over the whole history (about ${v.years} years)"><span>average volatility / yr</span><b>${pct(v.annual_vol)}</b></div>
      <div class="kpi"><span>last 12 months</span><b>${pct(v.annual_vol_1y)}</b></div>
      <div class="kpi"><span>worst drawdown</span><b>${pct(v.max_drawdown)}</b></div>
      <div class="kpi" title="Average size of a calendar month's move, up or down"><span>typical monthly move</span><b>${pct(v.avg_monthly_move)}</b></div>
      <div class="kpi"><span>beta</span><b>${v.beta == null ? "—" : v.beta.toFixed(2)}</b></div>
      <div class="kpi"><span>profile</span><b>${esc(v.label)}</b></div></div>
    <p class="small muted">Owner extra, not from Adam. Under 22% a year reads as defensive, 22-35% moderate, 35% and over growth-like. For comparison, the S&amp;P 500 is usually about 15-20%.</p></div>`;
}

function technicals(r) {
  const t = r.technicals;
  if (!t) return "";
  const lv = (t.buy_levels || []).map((b) => `<tr><td>T${b.tranche}</td><td>${fmt.money(b.price)}</td><td>${esc(b.source)}</td>
    <td>${b.touches ?? ""}</td><td>${badge(b.confirmed, "confirmed", "unconfirmed")}</td></tr>`).join("");
  const tf = ["daily", "weekly", "monthly"].map((k) => `<div class="kpi"><span>${k}</span><b>${esc(t[k]?.state || "—")}</b></div>`).join("");
  return `<div class="card"><h3>Technicals</h3>
    <div class="kpis">${tf}<div class="kpi"><span>10y uptrend</span>${badge(t.ten_year_uptrend, "YES", "NO")}</div>
      <div class="kpi" title="The moving average this stock bounces off most often (Lesson 6)"><span>Personality</span><b>${esc(personality(t.personality))}</b></div></div>
    <p class="small">${esc(t.scenario || "")} — ${esc(t.entry_reason || "")}</p>
    <table class="compact"><thead><tr><th>Tranche</th><th>Buy level</th><th>Source</th><th>Touches</th><th></th></tr></thead><tbody>${lv || `<tr><td colspan="5" class="muted">no levels</td></tr>`}</tbody></table>
    <p class="inline"><button type="button" class="small secondary" id="an-open-chart">Open chart</button>
      <label class="small">draw the supports of watchlist <select id="an-wl"><option value="">(the analysis buy levels)</option></select></label></p>
    <details id="an-chart-box"><summary><b>Chart</b> <span class="muted small">candles, Adam's moving averages, Bollinger, drawing, any timeframe</span></summary><div id="an-chart"></div></details>
  </div>`;
}

function trade(r) {
  const opts = state.portfolios.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  return `<div class="card"><h3>Paper trade</h3>
    <form id="trade-form" class="inline">
      <select id="trade-pf">${opts}</select>
      <select id="trade-side"><option>BUY</option><option>SELL</option></select>
      <label class="small" title="How you are entering: on the touch of the support, after it confirmed, or for another reason. Feeds the 'wait or buy?' evidence on the Alerts page.">Entry
        <select id="trade-entry"><option value="">choose…</option><option value="on_touch">on touch</option><option value="confirmed">confirmed</option><option value="special">special</option></select></label>
      <label class="check"><input type="checkbox" id="trade-tranche" checked> one VMI tranche (auto-size)</label>
      <label class="small">Position size ${sizeSelect("trade-mult", null, { auto: `automatic (category: ×${r.allocation_multiplier ?? 1})`, id: "trade-mult" })}</label>
      <input id="trade-qty" type="number" step="any" min="0" placeholder="or qty">
      <button class="primary">Submit (paper)</button>
    </form>
    <div id="trade-size" class="small muted"></div>
  </div>`;
}

function overrides() {
  return `<div class="card"><h3>Judgement overrides</h3>
    <p class="small muted">For distorted data or human nuance. Stored per ticker with a reason; the general formula never
      changes. Empty field = automatic. Same keys via CLI: <code>python -m vmi.overrides schema</code>.</p>
    <div id="ov-body">${loading()}</div></div>`;
}

let REPORT = null;     // the analysis being shown (its growth sources fill the "Use one source" dropdown)
function growthSourceSelect(name, v) {
  const known = (SCHEMA.find((x) => x.key === "exclude_sources") || {}).choices || [];
  const seen = (REPORT && REPORT.metrics && REPORT.metrics.growth_sources && REPORT.metrics.growth_sources.sources) || {};
  const extra = Object.keys((REPORT && REPORT.overrides && REPORT.overrides.extra_sources) || {});
  const names = [...new Set([...known, ...Object.keys(seen), ...extra, ...(v ? [v] : [])])];
  const pct = (k) => (typeof seen[k] === "number" ? ` (${(seen[k] * 100).toFixed(1)}%)` : "");
  return `<select ${name}><option value="">auto (blend of all sources)</option>${names.map((c) => `<option value="${esc(c)}" ${v === c ? "selected" : ""}>${esc(c)}${pct(c)}</option>`).join("")}</select>`;
}

function fieldInput(f, v) {
  const name = `name="${f.key}"`;
  if (f.key === "growth_source") return growthSourceSelect(name, v);
  if (f.kind === "choice") {
    return `<select ${name}>${f.choices.map((c) => `<option value="${esc(c)}" ${(v ?? "") === c ? "selected" : ""}>${esc(c || "auto")}</option>`).join("")}</select>`;
  }
  if (f.kind === "list_choice") {
    return `<span class="checks">${f.choices.map((c) => `<label class="check"><input type="checkbox" ${name} value="${esc(c)}" ${(v || []).includes(c) ? "checked" : ""}>${esc(c)}</label>`).join("")}</span>`;
  }
  if (f.kind === "json") return `<textarea ${name} rows="2" placeholder='{"sources": [...], "grade": "wide"}'>${v ? esc(JSON.stringify(v)) : ""}</textarea>`;
  if (f.kind === "list_text") return `<input ${name} value="${esc((v || []).join(", "))}" placeholder="MSFT, ORCL, SAP">`;
  if (f.kind === "list_number") return `<input ${name} value="${esc((v || []).join(", "))}" placeholder="405, 385, 363">`;
  if (f.kind === "dict_percent") return `<input ${name} value="${esc(Object.entries(v || {}).map(([k, x]) => `${k}=${x}`).join(", "))}" placeholder="factset=0.15, stockoracle=0.17">`;
  if (f.kind === "text") return `<input ${name} value="${esc(v ?? "")}" placeholder="auto">`;
  return `<input ${name} type="number" step="any" value="${v ?? ""}" placeholder="${f.kind === "percent" ? "0.13 = 13%" : "auto"}">`;
}

function overridesForm(o) {
  const groups = [...new Set(SCHEMA.map((f) => f.group))];
  const set = (f) => o[f.key] !== undefined && o[f.key] !== null && o[f.key] !== "";
  const body = groups.map((g) => {
    const fs = SCHEMA.filter((f) => f.group === g);
    const open = g === "Growth" || fs.some(set) ? "open" : "";
    return `<details ${open}><summary>${esc(g)}${fs.some(set) ? ` <span class="badge">${fs.filter(set).length} set</span>` : ""}</summary>
      <div class="grid">${fs.map((f) => `<label title="${esc(f.help)}" class="${["json", "list_choice", "dict_percent"].includes(f.kind) ? "wide" : ""}">${esc(f.label)}${fieldInput(f, o[f.key])}</label>`).join("")}</div></details>`;
  }).join("");
  return `<form id="ov-form">${body}
    <label class="wide">Reason (always write why)<input name="note" value="${esc(o.note ?? "")}"></label>
    <div class="inline">
      <label class="check"><input type="checkbox" name="commit"> save to committed judgements (config/judgements.json)</label>
      <button class="secondary">Save</button><button type="button" id="ov-clear" class="danger">Clear all</button>
    </div></form>`;
}

function readOverrides(form) {
  const data = {};
  for (const f of SCHEMA) {
    if (f.kind === "list_choice") {
      data[f.key] = [...form.querySelectorAll(`[name="${f.key}"]:checked`)].map((x) => x.value);
      continue;
    }
    const raw = form.elements[f.key]?.value?.trim() ?? "";
    data[f.key] = raw === "" ? null : f.kind === "json" ? JSON.parse(raw) : f.kind === "number" || f.kind === "percent" ? parseFloat(raw) : raw;
  }
  return { data, note: form.elements.note.value, commit: form.elements.commit.checked };
}

async function bindOverrides(out, r) {
  const box = $("#ov-body", out);
  if (!box) return;
  SCHEMA ||= await api.overrideSchema();
  REPORT = r;
  box.innerHTML = overridesForm(r.overrides || {});
  const reanalyse = () => { location.hash = `#/analysis/${r.ticker}?t=${Date.now()}`; };
  $("#ov-form", box).addEventListener("submit", (e) => {
    e.preventDefault();
    run(e.submitter, async () => { await api.setOverride(r.ticker, readOverrides(e.target)); toast("Overrides saved — re-analysing", "ok"); reanalyse(); });
  });
  $("#ov-clear", box).addEventListener("click", (e) => {
    const commit = $("#ov-form", box).elements.commit.checked;
    run(e.target, async () => { await api.clearOverride(r.ticker, commit); toast("Overrides cleared — re-analysing", "ok"); reanalyse(); });
  });
}

const view = (r) => `${header(r)}${overviewCard()}<div class="cols"><div>${valuation(r)}${volatility(r)}${technicals(r)}</div><div>${trade(r)}${overrides()}</div></div>${steps(r)}`;

const overviewCard = () => `<section class="card" id="an-overview"><h3>AI company overview</h3>
  <p class="small muted">What the company does, who pays it and how it makes money. Deeper runs add financial history and explain what changed. No moat grade or investment advice.</p>
  <div class="inline"><label class="small">Depth <select id="ex-level"><option value="quick">Quick — business and revenue model</option>
    <option value="standard">Standard — company progress and profits</option><option value="deep">Deep — profit trends, returns and liquidity</option></select></label>
    <button id="ex-go" disabled>Run company overview</button><label class="small check" id="ex-cache" hidden><input type="checkbox" id="ex-fresh"> Refresh cached result</label></div>
  <p id="ex-status" class="small muted">Checking AI availability …</p>
  <div id="ex-out" class="small" aria-live="polite"></div></section>`;

function showOverview(box, result) {
  const links = (urls) => urls.length ? `<div class="muted">Sources: ${urls.map((u) =>
    `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 72))}</a>`).join(" · ")}</div>` : "";
  box.innerHTML = `<p class="muted">${esc(result.name)} · ${esc(result.level)} · ${esc(result.generated)}${result.cached ? " · from cache" : ""}</p>` +
    result.sections.map((s) => `<h4>${esc(s.title)}</h4><p style="white-space:pre-wrap">${esc(s.text)}</p>${links(s.links)}
      ${s.figures ? `<details><summary>Financial figures used</summary><pre class="small muted" style="white-space:pre-wrap">${esc(s.figures)}</pre></details>` : ""}`).join("");
}

async function bindOverview(card, ticker) {
  const go = $("#ex-go", card), level = $("#ex-level", card), output = $("#ex-out", card), status = $("#ex-status", card);
  try {
    const [ai, settings] = await Promise.all([api.aiStatus(), api.aiSettings()]);
    level.value = settings.overview_depth;
    if (!ai.available) {
      status.innerHTML = 'Set up a model in <a href="#/ai-settings">AI Settings</a> to run an overview.';
      return;
    }
    status.textContent = "Uses public sources. Deeper runs take longer; check the cited evidence.";
    $("#ex-cache", card).hidden = !settings.cache_overviews;
    go.disabled = false;
    go.onclick = () => run(go, async () => {
      output.textContent = "Researching and writing the overview …";
      try { showOverview(output, await api.aiExplain(ticker, level.value, $("#ex-fresh", card).checked)); }
      catch (err) { output.textContent = err.message; }
    });
  } catch (err) {
    status.textContent = `Could not check AI availability: ${err.message}`;
  }
}

function bind(out, r) {
  bindOverview($("#an-overview", out), r.ticker);
  const cb = $("#an-chart-box", out);
  if (cb) cb.addEventListener("toggle", () => { if (cb.open && !cb.dataset.done) { cb.dataset.done = "1"; mountChart($("#an-chart", out), r.ticker, { levels: r.technicals?.buy_levels || [] }).then((h) => { chartH = h; applyWl(); }).catch(() => {}); } });
  // supports stated in the chosen watchlist for this stock are drawn as the tranche lines (T1 = highest)
  let chartH = null;
  const wlSel = $("#an-wl", out);
  async function applyWl() {
    if (!chartH || !chartH.setLevels) return;
    if (!wlSel.value) return chartH.setLevels(r.technicals?.buy_levels || []);
    try {
      const w = await api.watchlist(wlSel.value);
      const it = (w.items || []).find((i) => i.symbol === r.ticker);
      chartH.setLevels(((it && it.supports) || []).slice().sort((x, y) => y - x).map((price, i) => ({ price, tranche: i + 1 })));
    } catch { /* keep the current lines */ }
  }
  if (wlSel) {
    api.watchlists().then((ls) => {
      wlSel.insertAdjacentHTML("beforeend", ls.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join(""));
      return Promise.all(ls.map((l) => api.watchlist(l.id).then((w) => ((w.items || []).some((i) => i.symbol === r.ticker && (i.supports || []).length) ? l.id : null)).catch(() => null)));
    }).then((ids) => { const first = ids.find(Boolean); if (first) { wlSel.value = String(first); applyWl(); } }).catch(() => {});
    wlSel.addEventListener("change", applyWl);
  }
  const openBtn = $("#an-open-chart", out);
  if (cb && openBtn) openBtn.addEventListener("click", () => { cb.open = true; cb.scrollIntoView({ behavior: "smooth", block: "start" }); });
  const pf = $("#trade-pf", out);
  const chosen = () => { const v = $("#trade-mult", out)?.value; return v ? parseFloat(v) : (r.allocation_multiplier || 1); };
  const showSize = async () => {
    if (!pf.value) return;
    const mult = chosen();
    const s = await api.size(r.ticker, pf.value, mult).catch(() => null);
    if (s) $("#trade-size", out).textContent =
      `Full allocation ${fmt.money(s.full_allocation, 0)} (×${mult}) · tranche ${fmt.money(s.tranche_value, 0)} (1 of ${s.tranches}) ≈ ${s.shares_next_tranche} sh · held ${fmt.money(s.current_value, 0)} · remaining ${fmt.money(s.remaining_value, 0)} ${s.warning ? "· ⚠ " + s.warning : ""}`;
  };
  pf?.addEventListener("change", showSize);
  $("#trade-mult", out)?.addEventListener("change", showSize);
  showSize();
  $("#trade-form", out)?.addEventListener("submit", (e) => {
    e.preventDefault();
    const qty = parseFloat($("#trade-qty", out).value);
    const body = { symbol: r.ticker, side: $("#trade-side", out).value, multiplier: chosen(),
      tranche: $("#trade-tranche", out).checked && !qty, qty: qty || null };
    if (body.side === "BUY") {
      body.entry_type = $("#trade-entry", out).value;
      if (!body.entry_type) return toast("Say how you are entering: on touch, confirmed or special", "error");
    }
    run(e.submitter, async () => {
      const res = await api.stockOrder(pf.value, body);
      toast(`Filled ${res.trade.side} ${fmt.num(res.trade.qty, 4)} ${r.ticker} @ ${fmt.money(res.trade.price)} (${res.fill.liquidity}, ${res.fill.basis})`, "ok");
      showSize();
    });
  });
  bindOverrides(out, r);
}
