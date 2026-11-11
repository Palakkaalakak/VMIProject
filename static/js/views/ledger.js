// Ledger (#/ledger/ID): every trade with the running position and cash, back-dated order entry, edit/delete with a
// required reason, drift check / rebuild, audit trail, full JSON export. Positions and cash are always a replay of this list.
import { api } from "../api.js";
import { $, esc, fmt, loading, modal, run, table, toast, signClass } from "../ui.js";
import { refreshPortfolios, state } from "../state.js";

const isoLocal = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const toIso = (local) => (local ? new Date(local).toISOString() : undefined);   // browser local time -> UTC instant
const label = (r) => (r.sec_type === "OPT" ? r.key : r.symbol);

export async function render(root, params = {}) {
  await refreshPortfolios();
  const id = params.id ? +params.id : state.portfolios[0]?.id;
  if (!id) { root.innerHTML = `<div class="card">Create a portfolio first.</div>`; return; }
  root.innerHTML = `<div class="card"><div class="inline"><h2>Ledger</h2>
      <select id="lg-pf">${state.portfolios.map((p) => `<option value="${p.id}" ${p.id === id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      <a href="#/portfolios/${id}">← portfolio</a> <a href="#/review/${id}">Review</a> <a href="#/plans/${id}">Plans</a> <a href="#/optionbook/${id}">Option book</a></div>
      <p class="small muted">The ledger is the source of truth: cash and positions are recomputed from these trades. An order added or edited here is a genuine order, treated exactly as if it had been executed that way at that date and time (not a simulation); only the audit trail records that it was entered later. A tranche level at or above its fill price is marked filled.</p>
      <div id="lg-status"></div></div>
    <div id="lg-body">${loading()}</div>`;
  $("#lg-pf", root).addEventListener("change", (e) => (location.hash = `#/ledger/${e.target.value}`));
  await draw(root, id);
}

async function draw(root, id) {
  const [rows, ver, audit] = await Promise.all([api.ledger(id), api.verify(id), api.audit(id)]);
  $("#lg-status", root).innerHTML = verifyHtml(ver) + `<div class="inline">
      <button id="lg-add">+ Add order</button><button id="lg-verify" class="secondary">Check drift</button>
      <button id="lg-rebuild" class="secondary">Rebuild from ledger</button>
      <button id="lg-export" class="secondary">Download everything (JSON)</button></div>`;
  $("#lg-body", root).innerHTML = `<section class="card"><h3>Trades (${rows.length})</h3><div id="lg-table"></div></section>
    <section class="card"><h3>Audit trail</h3><div id="lg-audit"></div></section>`;
  const cols = [
    { key: "ts", label: "Time", render: (r) => esc(String(r.ts).replace("T", " ").slice(0, 16)) + (r.edited ? " ✎" : "") },
    { key: "side", label: "Side", render: (r) => `<b class="${r.side === "BUY" ? "pos" : "neg"}">${r.side}</b>` },
    { key: "symbol", label: "Instrument", render: (r) => `<a href="#/analysis/${esc(r.symbol)}">${esc(label(r))}</a>` },
    { key: "qty", label: "Qty", cls: "num", render: (r) => fmt.num(r.qty, 4) },
    { key: "price", label: "Fill", cls: "num", render: (r) => fmt.money(r.price, 4) },
    { key: "fees", label: "Fees", cls: "num", render: (r) => fmt.money(r.fees) },
    { key: "position_after", label: "Pos after", cls: "num", render: (r) => fmt.num(r.position_after, 4) },
    { key: "realized_after", label: "Realised", cls: "num", render: (r) => `<span class="${signClass(r.realized_after)}">${fmt.money(r.realized_after)}</span>` },
    { key: "cash_after", label: "Cash after", cls: "num", render: (r) => fmt.money(r.cash_after) },
    { key: "kind", label: "Kind", render: (r) => esc(`${r.kind}${r.source && r.source !== "paper" ? " · " + r.source : ""}`) },
    { key: "tags", label: "Tags / why", render: (r) => esc([r.tags, r.thesis || r.note].filter(Boolean).join(" — ")) },
    { key: "_a", label: "", render: () => `<button class="small secondary" data-action="edit">Edit</button> <button class="small danger" data-action="del">Delete</button>` },
  ];
  $("#lg-table", root).appendChild(table(cols, rows, {
    initialSort: { key: "ts", desc: true }, empty: "No trades yet.",
    actions: { edit: (r) => editModal(root, id, r), del: (r) => deleteModal(root, id, r) },
  }));
  $("#lg-audit", root).appendChild(table([
    { key: "ts", label: "When", render: (r) => esc(String(r.ts).replace("T", " ").slice(0, 19)) },
    { key: "action", label: "Action" }, { key: "trade_id", label: "Trade" }, { key: "reason", label: "Reason" },
    { key: "after", label: "Change", render: (r) => `<span class="small">${esc(r.action === "rebuild" ? rebuildDiff(r) : diff(r.before, r.after))}</span>` },
  ], audit, { initialSort: { key: "ts", desc: true }, empty: "No admin changes yet." }));
  $("#lg-add", root).addEventListener("click", () => addModal(root, id));
  $("#lg-verify", root).addEventListener("click", (e) => run(e.target, () => draw(root, id)));
  $("#lg-rebuild", root).addEventListener("click", (e) => {
    const reason = prompt("Rebuild positions and cash from the ledger. Reason?", "manual rebuild");
    if (reason) run(e.target, async () => { await api.rebuild(id, reason); toast("Rebuilt from ledger", "ok"); draw(root, id); });
  });
  $("#lg-export", root).addEventListener("click", (e) => run(e.target, async () => {
    const data = await api.exportAll(id);
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" })), download: `portfolio-${id}-export.json` });
    a.click();
  }));
}

function verifyHtml(v) {
  if (v.ok) return `<p class="note">✔ Stored positions and cash match the ledger (cash ${fmt.money(v.cash_replay)}).</p>`;
  return `<p class="note neg"><b>Drift:</b> stored cash ${fmt.money(v.cash_stored)} vs ledger ${fmt.money(v.cash_replay)}; ${v.position_diffs.length} position(s) differ${v.errors.length ? "; " + esc(v.errors.join("; ")) : ""}. Use “Rebuild from ledger”.</p>`;
}

function rebuildDiff(r) {
  const b = r.before || {}, a = r.after || {};
  const bits = [`cash ${fmt.money(b.cash)} → ${fmt.money(a.cash)}`];
  if ((b.diffs || []).length) bits.push(`${b.diffs.length} position(s) corrected`);
  if ((a.errors || []).length) bits.push(`errors: ${a.errors.join("; ")}`);
  return bits.join("; ");
}

function diff(b, a) {
  if (!b && a) return `added ${a.side} ${a.qty} ${a.key} @ ${a.price}`;
  if (b && !a) return `removed ${b.side} ${b.qty} ${b.key} @ ${b.price}`;
  if (b && a) { const ch = Object.keys(a).filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]) && k !== "context"); return ch.map((k) => `${k}: ${b[k]} → ${a[k]}`).join("; "); }
  return "";
}

