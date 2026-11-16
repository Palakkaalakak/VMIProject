// Position-size choices for the sizing plan: a fraction of the full allocation (1 = full). Speculative / turnaround / unproven
// ideas go from 1/2 down to 1/14 of a normal position.
import { esc } from "./ui.js";

export const SIZE_STEPS = [[1, "Full position"], [0.75, "3/4 (narrow moat)"],
  ...Array.from({ length: 13 }, (_, i) => [1 / (i + 2), `1/${i + 2}${i === 0 ? " (speculative / turnaround)" : ""}`])];

/** <select> of the steps; `value` = current fraction (closest step is selected); `auto` adds a leading "automatic" choice (empty value). */
export function sizeSelect(name, value, { auto = "", id = "" } = {}) {
  const v = value == null || value === "" ? null : +value;
  const near = v == null ? null : SIZE_STEPS.reduce((a, b) => (Math.abs(b[0] - v) < Math.abs(a[0] - v) ? b : a))[0];
  return `<select name="${esc(name)}" ${id ? `id="${esc(id)}"` : ""}>${auto ? `<option value="" ${v == null ? "selected" : ""}>${esc(auto)}</option>` : ""}` +
    SIZE_STEPS.map(([f, l]) => `<option value="${f}" ${f === near ? "selected" : ""}>${esc(l)}</option>`).join("") + `</select>`;
}
