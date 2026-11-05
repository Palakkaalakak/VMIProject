// Analysis view: full 7-step VMI report for one ticker + valuation methods, technical buy levels,
// judgement overrides and one-click paper trading (tranche sizing).
import { api } from "../api.js";
import { $, esc, fmt, badge, loading, run, toast, signClass } from "../ui.js";
import { state } from "../state.js";

const METHODS = ["", "dcf_fcf", "dcf_normalized", "dcf_cfo", "dni", "pb_bank", "pb_distressed", "pnav_reit", "ps_mean", "psg"];

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
        <button class="primary">Analyse</button>
      </form>
    </section>
    <div id="analysis-out"></div>`;
  $("#analysis-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const s = $("#analysis-symbol", root).value.trim().toUpperCase();
    if (s) location.hash = `#/analysis/${s}`;
  });
  if (params.symbol) load(root, params.symbol.toUpperCase());
}

async function load(root, symbol) {
  const out = $("#analysis-out", root);
  out.innerHTML = loading(`Analysing ${symbol} (fundamentals, estimates, 10y chart)…`);
  try {
    const r = await api.analyse(symbol, $("#analysis-tech", root).checked);
    out.innerHTML = view(r);
    bind(out, r);
  } catch (e) {
    out.innerHTML = `<div class="card error">${esc(e.message)}</div>`;
  }
}

const verdict = (r) => [
  ["Great business", r.great_business], ["Undervalued", r.undervalued], ["Entry signal", r.entry_ok], ["VMI buy", r.vmi_pass],
].map(([l, v]) => `<div class="kpi"><span>${l}</span>${badge(v, "YES", "NO")}</div>`).join("");

function header(r) {
  const v = r.valuation || {};
  return `<div class="card head">
    <div><h2>${esc(r.ticker)} <small>${esc(r.name || "")}</small></h2>
      <p class="muted">${esc(r.sector || "")} · ${esc(r.industry || "")} · type <b>${esc(r.biz_type)}</b> · ${esc(r.category || "")} · ${esc(r.style || "")} · moat <b>${esc(r.moat)}</b></p></div>
    <div class="kpis">
      <div class="kpi"><span>Price</span><b>${fmt.money(r.price)}</b></div>
      <div class="kpi"><span>Intrinsic value</span><b>${fmt.money(r.intrinsic_value)}</b></div>
      <div class="kpi"><span>Margin of safety</span><b class="${signClass(v.margin_of_safety)}">${fmt.pct(v.margin_of_safety)}</b></div>
      <div class="kpi"><span>Conservative</span><b>${fmt.money(v.conservative_value)}</b></div>
      ${verdict(r)}
    </div>
    ${r.overrides && Object.keys(r.overrides).length ? `<p class="note">Judgement override active (${esc(r.overrides.source || "")}): ${esc(r.overrides.note || JSON.stringify(r.overrides))}</p>` : ""}
  </div>`;
}

