// Plans (#/plans/ID): sizing + automation settings of a portfolio and the tranche plan of every stock (buy levels,
// sell levels, auto or alert-only). Levels hit while the app/IBKR was off are back-filled from daily bars.
import { api } from "../api.js";
import { $, esc, fmt, loading, modal, run, table, toast } from "../ui.js";
import { refreshPortfolios, state } from "../state.js";

export async function render(root, params = {}) {
  await refreshPortfolios();
  const id = params.id ? +params.id : state.portfolios[0]?.id;
  if (!id) { root.innerHTML = `<div class="card">Create a portfolio first.</div>`; return; }
  root.innerHTML = `<div class="card"><div class="inline"><h2>Tranche plans &amp; sizing</h2>
      <select id="pl-pf">${state.portfolios.map((p) => `<option value="${p.id}" ${p.id === id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      <a href="#/portfolios/${id}">← portfolio</a> <a href="#/ledger/${id}">Ledger</a></div></div><div id="pl-body">${loading()}</div>`;
  $("#pl-pf", root).addEventListener("change", (e) => (location.hash = `#/plans/${e.target.value}`));
  await draw(root, id);
}

async function draw(root, id) {
  const [d, wls] = await Promise.all([api.plans(id), api.watchlists()]);
  const c = d.settings;
  $("#pl-body", root).innerHTML = `
    <section class="card"><h3>Sizing &amp; automation</h3>
      <form id="pl-set" class="grid">
        <label>Auto-buy at levels <select name="auto_trade"><option value="false" ${c.auto_trade ? "" : "selected"}>No: alert only</option><option value="true" ${c.auto_trade ? "selected" : ""}>Yes: fill automatically</option></select></label>
        <label>Position size from <select name="sizing_mode">
          <option value="watchlist" ${c.sizing_mode === "watchlist" ? "selected" : ""}>Watchlist size (equity ÷ stocks in the list)</option>
          <option value="target" ${c.sizing_mode === "target" ? "selected" : ""}>Target number of positions</option>
          <option value="manual" ${c.sizing_mode === "manual" ? "selected" : ""}>Manual $ per stock</option></select></label>
        <label>Watchlist <select name="watchlist_id"><option value="">—</option>${wls.map((w) => `<option value="${w.id}" ${c.watchlist_id === w.id ? "selected" : ""}>${esc(w.name)} (${w.count ?? ""})</option>`).join("")}</select></label>
        <label>Manual $ per stock <input name="manual_allocation" type="number" step="any" value="${c.manual_allocation ?? ""}"></label>
        <label>Tranches per position <input name="tranches" type="number" min="1" max="10" value="${c.tranches}"></label>
        <label>Regular market hours only <select name="market_hours_only"><option value="true" ${c.market_hours_only ? "selected" : ""}>Yes</option><option value="false" ${c.market_hours_only ? "" : "selected"}>No</option></select></label>
        <label>Fill levels hit while offline <select name="backfill"><option value="true" ${c.backfill ? "selected" : ""}>Yes (back-dated)</option><option value="false" ${c.backfill ? "" : "selected"}>No</option></select></label>
        <button class="primary">Save settings</button></form>
      <p class="small muted">Full allocation per stock right now: <b>${fmt.money(d.full_allocation.full, 0)}</b> (${esc(d.full_allocation.basis)}).
        Backfill uses daily bars: it fills at the level, or at the open if the price gapped through it, dated that day.</p></section>
    <section class="card"><div class="inline"><h3>Plans (${d.plans.length})</h3>
      <button id="pl-new">+ Plan</button>
      <select id="pl-wl"><option value="">From watchlist…</option>${wls.map((w) => `<option value="${w.id}">${esc(w.name)}</option>`).join("")}</select>
      <button id="pl-run" class="secondary">Run now</button></div><div id="pl-table"></div></section>`;
  $("#pl-table", root).appendChild(table([
    { key: "symbol", label: "Stock", render: (r) => `<a href="#/analysis/${esc(r.symbol)}"><b>${esc(r.symbol)}</b></a>` },
    { key: "status", label: "Status" },
    { key: "auto", label: "Auto", render: (r) => (r.auto == null ? `<span class="muted">portfolio (${c.auto_trade ? "on" : "off"})</span>` : r.auto ? "on" : "off") },
    { key: "intrinsic_value", label: "IV", cls: "num", render: (r) => fmt.money(r.intrinsic_value) },
    { key: "buy", label: "Buy levels", render: (r) => levels(r.buy_levels, "buy") },
    { key: "sell", label: "Sell levels", render: (r) => levels(r.sell_levels, "sell") },
    { key: "last_checked", label: "Checked", render: (r) => esc(String(r.last_checked || "").slice(0, 16).replace("T", " ")) },
    { key: "_a", label: "", render: () => `<button class="small secondary" data-action="edit">Edit</button> <button class="small secondary" data-action="hist">History</button> <button class="small danger" data-action="del">Delete</button>` },
  ], d.plans, { empty: "No plans: add one, or build them from a watchlist's support levels.", actions: {
    edit: (r) => editModal(root, id, r), hist: (r) => modal(`${r.symbol} history`, `<pre class="small">${esc(JSON.stringify(r.history, null, 1))}</pre>`),
    del: (r, b) => confirm(`Delete the plan for ${r.symbol}?`) && run(b, async () => { await api.deletePlan(id, r.symbol); draw(root, id); }) } }));
  $("#pl-set", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target, num = (v) => (v === "" ? null : +v);
    run(e.submitter, async () => {
      await api.savePfSettings(id, { auto_trade: f.auto_trade.value === "true", sizing_mode: f.sizing_mode.value, watchlist_id: num(f.watchlist_id.value),
        manual_allocation: num(f.manual_allocation.value), tranches: +f.tranches.value, market_hours_only: f.market_hours_only.value === "true", backfill: f.backfill.value === "true" });
      toast("Settings saved", "ok"); draw(root, id);
    });
  });
  $("#pl-new", root).addEventListener("click", () => editModal(root, id, null));
  $("#pl-wl", root).addEventListener("change", (e) => e.target.value && run(e.target, async () => {
    const r = await api.plansFromWatchlist(id, +e.target.value);
    toast(`${r.created.length} plans created${Object.keys(r.skipped).length ? `, ${Object.keys(r.skipped).length} skipped` : ""}`, "ok"); draw(root, id);
  }));
  $("#pl-run", root).addEventListener("click", (e) => run(e.target, async () => { const ev = await api.runPlans(id); toast(ev.length ? `${ev.length} event(s): ${ev.map((x) => x.event).join(", ")}` : "Nothing to do", "ok"); draw(root, id); }));
}

