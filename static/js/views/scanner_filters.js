// Scanner results filters (client-side, over the rows of the latest scan). Kept apart from scanner.js so a filter is
// one entry in FIELDS and nothing else.
import { esc } from "../ui.js";

const STORE = "vmi.scanner.filters";
const STEP_NAMES = ["Track record", "Growth", "Moat", "Profitability", "Debt", "Price < IV", "Chart entry"];
const pctOf = (v) => (v === "" || v == null ? null : parseFloat(v) / 100);
const num = (v) => (v === "" || v == null ? null : parseFloat(v));

// kind: "min"/"max" compare a numeric row field; "pick" matches a text field; "flag" is a tri-state boolean field.
const FIELDS = [
  { id: "min_steps", label: "Min steps passed (of 7)", kind: "min", field: "steps_passed", parse: num },
  { id: "min_mos", label: "Min margin of safety %", kind: "min", field: "margin_of_safety", parse: pctOf },
  { id: "max_mos", label: "Max margin of safety %", kind: "max", field: "margin_of_safety", parse: pctOf },
  { id: "min_growth", label: "Min growth %", kind: "min", field: "growth", parse: pctOf },
  { id: "min_growth_low", label: "Growth: lowest estimate at least %", kind: "min", field: "growth_low", parse: pctOf },
  { id: "min_growth_avg", label: "Growth: average estimate at least %", kind: "min", field: "growth_avg", parse: pctOf },
  { id: "min_growth_high", label: "Growth: highest estimate at least %", kind: "min", field: "growth_high", parse: pctOf },
  { id: "max_growth_low", label: "Growth: lowest estimate at most %", kind: "max", field: "growth_low", parse: pctOf },
  { id: "max_growth_avg", label: "Growth: average estimate at most %", kind: "max", field: "growth_avg", parse: pctOf },
  { id: "max_growth_high", label: "Growth: highest estimate at most %", kind: "max", field: "growth_high", parse: pctOf },
  { id: "max_growth", label: "Max growth %", kind: "max", field: "growth", parse: pctOf },
  { id: "min_roe", label: "Min ROE %", kind: "min", field: "roe", parse: pctOf },
  { id: "min_roic", label: "Min ROIC %", kind: "min", field: "roic", parse: pctOf },
  { id: "min_margin", label: "Min net margin %", kind: "min", field: "net_margin", parse: pctOf },
  { id: "max_peg", label: "Max PEG", kind: "max", field: "peg", parse: num },
  { id: "min_yield", label: "Min dividend yield %", kind: "min", field: "dividend_yield", parse: pctOf },
  { id: "min_cap", label: "Min market cap ($B)", kind: "min", field: "market_cap", parse: (v) => (num(v) == null ? null : num(v) * 1e9) },
  { id: "max_beta", label: "Max beta", kind: "max", field: "beta", parse: num },
  { id: "q", label: "Search name / ticker / industry", kind: "text" },
  { id: "sector", label: "Sector", kind: "pick", field: "sector" },
  { id: "industry", label: "Industry (niche)", kind: "pick", field: "industry" },
  { id: "max_industry_rank", label: "Top N by market cap within its industry (1 = leader)", kind: "max", field: "industry_rank", parse: num },
  { id: "min_industry_share", label: "Min share of the industry's market cap %", kind: "min", field: "industry_share", parse: pctOf },
  { id: "min_industry_n", label: "Industry has at least N companies in the results", kind: "min", field: "industry_n", parse: num },
  { id: "method", label: "Valuation method", kind: "pick", field: "method" },
  { id: "moat", label: "Moat", kind: "pick", field: "moat" },
  { id: "style", label: "Style", kind: "pick", field: "style" },
  { id: "category", label: "Category", kind: "pick", field: "category" },
  { id: "trend", label: "Daily trend", kind: "pick", field: "trend" },
  { id: "great_business", label: "Great business (steps 1–5)", kind: "flag", field: "great_business" },
  { id: "undervalued", label: "Below IV (step 6)", kind: "flag", field: "undervalued" },
  { id: "entry_ok", label: "Chart entry OK (step 7)", kind: "flag", field: "entry_ok" },
  { id: "vmi_pass", label: "VMI buy signal", kind: "flag", field: "vmi_pass" },
  { id: "moat_reviewed", label: "Moat reviewed by you", kind: "flag", field: "moat_reviewed" },
  { id: "iv_low_confidence", label: "IV low confidence (methods disagree)", kind: "flag", field: "iv_low_confidence" },
  { id: "judged", label: "Has a judgement override", kind: "flag", field: "pinned", truthy: true },
];

