// Shared UI helpers: formatting, DOM building, toasts, sortable tables. No feature logic lives here.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const fmt = {
  money: (v, d = 2) => (v == null || isNaN(v) ? "—" : "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })),
  num: (v, d = 2) => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d })),
  pct: (v, d = 1) => (v == null || isNaN(v) ? "—" : (v * 100).toFixed(d) + "%"),
  big: (v) => {
    if (v == null || isNaN(v)) return "—";
    const a = Math.abs(v);
    return a >= 1e12 ? (v / 1e12).toFixed(2) + "T" : a >= 1e9 ? (v / 1e9).toFixed(2) + "B" : a >= 1e6 ? (v / 1e6).toFixed(1) + "M" : fmt.num(v, 0);
  },
  date: (v) => (v ? String(v).slice(0, 10) : "—"),
  expiry: (v) => (v && v.length === 8 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}` : v || "—"),
};

export const signClass = (v) => (v == null ? "" : v > 0 ? "pos" : v < 0 ? "neg" : "");
export const badge = (ok, yes = "PASS", no = "FAIL", na = "N/A") =>
  ok === null || ok === undefined ? `<span class="badge na">${na}</span>` : ok ? `<span class="badge ok">${yes}</span>` : `<span class="badge bad">${no}</span>`;

export function toast(msg, kind = "info", ms = 4000) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// Wrap an async action: shows errors as toasts, disables the trigger button while running.
export async function run(btn, fn) {
  if (btn) { btn.disabled = true; btn.dataset.label ??= btn.textContent; btn.textContent = "…"; }
  try { return await fn(); }
  catch (e) { toast(e.message || String(e), "error", 7000); }
  finally { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; } }
}

export const loading = (text = "Loading…") => `<div class="loading"><span class="spinner"></span>${esc(text)}</div>`;

/**
 * Sortable table. columns: [{key, label, render?(row) -> html, sort?(row) -> value, cls?}]
 * Returns an element; clicking headers re-sorts client-side (stable, nulls last).
 * Row buttons: render `<button data-action="name">` in a cell and pass actions: {name: (row, btn) => …};
 * clicks are delegated, so cells stay pure HTML strings.
 */
export function table(columns, rows, { onRow, actions = {}, empty = "No data", initialSort } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  let sortKey = initialSort?.key, desc = initialSort?.desc ?? true;
  const val = (c, r) => (c.sort ? c.sort(r) : r[c.key]);
  const draw = () => {
    const col = columns.find((c) => c.key === sortKey);
    const data = col ? [...rows].sort((a, b) => {
      const x = val(col, a), y = val(col, b);
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (desc ? -1 : 1);
    }) : rows;
    wrap.innerHTML = `<table><thead><tr>${columns.map((c) =>
      `<th data-k="${c.key}" class="${c.cls || ""} ${c.key === sortKey ? (desc ? "desc" : "asc") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
      <tbody>${data.length ? data.map((r, i) => `<tr data-i="${rows.indexOf(r)}">${columns.map((c) =>
        `<td class="${c.cls || ""}">${c.render ? c.render(r) : esc(r[c.key] ?? "—")}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${columns.length}" class="muted center">${esc(empty)}</td></tr>`}</tbody></table>`;
    $$("th", wrap).forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k; desc = sortKey === k ? !desc : true; sortKey = k; draw();
    }));
  };
  wrap.addEventListener("click", (ev) => {
    const tr = ev.target.closest("tbody tr[data-i]");
    if (!tr) return;
    const row = rows[+tr.dataset.i];
    const btn = ev.target.closest("[data-action]");
    if (btn && actions[btn.dataset.action]) return actions[btn.dataset.action](row, btn);
    if (onRow && !ev.target.closest("button, a, input, select")) onRow(row);
  });
  draw();
  return wrap;
}

export function modal(title, html) {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal"><header><h3>${esc(title)}</h3><button class="icon close" aria-label="close">✕</button></header><div class="modal-body">${html}</div></div>`;
  const close = () => back.remove();
  back.addEventListener("click", (e) => { if (e.target === back) close(); });
  $(".close", back).addEventListener("click", close);
  document.body.appendChild(back);
  return { el: back, close };
}
