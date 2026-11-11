// Options: chain (calls/puts around spot) with greeks + yields, VMI covered-call / cash-secured-put suggestions,
// paper orders. Rows never disappear: the backend merges with the last good snapshot (stale rows are flagged).
import { api } from "../api.js";
import { $, esc, fmt, loading, run, table, toast } from "../ui.js";
import { state, refreshPortfolios } from "../state.js";

export async function render(root, params = {}) {
  if (!state.portfolios.length) await refreshPortfolios();
  root.innerHTML = `
    <section class="card">
      <form id="opt-form" class="inline">
        <input id="opt-symbol" placeholder="Ticker" value="${esc(params.symbol || "")}" required>
        <select id="opt-exp"><option value="">nearest ~30 DTE</option></select>
        <select id="opt-right"><option value="P">Puts (CSP)</option><option value="C">Calls (CC)</option><option value="">Both</option></select>
        <label>Strike window <select id="opt-width"><option value="0.15">±15%</option><option value="0.3" selected>±30%</option><option value="0.5">±50%</option></select></label>
        <button class="primary">Load chain</button>
        <button type="button" id="opt-suggest" class="secondary">VMI suggestions</button>
        <a class="button" href="#/optionbook">Option book (saved payoff graphs)</a>
      </form>
      <p class="small muted">VMI rules: sell cash-secured puts at strikes on your buy levels / below IV on stocks you want to own; covered calls only above your cost and IV-relevant resistance.</p>
    </section>
    <section id="opt-suggestions"></section>
    <section class="card"><div id="opt-chain" class="muted">Enter a ticker.</div></section>`;
  const form = $("#opt-form", root);
  const sym = () => $("#opt-symbol", root).value.trim().toUpperCase();
  form.addEventListener("submit", (e) => { e.preventDefault(); run(e.submitter, () => loadChain(root, sym())); });
  $("#opt-symbol", root).addEventListener("change", () => loadExpirations(root, sym()));
  $("#opt-right", root).addEventListener("change", () => root._chain && drawChain(root, root._chain));
  $("#opt-suggest", root).addEventListener("click", (e) => run(e.target, () => loadSuggestions(root, sym())));
  if (params.symbol) { await loadExpirations(root, params.symbol); loadChain(root, params.symbol.toUpperCase()); }
}

async function loadExpirations(root, symbol) {
  if (!symbol) return;
  const exps = await api.expirations(symbol).catch(() => []);
  $("#opt-exp", root).innerHTML = `<option value="">nearest ~30 DTE</option>` +
    exps.map((e) => `<option value="${e}">${fmt.expiry(e)}</option>`).join("");
}

async function loadChain(root, symbol) {
  const box = $("#opt-chain", root);
  box.innerHTML = loading(`Loading ${symbol} chain…`);
  const t0 = performance.now();
  const c = await api.chain(symbol, $("#opt-exp", root).value || null, $("#opt-width", root).value);
  c._clientMs = Math.round(performance.now() - t0);
  root._chain = c;
  if (!$("#opt-exp", root).value && c.expirations?.length && $("#opt-exp", root).options.length <= 1) {
    $("#opt-exp", root).innerHTML = c.expirations.map((e) => `<option value="${e}" ${e === c.expiry ? "selected" : ""}>${fmt.expiry(e)}</option>`).join("");
  }
  drawChain(root, c);
}

function drawChain(root, c) {
  const right = $("#opt-right", root).value;
  const rows = (c.rows || []).filter((r) => !right || r.right === right);
  const box = $("#opt-chain", root);
  box.innerHTML = `<p class="small">${esc(c.symbol)} spot <b>${fmt.money(c.spot)}</b> · expiry <b>${fmt.expiry(c.expiry)}</b> (${c.dte} DTE) ·
    source ${esc(c.source)} · ${rows.length} rows · server ${c.ms} ms / total ${c._clientMs} ms</p>`;
  box.appendChild(table(chainCols(), rows, {
    initialSort: { key: "strike", desc: false },
    actions: { sell: (r, b) => order(r, "SELL", b), buy: (r, b) => order(r, "BUY", b) },
  }));
}

