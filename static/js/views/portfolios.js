// Paper portfolios: summaries, positions (marked to market), trade log, create / reset / delete.
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, toast, signClass } from "../ui.js";
import { refreshPortfolios, state } from "../state.js";
import { pieChart, bindChartTips } from "../charts.js";

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
  box.innerHTML = loading("Marking positions to market…");
  const [p, trades, lists] = await Promise.all([api.portfolio(id), api.trades(id), api.watchlists().catch(() => [])]);
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
        <button type="button" id="pf-pre" class="secondary" title="Value the portfolio as if the market opened at the current pre-market prices. Needs IBKR connected.">View with pre-market levels</button>
        <button id="pf-reset" class="secondary">Reset</button>
        <button id="pf-delete" class="danger">Delete</button>
      </div>
    </section>
    <section class="card" id="pf-pre-box" hidden></section>
    <section class="card"><h3>Positions</h3><div id="pf-pos"></div></section>
    <section class="card" id="pf-break"><h3>Breakdown <span class="muted small">by market value · cash is its own slice · option positions are one "Options" slice (absolute market value of the legs)</span></h3>
      <div class="inline"><span class="seg" id="pf-by">${BY.map(([k, l]) => `<button type="button" class="secondary small ${k === "sector" ? "on" : ""}" data-v="${k}">${esc(l)}</button>`).join("")}</span></div>
      <div class="pf-break"><div id="pf-pie"></div><div id="pf-tags"></div></div></section>
    <section class="card"><h3>Trades</h3><div id="pf-trades"></div></section>`;
  $("#pf-pos", box).appendChild(table(POS_COLS, p.positions || [], { actions: posActions(id, () => detail(box, id)), empty: "No positions — analyse a stock and buy a tranche.", initialSort: { key: "market_value" } }));
  $("#pf-trades", box).appendChild(table(TRADE_COLS, trades || [], { empty: "No trades yet", initialSort: { key: "ts" } }));
  breakdownCard(box, id, p.equity);
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
  { key: "ts", label: "Time", render: (r) => esc(String(r.ts).replace("T", " ").slice(0, 19)) },
  { key: "side", label: "Side" },
  { key: "symbol", label: "Instrument", render: (r) => esc(label(r)) },
  { key: "qty", label: "Qty", cls: "num", render: (r) => fmt.num(r.qty, 4) },
  { key: "price", label: "Fill", cls: "num", render: (r) => fmt.money(r.price, 4) },
  { key: "mid", label: "Mid", cls: "num", render: (r) => fmt.money(r.mid, 4) },
  { key: "slippage", label: "Slippage", cls: "num", render: (r) => fmt.money(r.slippage, 4) },
  { key: "liquidity", label: "Liquidity" },
  { key: "note", label: "Note" },
];
