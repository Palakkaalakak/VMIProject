// Valuation calculator: edit the growth / discount-rate / cash-flow inputs and see the intrinsic value move live.
// Nothing is saved unless "Save as my override" is pressed (it reuses the normal overrides API).
import { api } from "../api.js";
import { esc, run, toast, fmt } from "../ui.js";
import { kpi, pct, usd, muted } from "./overview_util.js";

// [override key, label, key in the report's method inputs, unit]; "pct" fields are typed as percent, "m" as millions
const FIELDS = [
  ["growth", "Growth years 1–5 (%)", "growth_1_5", "pct"], ["growth_6_10", "Growth years 6–10 (%)", "growth_6_10", "pct"],
  ["growth_11_20", "Growth years 11–20 (%)", "growth_11_20", "pct"], ["discount_rate", "Discount rate (%)", "discount_rate", "pct"],
  ["base_cf", "Base cash flow (millions)", "base_cash_flow", "m"], ["shares", "Shares (millions)", "shares", "m"],
  ["cash", "Cash (millions)", "cash", "m"], ["debt", "Debt (millions)", "debt", "m"],
];
const show = (v, unit) => (v == null || !isFinite(v) ? "" : unit === "pct" ? (v * 100).toFixed(2) : (v / 1e6).toFixed(2));
const toRaw = (text, unit) => (text.trim() === "" || !isFinite(+text) ? null : unit === "pct" ? +text / 100 : +text * 1e6);

/** Status of the price against the two values: green below the conservative value, yellow up to IV, red above IV. */
export function gaugeState(price, iv, cons) {
  if (price == null || iv == null || !(iv > 0)) return null;
  const c = cons == null ? iv : Math.min(cons, iv);
  const word = price <= c ? ["good", "Undervalued"] : price <= iv ? ["mid", "Fair"] : ["bad", "Overvalued"];
  return { cons: c, iv, price, cls: word[0], word: word[1] };
}

function gauge(price, iv, cons) {
  const g = gaugeState(price, iv, cons);
  if (!g) return muted("No gauge: the intrinsic value or the price is not available.");
  const max = Math.max(g.iv * 1.4, g.price * 1.08), at = (v) => `${Math.min(100, (v / max) * 100).toFixed(1)}%`;
  return `<div class="gauge-wrap"><div class="gauge" role="img" aria-label="Price ${esc(usd(g.price))} is ${g.word.toLowerCase()}">
      <i class="gz good" style="width:${at(g.cons)}"></i><i class="gz mid" style="left:${at(g.cons)};width:${(((g.iv - g.cons) / max) * 100).toFixed(1)}%"></i>
      <i class="gz bad" style="left:${at(g.iv)};right:0"></i><i class="gmark" style="left:${at(g.price)}"></i></div>
    <div class="gauge-scale small muted"><span style="left:${at(g.cons)}">conservative ${esc(usd(g.cons))}</span><span style="left:${at(g.iv)}">IV ${esc(usd(g.iv))}</span></div>
    <p><span class="badge ${g.cls === "good" ? "ok" : g.cls === "bad" ? "bad" : "warn"}">${g.word}</span>
      <span class="small">price ${esc(usd(g.price))} · green below the conservative value, yellow between it and the intrinsic value, red above it.</span></p></div>`;
}

