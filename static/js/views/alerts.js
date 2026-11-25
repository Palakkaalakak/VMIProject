// Alerts: watchlist notifications (price reached a buy level, dropped below IV). Polled by app.js.
import { api } from "../api.js";
import { esc, fmt, loading, run, table } from "../ui.js";

const pct = (v, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const GROUP_NAMES = { on_touch: "Bought on the touch", confirmed: "Bought after confirmation", special: "Bought for another reason",
  untyped: "Bought (no type recorded)", waited_no_entry: "Waited, never bought" };

function timingCard(prompts, st) {
  const ask = prompts.length ? `<div class="note"><b>Still waiting for confirmation?</b> (asked at most every 2 days; no answer counts as waiting)
    ${prompts.map((t) => `<div class="inline" data-touch="${t.id}"><a href="#/analysis/${esc(t.symbol)}"><b>${esc(t.symbol)}</b></a> touched ${fmt.money(t.level)} on ${esc(String(t.touched_at).slice(0, 10))} (price ${fmt.money(t.touch_price)})
      <button class="small" data-wait="1">Yes, waiting</button><button class="small secondary" data-wait="0">No</button></div>`).join("")}</div>` : "";
  const rows = Object.entries(st.groups).filter(([, g]) => g.n).map(([k, g]) => `<tr><td>${esc(GROUP_NAMES[k] || k)}</td><td class="num">${g.n}</td>
    <td class="num">${pct(g.avg_cost_vs_touch)}</td><td class="num">${pct(g.avg_ret20)}</td><td class="num">${pct(g.avg_ret60)}</td>
    <td class="num">${pct(g.breakdown_rate, 0)}</td><td class="num">${pct(g.missed_rate, 0)}</td></tr>`).join("");
  return `<section class="card" id="timing"><h3>Entry timing: buy on the touch or wait for confirmation?</h3>${ask}
    <p class="small">${esc(st.verdict)}</p>
    ${rows ? `<table class="compact"><thead><tr><th></th><th>Touches</th><th>Paid vs touch price</th><th>20-bar return</th><th>60-bar return</th><th>Broke down</th><th>Rallied unbought</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<p class="muted small">No finished touches yet. Touches are recorded when a watchlist support or a plan level is reached; when you buy, say how (on touch / confirmed / special) in the trade form.</p>`}
    <p class="small muted">${esc(Object.entries(st.definitions || {}).map(([k, v]) => `${k.replace("_", " ")}: ${v}`).join(" · "))}. Evidence for you, not an Adam rule. ${st.open_now} touch(es) still open.</p></section>`;
}

export async function render(root) {
  root.innerHTML = loading();
  const [rows, prompts, stats] = await Promise.all([api.alerts(), api.touchPrompts().catch(() => []), api.touchStats().catch(() => ({ groups: {}, verdict: "", definitions: {}, open_now: 0 }))]);
  root.innerHTML = timingCard(prompts, stats) + `<section class="card"><div class="inline"><h3>Alerts</h3><span class="spacer"></span>
    <button id="al-check" class="secondary">Check now</button><button id="al-seen" class="secondary">Mark all seen</button></div><div id="al-list"></div></section>`;
  root.querySelector("#al-list").appendChild(table([
    { key: "ts", label: "Time", render: (r) => esc(String(r.ts || "").replace("T", " ").slice(0, 19)) },
    { key: "symbol", label: "Ticker", render: (r) => `<a href="#/analysis/${esc(r.symbol)}"><b>${esc(r.symbol)}</b></a>` },
    { key: "kind", label: "Kind" },
    { key: "message", label: "Message" },
    { key: "price", label: "Price", cls: "num", render: (r) => fmt.money(r.price) },
    { key: "seen", label: "", render: (r) => (r.seen ? "" : '<span class="badge ok">new</span>') },
  ], rows, { empty: "No alerts yet. Add tickers with IV/supports to a watchlist — checks run every 60s while the app is open.", initialSort: { key: "ts" } }));
  root.querySelectorAll("[data-wait]").forEach((b) => b.addEventListener("click", () => run(b, async () => {
    await api.touchAnswer(b.closest("[data-touch]").dataset.touch, b.dataset.wait === "1");
    b.closest("[data-touch]").remove();
  })));
  root.querySelector("#al-check").addEventListener("click", (e) => run(e.target, async () => { await api.checkAlerts(); render(root); }));
  root.querySelector("#al-seen").addEventListener("click", (e) => run(e.target, async () => { await api.markSeen(null); render(root); }));
}
