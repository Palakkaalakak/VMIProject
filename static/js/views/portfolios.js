// Paper portfolios: summaries, positions (marked to market), trade log, create / reset / delete.
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, toast, signClass } from "../ui.js";
import { refreshPortfolios, state } from "../state.js";
import { pieChart, bindChartTips } from "../charts.js";
import { mountHistoryChart } from "../chart_view.js";

let disposeHistory;
export function destroy() { disposeHistory?.(); disposeHistory = undefined; }

export async function render(root, params = {}) {
  root.innerHTML = loading("Loading portfolios…");
  await refreshPortfolios();
  const sel = params.id ? +params.id : state.portfolios[0]?.id;
  root.innerHTML = `
    <section class="card">
      <div class="tabs" id="pf-tabs">${state.portfolios.map((p) => `
        <a href="#/portfolios/${p.id}" class="tab ${p.id === sel ? "active" : ""}">${esc(p.name)}
          <span class="${signClass(p.total_return)}">${fmt.pct(p.total_return)}</span></a>`).join("")}
        <button id="pf-new" class="secondary">+ New</button></div>
    </section>
    <div id="pf-detail"></div>`;
  $("#pf-new", root).addEventListener("click", (e) => run(e.target, () => createPortfolio()));
  if (sel) detail($("#pf-detail", root), sel);
}

async function createPortfolio() {
  const name = prompt("Portfolio name (e.g. Growth 2, Dividend)");
  if (!name) return;
  const style = (prompt("Style: growth | defensive | balanced", "balanced") || "balanced").toLowerCase();
  const cash = parseFloat(prompt("Starting cash", "100000") || "100000");
  const wls = await api.watchlists().catch(() => []);
  const wl = wls.length ? prompt(`Size positions from which watchlist? Type its number, or leave empty for a target count.\n${wls.map((w) => `${w.id}: ${w.name} (${w.count})`).join("\n")}`, "") : "";
  const auto = confirm("Fill tranche levels automatically (paper)?\nOK = auto-buy when a level is hit, Cancel = alert only. You can change this later in Plans.");
  const p = await api.createPortfolio({ name, style, cash, watchlist_id: wl ? +wl : null, auto_trade: auto });
  toast(`Created ${p.name}`, "ok");
  location.hash = `#/portfolios/${p.id}`;
}

