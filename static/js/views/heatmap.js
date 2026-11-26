// S&P 500 heatmap: treemap grouped by sector, tile area = market cap, colour = the chosen metric. Click a tile -> analysis.
import { api } from "../api.js";
import { $, esc, fmt, loading } from "../ui.js";
import { bindChartTips } from "../charts.js";
import { sectorLayout, heatColor, HEAT_LIMITS } from "../treemap.js";

const METRICS = [["change_1d", "1 day"], ["change_1m", "1 month"], ["ytd", "Year to date"], ["price_vs_iv", "Price vs intrinsic value (−20% = undervalued)"]];
const W = 1200, H = 700;
const pct = (v, d = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
let metric = "change_1d";

export async function render(root) {
  try { metric = localStorage.getItem("vmi.heatmap.metric") || metric; } catch { /* no storage */ }
  if (!METRICS.some(([k]) => k === metric)) metric = "change_1d";
  root.innerHTML = `<section class="card"><div class="inline">
      <h3 style="margin:0">S&amp;P 500 heatmap</h3>
      <span class="seg" id="hm-seg">${METRICS.map(([k, l]) => `<button type="button" class="secondary small ${k === metric ? "on" : ""}" data-v="${k}">${esc(l)}</button>`).join("")}</span>
      <span class="spacer"></span><span id="hm-info" class="small muted"></span></div>
    <div id="hm-scale" class="hm-scale"></div></section>
    <section class="card"><div id="hm-body">${loading("Loading S&P 500 prices (the first load can take a minute)…")}</div></section>`;
  $("#hm-seg", root).addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    metric = b.dataset.v;
    try { localStorage.setItem("vmi.heatmap.metric", metric); } catch { /* ignore */ }
    $("#hm-seg", root).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    load(root);
  });
  load(root);
}

async function load(root) {
  const body = $("#hm-body", root), my = metric;
  body.innerHTML = loading("Loading S&P 500 prices (the first load can take a minute)…");
  let data;
  try { data = await api.heatmap(my); }
  catch (e) { if (my === metric) body.innerHTML = `<p class="note neg">The heatmap could not be built: ${esc(e.message)}</p>`; return; }
  if (my !== metric) return;                                  // the user switched metric meanwhile
  const limit = HEAT_LIMITS[my], label = METRICS.find(([k]) => k === my)[1];
  const layout = sectorLayout(data.tiles, { x: 0, y: 0, w: W, h: H });
  const byKey = Object.fromEntries(data.tiles.map((t) => [t.symbol, t]));
  const parts = layout.map((sec) => {
    const tiles = sec.stocks.map((p) => {
      const t = byKey[p.symbol], fill = heatColor(my === "price_vs_iv" && t.value != null ? -t.value : t.value, limit)   // undervalued (negative) is green, big = p.w > 46 && p.h > 26;
      const tip = `<strong>${esc(t.symbol)}</strong> ${esc(t.name)}<br>${esc(t.sector)}<br>Price ${esc(fmt.money(t.price))}<br>
        ${esc(label)}: <b>${esc(pct(t.value))}</b>${t.value == null && my === "price_vs_iv" ? " (not in the latest scan)" : ""}<br>
        1d ${esc(pct(t.change_1d))} · 1m ${esc(pct(t.change_1m))} · YTD ${esc(pct(t.ytd))}<br>Market cap ${esc(fmt.big(t.market_cap))}`;
      return `<g class="hm-tile" data-sym="${esc(t.symbol)}"><rect class="chart-hit" x="${p.x.toFixed(1)}" y="${p.y.toFixed(1)}" width="${p.w.toFixed(1)}" height="${p.h.toFixed(1)}" style="fill:${fill}" data-tip="${esc(tip)}"/>
        ${big ? `<text x="${(p.x + p.w / 2).toFixed(1)}" y="${(p.y + p.h / 2 - 1).toFixed(1)}" text-anchor="middle" font-size="${Math.min(15, Math.max(9, p.w / 5)).toFixed(0)}" font-weight="700">${esc(t.symbol)}</text>
        <text x="${(p.x + p.w / 2).toFixed(1)}" y="${(p.y + p.h / 2 + 12).toFixed(1)}" text-anchor="middle" font-size="10">${esc(t.value == null ? "n/a" : pct(t.value, 1))}</text>` : ""}</g>`;
    }).join("");
    return `<text class="hm-sector" x="${(sec.x + 4).toFixed(1)}" y="${(sec.y + 12).toFixed(1)}">${esc(sec.sector)}</text>${tiles}`;
  }).join("");
  body.innerHTML = `<div class="hm-wrap" id="hm-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="S&amp;P 500 heatmap">${parts}</svg></div>
    ${my === "price_vs_iv" ? `<p class="small muted">Grey tiles have no intrinsic value: only stocks in the latest saved scan${data.scan_run_id ? ` (run ${data.scan_run_id})` : ""} have one. Run the Superscanner on the S&amp;P 500 to fill more.</p>` : ""}`;
  const wrap = $("#hm-wrap", body);
  bindChartTips(wrap);
  wrap.addEventListener("click", (e) => { const g = e.target.closest(".hm-tile"); if (g) location.hash = `#/analysis/${g.dataset.sym}`; });
  $("#hm-info", root).textContent = `${data.n_priced} of ${data.n_members} stocks priced · area = market cap · prices from the last close, cached up to 15 minutes`;
  const steps = [-1, -0.5, 0, 0.5, 1].map((f) => ({ v: f * limit, c: heatColor(my === "price_vs_iv" ? -f * limit : f * limit, limit) }));
  $("#hm-scale", root).innerHTML = `${steps.map((s) => `<i style="background:${s.c}"></i><span>${pct(s.v, 0)}</span>`).join(" ")}<i style="background:${heatColor(null, 1)}"></i><span>no data</span>
    <span class="muted">· ${esc(label)}; colour is full at ±${(limit * 100).toFixed(0)}%</span>`;
}
