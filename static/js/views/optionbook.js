// Option book (#/optionbook/ID): saved payoff profiles. Everything is recomputed from the SAVED inputs (legs, spot, IV,
// date), so positions can be analysed with no IBKR connection and no live quotes.
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, toast, signClass } from "../ui.js";
import { heat, lineChart } from "../charts.js";
import { refreshPortfolios, state } from "../state.js";

const today = () => new Date().toISOString().slice(0, 10);

export async function render(root, params = {}) {
  await refreshPortfolios();
  const id = params.id ? +params.id : state.portfolios[0]?.id;
  root.innerHTML = `<div class="card"><div class="inline"><h2>Option book</h2>
      <select id="ob-pf">${state.portfolios.map((p) => `<option value="${p.id}" ${p.id === id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      <a href="#/portfolios/${id}">← portfolio</a> <a href="#/options">Options chain</a></div>
      <p class="small muted">Snapshots are saved automatically after every option trade and once a day. Change the price, IV or date below to see the P&L without any live data.</p>
      <form id="ob-new" class="inline"><input name="symbol" placeholder="Ticker" required style="width:6rem">
        <button class="secondary">Snapshot this portfolio's open options</button>
        <button type="button" id="ob-manual" class="secondary">Manual what-if position…</button></form></div>
    <div id="ob-list" class="card"></div><div id="ob-detail"></div>`;
  $("#ob-pf", root).addEventListener("change", (e) => (location.hash = `#/optionbook/${e.target.value}`));
  $("#ob-new", root).addEventListener("submit", (e) => {
    e.preventDefault();
    run(e.submitter, async () => { const s = await api.createSnapshot({ symbol: e.target.symbol.value, portfolio_id: id, label: "manual snapshot" }); toast("Snapshot saved", "ok"); await list(root, id); open(root, s.id); });
  });
  $("#ob-manual", root).addEventListener("click", () => manual(root, id));
  await list(root, id);
  if (params.sid) open(root, +params.sid);
}

async function list(root, id) {
  const rows = await api.snapshots({ portfolio_id: id });
  const box = $("#ob-list", root);
  box.innerHTML = `<h3>Saved snapshots (${rows.length})</h3>`;
  box.appendChild(table([
    { key: "ts", label: "Saved", render: (r) => esc(String(r.ts).replace("T", " ").slice(0, 16)) },
    { key: "symbol", label: "Underlying", render: (r) => `<b>${esc(r.symbol)}</b>` },
    { key: "reason", label: "Why" }, { key: "label", label: "Label" },
    { key: "spot", label: "Spot then", cls: "num", sort: (r) => r.inputs.spot, render: (r) => fmt.money(r.inputs.spot) },
    { key: "legs", label: "Legs", render: (r) => esc(r.inputs.legs.map((l) => (l.type === "STK" ? `${l.qty} sh` : `${l.qty > 0 ? "+" : ""}${l.qty} ${l.strike}${l.right} ${l.expiry}`)).join(" · ")) },
    { key: "_a", label: "", render: () => `<button class="small secondary" data-action="open">Open</button> <button class="small danger" data-action="del">Delete</button>` },
  ], rows, { initialSort: { key: "ts", desc: true }, empty: "No snapshots yet: trade an option or use the buttons above.",
    actions: { open: (r) => open(root, r.id), del: (r, b) => confirm("Delete this snapshot?") && run(b, async () => { await api.deleteSnapshot(r.id); list(root, id); }) } }));
}

async function open(root, sid, over = {}) {
  const box = $("#ob-detail", root);
  box.innerHTML = loading();
  const snap = await api.snapshot(sid);
  const inp = snap.inputs;
  const rc = await api.recompute(sid, over);
  const used = rc.inputs_used, r = rc.result;
  const keys = Object.keys(r.curves);
  const names = { expiry: "At expiry" };
  box.innerHTML = `<section class="card"><h3>${esc(snap.symbol)} · ${esc(snap.label)} <span class="small muted">saved ${esc(String(snap.ts).slice(0, 16))} (${esc(snap.reason)})</span></h3>
    <form id="ob-re" class="inline"><label>Spot <input name="spot" type="number" step="any" value="${used.spot}" style="width:7rem"></label>
      <label>IV shift (pts, +0.05 = +5 vol) <input name="iv" type="number" step="0.01" value="${used.iv_shift}" style="width:6rem"></label>
      <label>Valuation date <input name="as_of" type="date" value="${used.as_of}"></label>
      <button class="primary">Recompute</button><button type="button" id="ob-reset" class="secondary">Back to saved</button></form>
    <div class="kpis"><div class="kpi"><span>P&L now (model)</span><b class="${signClass(r.pnl_now)}">${fmt.money(r.pnl_now)}</b></div>
      <div class="kpi"><span>Value now</span><b>${fmt.money(r.value_now)}</b></div>
      <div class="kpi"><span>Max profit (range)</span><b>${r.unbounded_upside ? "unbounded" : fmt.money(r.max_profit_in_range)}</b></div>
      <div class="kpi"><span>Max loss (range)</span><b class="neg">${fmt.money(r.max_loss_in_range)}</b></div>
      <div class="kpi"><span>Breakevens</span><b>${r.breakevens.map((b) => fmt.money(b)).join(" / ") || "—"}</b></div>
      <div class="kpi"><span>Δ / Γ / Θ per day / ν per vol pt</span><b class="small">${["delta", "gamma", "theta", "vega"].map((k) => fmt.num(r.greeks[k], 2)).join(" / ")}</b></div></div>
    ${lineChart({ series: keys.map((k, i) => ({ name: names[k] || `Date ${k}`, xs: r.spots, ys: r.curves[k], dash: k === "expiry" ? "" : i ? "5 3" : "" })), xLabel: "Underlying price", yLabel: "P&L $", vlines: [{ x: used.spot, label: "spot" }], fmtX: (v) => v.toFixed(0) })}
    <p class="small muted">Legs (IV used per leg): ${esc(inp.legs.map((l) => (l.type === "STK" ? `${l.qty} sh @ ${l.entry}` : `${l.qty} × ${l.strike}${l.right} ${l.expiry} @ ${l.entry} (IV ${fmt.pct(l.iv, 0)}${l.iv_source ? ", " + l.iv_source : ""})`)).join("; "))}</p></section>
    <section class="card"><h3>Scenario grids: underlying move × IV change</h3><div class="inline">${keys.map((k, i) => `<button class="secondary ${i ? "" : "active"}" data-k="${k}">${esc(names[k] || k)}</button>`).join("")}</div><div id="ob-grid"></div></section>`;
  const grid = (k) => {
    const sc = r.scenarios, g = sc.grids[k], max = Math.max(...g.flat().map(Math.abs));
    $("#ob-grid", root).innerHTML = `<table class="compact"><thead><tr><th>Move \\ IV</th>${sc.iv_shifts.map((s) => `<th class="num">${s > 0 ? "+" : ""}${(s * 100).toFixed(0)} pts</th>`).join("")}</tr></thead><tbody>
      ${sc.moves.map((m, i) => `<tr><th>${m > 0 ? "+" : ""}${(m * 100).toFixed(0)}% (${fmt.money(used.spot * (1 + m), 0)})</th>${g[i].map((v) => `<td class="num" style="${heat(v, max)}">${fmt.money(v, 0)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  };
  grid(keys[0]);
  box.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => { grid(b.dataset.k); box.querySelectorAll("[data-k]").forEach((x) => x.classList.toggle("active", x === b)); }));
  $("#ob-re", box).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    run(e.submitter, () => open(root, sid, { spot: +f.spot.value, iv_shift: +f.iv.value, as_of: f.as_of.value }));
  });
  $("#ob-reset", box).addEventListener("click", (e) => run(e.target, () => open(root, sid)));
}

function manual(root, id) {
  const box = $("#ob-detail", root);
  box.innerHTML = `<section class="card"><h3>Manual what-if position</h3>
    <form id="ob-man" class="grid"><label>Underlying <input name="symbol" required></label><label>Spot <input name="spot" type="number" step="any" required></label>
      <label>As-of date <input name="as_of" type="date" value="${today()}"></label>
      <label class="wide">Legs, one per line: <code>C|P  strike  expiry(YYYYMMDD)  qty(+long/-short)  entry premium  [iv]</code> or <code>STK  shares  entry</code>
        <textarea name="legs" rows="5" placeholder="P 100 20270115 -1 3.00&#10;STK 100 98"></textarea></label>
      <button class="primary">Save &amp; open</button></form></section>`;
  $("#ob-man", box).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const legs = f.legs.value.split("\n").map((l) => l.trim().split(/\s+/)).filter((p) => p[0]).map((p) => p[0].toUpperCase() === "STK"
      ? { type: "STK", qty: +p[1], entry: +p[2], multiplier: 1 }
      : { type: "OPT", right: p[0].toUpperCase(), strike: +p[1], expiry: p[2], qty: +p[3], entry: +p[4], iv: p[5] ? +p[5] : undefined });
    run(e.submitter, async () => { const s = await api.createSnapshot({ symbol: f.symbol.value, portfolio_id: id, spot: +f.spot.value, as_of: f.as_of.value, legs, label: "manual what-if" }); await list(root, id); open(root, s.id); });
  });
}