const field = (name, label, type = "text", extra = "") => `<label>${label} <input name="${name}" type="${type}" ${extra}></label>`;

function orderForm(r = {}) {
  const opt = r.sec_type === "OPT";
  return `<form class="grid">
    ${field("symbol", "Symbol", "text", `required value="${esc(r.symbol || "")}"`)}
    <label>Side <select name="side"><option ${r.side === "BUY" ? "selected" : ""}>BUY</option><option ${r.side === "SELL" ? "selected" : ""}>SELL</option></select></label>
    ${field("qty", opt ? "Contracts" : "Shares", "number", `step="any" required value="${r.qty ?? ""}"`)}
    ${field("price", "Fill price (per share)", "number", `step="any" required value="${r.price ?? ""}"`)}
    ${field("ts", "Date & time (your local time)", "datetime-local", `required value="${r.ts ? new Date(r.ts).toISOString().slice(0, 16) : isoLocal()}"`)}
    ${field("fees", "Fees $", "number", `step="any" value="${r.fees ?? 0}"`)}
    <label>Type <select name="sec_type"><option value="STK" ${opt ? "" : "selected"}>Stock</option><option value="OPT" ${opt ? "selected" : ""}>Option</option></select></label>
    ${field("expiry", "Option expiry YYYYMMDD", "text", `value="${esc(opt ? r.key.split(" ")[1] : "")}"`)}
    ${field("strike", "Option strike", "number", `step="any" value="${opt ? r.key.split(" ")[2] : ""}"`)}
    <label>Right <select name="right"><option value="">—</option><option ${opt && r.key.endsWith(" C") ? "selected" : ""}>C</option><option ${opt && r.key.endsWith(" P") ? "selected" : ""}>P</option></select></label>
    ${field("tags", "Tags (comma separated)", "text", `value="${esc(r.tags || "")}"`)}
    <label class="wide">Thesis / why this trade <input name="thesis" value="${esc(r.thesis || "")}"></label>
    <label class="wide">Note <input name="note" value="${esc(r.note || "")}"></label>
    <label class="wide"><b>Reason for this admin change (required)</b> <input name="reason" required placeholder="e.g. fill missed while IBKR was offline"></label>
    <label class="check"><input type="checkbox" name="neg"> allow cash to go negative at some point</label>
    <button class="primary">Save</button></form>`;
}

