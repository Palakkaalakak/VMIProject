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
  { id: "max_growth", label: "Max growth %", kind: "max", field: "growth", parse: pctOf },
  { id: "min_roe", label: "Min ROE %", kind: "min", field: "roe", parse: pctOf },
  { id: "min_roic", label: "Min ROIC %", kind: "min", field: "roic", parse: pctOf },
  { id: "min_margin", label: "Min net margin %", kind: "min", field: "net_margin", parse: pctOf },
  { id: "max_peg", label: "Max PEG", kind: "max", field: "peg", parse: num },
  { id: "min_yield", label: "Min dividend yield %", kind: "min", field: "dividend_yield", parse: pctOf },
  { id: "min_cap", label: "Min market cap ($B)", kind: "min", field: "market_cap", parse: (v) => (num(v) == null ? null : num(v) * 1e9) },
  { id: "max_beta", label: "Max beta", kind: "max", field: "beta", parse: num },
  { id: "sector", label: "Sector", kind: "pick", field: "sector" },
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

const uniq = (rows, f) => [...new Set(rows.map((r) => r[f]).filter((x) => x != null && x !== ""))].sort();
const tri = (id, label) => `<label>${esc(label)} <select name="${id}"><option value="">any</option><option value="yes">yes</option><option value="no">no</option></select></label>`;

export function filterPanel(rows) {
  const parts = FIELDS.map((f) => {
    if (f.kind === "flag") return tri(f.id, f.label);
    if (f.kind === "pick") return `<label>${esc(f.label)} <select name="${f.id}"><option value="">any</option>${uniq(rows, f.field).map((o) => `<option>${esc(o)}</option>`).join("")}</select></label>`;
    return `<label>${esc(f.label)} <input name="${f.id}" type="number" step="any" style="width:6rem"></label>`;
  });
  const steps = STEP_NAMES.map((n, i) => `<label>Step ${i + 1} ${esc(n)} <select name="step${i + 1}"><option value="">any</option><option value="pass">must pass</option><option value="fail">must fail</option></select></label>`);
  return `<details id="scan-filters" class="card"><summary><b>Filters</b> <span class="muted small" id="scan-count"></span></summary>
    <form class="grid">${steps.join("")}${parts.join("")}<button type="button" class="secondary" id="scan-reset">Reset</button></form></details>`;
}

export function readFilters(form) {
  const out = {};
  new FormData(form).forEach((v, k) => { if (v !== "") out[k] = v; });
  return out;
}

export function applyFilters(rows, f) {
  return rows.filter((r) => {
    for (let i = 1; i <= 7; i++) {
      const want = f[`step${i}`];
      if (want && Boolean((r.steps || {})[i]) !== (want === "pass")) return false;
    }
    for (const d of FIELDS) {
      const raw = f[d.id];
      if (raw === undefined) continue;
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
}