const COLOR = { filled: "pos", skipped: "muted", alerted: "", pending: "" };
const levels = (ls, side) => (ls || []).map((l) => `<span class="small ${COLOR[l.status] || ""}" title="${esc(l.note || "")}">${l.price != null ? fmt.money(l.price) : `IV+${(l.over_iv * 100).toFixed(0)}%`} × ${(l.fraction * 100).toFixed(0)}% <i>${esc(l.status)}</i></span>`).join("<br>") || "<span class='muted'>—</span>";

// one level per line: "price fraction" or for sells "+50% fraction" (percent over the plan's IV)
const toText = (ls) => (ls || []).map((l) => `${l.price != null ? l.price : "+" + l.over_iv * 100 + "%"} ${l.fraction}`).join("\n");
function parse(text) {
  return text.split("\n").map((s) => s.trim()).filter(Boolean).map((line) => {
    const [a, b] = line.split(/\s+/);
    const x = a.endsWith("%") ? { over_iv: parseFloat(a) / 100 } : { price: parseFloat(a) };
    if (b) x.fraction = parseFloat(b);
    return x;
  });
}

function editModal(root, id, r) {
  const m = modal(r ? `Plan: ${r.symbol}` : "New plan", `<form class="grid">
    <label>Stock <input name="symbol" required value="${esc(r?.symbol || "")}" ${r ? "readonly" : ""}></label>
    <label>Intrinsic value <input name="iv" type="number" step="any" value="${r?.intrinsic_value ?? ""}"></label>
    <label>Only buy below IV <select name="below"><option value="true" ${r?.require_below_iv === false ? "" : "selected"}>Yes</option><option value="false" ${r?.require_below_iv === false ? "selected" : ""}>No</option></select></label>
    <label>Full allocation $ (blank = portfolio sizing) <input name="alloc" type="number" step="any" value="${r?.allocation ?? ""}"></label>
    <label>Category multiplier (½ speculative, ¾ narrow) <input name="mult" type="number" step="any" value="${r?.multiplier ?? 1}"></label>
    <label>Auto <select name="auto"><option value="">follow portfolio</option><option value="true" ${r?.auto === true ? "selected" : ""}>on</option><option value="false" ${r?.auto === false ? "selected" : ""}>off</option></select></label>
    <label class="wide">Buy levels (one per line: <code>price fraction</code>, fractions of the full allocation; blank fraction = equal split)<textarea name="buy" rows="4">${esc(toText(r?.buy_levels))}</textarea></label>
    <label class="wide">Sell levels (<code>price fraction</code> or <code>+50% fraction</code> = 50% over IV; fraction of shares held)<textarea name="sell" rows="3">${esc(toText(r?.sell_levels))}</textarea></label>
    <label class="wide">Notes <input name="notes" value="${esc(r?.notes || "")}"></label>
    <button class="primary">Save plan</button></form>`);
  $("form", m.el).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target, num = (v) => (v === "" ? null : +v);
    run(e.submitter, async () => {
      await api.savePlan(id, { symbol: f.symbol.value, intrinsic_value: num(f.iv.value), require_below_iv: f.below.value === "true", allocation: num(f.alloc.value),
        multiplier: +f.mult.value || 1, auto: f.auto.value === "" ? null : f.auto.value === "true", buy_levels: parse(f.buy.value), sell_levels: parse(f.sell.value),
        notes: f.notes.value, status: "active" });
      m.close(); toast("Plan saved", "ok"); draw(root, id);
    });
  });
}