function payload(form) {
  const f = new FormData(form), g = (k) => f.get(k);
  const d = { symbol: g("symbol").toUpperCase(), side: g("side"), qty: +g("qty"), price: +g("price"), ts: toIso(g("ts")),
    fees: +g("fees") || 0, sec_type: g("sec_type"), tags: g("tags"), thesis: g("thesis"), note: g("note") };
  if (d.sec_type === "OPT") Object.assign(d, { expiry: g("expiry"), strike: +g("strike"), right: g("right"), multiplier: 100 });
  return { d, reason: g("reason"), allow_negative_cash: form.neg.checked };
}

function addModal(root, id) {
  const m = modal("Add a real order (back-dated allowed)", orderForm());
  $("form", m.el).addEventListener("submit", (e) => {
    e.preventDefault();
    const { d, reason, allow_negative_cash } = payload(e.target);
    run(e.submitter, async () => { await api.ledgerAdd(id, { ...d, reason, allow_negative_cash }); m.close(); toast("Order added; portfolio rebuilt", "ok"); draw(root, id); });
  });
}

function editModal(root, id, r) {
  const m = modal(`Edit trade #${r.id}`, orderForm(r));
  $("form", m.el).addEventListener("submit", (e) => {
    e.preventDefault();
    const { d, reason, allow_negative_cash } = payload(e.target);
    run(e.submitter, async () => { await api.ledgerUpdate(r.id, { changes: d, reason, allow_negative_cash }); m.close(); toast("Trade updated; portfolio rebuilt", "ok"); draw(root, id); });
  });
}

function deleteModal(root, id, r) {
  const m = modal(`Delete trade #${r.id}`, `<p>${esc(r.side)} ${fmt.num(r.qty, 4)} ${esc(label(r))} @ ${fmt.money(r.price, 4)} on ${esc(String(r.ts).slice(0, 16))}</p>
    <form><label class="wide"><b>Reason (required)</b> <input name="reason" required></label>
    <label class="check"><input type="checkbox" name="neg"> allow cash to go negative</label><button class="danger">Delete trade</button></form>`);
  $("form", m.el).addEventListener("submit", (e) => {
    e.preventDefault();
    run(e.submitter, async () => { await api.ledgerDelete(r.id, { reason: e.target.reason.value, allow_negative_cash: e.target.neg.checked }); m.close(); toast("Trade deleted; portfolio rebuilt", "ok"); draw(root, id); });
  });
}
