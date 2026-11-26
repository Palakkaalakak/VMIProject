// Small helpers shared by the "More detailed overview" section modules.
import { esc } from "../ui.js";

/** A KPI tile; `text` is plain text (escaped here), `cls` an optional colour class (pos / neg). */
export const kpi = (label, text, cls = "", title = "") =>
  `<div class="kpi" ${title ? `title="${esc(title)}"` : ""}><span>${esc(label)}</span><b class="${cls}">${esc(text ?? "—")}</b></div>`;

/** Number with fixed decimals and thousands separators; null / NaN -> "—". */
export const num = (v, d = 0) =>
  v == null || !isFinite(v) ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

/** Percent from a fraction: 0.123 -> "12.3%". */
export const pct = (v, d = 1) => (v == null || !isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`);

/** Money with 2 decimals ("$12.34"). */
export const usd = (v, d = 2) => (v == null || !isFinite(v) ? "—" : `${v < 0 ? "-" : ""}$${num(Math.abs(v), d)}`);

/** Muted one-line message, used for empty data and failures. */
export const muted = (text) => `<p class="muted">${esc(text)}</p>`;

/** Only plain https links from the backend are rendered as links. */
export const safeUrl = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);

/** Tiny segmented control: buttons with data-v; returns html. */
export const seg = (name, options, current) =>
  `<span class="seg" data-seg="${esc(name)}">${options.map(([v, l]) =>
    `<button type="button" class="secondary small ${String(v) === String(current) ? "on" : ""}" data-v="${esc(v)}">${esc(l)}</button>`).join("")}</span>`;

/** Wire every .seg under root: clicking a button marks it and calls onPick(name, value). */
export function bindSeg(root, onPick) {
  root.querySelectorAll(".seg").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    g.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onPick(g.dataset.seg, b.dataset.v);
  }));
}
