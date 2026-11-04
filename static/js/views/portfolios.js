// Paper portfolios: summaries, positions (marked to market), trade log, create / reset / delete.
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, toast, signClass } from "../ui.js";
import { refreshPortfolios, state } from "../state.js";

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
  const p = await api.createPortfolio({ name, style, cash });
  toast(`Created ${p.name}`, "ok");
  location.hash = `#/portfolios/${p.id}`;
}

async function detail(box, id) {
  box.innerHTML = loading("Marking positions to market…");
  const [p, trades] = await Promise.all([api.portfolio(id), api.trades(id)]);
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
        <button id="pf-reset" class="secondary">Reset</button>
        <button id="pf-delete" class="danger">Delete</button>
      </div>
    </section>
    <section class="card"><h3>Positions</h3><div id="pf-pos"></div></section>
    <section class="card"><h3>Trades</h3><div id="pf-trades"></div></section>`;
  $("#pf-pos", box).appendChild(table(POS_COLS, p.positions || [], { actions: posActions(id, () => detail(box, id)), empty: "No positions — analyse a stock and buy a tranche.", initialSort: { key: "market_value" } }));
  $("#pf-trades", box).appendChild(table(TRADE_COLS, trades || [], { empty: "No trades yet", initialSort: { key: "ts" } }));
  $("#pf-reset", box).addEventListener("click", (e) => confirm(`Reset ${p.name} to ${fmt.money(p.starting_cash, 0)}? All positions and trades are deleted.`) &&
    run(e.target, async () => { await api.resetPortfolio(id); detail(box, id); }));
  $("#pf-delete", box).addEventListener("click", (e) => confirm(`Delete ${p.name}?`) &&
    run(e.target, async () => { await api.deletePortfolio(id); location.hash = "#/portfolios"; }));
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
