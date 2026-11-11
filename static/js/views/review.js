// Review (#/review/ID): what the trades taught us. Statistics, behaviour flags, breakdowns, every FIFO lot with its
// path and what happened after the sale, what-if studies (hold, exit over IV, tranche exits, stops, covered calls…)
// and the equity curve.
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, signClass } from "../ui.js";
import { lineChart } from "../charts.js";
import { refreshPortfolios, state } from "../state.js";

const WHAT_IFS = {
  hold_instead: { label: "Keep instead of sell", params: [] },
  exit_over_iv: { label: "Sell everything at X over the IV recorded at entry", params: [["pct", "X (0.5 = 50% over IV)", 0.5]] },
  exit_tranches: { label: "Sell in tranches over IV", params: [["levels", "Levels pct:fraction,…", "0.5:0.5,1.0:0.5"]] },
  stop_target: { label: "Stop-loss / take-profit", params: [["stop", "Stop (0.2 = -20%)", 0.2], ["target", "Target (0.5 = +50%)", ""]] },
  hold_days: { label: "Hold exactly N days", params: [["days", "Days", 365]] },
  entry_all_at_once: { label: "All shares at the first tranche's price", params: [] },
  covered_calls: { label: "Sell covered calls while held", params: [["otm", "OTM (0.1 = 10%)", 0.1], ["dte", "Days to expiry", 30], ["iv", "IV (blank = realised vol)", ""]] },
  benchmark: { label: "Same money into a benchmark", params: [["symbol", "Symbol", "SPY"]] },
};

export async function render(root, params = {}) {
  await refreshPortfolios();
  const id = params.id ? +params.id : state.portfolios[0]?.id;
  if (!id) { root.innerHTML = `<div class="card">Create a portfolio first.</div>`; return; }
  root.innerHTML = `<div class="card"><div class="inline"><h2>Trade review</h2>
      <select id="rv-pf">${state.portfolios.map((p) => `<option value="${p.id}" ${p.id === id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
      <a href="#/portfolios/${id}">← portfolio</a> <a href="#/ledger/${id}">Ledger</a></div>
      <p class="small muted">Built from the ledger, the context saved on every trade and daily prices. What-ifs use daily closes (approximate; dividends ignored).</p></div>
    <div id="rv-body">${loading("Reading the ledger and prices…")}</div>`;
  $("#rv-pf", root).addEventListener("change", (e) => (location.hash = `#/review/${e.target.value}`));
  const [s, curve] = await Promise.all([api.review(id), api.equityCurve(id).catch(() => null)]);
  const st = s.stocks;
  $("#rv-body", root).innerHTML = `
    <section class="card"><div class="kpis">
      ${kpi("Closed lots", st.closed)}${kpi("Win rate", fmt.pct(st.win_rate))}${kpi("Avg win", fmt.money(st.avg_win))}${kpi("Avg loss", fmt.money(st.avg_loss))}
      ${kpi("Profit factor", fmt.num(st.profit_factor))}${kpi("Expectancy / lot", fmt.money(st.expectancy))}${kpi("Avg hold (days)", fmt.num(st.avg_hold_days, 0))}
      ${kpi("Total P&L", `<span class="${signClass(st.total_pnl)}">${fmt.money(st.total_pnl)}</span>`)}${kpi("Fees", fmt.money(s.fees))}${kpi("Slippage", fmt.money(s.slippage))}</div></section>
    <section class="card"><h3>Behaviour flags</h3>${flags(s.flags)}</section>
    <section class="card"><h3>Equity curve</h3><div id="rv-curve"></div></section>
    <section class="card"><h3>What if…</h3>${whatIfForm()}<div id="rv-wi" class="muted small">Pick a scenario and run it.</div></section>
    <section class="card"><h3>Breakdowns</h3><div id="rv-groups"></div></section>
    <section class="card"><h3>Every lot (FIFO)</h3><div id="rv-lots"></div></section>`;
  if (curve?.points?.length) {
    $("#rv-curve", root).innerHTML = `<p class="small muted">${esc(curve.source)} · max drawdown ${fmt.pct(curve.max_drawdown)}</p>` +
      lineChart({ series: [{ name: "Equity $", xs: curve.points.map((_, i) => i), ys: curve.points.map((p) => p.equity) }], zero: false, xLabel: `${curve.points[0].day} → ${curve.points.at(-1).day}`, fmtX: (v) => curve.points[Math.round(v)]?.day.slice(2) || "" });
  } else $("#rv-curve", root).innerHTML = `<p class="muted">Not enough history yet.</p>`;
  groups($("#rv-groups", root), s.breakdowns);
  $("#rv-lots", root).appendChild(table(LOT_COLS, s.lots, { initialSort: { key: "entry_ts", desc: true }, empty: "No lots yet." }));
  const form = $("#rv-wif", root);
  const drawParams = () => {
    const w = WHAT_IFS[form.name.value];
    $("#rv-wparams", root).innerHTML = w.params.map(([k, l, d]) => `<label>${esc(l)} <input name="${k}" value="${d}" style="width:9rem"></label>`).join("");
  };
  form.name.addEventListener("change", drawParams);
  drawParams();
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = {};
    new FormData(form).forEach((v, k) => { if (k !== "name" && v !== "") q[k] = v; });
    run(e.submitter, async () => { $("#rv-wi", root).innerHTML = whatIfHtml(await api.whatIf(id, form.name.value, q)); });
  });
}

const kpi = (l, v) => `<div class="kpi"><span>${esc(l)}</span><b>${v ?? "—"}</b></div>`;
const flags = (f) => Object.entries(f).map(([k, v]) => `<p class="small"><b>${esc(k.replaceAll("_", " "))}</b> (${v.length}): ${v.length ? esc(v.join(", ")) : "<span class='muted'>none</span>"}</p>`).join("");

