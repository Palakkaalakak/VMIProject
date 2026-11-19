// Shared rendering of editable rule fields (used by the Settings page and the scanner's Custom editor).
import { esc, tip } from "./ui.js";

const KIND = { adam: ["Adam", "ok"], interpretation: ["interpretation", "na"], owner: ["owner", "na"],
  approved: ["approved", "na"], calibration: ["calibration", "na"], model: ["software", "na"], unspecified: ["UNSPECIFIED", "bad"] };
export const badgeFor = (s) => `<span class="badge ${KIND[s.source_kind]?.[1] || "na"}" title="${esc(s.source_note)}">${esc(KIND[s.source_kind]?.[0] || s.source_kind)}</span>`;
/** "Readable title (?)" for a schema entry; the technical key stays visible in small print for searching. */
export const ruleTitle = (s) => `<b>${esc(s.title || s.key)}</b>${tip([s.help, s.source_note].filter((x, i, a) => x && a.indexOf(x) === i).join(" — "))} ${badgeFor(s)} <span class="techkey">${esc(s.section)}.${esc(s.key)}</span>`;
export const show = (v) => (Array.isArray(v) ? JSON.stringify(v) : String(v));

/** One input for a schema entry; `value` overrides the current value (preset values in the scanner). */
export function ruleInput(s, value = s.value) {
  const name = `name="${esc(s.section)}.${esc(s.key)}"`;
  if (s.type === "choice") return `<select ${name}>${s.choices.map((c) => `<option ${c === value ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
  if (s.type === "bool") return `<select ${name}><option value="true" ${value ? "selected" : ""}>yes</option><option value="false" ${value ? "" : "selected"}>no</option></select>`;
  if (s.type === "int" || s.type === "float") return `<input ${name} type="number" step="any" value="${esc(value)}">`;
  return `<input ${name} value="${esc(show(value))}">`;
}

/** Collapsible groups with every rule (help text, source badge, input). `base` = {section: {key: value}} shown instead of the current values. */
export function ruleGroups(schema, base = {}, open = []) {
  const sections = [...new Set(schema.map((s) => s.section))];
  return sections.map((sec) => {
    const rows = schema.filter((s) => s.section === sec);
    return `<details ${open.includes(sec) ? "open" : ""}><summary><b>${esc(rows[0].section_title || sec)}</b> <span class="muted small">${esc(rows[0].section_help)}</span></summary>
      <table class="compact"><tbody>${rows.map((s) => `<tr>
        <td>${ruleTitle(s)}</td>
        <td>${ruleInput(s, base[s.section]?.[s.key] ?? s.value)}</td></tr>`).join("")}</tbody></table></details>`;
  }).join("");
}
