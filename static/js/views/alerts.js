// Alerts: watchlist notifications (price reached a buy level, dropped below IV). Polled by app.js.
import { api } from "../api.js";
import { esc, fmt, loading, run, table } from "../ui.js";

export async function render(root) {
  root.innerHTML = loading();
  const rows = await api.alerts();
  root.innerHTML = `<section class="card"><div class="inline"><h3>Alerts</h3><span class="spacer"></span>
    <button id="al-check" class="secondary">Check now</button><button id="al-seen" class="secondary">Mark all seen</button></div><div id="al-list"></div></section>`;
  root.querySelector("#al-list").appendChild(table([
    { key: "ts", label: "Time", render: (r) => esc(String(r.ts || "").replace("T", " ").slice(0, 19)) },
    { key: "symbol", label: "Ticker", render: (r) => `<a href="#/analysis/${esc(r.symbol)}"><b>${esc(r.symbol)}</b></a>` },
    { key: "kind", label: "Kind" },
    { key: "message", label: "Message" },
    { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
    { key: "seen", label: "", render: (r) => (r.seen ? "" : '<span class="badge ok">new</span>') },
  ], rows, { empty: "No alerts yet. Add tickers with IV/supports to a watchlist — checks run every 60s while the app is open.", initialSort: { key: "ts" } }));
  root.querySelector("#al-check").addEventListener("click", (e) => run(e.target, async () => { await api.checkAlerts(); render(root); }));
  root.querySelector("#al-seen").addEventListener("click", (e) => run(e.target, async () => { await api.markSeen(null); render(root); }));
}