function whatIfForm() {
  return `<form id="rv-wif" class="inline"><select name="name">${Object.entries(WHAT_IFS).map(([k, w]) => `<option value="${k}">${esc(w.label)}</option>`).join("")}</select>
    <span id="rv-wparams" class="inline"></span><button class="primary">Run</button></form>`;
}

function whatIfHtml(r) {
  const rows = r.lots.map((l) => `<tr><td>${esc(l.key)}</td><td>${esc(l.entry || "")}</td><td class="num">${fmt.money(l.actual_pnl)}</td><td class="num">${fmt.money(l.alt_pnl)}</td>
    <td class="num ${signClass((l.alt_pnl ?? 0) - (l.actual_pnl ?? 0))}">${l.alt_pnl == null || l.actual_pnl == null ? "—" : fmt.money(l.alt_pnl - l.actual_pnl)}</td>
    <td class="small">${esc(l.how || l.alt_exit || (l.calls_net != null ? `calls net ${fmt.money(l.calls_net)}` : ""))}</td></tr>`).join("");
  return `<p><b>${esc(r.what_if)}</b> · actual ${fmt.money(r.actual_pnl)} · alternative ${fmt.money(r.alternative_pnl)} ·
    <b class="${signClass(r.difference)}">difference ${fmt.money(r.difference)}</b></p>
    <table class="compact"><thead><tr><th>Lot</th><th>Entry</th><th>Actual</th><th>Alternative</th><th>Δ</th><th>How</th></tr></thead><tbody>${rows || `<tr><td colspan="6" class="muted">No lots.</td></tr>`}</tbody></table>
    ${(r.notes || []).map((n) => `<p class="note small">${esc(n)}</p>`).join("")}${r.skipped_no_iv?.length ? `<p class="small muted">Skipped (no IV recorded at entry): ${esc(r.skipped_no_iv.join(", "))}</p>` : ""}`;
}

function groups(box, g) {
  for (const [name, d] of Object.entries(g)) {
    const rows = Object.entries(d).map(([k, v]) => ({ group: k, ...v }));
    const h = document.createElement("h4"); h.textContent = name.replaceAll("_", " ");
    box.appendChild(h);
    box.appendChild(table([
      { key: "group", label: "Group" }, { key: "lots", label: "Lots", cls: "num" }, { key: "closed", label: "Closed", cls: "num" },
      { key: "win_rate", label: "Win rate", cls: "num", render: (r) => fmt.pct(r.win_rate) }, { key: "avg_return", label: "Avg return", cls: "num", render: (r) => fmt.pct(r.avg_return) },
      { key: "total_pnl", label: "P&L", cls: "num", render: (r) => `<span class="${signClass(r.total_pnl)}">${fmt.money(r.total_pnl)}</span>` },
      { key: "profit_factor", label: "PF", cls: "num", render: (r) => fmt.num(r.profit_factor) }, { key: "avg_hold_days", label: "Hold d", cls: "num", render: (r) => fmt.num(r.avg_hold_days, 0) },
    ], rows, { initialSort: { key: "total_pnl" } }));
  }
}

const pct = (k) => (r) => `<span class="${signClass(r.stats[k])}">${fmt.pct(r.stats[k])}</span>`;
const LOT_COLS = [
  { key: "key", label: "Lot", render: (r) => `<b>${esc(r.key)}</b> <span class="small muted">${esc(r.direction)}</span>` },
  { key: "qty", label: "Qty", cls: "num", render: (r) => fmt.num(r.qty, 4) },
  { key: "entry_ts", label: "Entry", render: (r) => `${esc(r.entry_ts.slice(0, 10))} @ ${fmt.money(r.entry_price)}` },
  { key: "exit_ts", label: "Exit", render: (r) => (r.exit_ts ? `${esc(r.exit_ts.slice(0, 10))} @ ${fmt.money(r.exit_price)}` : "<span class='muted'>open</span>") },
  { key: "return", label: "Return", cls: "num", sort: (r) => r.stats.return, render: pct("return") },
  { key: "pnl", label: "P&L", cls: "num", sort: (r) => r.stats.pnl ?? r.stats.unrealized_pnl, render: (r) => fmt.money(r.stats.pnl ?? r.stats.unrealized_pnl) },
  { key: "hold", label: "Days", cls: "num", sort: (r) => r.stats.hold_days, render: (r) => r.stats.hold_days ?? "—" },
  { key: "mfe", label: "Best", cls: "num", sort: (r) => r.stats.mfe, render: pct("mfe") },
  { key: "mae", label: "Worst", cls: "num", sort: (r) => r.stats.mae, render: pct("mae") },
  { key: "a90", label: "+90d after sale", cls: "num", sort: (r) => r.stats.after_90d, render: pct("after_90d") },
  { key: "atoday", label: "Since sale", cls: "num", sort: (r) => r.stats.after_today, render: pct("after_today") },
  { key: "kept", label: "If kept $", cls: "num", sort: (r) => r.stats.if_kept_extra_pnl, render: (r) => `<span class="${signClass(r.stats.if_kept_extra_pnl)}">${fmt.money(r.stats.if_kept_extra_pnl)}</span>` },
  { key: "evi", label: "Entry vs IV", cls: "num", sort: (r) => r.stats.entry_vs_iv, render: pct("entry_vs_iv") },
  { key: "mos", label: "MOS at entry", cls: "num", sort: (r) => r.entry.margin_of_safety, render: (r) => fmt.pct(r.entry.margin_of_safety) },
  { key: "why", label: "Tags / thesis", sort: (r) => r.entry.tags?.join(","), render: (r) => esc([...(r.entry.tags || []), r.entry.thesis].filter(Boolean).join(" — ")) },
];