// Free-form conditions: any numeric column with an operator (above, at least, below, at most, equals, between). Kept in the
// hidden field "conds" as JSON [{f: metric id, op, a, b}] so it is saved and restored like every other filter.
const cap = (v) => (num(v) == null ? null : num(v) * 1e9);
export const METRICS = [
  { id: "steps", label: "Steps passed (of 7)", field: "steps_passed", parse: num },
  { id: "mos", label: "Margin of safety %", field: "margin_of_safety", parse: pctOf },
  { id: "growth", label: "Growth (valuation blend) %", field: "growth", parse: pctOf },
  { id: "growth_low", label: "Growth: lowest estimate %", field: "growth_low", parse: pctOf },
  { id: "growth_avg", label: "Growth: average estimate %", field: "growth_avg", parse: pctOf },
  { id: "growth_high", label: "Growth: highest estimate %", field: "growth_high", parse: pctOf },
  { id: "roe", label: "ROE %", field: "roe", parse: pctOf },
  { id: "roic", label: "ROIC %", field: "roic", parse: pctOf },
  { id: "net_margin", label: "Net margin %", field: "net_margin", parse: pctOf },
  { id: "peg", label: "PEG", field: "peg", parse: num },
  { id: "yield", label: "Dividend yield %", field: "dividend_yield", parse: pctOf },
  { id: "cap", label: "Market cap ($B)", field: "market_cap", parse: cap },
  { id: "price", label: "Price ($)", field: "price", parse: num },
  { id: "iv", label: "Intrinsic value ($)", field: "intrinsic_value", parse: num },
  { id: "beta", label: "Beta", field: "beta", parse: num },
  { id: "industry_rank", label: "Rank by market cap in its industry", field: "industry_rank", parse: num },
  { id: "industry_share", label: "Share of its industry's market cap %", field: "industry_share", parse: pctOf },
];
export const OPS = [[">", "above"], [">=", "at least"], ["<", "below"], ["<=", "at most"], ["=", "equals"], ["between", "between"]];

/** True when value v satisfies one condition c (the metric's parse turns the typed number into the row's unit). */
export function matches(c, v) {
  const m = METRICS.find((x) => x.id === c.f);
  if (!m || v == null) return !m;                       // unknown metric: ignore the condition; missing data never passes
  const a = m.parse(String(c.a ?? "")), b = m.parse(String(c.b ?? ""));
  if (a == null) return true;                           // not filled in yet
  const tol = Math.abs(m.parse("1")) * 0.05;
  switch (c.op) {
    case ">": return v > a;
    case ">=": return v >= a;
    case "<": return v < a;
    case "<=": return v <= a;
    case "=": return Math.abs(v - a) <= tol;
    case "between": return b == null ? v >= a : v >= Math.min(a, b) && v <= Math.max(a, b);
    default: return true;
  }
}

const readConds = (form) => { try { return JSON.parse(form.elements.conds?.value || "[]"); } catch { return []; } };