export function mountValuation(body, symbol, report) {
  const v = report.valuation || {}, methods = v.methods || {};
  const sel = methods[v.selected] || {}, inp = sel.inputs || {};
  const initial = Object.fromEntries(FIELDS.map(([k, , ik, unit]) => [k, show(inp[ik], unit)]));
  const fromReport = { price: report.price, selected: v.selected, intrinsic_value: report.intrinsic_value, conservative_value: v.conservative_value,
    margin_of_safety: v.margin_of_safety, methods, changed: [] };
  body.innerHTML = `<p class="note"><b>A what-if only.</b> Nothing here is saved and the Analysis tab does not change, unless you press "Save as my override".</p>
    <form id="vc-form" class="grid" autocomplete="off">${FIELDS.map(([k, label, , unit]) => `<label>${esc(label)}
        <input name="${k}" type="number" step="any" inputmode="decimal" value="${esc(initial[k])}" placeholder="auto"></label>`).join("")}
      <label>Method<select name="method"><option value="">automatic${v.selected ? ` (${esc(sel.label || v.selected)})` : ""}</option>
        ${Object.entries(methods).map(([k, m]) => `<option value="${esc(k)}">${esc(m.label || k)}</option>`).join("")}</select></label></form>
    <div class="inline"><button type="button" class="secondary" id="vc-reset">Reset to analysis</button>
      <button type="button" class="primary" id="vc-save" disabled>Save as my override</button><span class="small muted" id="vc-state"></span></div>
    <div id="vc-out"></div>`;
  const form = body.querySelector("#vc-form"), out = body.querySelector("#vc-out"), state = body.querySelector("#vc-state"), saveBtn = body.querySelector("#vc-save");

  // only the inputs the user actually changed are sent; the rest stay as the analysis computed them
  const edits = () => {
    const e = {};
    for (const [k, , , unit] of FIELDS) if (form.elements[k].value !== initial[k]) { const r = toRaw(form.elements[k].value, unit); if (r != null) e[k] = r; }
    if (form.elements.method.value) e.method = form.elements.method.value;
    return e;
  };
  const draw = (res, preview) => {
    const rows = Object.entries(res.methods || {}).map(([k, m]) => `<tr class="${k === res.selected ? "selected" : ""}"><td>${k === res.selected ? "★ " : ""}${esc(m.label || k)}</td>
      <td class="num">${esc(usd(m.intrinsic_value))}</td><td>${m.applicable === false ? '<span class="badge na">caveat</span>' : ""}</td></tr>`).join("");
    const mos = res.margin_of_safety;
    out.innerHTML = `<div class="kpis">${kpi("Price", usd(res.price ?? report.price))}${kpi("Intrinsic value", usd(res.intrinsic_value), "", (methods[res.selected] || res.methods?.[res.selected] || {}).label || "")}
      ${kpi("Conservative value", usd(res.conservative_value))}${kpi("Price vs IV", fmt.gap(mos), mos == null ? "" : mos >= 0 ? "pos" : "neg")}
      ${kpi("Method", (res.methods?.[res.selected] || {}).label || res.selected || "—")}</div>
      ${preview ? `<p class="small"><span class="badge warn">preview</span> changed: ${esc((res.changed || []).join(", ") || "nothing")}</p>` : ""}
      ${gauge(res.price ?? report.price, res.intrinsic_value, res.conservative_value)}
      <details ${rows ? "open" : ""}><summary>Intrinsic value by method</summary><table class="compact"><tbody>${rows || `<tr><td class="muted">no methods</td></tr>`}</tbody></table></details>
      ${(res.notes || []).slice(0, 3).map((n) => `<p class="small muted">${esc(n)}</p>`).join("")}`;
  };
  draw(fromReport, false);

  let timer = null, seq = 0;
  const recompute = async () => {
    const e = edits(), mine = ++seq;
    saveBtn.disabled = !Object.keys(e).length;
    if (!Object.keys(e).length) { state.textContent = ""; draw(fromReport, false); return; }
    state.textContent = "calculating…";
    try {
      const res = await api.ovValuationPreview(symbol, e);
      if (mine !== seq) return;                      // a newer edit is already on its way
      state.textContent = "";
      draw(res, true);
    } catch (err) { if (mine === seq) state.textContent = `Could not calculate: ${err.message}`; }
  };
  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(recompute, 350); });
  form.addEventListener("submit", (e) => e.preventDefault());
  body.querySelector("#vc-reset").addEventListener("click", () => {
    clearTimeout(timer);
    for (const [k] of FIELDS) form.elements[k].value = initial[k];
    form.elements.method.value = "";
    recompute();
  });
  saveBtn.addEventListener("click", () => run(saveBtn, async () => {
    const e = edits();
    if (!Object.keys(e).length) return toast("Nothing was changed", "info");
    await api.setOverride(symbol, { data: e, note: "Saved from the valuation calculator", commit: false });
    toast("Saved as your override — re-analysing", "ok");
    location.hash = `#/analysis/${symbol}?t=${Date.now()}`;
  }));
}