const chainCols = () => [
  { key: "right", label: "", render: (r) => (r.right === "P" ? "Put" : "Call") },
  { key: "strike", label: "Strike", cls: "num", render: (r) => `<b>${fmt.num(r.strike)}</b>${r.stale ? ' <span class="badge na" title="kept from last good snapshot">stale</span>' : ""}` },
  { key: "otm_pct", label: "OTM", cls: "num", render: (r) => fmt.pct(r.otm_pct) },
  { key: "bid", label: "Bid", cls: "num", render: (r) => fmt.num(r.bid) },
  { key: "ask", label: "Ask", cls: "num", render: (r) => fmt.num(r.ask) },
  { key: "mid", label: "Mid", cls: "num", render: (r) => fmt.num(r.mid) },
  { key: "spread_pct", label: "Spread", cls: "num", render: (r) => fmt.pct(r.spread_pct) },
  { key: "iv", label: "IV", cls: "num", render: (r) => fmt.pct(r.iv) },
  { key: "delta", label: "Δ", cls: "num", render: (r) => fmt.num(r.delta, 3) },
  { key: "theta", label: "Θ", cls: "num", render: (r) => fmt.num(r.theta, 3) },
  { key: "prob_itm", label: "P(ITM)", cls: "num", render: (r) => fmt.pct(r.prob_itm) },
  { key: "yield_pct", label: "Yield", cls: "num", render: (r) => fmt.pct(r.yield_pct, 2) },
  { key: "annualized_pct", label: "Annualised", cls: "num", render: (r) => fmt.pct(r.annualized_pct) },
  { key: "breakeven", label: "Breakeven", cls: "num", render: (r) => fmt.money(r.breakeven) },
  { key: "open_interest", label: "OI", cls: "num", render: (r) => fmt.num(r.open_interest, 0) },
  { key: "_a", label: "", render: () => `<button class="small primary" data-action="sell">Sell</button> <button class="small secondary" data-action="buy">Buy</button>` },
];

async function loadSuggestions(root, symbol) {
  if (!symbol) return toast("Enter a ticker", "error");
  const box = $("#opt-suggestions", root);
  box.innerHTML = `<div class="card">${loading("Finding VMI-aligned strikes…")}</div>`;
  const exp = $("#opt-exp", root).value || null;
  const [csp, cc] = await Promise.all([api.suggest(symbol, "CSP", exp), api.suggest(symbol, "CC", exp)]);
  box.innerHTML = "";
  for (const s of [csp, cc]) {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h3>${s.strategy === "CSP" ? "Cash-secured puts" : "Covered calls"} — ${fmt.expiry(s.expiry)} (${s.dte} DTE)</h3>
      ${(s.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}`;
    card.appendChild(table(chainCols(), s.picks || [], { empty: "No suitable strikes", actions: { sell: (r, b) => order(r, "SELL", b), buy: (r, b) => order(r, "BUY", b) } }));
    box.appendChild(card);
  }
}

function order(r, side, btn) {
  const pf = state.portfolios[0];
  if (!pf) return toast("Create a portfolio first", "error");
  const choice = prompt(`${side} ${r.symbol} ${fmt.expiry(r.expiry)} ${r.strike}${r.right}\nPortfolio id (${state.portfolios.map((p) => `${p.id}=${p.name}`).join(", ")})\nthen contracts, e.g. "${pf.id} 1"`, `${pf.id} 1`);
  if (!choice) return;
  const [pid, n] = choice.trim().split(/\s+/).map(Number);
  run(btn, async () => {
    const res = await api.optionOrder(pid, { symbol: r.symbol, expiry: r.expiry, strike: r.strike, right: r.right, side, contracts: n || 1 });
    toast(`Filled ${side} ${n || 1}× ${r.strike}${r.right} @ ${fmt.money(res.trade.price, 2)} (${res.fill.liquidity})` +
      (res.snapshot_id ? " · payoff snapshot saved (Option book)" : ""), "ok");
  });
}