function steps(r) {
  return `<div class="card"><h3>7 steps</h3>${(r.steps || []).map((s) => `
    <details ${s.passed ? "" : "open"}><summary>${badge(s.passed)} <b>Step ${s.step}</b> — ${esc(s.title)} <span class="muted">score ${fmt.pct(s.score, 0)}</span></summary>
      <table class="compact"><tbody>${s.checks.map((c) => `<tr><td>${badge(c.passed)}</td><td>${esc(c.name)}</td>
        <td>${esc(typeof c.value === "number" ? fmt.num(c.value, 4) : Array.isArray(c.value) ? c.value.map((x) => fmt.num(x, 3)).join(", ") : typeof c.value === "object" && c.value ? JSON.stringify(c.value) : c.value ?? "")}</td>
        <td class="muted">${esc(c.threshold ?? "")}</td><td class="muted small">${esc(c.note || "")}</td></tr>`).join("")}</tbody></table>
      ${(s.notes || []).filter((n) => !n.startsWith("moat_grade=")).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
    </details>`).join("")}</div>`;
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
    ${inp.base_cash_flow != null ? `<p class="small">Base: <b>${fmt.big(inp.base_cash_flow)}</b> (${esc(inp.base_desc)}) · debt ${fmt.big(inp.debt)} · cash ${fmt.big(inp.cash)} · shares ${fmt.big(inp.shares)} · β ${fmt.num(inp.beta)} → rate ${fmt.pct(inp.discount_rate)} · IV haircut ${fmt.pct(inp.iv_haircut, 0)}${inp.statement_currency && inp.statement_currency !== "USD" ? ` · ${esc(inp.statement_currency)}→USD ${fmt.num(inp.fx, 4)}` : ""}</p>` : ""}
    ${scen ? `<table class="compact"><thead><tr><th>Scenario</th><th>IV</th><th>growth 1–5 / 6–10 / 11–20</th><th></th></tr></thead><tbody>${scen}</tbody></table>` : ""}
    <details><summary>All methods</summary><table class="compact"><tbody>${rows}</tbody></table></details>
    ${(v.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
  </div>`;
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
  </div>`;
}

function trade(r) {
  const opts = state.portfolios.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
  return `<div class="card"><h3>Paper trade</h3>
    <form id="trade-form" class="inline">
      <select id="trade-pf">${opts}</select>
      <select id="trade-side"><option>BUY</option><option>SELL</option></select>
      <label class="check"><input type="checkbox" id="trade-tranche" checked> one VMI tranche (auto-size)</label>
      <input id="trade-qty" type="number" step="any" min="0" placeholder="or qty">
      <button class="primary">Submit (paper)</button>
    </form>
    <div id="trade-size" class="small muted"></div>
  </div>`;
}

function overrides(r) {
  const o = r.overrides || {};
  return `<div class="card"><h3>Judgement override</h3>
    <p class="small muted">For distorted data only (e.g. temporarily depressed consensus). Stored per ticker; the general formula never changes.</p>
    <form id="ov-form" class="grid">
      <label>Growth yrs 1–5 <input name="growth" type="number" step="0.001" value="${o.growth ?? ""}" placeholder="0.13"></label>
      <label>Method <select name="method">${METHODS.map((m) => `<option ${o.method === m ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label>Biz type <input name="biz_type" value="${esc(o.biz_type ?? "")}"></label>
      <label>IV override <input name="iv_override" type="number" step="any" value="${o.iv_override ?? ""}"></label>
      <label class="wide">Note (why) <input name="note" value="${esc(o.note ?? "")}"></label>
      <button class="secondary">Save override</button>
    </form></div>`;
}

const view = (r) => `${header(r)}<div class="cols"><div>${valuation(r)}${technicals(r)}</div><div>${trade(r)}${overrides(r)}</div></div>${steps(r)}`;

function bind(out, r) {
  const pf = $("#trade-pf", out), mult = r.allocation_multiplier || 1;
  const showSize = async () => {
    if (!pf.value) return;
    const s = await api.size(r.ticker, pf.value, mult).catch(() => null);
    if (s) $("#trade-size", out).textContent =
      `Full allocation ${fmt.money(s.full_allocation, 0)} (×${mult}) · tranche ${fmt.money(s.tranche_value, 0)} ≈ ${s.shares_next_tranche} sh · held ${fmt.money(s.current_value, 0)} · remaining ${fmt.money(s.remaining_value, 0)} ${s.warning ? "· ⚠ " + s.warning : ""}`;
  };
  pf?.addEventListener("change", showSize);
  showSize();
  $("#trade-form", out)?.addEventListener("submit", (e) => {
    e.preventDefault();
    const qty = parseFloat($("#trade-qty", out).value);
    const body = { symbol: r.ticker, side: $("#trade-side", out).value, multiplier: mult,
      tranche: $("#trade-tranche", out).checked && !qty, qty: qty || null };
    run(e.submitter, async () => {
      const res = await api.stockOrder(pf.value, body);
      toast(`Filled ${res.trade.side} ${fmt.num(res.trade.qty, 4)} ${r.ticker} @ ${fmt.money(res.trade.price)} (${res.fill.liquidity}, ${res.fill.basis})`, "ok");
      showSize();
    });
  });
  $("#ov-form", out)?.addEventListener("submit", (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const num = (k) => (f[k] === "" ? null : parseFloat(f[k]));
    const body = { growth: num("growth"), iv_override: num("iv_override"), method: f.method || null, biz_type: f.biz_type || null, note: f.note || "" };
    run(e.submitter, async () => { await api.setOverride(r.ticker, body); toast("Override saved — re-analysing", "ok"); location.hash = `#/analysis/${r.ticker}?t=${Date.now()}`; });
  });
}
