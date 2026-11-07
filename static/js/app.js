// App shell: hash router (#/view/param), view lifecycle (render/destroy), header status + alert polling.
// To add a view: create static/js/views/<name>.js exporting render(root, params) [and optional destroy()],
// then add one entry to ROUTES and one <a data-view> in index.html.
import { api } from "./api.js";
import { $, $$, toast } from "./ui.js";
import { refreshPortfolios } from "./state.js";

const ROUTES = {
  analysis: { load: () => import("./views/analysis.js"), param: "symbol" },
  moat: { load: () => import("./views/moat.js"), param: "symbol" },
  scanner: { load: () => import("./views/scanner.js") },
  watchlists: { load: () => import("./views/watchlists.js"), param: "id" },
  portfolios: { load: () => import("./views/portfolios.js"), param: "id" },
  options: { load: () => import("./views/options.js"), param: "symbol" },
  alerts: { load: () => import("./views/alerts.js") },
  settings: { load: () => import("./views/settings.js") },
};
const DEFAULT = "analysis";
let current = null;

function parse() {
  const [path] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, arg] = path.split("/");
  const route = ROUTES[name] ? name : DEFAULT;
  const params = arg && ROUTES[route].param ? { [ROUTES[route].param]: decodeURIComponent(arg) } : {};
  return { route, params };
}

async function navigate() {
  const { route, params } = parse();
  $$("#main-nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === route));
  try {
    current?.destroy?.();
    const mod = await ROUTES[route].load();
    current = mod;
    const root = $("#view");
    root.innerHTML = "";
    await mod.render(root, params);
  } catch (e) {
    $("#view").innerHTML = `<div class="card error">Failed to load view: ${e.message}</div>`;
  }
}

async function pollHealth() {
  const el = $("#conn-status");
  try {
    const h = await api.health();
    const ok = h.ib?.connected;
    el.textContent = ok ? "IB connected" : "IB offline (Yahoo fallback)";
    el.className = `status ${ok ? "ok" : "warn"}`;
    el.title = ok ? `${h.ib.host}:${h.ib.port}` : (h.ib?.last_error || "TWS / IB Gateway not reachable");
  } catch {
    el.textContent = "server offline"; el.className = "status bad";
  }
}

let lastAlertId = 0;
async function pollAlerts() {
  try {
    const unseen = await api.alerts();
    const fresh = unseen.filter((a) => !a.seen);
    const badge = $("#alert-count");
    badge.hidden = !fresh.length;
    badge.textContent = fresh.length;
    for (const a of fresh.filter((a) => a.id > lastAlertId).reverse()) {
      if (lastAlertId) notify(a);            // don't spam on first load
    }
    lastAlertId = Math.max(lastAlertId, ...unseen.map((a) => a.id), 0);
  } catch { /* server offline — health poll reports it */ }
}

function notify(a) {
  toast(`🔔 ${a.symbol}: ${a.message}`, "ok", 10000);
  if ("Notification" in window && Notification.permission === "granted") new Notification(`VMI: ${a.symbol}`, { body: a.message });
}

$("#quick-search").addEventListener("submit", (e) => {
  e.preventDefault();
  const s = $("#quick-symbol").value.trim().toUpperCase();
  if (s) { location.hash = `#/analysis/${s}`; $("#quick-symbol").value = ""; }
});
window.addEventListener("hashchange", navigate);
if ("Notification" in window && Notification.permission === "default") {
  document.addEventListener("click", () => Notification.requestPermission(), { once: true });
}

await refreshPortfolios();
navigate();
pollHealth(); setInterval(pollHealth, 15000);
pollAlerts(); setInterval(pollAlerts, 30000);