/** (Re)draw the condition rows from the hidden field; edits write back and fire "input" so the list refilters. */
export function drawConds(form) {
  const box = form.querySelector(".conds");
  if (!box) return;
  const conds = readConds(form);
  const write = () => { form.elements.conds.value = conds.length ? JSON.stringify(conds) : ""; form.dispatchEvent(new Event("input", { bubbles: true })); };
  box.innerHTML = conds.map((c, i) => `<div class="inline" data-i="${i}">
      <select data-k="f">${METRICS.map((m) => `<option value="${m.id}" ${m.id === c.f ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select>
      <select data-k="op">${OPS.map(([o, l]) => `<option value="${o}" ${o === c.op ? "selected" : ""}>${l}</option>`).join("")}</select>
      <input data-k="a" type="number" step="any" value="${esc(c.a ?? "")}" style="width:6rem">
      ${c.op === "between" ? `and <input data-k="b" type="number" step="any" value="${esc(c.b ?? "")}" style="width:6rem">` : ""}
      <button type="button" class="small danger" data-del="${i}" title="Remove this condition">✕</button></div>`).join("");
  box.querySelectorAll("[data-k]").forEach((el) => el.addEventListener("input", (e) => {
    e.stopPropagation();
    const i = +el.closest("[data-i]").dataset.i;
    conds[i][el.dataset.k] = el.value;
    write();
    if (el.dataset.k === "op") drawConds(form);
  }));
  box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => { conds.splice(+b.dataset.del, 1); write(); drawConds(form); }));
  const add = form.querySelector(".conds-add");
  if (add && !add.dataset.bound) {
    add.dataset.bound = "1";
    add.addEventListener("click", () => { const c = readConds(form); c.push({ f: "roe", op: ">=", a: "", b: "" }); form.elements.conds.value = JSON.stringify(c); drawConds(form); });
  }
}

const uniq = (rows, f) => [...new Set(rows.map((r) => r[f]).filter((x) => x != null && x !== ""))].sort();
const tri = (id, label) => `<label>${esc(label)} <select name="${id}"><option value="">any</option><option value="yes">yes</option><option value="no">no</option></select></label>`;

// Growth profiles: which 5-year analyst estimate must clear the threshold (default 15%, Adam's growth/defensive line).
//   conservative = even the LOWEST estimate says growth; balanced = the AVERAGE; optimistic = at least the HIGHEST does.
//   Defensive mirrors it: conservative = even the HIGHEST estimate is below the line; balanced = average; optimistic = lowest.
const PROFILES = {
  growth_conservative: ["Growth (conservative): lowest estimate ≥ threshold", (r, t) => (r.growth_low ?? r.growth) >= t],
  growth_balanced: ["Growth (balanced): average estimate ≥ threshold", (r, t) => (r.growth_avg ?? r.growth) >= t],
  growth_optimistic: ["Growth (optimistic): highest estimate ≥ threshold", (r, t) => (r.growth_high ?? r.growth) >= t],
  defensive_conservative: ["Defensive (conservative): highest estimate < threshold", (r, t) => (r.growth_high ?? r.growth) < t],
  defensive_balanced: ["Defensive (balanced): average estimate < threshold", (r, t) => (r.growth_avg ?? r.growth) < t],
  defensive_optimistic: ["Defensive (optimistic): lowest estimate < threshold", (r, t) => (r.growth_low ?? r.growth) < t],
};

export function filterPanel(rows) {
  const parts = FIELDS.map((f) => {
    if (f.kind === "flag") return tri(f.id, f.label);
    if (f.kind === "text") return `<label class="wide">${esc(f.label)} <input name="${f.id}" placeholder="e.g. payment, semiconductor, WST"></label>`;
    if (f.kind === "pick") return `<label>${esc(f.label)} <select name="${f.id}"><option value="">any</option>${uniq(rows, f.field).map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>`;
    return `<label>${esc(f.label)} <input name="${f.id}" type="number" step="any" style="width:6rem"></label>`;
  });
  const steps = STEP_NAMES.map((n, i) => `<label>Step ${i + 1} ${esc(n)} <select name="step${i + 1}"><option value="">any</option><option value="pass">must pass</option><option value="fail">must fail</option></select></label>`);
  const profile = `<label class="wide">Growth profile <select name="profile"><option value="">any</option>${Object.entries(PROFILES).map(([k, v]) => `<option value="${k}">${esc(v[0])}</option>`).join("")}</select></label>
    <label>Threshold % p.a. <input name="profile_threshold" type="number" step="any" value="15" style="width:6rem"></label>`;
  return `<details id="scan-filters" class="card"><summary><b>Filters</b> <span class="muted small" id="scan-count"></span></summary>
    <form class="grid">${profile}<div class="wide" style="grid-column:1/-1"><b>Conditions</b> <span class="muted small">any column: above, at least, below, at most, equals, between</span><input type="hidden" name="conds"><div class="conds"></div><button type="button" class="small secondary conds-add">+ Add condition</button></div>${steps.join("")}${parts.join("")}<button type="button" class="secondary" id="scan-reset">Reset</button></form></details>`;
}

export function readFilters(form) {
  const out = {};
  new FormData(form).forEach((v, k) => { if (v !== "") out[k] = v; });
  return out;
}

export function applyFilters(rows, f) {
  return rows.filter((r) => {
    if (f.profile && PROFILES[f.profile]) {
      const t = (f.profile_threshold === undefined || f.profile_threshold === "" ? 15 : parseFloat(f.profile_threshold)) / 100;
      if (!PROFILES[f.profile][1](r, t)) return false;
    }
    for (let i = 1; i <= 7; i++) {
      const want = f[`step${i}`];
      if (want && Boolean((r.steps || {})[i]) !== (want === "pass")) return false;
    }
    let conds = [];
    try { conds = JSON.parse(f.conds || "[]"); } catch { /* ignore a damaged saved value */ }
    for (const c of conds) { const m = METRICS.find((x) => x.id === c.f); if (m && !matches(c, r[m.field])) return false; }
    for (const d of FIELDS) {
      const raw = f[d.id];
      if (raw === undefined) continue;
      if (d.kind === "text") { if (!`${r.symbol} ${r.name} ${r.industry} ${r.sector}`.toLowerCase().includes(raw.toLowerCase())) return false; continue; }
      const v = r[d.field];
      if (d.kind === "flag") { if (Boolean(d.truthy ? v : v === true) !== (raw === "yes")) return false; }
      else if (d.kind === "pick") { if (String(v ?? "") !== raw) return false; }
      else {
        const lim = d.parse(raw);
        if (lim == null) continue;
        if (v == null || (d.kind === "min" ? v < lim : v > lim)) return false;
      }
    }
    return true;
  });
}

export const loadSaved = () => { try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch { return {}; } };
export const save = (f) => { try { localStorage.setItem(STORE, JSON.stringify(f)); } catch { /* private window */ } };

export function setForm(form, f) {
  for (const el of form.elements) if (el.name) el.value = f[el.name] ?? "";
  drawConds(form);
}

/** Industry leadership among ALL saved results (call once after loading, before filtering): industry_rank by market cap,
 *  industry_n, industry_share of the industry's total market cap. Lets you narrow to the dominant force of a niche. */
export function addIndustryStats(rows) {
  const by = {};
  for (const r of rows) (by[r.industry || "?"] ||= []).push(r);
  for (const g of Object.values(by)) {
    const total = g.reduce((a, r) => a + (r.market_cap || 0), 0);
    [...g].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0)).forEach((r, i) => {
      r.industry_rank = i + 1; r.industry_n = g.length; r.industry_share = total ? (r.market_cap || 0) / total : null;
    });
  }
  return rows;
}
