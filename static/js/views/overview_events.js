// Dividends and Earnings sections of the "More detailed overview" tab.
import { api } from "../api.js";
import { esc } from "../ui.js";
import { barChart, bindChartTips, fmtMillions } from "../charts.js";
import { kpi, pct, usd, muted, safeUrl } from "./overview_util.js";

// ------------------------------------------------------------------------------------------------ dividends
export async function mountDividends(body, symbol) {
  const d = await api.ovDividends(symbol);
  if (!d.pays_dividend) { body.innerHTML = muted(`${symbol} pays no dividend (Yahoo lists no dividend payments for it).`); return; }
  const g = d.growth || {};
  const years = d.years || [];
  body.innerHTML = `<div class="kpis">${kpi("Annual dividend (TTM)", usd(d.ttm_dps, 3))}${kpi("Current yield", pct(d.current_yield, 2))}
    ${kpi("Next ex-dividend date", d.next_ex_date || "—")}${kpi("Next pay date", d.next_pay_date || "—")}
    ${kpi("DPS growth 3y / yr", pct(g.cagr_3y))}${kpi("DPS growth 5y / yr", pct(g.cagr_5y))}${kpi("DPS growth 10y / yr", pct(g.cagr_10y))}</div>
    <h4>Yield history <span class="small muted">dividends of the last 12 months / month-end price</span></h4>
    <div id="dv-yield">${d.yield_history.length ? "" : muted("Not enough history for a yield chart (needs a full year of dividends).")}</div>
    <h4>Dividend per share by year</h4><div id="dv-dps"></div>
    <h4>Payout ratios</h4>
    <div class="table-wrap"><table class="compact"><thead><tr><th>Year</th><th class="num">DPS</th><th class="num">EPS (diluted)</th><th class="num">Payout of EPS</th>
      <th class="num">FCF / share</th><th class="num">Payout of FCF</th></tr></thead><tbody>
      ${[...years].reverse().map((y) => `<tr><td>${y.year}${y.partial ? " *" : ""}</td><td class="num">${esc(usd(y.dps, 3))}</td><td class="num">${esc(usd(y.eps))}</td>
        <td class="num">${esc(pct(y.payout_eps, 0))}</td><td class="num">${esc(usd(y.fcf_per_share))}</td><td class="num">${esc(pct(y.payout_fcf, 0))}</td></tr>`).join("")}</tbody></table></div>
    <p class="small muted">* the current year, still being paid. Payout above 100% means more was paid out than earned that year. Growth rates use complete years only.</p>
    <h4>Recent payments</h4>
    <div class="table-wrap"><table class="compact"><thead><tr><th>Ex-dividend date</th><th>Pay date</th><th class="num">Amount</th></tr></thead><tbody>
      ${d.next_ex_date ? `<tr><td>${esc(d.next_ex_date)} <span class="badge na">next</span></td><td>${esc(d.next_pay_date || "—")}</td><td class="num muted">—</td></tr>` : ""}
      ${[...(d.history || [])].reverse().slice(0, 12).map((h) => `<tr><td>${esc(h.date)}</td><td class="muted">—</td><td class="num">${esc(usd(h.amount, 4))}</td></tr>`).join("")}</tbody></table></div>
    <p class="small muted">Yahoo gives the ex-dividend date of past payments; the pay date is only known for the next one.</p>`;
  if (d.yield_history.length) {
    const el = body.querySelector("#dv-yield"); bindChartTips(el);
    el.innerHTML = barChart({ categories: d.yield_history.map((x) => x.date.slice(0, 7)), kind: "line", height: 260,
      series: [{ name: "Dividend yield", values: d.yield_history.map((x) => x.yield), color: "#22c55e" }],
      fmtY: (v) => `${(v * 100).toFixed(1)}%`, fmtTip: (v) => pct(v, 2) });
  }
  const el = body.querySelector("#dv-dps"); bindChartTips(el);
  el.innerHTML = barChart({ categories: years.map((y) => `${y.year}${y.partial ? "*" : ""}`), height: 260,
    series: [{ name: "Dividend per share", values: years.map((y) => y.dps), color: "#3b82f6" }],
    fmtY: (v) => `$${+v.toFixed(2)}`, fmtTip: (v) => usd(v, 3) });
}

// ------------------------------------------------------------------------------------------------ earnings
export async function mountEarnings(body, symbol) {
  const e = await api.ovEarnings(symbol);
  const hist = e.history || [], quarters = e.quarters || [], releases = e.releases || [];
  const surprise = (x) => (x == null ? '<td class="num muted">—</td>' : `<td class="num ${x >= 0 ? "pos" : "neg"}">${x >= 0 ? "+" : ""}${x.toFixed(1)}%</td>`);
  body.innerHTML = `<div class="kpis">${kpi("Next earnings date", e.next_date || "—")}</div>
    <h4>EPS: actual vs estimate</h4>
    ${hist.length ? `<div class="table-wrap"><table class="compact"><thead><tr><th>Date</th><th class="num">Estimate</th><th class="num">Actual</th><th class="num">Surprise</th></tr></thead><tbody>
      ${hist.map((h) => `<tr><td>${esc(h.date)}</td><td class="num">${esc(usd(h.eps_estimate))}</td><td class="num">${esc(usd(h.eps_actual))}</td>${surprise(h.surprise_pct)}</tr>`).join("")}</tbody></table></div>
      <p class="small muted">Green: the company beat the analysts' estimate; red: it missed.</p>` : muted("No EPS estimate history is available for this company.")}
    <h4>Quarterly revenue and net income</h4><div id="er-q">${quarters.length ? "" : muted("No quarterly statements are available.")}</div>
    <h4>Latest earnings releases <span class="small muted">SEC filings (8-K, item 2.02)</span></h4>
    ${releases.length ? `<ul class="plain">${releases.map((r) => { const u = safeUrl(r.url), i = safeUrl(r.index_url);
      return `<li><b>${esc(r.filed)}</b> · ${esc(r.form)} · ${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">press release ↗</a>` : ""}${i ? ` · <a href="${esc(i)}" target="_blank" rel="noopener noreferrer">filing index ↗</a>` : ""}</li>`; }).join("")}</ul>`
      : muted("No earnings releases were found in the SEC filings list (foreign filers use other forms).")}
    <p class="note">${esc(e.transcripts_note || "Earnings-call transcripts are not included.")}</p>`;
  if (quarters.length) {
    const el = body.querySelector("#er-q"); bindChartTips(el);
    const big = Math.max(...quarters.flatMap((q) => [Math.abs(q.revenue ?? 0), Math.abs(q.net_income ?? 0)])) >= 1000;
    el.innerHTML = barChart({ categories: quarters.map((q) => q.end.slice(0, 7)), height: 260,
      series: [{ name: "Revenue", values: quarters.map((q) => q.revenue) }, { name: "Net income", values: quarters.map((q) => q.net_income) }],
      fmtY: (v) => String(+(v / (big ? 1000 : 1)).toFixed(2)), fmtTip: (v) => fmtMillions(v), yLabel: big ? "$ billions" : "$ millions" });
  }
}