async function detail(box, id) {
  destroy();
  box.innerHTML = loading("Marking positions to market…");
  const [p, trades, lists] = await Promise.all([api.portfolio(id), api.trades(id), api.watchlists().catch(() => [])]);
  if (!box.isConnected) return;
  const wl = lists.find((w) => w.id === p.settings?.watchlist_id);   // the watchlist this portfolio is sized from
  box.innerHTML = `
    <section class="card">
      <div class="kpis">
        <div class="kpi"><span>Equity</span><b>${fmt.money(p.equity)}</b></div>
        <div class="kpi"><span>Cash</span><b>${fmt.money(p.cash)}</b></div>
        <div class="kpi"><span>Free cash</span><b>${fmt.money(p.free_cash)}</b></div>
        <div class="kpi"><span>CSP collateral</span><b>${fmt.money(p.reserved_cash)}</b></div>
        <div class="kpi"><span>Unrealised</span><b class="${signClass(p.unrealized_pnl)}">${fmt.money(p.unrealized_pnl)}</b></div>
        <div class="kpi"><span>Realised</span><b class="${signClass(p.realized_pnl)}">${fmt.money(p.realized_pnl)}</b></div>
        <div class="kpi"><span>Total return</span><b class="${signClass(p.total_return)}">${fmt.pct(p.total_return)}</b></div>
        <div class="kpi"><span>Full allocation</span><b>${fmt.money(p.full_allocation, 0)}</b><small>${p.target_positions} positions · ${esc(p.style)}</small></div>
      </div>
      <div class="inline">
        ${wl ? `<a class="button" href="#/watchlists/${wl.id}" title="The watchlist this portfolio is sized from">Watchlist: ${esc(wl.name)} (${wl.count})</a>` : ""}
        <a class="button" href="#/plans/${id}">Plans &amp; sizing</a> <a class="button" href="#/ledger/${id}">Ledger (edit orders)</a>
        <a class="button" href="#/review/${id}">Review &amp; what-ifs</a> <a class="button" href="#/optionbook/${id}">Option book</a>
        <button type="button" id="pf-history-jump" class="secondary">History &amp; charts</button>
        <button type="button" id="pf-pre" class="secondary" title="Value the portfolio as if the market opened at the current pre-market prices. Needs IBKR connected.">View with pre-market levels</button>
        <button id="pf-reset" class="secondary">Reset</button>
        <button id="pf-delete" class="danger">Delete</button>
      </div>
    </section>
    <section class="card" id="pf-pre-box" hidden></section>
    <section class="card" id="pf-history"></section>
    <section class="card"><h3>Positions</h3><div id="pf-pos"></div></section>
    <section class="card" id="pf-break"><h3>Breakdown <span class="muted small">by market value · cash is its own slice · option positions are one "Options" slice (absolute market value of the legs)</span></h3>
      <div class="inline"><span class="seg" id="pf-by">${BY.map(([k, l]) => `<button type="button" class="secondary small ${k === "sector" ? "on" : ""}" data-v="${k}">${esc(l)}</button>`).join("")}</span></div>
      <div class="pf-break"><div id="pf-pie"></div><div id="pf-tags"></div></div></section>
    <section class="card"><h3>Trades</h3><div id="pf-trades"></div></section>`;
  $("#pf-pos", box).appendChild(table(POS_COLS, p.positions || [], { actions: posActions(id, () => detail(box, id)), empty: "No positions — analyse a stock and buy a tranche.", initialSort: { key: "market_value" } }));
  $("#pf-trades", box).appendChild(table(TRADE_COLS, trades || [], { empty: "No trades yet", initialSort: { key: "ts" } }));
  breakdownCard(box, id, p.equity);
  const history = $("#pf-history", box);
  disposeHistory = historyCard(history, p);
  $("#pf-history-jump", box).onclick = () => history.scrollIntoView({ block: "start", behavior: "smooth" });
  $("#pf-pre", box).addEventListener("click", async (e) => {
    const out = $("#pf-pre-box", box), btn = e.currentTarget;
    out.hidden = false; btn.disabled = true; out.innerHTML = loading("Asking IBKR for extended-hours prices…");
    try {
      const v = await api.premarket(id);
      const k = (label, val, cls = "") => `<div class="kpi"><span>${label}</span><b class="${cls}">${val}</b></div>`;
      out.innerHTML = `<h3>Pre-market view <span class="muted small">if the market opened at these prices · view only</span></h3>
        ${v.session === "extended" ? "" : `<p class="small neg">The market is not in an extended session right now (${esc(v.session)}): there are no live pre-market prices, so stocks use the previous trading day's after-hours price.</p>`}
        <div class="kpis">${k("Equity at these prices", fmt.money(v.equity))}${k("Equity now", fmt.money(v.equity_now))}
          ${k("Change", `${fmt.money(v.change)} (${fmt.pct(v.change_pct, 2)})`, signClass(v.change))}${k("Unrealised", fmt.money(v.unrealized_pnl), signClass(v.unrealized_pnl))}</div>
        ${v.missing.length ? `<p class="small muted">Neither a pre-market nor a previous after-hours price (kept at the current mark): ${esc(v.missing.join(", "))}</p>` : ""}
        <table class="compact"><thead><tr><th>Position</th><th>Qty</th><th>Previous close</th><th>Extended price</th><th>Source</th><th>Move</th><th>Value</th><th>Value change</th><th>Weight</th></tr></thead><tbody>${v.positions.map((r) => `<tr><td>${esc(r.sec_type === "OPT" ? r.key : r.symbol)}</td><td class="num">${fmt.num(r.qty, 4)}</td><td class="num">${fmt.money(r.prev_close)}</td><td class="num">${r.pre_price ? fmt.money(r.pre_price) : "—"}</td><td class="small">${esc(r.source || (r.sec_type === "OPT" ? "current mark" : "neither"))}</td><td class="num ${signClass(r.move)}">${r.move == null ? "—" : fmt.pct(r.move, 2)}</td><td class="num">${fmt.money(r.value)}</td><td class="num ${signClass(r.value_change)}">${fmt.money(r.value_change)}</td><td class="num">${fmt.pct(r.weight)}</td></tr>`).join("")}</tbody></table>`;
    } catch (err) { out.innerHTML = `<p class="small neg">${esc(err.message)}</p>`; }
    btn.disabled = false;
  });
  $("#pf-reset", box).addEventListener("click", (e) => confirm(`Reset ${p.name} to ${fmt.money(p.starting_cash, 0)}? All positions and trades are deleted.`) &&
    run(e.target, async () => { await api.resetPortfolio(id); detail(box, id); }));
  $("#pf-delete", box).addEventListener("click", (e) => confirm(`Delete ${p.name}?`) &&
    run(e.target, async () => { await api.deletePortfolio(id); location.hash = "#/portfolios"; }));
}

const HISTORY_METRICS = {
  equity: ["Equity", "Cash plus the net value of positions. This is the total account value."],
  cash: ["Cash", "Uninvested cash, including any cash reserved as option collateral."],
  market_value: ["Net market value", "Value of open positions only. Short positions subtract from this figure. Cash is excluded."],
  free_cash: ["Free cash", "Cash after subtracting cash-secured put collateral."],
  realized_pnl: ["Realised P&L", "Profit or loss already locked in by closing trades."],
  unrealized_pnl: ["Unrealised P&L", "Paper profit or loss on open positions at the historical mark."],
  total_return: ["Total return", "Equity change as a percentage of the portfolio’s own starting cash."],
  drawdown: ["Drawdown", "How far equity is below its highest point in this date range. Zero means a peak."],
};
const historyKpi = (label, value) => `<div class="kpi"><span>${label}</span><b>${value}</b></div>`;
const numCol = (key, label, render = fmt.money) => ({ key, label, cls: "num", render: (r) => render(r[key]) });
const pct2 = (x) => fmt.pct(x, 2);

function download(data, name, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function historyCard(box, portfolio) {
  const { id, name } = portfolio;
  const peers = state.portfolios.filter((p) => p.id !== id);
  box.innerHTML = `<h3>Portfolio history</h3>
    <p class="small muted ph-subtitle">Admin edits and Backdater fills count on the original trade dates. Daily valuations are historical marks, not live quotes.</p>
    <form id="ph-range" class="inline">
      <label>From <input type="date" name="start"></label><label>Through <input type="date" name="end"></label>
      <button class="secondary">Apply range</button><button type="button" class="secondary" id="ph-all">All history</button>
      <span class="spacer"></span><button type="button" class="secondary" id="ph-csv">Download CSV</button>
      <button type="button" class="secondary" id="ph-json">Export portfolio JSON</button>
    </form>
    <div id="ph-stats"></div>
    <div class="ph-section">
      <h4>Chart metric</h4><div id="ph-metrics" class="inline ph-metrics" role="group" aria-label="Chart metric">
        ${Object.entries(HISTORY_METRICS).map(([key, [label]]) => `<button type="button" class="secondary small" data-metric="${key}" aria-pressed="${key === "equity"}">${label}</button>`).join("")}
      </div><p class="small muted ph-subtitle" id="ph-definition"></p>
      <div class="inline"><label>Compare with <select id="ph-compare" ${peers.length ? "" : "disabled"}><option value="">${peers.length ? "No comparison" : "No other portfolio"}</option>${peers.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select></label>
        <label id="ph-scale-label" hidden>Equity comparison <select id="ph-scale"><option value="relative">% change from common start</option><option value="absolute">Dollar values</option></select></label>
        <span id="ph-compare-status" class="small muted" aria-live="polite"></span></div>
      <div id="ph-chart">${loading("Loading chart…")}</div><div id="ph-compare-stats"></div>
    </div>
    <div class="ph-section"><h4>Find a point in time</h4>
      <form id="ph-at" class="inline">
        <label>Date (ET) <input type="date" name="day" required></label>
        <label>Time (ET, optional) <input type="time" name="time" step="1"></label>
        <button class="primary">Look up value</button>
      </form><p class="small muted ph-subtitle">Leave time blank for end of day. Cash and holdings are exact to the trade timestamp; values use eligible daily closes or recorded quotes. Missing prices are estimated at cost.</p>
      <div id="ph-snapshot" aria-live="polite"></div>
    </div>
    <details class="ph-section"><summary>Daily history data (primary portfolio)</summary><div id="ph-days"></div></details>
    <div class="ph-section"><h4>Ask local AI <small class="muted">Quick</small></h4>
      <p class="small muted ph-subtitle">Answers use this range, the selected snapshot and any active comparison. No web searches or new price requests.</p>
      <form id="ph-ai" class="inline"><label class="grow">Question <input name="question" maxlength="500" required placeholder="Why did cash fall while equity stayed flat?"></label>
        <button class="secondary">Ask</button><a href="#/ai-settings" class="small">AI Settings</a></form>
      <p class="ph-answer small" id="ph-answer" aria-live="polite"></p>
    </div>`;
  const range = $("#ph-range", box), atForm = $("#ph-at", box), chart = $("#ph-chart", box),
    stats = $("#ph-stats", box), days = $("#ph-days", box), snapshot = $("#ph-snapshot", box),
    compare = $("#ph-compare", box), scale = $("#ph-scale", box), compareStatus = $("#ph-compare-status", box);
  const start = range.elements.start, end = range.elements.end, atDay = atForm.elements.day, atTime = atForm.elements.time;
  let data, peerData, widget, snapshotData, peerSnapshot, activeAt, activeRange = {}, metric = "equity";
  let rangeRequest = 0, compareRequest = 0, snapshotRequest = 0, destroyed = false;
  const peer = () => peers.find((p) => p.id === +compare.value);
  const selectDay = (day) => { atDay.value = day; atTime.value = ""; showSnapshot(); };
  const layout = () => {
    const comparison = peerData && peer();
    const rel = !!comparison && metric === "equity" && scale.value === "relative";
    const left = data?.points.filter((p) => p.day >= data.first_day) || [];
    const right = peerData?.points.filter((p) => p.day >= peerData.first_day) || [];
    const common = left.length && right.length ? [left[0].day, right[0].day].sort().at(-1) : null;
    const a = rel && left.find((p) => p.day === common), b = rel && right.find((p) => p.day === common);
    const comparable = a?.equity > 0 && b?.equity > 0;
    const pct = rel || ["total_return", "drawdown"].includes(metric);
    const series = (points, base, label) => ({ name: label,
      data: points.flatMap((p) => (rel && (!comparable || p.day < common)) || !Number.isFinite(p[metric]) ? [] :
        [{ time: p.day, value: rel ? p.equity / base.equity - 1 : metric === "drawdown" ? -p[metric] : p[metric] }]),
      estimates: new Map(points.map((p) => [p.day, p.estimated_positions])),
    });
    return { rel, common: comparable ? common : null, entries: [series(left, a, name), ...(comparison ? [series(right, b, comparison.name)] : [])],
      format: pct ? pct2 : fmt.money, minMove: pct ? 0.0001 : 0.01,
      drawingKey: `${id}.${comparison?.id || "solo"}.${metric}.${rel ? `relative.${common}` : "absolute"}` };
  };
  const paintChart = () => {
    const view = layout();
    const summary = $("#ph-compare-stats", box);
    $("#ph-scale-label", box).hidden = !compare.value || metric !== "equity";
    $("#ph-definition", box).textContent = HISTORY_METRICS[metric][1] + (view.rel && view.common ? ` Both lines start at 0% on ${view.common}.` : "");
    summary.replaceChildren();
    if (!data) return;
    widget?.setData(view);
    if (activeAt) widget?.selectDay(activeAt.slice(0, 10));
    if (!peerData) return;
    const [left, right] = view.entries;
    const rightLast = right.data.at(-1), leftLast = left.data.at(-1);
    const aligned = leftLast && rightLast && leftLast.time === rightLast.time;
    if (!aligned) { summary.textContent = "No overlapping values to compare for this metric and range. Try dollar values or another range."; return; }
    summary.innerHTML = `<p class="small muted">Same-date comparison · ${esc(leftLast.time)}</p><div class="kpis">
      ${historyKpi(esc(left.name), view.format(leftLast.value))}${historyKpi(esc(right.name), view.format(rightLast.value))}
      ${historyKpi("Difference (first minus second)", view.format === pct2 ? `${((leftLast.value - rightLast.value) * 100).toFixed(2)} pp` : fmt.money(leftLast.value - rightLast.value))}</div>`;
  };
  const loadComparison = async () => {
    const request = ++compareRequest, target = peer();
    peerData = null; peerSnapshot = null;
    compareStatus.textContent = target ? "Loading comparison…" : "";
    paintChart();
    if (!target || !data) return;
    try {
      const result = await api.portfolioHistory(target.id, { start: data.points[0].day, end: data.points.at(-1).day });
      if (destroyed || request !== compareRequest) return;
      peerData = result;
      compareStatus.textContent = "Same date range · dashed line is the comparison";
      paintChart();
      if (activeAt) showSnapshot(activeAt);
    } catch (e) { if (!destroyed && request === compareRequest) compareStatus.textContent = e.message; }
  };
  const load = async (params = {}) => {
    const request = ++rangeRequest;
    stats.innerHTML = loading("Replaying orders and loading daily prices…");
    try {
      const response = await api.portfolioHistory(id, params);
      if (destroyed || request !== rangeRequest) return;
      data = response; activeRange = params;
      const [first, last] = [data.points[0], data.points.at(-1)];
      start.value = first.day; end.value = last.day; atDay.value ||= last.day;
      stats.innerHTML = `<div class="kpis">${historyKpi("Ending equity", fmt.money(last.equity))}
        ${historyKpi("Range return", pct2(data.period_return))}${historyKpi("Max drawdown (range)", pct2(data.max_drawdown))}
        ${historyKpi("Days with cost estimates", data.estimated_days)}</div>`;
      days.replaceChildren(table([
        { key: "day", label: "Date (ET)", render: (p) => `<button type="button" class="small secondary" data-action="snapshot">${esc(p.day)}</button>` },
        numCol("equity", "Equity"), numCol("cash", "Cash"), numCol("market_value", "Market value"),
        numCol("realized_pnl", "Realised"), numCol("unrealized_pnl", "Unrealised"), numCol("total_return", "Return", pct2),
        numCol("drawdown", "Drawdown", pct2), { key: "estimated_positions", label: "Estimated marks", cls: "num" },
      ], data.points.slice(-1000), { initialSort: { key: "day", desc: true }, actions: { snapshot: (p) => selectDay(p.day) } }));
      if (data.points.length > 1000) days.insertAdjacentHTML("afterbegin", `<p class="small muted">Showing the latest 1,000 rows. Narrow the range or download CSV for all rows.</p>`);
      loadComparison();
    } catch (e) { if (!destroyed && request === rangeRequest) stats.textContent = e.message; }
  };
  const showSnapshot = async (at = atDay.value + (atTime.value ? `T${atTime.value}` : "")) => {
    const request = ++snapshotRequest, target = peer();
    snapshotData = peerSnapshot = undefined;
    snapshot.innerHTML = loading("Looking up portfolio values…");
    try {
      const [p, matched] = await Promise.all([api.portfolioSnapshot(id, at),
        target && (!peerData || at.slice(0, 10) >= peerData.first_day)
          ? api.portfolioSnapshot(target.id, at).catch((e) => ({ error: e.message })) : null]);
      if (destroyed || request !== snapshotRequest) return;
      snapshotData = p; peerSnapshot = matched?.error ? null : matched; activeAt = at;
      widget?.selectDay(p.day);
      snapshot.innerHTML = `<h4>${esc(p.as_of.slice(0, 19).replace("T", " "))} ET · ${esc(name)}</h4>
        <div class="kpis">${historyKpi("Equity", fmt.money(p.equity))}${historyKpi("Cash", fmt.money(p.cash))}
          ${historyKpi("Net market value", fmt.money(p.market_value))}${historyKpi("Free cash", fmt.money(p.free_cash))}
          ${historyKpi("Realised P&L", fmt.money(p.realized_pnl))}${historyKpi("Unrealised P&L", fmt.money(p.unrealized_pnl))}</div>`;
      if (target) {
        if (!peerSnapshot) snapshot.insertAdjacentHTML("beforeend", `<p class="small muted">${esc(target.name)}: ${esc(matched?.error || "No history on this date.")}</p>`);
        else snapshot.appendChild(table([
          { key: "name", label: "Same-time values" }, numCol("equity", "Equity"), numCol("cash", "Cash"), numCol("market_value", "Net market value"),
          numCol("total_return", "Total return", pct2), { key: "estimated_positions", label: "Estimated marks" },
        ], [{ name, ...p }, { name: target.name, ...peerSnapshot }]));
      }
      snapshot.appendChild(table([
        { key: "key", label: "Position" }, numCol("qty", "Quantity", (n) => fmt.num(n, 4)), numCol("avg_cost", "Avg cost"),
        numCol("price", "Marked price"), { key: "price_day", label: "Price date" }, { key: "price_source", label: "Price source" },
        numCol("market_value", "Value"), numCol("unrealized_pnl", "Unrealised"), numCol("weight", "Weight", pct2),
      ], p.positions, { initialSort: { key: "market_value" }, empty: "Cash only at that time." }));
    } catch (e) { if (!destroyed && request === snapshotRequest) { activeAt = undefined; snapshot.textContent = e.message; } }
  };
  range.onsubmit = (e) => { e.preventDefault(); load({ start: start.value, end: end.value }); };
  $("#ph-all", box).onclick = () => load();
  $("#ph-metrics", box).onclick = (e) => {
    if (!e.target.dataset.metric) return;
    metric = e.target.dataset.metric;
    box.querySelectorAll("[data-metric]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.metric === metric)));
    paintChart();
  };
  scale.onchange = paintChart;
  compare.onchange = () => { loadComparison(); if (!peer() && activeAt) showSnapshot(activeAt); };
  atForm.onsubmit = (e) => { e.preventDefault(); showSnapshot(); };
  $("#ph-csv", box).onclick = (e) => run(e.target, async () => {
    download(await api.portfolioHistoryCsv(id, activeRange), `portfolio-${id}-history.csv`, "text/csv");
  });
  $("#ph-json", box).onclick = (e) => run(e.target, async () => {
    const all = await api.exportAll(id, { history: true, as_of: activeAt });
    download(JSON.stringify(all, null, 2), `portfolio-${id}-export.json`, "application/json");
  });
  $("#ph-ai", box).onsubmit = (e) => {
    e.preventDefault();
    const answer = $("#ph-answer", box);
    const question = e.currentTarget.elements.question.value.trim();
    if (!question || !data) { answer.textContent = "Wait for history to load and enter a question."; return; }
    answer.textContent = "Asking the local model…";
    run(e.submitter, async () => {
      try {
        const askedDays = [...new Set(question.match(/\b\d{4}-\d{2}-\d{2}\b/g) || [])].slice(0, 2);
        const res = await api.portfolioAsk(id, { question, context: JSON.stringify({ metric,
          primary: quickFacts(name, data, snapshotData, askedDays), comparison: peerData && quickFacts(peer()?.name, peerData, peerSnapshot, askedDays) }) });
        answer.textContent = `${res.answer}\n\nLocal AI · ${res.model}`;
      } catch (error) { answer.textContent = error.message; }
    });
  };
  mountHistoryChart(chart, selectDay).then((mounted) => {
    if (destroyed) { mounted?.destroy(); return; }
    widget = mounted;
    paintChart();
  }).catch((e) => { if (!destroyed) chart.textContent = e.message; });
  paintChart(); load();
  return () => { destroyed = true; widget?.destroy(); };
}

function quickFacts(name, report, snapshot, askedDays) {
  const fields = ["day", "equity", "cash", "market_value", "realized_pnl", "unrealized_pnl", "estimated_positions"];
  const brief = (p) => Object.fromEntries(fields.map((k) => [k, typeof p[k] === "number" ? +p[k].toFixed(2) : p[k]]));
  const points = report.points.filter((p) => p.day >= report.first_day);
  const changes = points.slice(1).map((p, i) => ({ day: p.day, cash_delta: +(p.cash - points[i].cash).toFixed(2),
    equity_delta: +(p.equity - points[i].equity).toFixed(2), market_value_delta: +(p.market_value - points[i].market_value).toFixed(2) }));
  const major = (key) => [...changes].sort((a, b) => Math.abs(b[key]) - Math.abs(a[key])).filter((d) => d[key]).slice(0, 2);
  return { name: name?.slice(0, 80), first: points.length ? brief(points[0]) : null, last: points.length ? brief(points.at(-1)) : null,
    requested_days: points.filter((p) => askedDays.includes(p.day)).map(brief),
    range_return_pct: report.period_return == null ? null : +(report.period_return * 100).toFixed(2),
    max_drawdown_pct: +(report.max_drawdown * 100).toFixed(2), largest_cash_moves: major("cash_delta"), largest_equity_moves: major("equity_delta"),
    snapshot: snapshot && { ...brief(snapshot), as_of: snapshot.as_of,
      positions: snapshot.positions.slice(0, 5).map((p) => ({ key: p.key.slice(0, 80), quantity: p.qty, market_value: +p.market_value.toFixed(2) })) } };
}

const BY = [["sector", "Sector"], ["country", "Country"], ["category", "Category"], ["strategy", "Strategy"]];

function breakdownCard(box, id, equity) {
  const pie = $("#pf-pie", box), tags = $("#pf-tags", box);
  let by = "sector", n = 0;
  const load = async () => {
    const mine = ++n;
    pie.innerHTML = loading(by === "strategy" ? "Loading…" : "Looking up sector, country and category (cached after the first time)…");
    let d;
    try { d = await api.breakdown(id, by); }
    catch (e) { if (mine === n) pie.innerHTML = `<p class="note neg">Breakdown unavailable: ${esc(e.message)}</p>`; return; }
    if (mine !== n) return;
    pie.innerHTML = pieChart({ slices: d.slices, fmtValue: (v) => fmt.money(v, 0), centre: d.total ? fmt.money(d.total, 0) : "" });
    bindChartTips(pie);
    tags.innerHTML = d.holdings.length ? `<table class="compact"><thead><tr><th>Holding</th><th class="num">Value</th><th>Strategy tag</th></tr></thead><tbody>
      ${d.holdings.map((h) => `<tr><td><b>${esc(h.symbol)}</b></td><td class="num">${fmt.money(h.value, 0)}</td><td><select data-sym="${esc(h.symbol)}">
        <option value="">— none —</option>${d.strategies.map((s) => `<option ${s === h.tag ? "selected" : ""}>${esc(s)}</option>`).join("")}</select></td></tr>`).join("")}</tbody></table>
      <p class="small muted">Your own label per holding; the Strategy pie groups by it.</p>` : `<p class="muted">No stock holdings to tag.</p>`;
  };
  $("#pf-by", box).addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    by = b.dataset.v;
    $("#pf-by", box).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    load();
  });
  tags.addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-sym]");
    if (sel) run(null, async () => { await api.setTag(id, sel.dataset.sym, sel.value || null); toast(`${sel.dataset.sym}: ${sel.value || "tag cleared"}`, "ok"); if (by === "strategy") load(); });
  });
  load();
}

const label = (r) => (r.sec_type === "OPT" ? `${r.symbol} ${fmt.expiry(r.expiry)} ${r.strike}${r.right}` : r.symbol);

const POS_COLS = [
  { key: "symbol", label: "Position", render: (r) => `<a href="#/analysis/${esc(r.symbol)}"><b>${esc(label(r))}</b></a>` },
  { key: "qty", label: "Qty", cls: "num", render: (r) => fmt.num(r.qty, 4) },
  { key: "avg_cost", label: "Avg cost", cls: "num", render: (r) => fmt.money(r.avg_cost) },
  { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
  { key: "market_value", label: "Value", cls: "num", render: (r) => fmt.money(r.market_value) },
  { key: "unrealized_pnl", label: "P&L", cls: "num", render: (r) => `<span class="${signClass(r.unrealized_pnl)}">${fmt.money(r.unrealized_pnl)}</span>` },
  { key: "return_pct", label: "Return", cls: "num", render: (r) => `<span class="${signClass(r.return_pct)}">${fmt.pct(r.return_pct)}</span>` },
  { key: "weight", label: "Weight", cls: "num", render: (r) => fmt.pct(r.weight) },
  { key: "tranches_filled", label: "Tranches", cls: "num" },
  { key: "_act", label: "", render: (r) => r.sec_type === "STK" ? `<button class="small secondary" data-action="sellAll">Sell all</button>` : "" },
];

const posActions = (pid, refresh) => ({
  sellAll: (r, btn) => run(btn, async () => {
    const res = await api.stockOrder(pid, { symbol: r.symbol, side: "SELL", qty: r.qty });
    toast(`Sold ${fmt.num(r.qty, 4)} ${r.symbol} @ ${fmt.money(res.trade.price)}`, "ok");
    refresh();
  }),
});

const TRADE_COLS = [
  { key: "ts", label: "Effective time (UTC)", render: (r) => esc(String(r.ts).replace("T", " ").slice(0, 19)) },
  { key: "side", label: "Side" },
  { key: "symbol", label: "Instrument", render: (r) => esc(label(r)) },
  { key: "qty", label: "Qty", cls: "num", render: (r) => fmt.num(r.qty, 4) },
  { key: "price", label: "Fill", cls: "num", render: (r) => fmt.money(r.price, 4) },
  { key: "mid", label: "Mid", cls: "num", render: (r) => fmt.money(r.mid, 4) },
  { key: "slippage", label: "Slippage", cls: "num", render: (r) => fmt.money(r.slippage, 4) },
  { key: "liquidity", label: "Liquidity" },
  { key: "note", label: "Note" },
];
