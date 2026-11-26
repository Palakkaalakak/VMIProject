// "More detailed overview" tab of the Analysis page. Each section fetches its own endpoint the first time it is
// scrolled to or clicked, shows a loading line, and on failure a muted message (never throws).
import { api } from "../api.js";
import { esc, fmt, loading } from "../ui.js";
import { barChart, bindChartTips, alignPrices, fmtMillions, sparkline } from "../charts.js";
import { kpi, num, pct, usd, muted, seg, bindSeg } from "./overview_util.js";

const SECTIONS = [
  ["snapshot", "Snapshot"], ["trends", "Financial trends"], ["statements", "Statements"], ["metrics", "Company metrics"],
  ["efficiency", "Efficiency"], ["valuation", "Valuation calculator"], ["dividends", "Dividends"], ["earnings", "Earnings"],
];

export function mountOverview(box, symbol, report) {
  box.innerHTML = `<nav class="ov-nav" aria-label="Overview sections">${SECTIONS.map(([k, l]) => `<button type="button" class="link" data-go="${k}">${esc(l)}</button>`).join("")}</nav>
    ${SECTIONS.map(([k, l]) => `<section class="card ov-sec" id="ov-${k}" data-key="${k}"><h3>${esc(l)}</h3><div class="ov-body"></div></section>`).join("")}`;
  const hdr = document.querySelector("#app-header");
  box.querySelector(".ov-nav").style.top = `${hdr ? hdr.offsetHeight : 0}px`;
  let metricsPromise = null;           // the metrics endpoint feeds both "Company metrics" and "Efficiency"
  const metricsData = () => (metricsPromise ||= api.ovMetrics(symbol).catch((e) => { metricsPromise = null; throw e; }));
  const loaders = {
    snapshot: (b) => snapshot(b, symbol),
    trends: (b) => trends(b, symbol),
    statements: (b) => statements(b, symbol),
    metrics: async (b) => metricsTable(b, await metricsData()),
    efficiency: async (b) => efficiencyCharts(b, await metricsData()),
    valuation: async (b) => (await import("./overview_valuation.js")).mountValuation(b, symbol, report),
    dividends: async (b) => (await import("./overview_events.js")).mountDividends(b, symbol),
    earnings: async (b) => (await import("./overview_events.js")).mountEarnings(b, symbol),
  };
  const open = async (sec) => {
    if (sec.dataset.state === "loading" || sec.dataset.state === "done") return;
    sec.dataset.state = "loading";
    const body = sec.querySelector(".ov-body");
    body.innerHTML = loading();
    try { await loaders[sec.dataset.key](body); sec.dataset.state = "done"; }
    catch (e) {
      body.innerHTML = `${muted(`This section could not be loaded: ${e?.message || e}`)}<button type="button" class="link" data-retry>Try again</button>`;
      body.querySelector("[data-retry]").onclick = () => open(sec);
      sec.dataset.state = "failed";
    }
  };
  const secs = [...box.querySelectorAll(".ov-sec")];
  box.querySelector(".ov-nav").addEventListener("click", (e) => {
    const b = e.target.closest("[data-go]");
    if (!b) return;
    const sec = box.querySelector(`#ov-${b.dataset.go}`);
    open(sec);
    sec.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((ents) => ents.forEach((en) => { if (en.isIntersecting) { io.unobserve(en.target); open(en.target); } }), { rootMargin: "150px" });
    secs.forEach((s) => io.observe(s));
  } else secs.forEach(open);
  open(secs[0]);
}

// ------------------------------------------------------------------------------------------------ snapshot
async function snapshot(body, symbol) {
  const s = await api.ovSnapshot(symbol);
  const range = s.low_52w != null && s.high_52w != null && s.price != null && s.high_52w > s.low_52w
    ? Math.max(0, Math.min(100, ((s.price - s.low_52w) / (s.high_52w - s.low_52w)) * 100)) : null;
  body.innerHTML = `<div class="kpis">
    ${kpi("Price", usd(s.price))}${kpi("Market cap", s.market_cap == null ? "—" : `$${fmt.big(s.market_cap)}`)}
    ${kpi("Shares (diluted)", s.shares_diluted == null ? "—" : fmt.big(s.shares_diluted))}
    ${kpi("P/E (trailing)", num(s.pe, 1))}${kpi("P/E (forward)", num(s.forward_pe, 1))}${kpi("PEG", num(s.peg, 2))}${kpi("Beta", num(s.beta, 2))}
    ${kpi("Revenue / share", usd(s.revenue_per_share))}${kpi("EPS (TTM)", usd(s.eps))}${kpi("Dividend yield", s.dividend_yield ? pct(s.dividend_yield, 2) : "—")}
    ${kpi("Next earnings", s.next_earnings || "—")}</div>
    <div class="range" title="Where the price sits between its 52-week low and high">
      <span class="small muted">52-week range</span><span class="small">${esc(usd(s.low_52w))}</span>
      <div class="range-bar">${range == null ? "" : `<i style="left:${range.toFixed(1)}%"></i>`}</div><span class="small">${esc(usd(s.high_52w))}</span></div>
    <p class="small muted">${esc([s.sector, s.industry].filter(Boolean).join(" · "))}${s.currency && s.currency !== "USD" ? ` · statements in ${esc(s.currency)}` : ""} · "—" means the data source has no value.</p>`;
}

// ------------------------------------------------------------------------------------------------ financial trends
const TREND_DEFAULT = ["revenue", "net_income", "fcf"];

async function trends(body, symbol) {
  const cache = {};
  const st = { period: "annual", years: 10, kind: "bar", price: false, sel: new Set(TREND_DEFAULT) };
  const get = async () => (cache[st.period] ||= await api.ovTrends(symbol, st.period));
  let data = await get();
  body.innerHTML = `<div class="inline ov-controls">
      <span class="checks" id="tr-series"></span>
      ${seg("period", [["annual", "Annual"], ["quarterly", "Quarterly"]], st.period)}
      ${seg("years", [[5, "5y"], [10, "10y"]], st.years)}
      ${seg("kind", [["bar", "Bars"], ["line", "Lines"]], st.kind)}
      <label class="check"><input type="checkbox" id="tr-price"> price overlay</label></div>
    <div id="tr-chart"></div><p class="small muted" id="tr-note"></p>`;
  const chart = body.querySelector("#tr-chart");
  bindChartTips(chart);
  const draw = () => {
    body.querySelector("#tr-series").innerHTML = data.series.map((s) =>
      `<label class="check"><input type="checkbox" data-k="${esc(s.key)}" ${st.sel.has(s.key) ? "checked" : ""}>${esc(s.label)}</label>`).join("");
    const n = st.years * (st.period === "quarterly" ? 4 : 1);
    const picked = data.series.filter((s) => st.sel.has(s.key));
    const ends = [...new Set(picked.flatMap((s) => s.points.slice(-n).map((p) => p.end)))].sort();
    const label = new Map(picked.flatMap((s) => s.points.map((p) => [p.end, p.label])));
    const vals = picked.flatMap((s) => s.points.map((p) => p.value)).filter((v) => v != null);
    const big = Math.max(0, ...vals.map(Math.abs)) >= 1000;       // millions -> billions when the numbers are large
    const div = big ? 1000 : 1;
    const series = picked.map((s) => ({ name: s.label, values: ends.map((e) => s.points.find((p) => p.end === e)?.value ?? null) }));
    const hasPrice = (data.price || []).length > 0;
    body.querySelector("#tr-price").disabled = !hasPrice;
    const showPrice = st.price && hasPrice;
    chart.innerHTML = picked.length ? barChart({
      categories: ends.map((e) => (st.period === "annual" ? e.slice(0, 4) : label.get(e))), series, kind: st.kind,
      line: showPrice ? { name: "Share price", values: alignPrices(data.price, ends) } : null,
      fmtY: (v) => String(+(v / div).toFixed(2)), fmtTip: (v) => fmtMillions(v), fmtLine: (v) => `$${v.toFixed(v < 100 ? 1 : 0)}`,
      yLabel: `${data.currency || "USD"} ${big ? "billions" : "millions"}`,
    }) : muted("Tick at least one series.");
    body.querySelector("#tr-note").textContent = data.series.length
      ? `Values in ${data.currency || "USD"} ${big ? "billions ($B)" : "millions ($M)"}.${st.period === "annual" ? " Years are fiscal years." : ""}`
      : "No statement data for this company.";
  };
  body.addEventListener("change", (e) => {
    if (e.target.id === "tr-price") st.price = e.target.checked;
    else if (e.target.dataset.k) { if (e.target.checked) st.sel.add(e.target.dataset.k); else st.sel.delete(e.target.dataset.k); }
    else return;
    draw();
  });
  bindSeg(body, async (name, v) => {
    if (name === "period") { st.period = v; try { data = await get(); } catch (e) { chart.innerHTML = muted(`Could not load: ${e.message}`); return; } }
    else st[name] = name === "years" ? +v : v;
    draw();
  });
  draw();
}

// ------------------------------------------------------------------------------------------------ statements
const UNIT_NOTE = { m: "", ps: " (per share)", sh: " (millions of shares)" };

function statementCell(v, unit, ttm) {
  const cls = `num${ttm ? " ttm" : ""}`;
  if (v == null) return `<td class="${cls} muted">—</td>`;
  return `<td class="${cls}${v < 0 ? " neg" : ""}">${esc(num(v, unit === "ps" ? 2 : unit === "sh" ? 1 : 0))}</td>`;
}

async function statements(body, symbol) {
  const cache = {};
  const st = { period: "annual", tab: "income" };
  const get = async () => (cache[st.period] ||= await api.ovStatements(symbol, st.period));
  body.innerHTML = `<div class="inline ov-controls">${seg("tab", [["income", "Income statement"], ["balance", "Balance sheet"], ["cashflow", "Cash flow"]], st.tab)}
    ${seg("period", [["annual", "Annual"], ["quarterly", "Quarterly"]], st.period)}</div><div id="st-out"></div>`;
  const out = body.querySelector("#st-out");
  const draw = async () => {
    out.innerHTML = loading();
    let d;
    try { d = await get(); } catch (e) { out.innerHTML = muted(`Could not load: ${e.message}`); return; }
    const sec = d.sections.find((x) => x.key === st.tab);
    if (!sec) { out.innerHTML = muted("This statement is not available for this company."); return; }
    const isTtm = d.columns.map((c) => c.label === "TTM");
    out.innerHTML = `<div class="table-wrap stmt-wrap"><table class="compact stmt"><thead><tr><th>${esc(sec.title)}</th>
      ${d.columns.map((c, i) => `<th class="num${isTtm[i] ? " ttm" : ""}">${esc(d.period === "annual" && !isTtm[i] && c.end ? c.end.slice(0, 4) : c.label)}</th>`).join("")}</tr></thead><tbody>
      ${sec.rows.map((r) => `<tr><th class="rowh">${esc(r.label)}<span class="muted small">${UNIT_NOTE[r.unit] || ""}</span></th>${r.values.map((v, i) => statementCell(v, r.unit, isTtm[i])).join("")}</tr>`).join("")}</tbody></table></div>
      <p class="small muted">${esc(d.currency || "")} millions unless a row says per share; negatives in red; TTM = trailing twelve months (annual view only).${d.period === "quarterly" ? " Quarterly columns are labelled by quarter-end month." : ""}</p>`;
  };
  bindSeg(body, (name, v) => { st[name] = v; draw(); });
  await draw();
}

// ------------------------------------------------------------------------------------------------ company metrics
const ARROWS = { rising: ["▲", "pos"], falling: ["▼", "neg"], stable: ["►", "muted"] };

function metricsTable(body, m) {
  const rows = Object.values(m.metrics || {});
  if (!rows.length) { body.innerHTML = muted("No margin or return history is available for this company."); return; }
  body.innerHTML = `<div class="table-wrap"><table class="compact"><thead><tr><th>Metric</th><th class="num">Latest (FY)</th><th class="num">5y (avg)</th>
    <th class="num">10y (avg)</th><th>Trend</th><th>Last 10 years</th></tr></thead><tbody>
    ${rows.map((r) => { const a = ARROWS[r.trend]; return `<tr><td>${esc(r.label)}</td><td class="num">${esc(pct(r.latest))}</td><td class="num">${esc(pct(r.avg5))}</td>
      <td class="num">${esc(pct(r.avg10))}</td><td>${a ? `<span class="${a[1]}">${a[0]} ${esc(r.trend)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${sparkline(r.series.map((x) => x.value))}</td></tr>`; }).join("")}</tbody></table></div>
    <p class="small muted">"Latest (FY)" is the last fiscal year; the averages cover the last 5 / 10 fiscal years and show "—" without enough history. Trend compares the last 3 years with the 3 before. The Analysis tab judges its steps on its own basis (latest fiscal year or the normalised average, named in its header). Lines a company does not report (a bank has no gross profit) are left out.</p>`;
}

// ------------------------------------------------------------------------------------------------ efficiency
function efficiencyCharts(body, m) {
  const rv = m.revenue_vs_receivables || { series: [] }, ccc = m.cash_conversion_cycle || { series: [] };
  const verdict = rv.revenue_ahead == null ? "" : rv.revenue_ahead
    ? `Revenue (${pct(rv.revenue_cagr_3y)} a year) kept pace with or beat receivables (${pct(rv.receivables_cagr_3y)}) over 3 years: no sign of sales being pushed onto credit.`
    : `Receivables (${pct(rv.receivables_cagr_3y)} a year) grew faster than revenue (${pct(rv.revenue_cagr_3y)}) over 3 years: check how much is sold on credit.`;
  body.innerHTML = `<h4>Revenue growth vs receivables growth</h4><div id="ef-rv">${rv.series.length ? "" : muted("Needs receivables and revenue history; not available for this company.")}</div>
    ${verdict ? `<p class="small">${esc(verdict)}</p>` : ""}
    <h4>Cash conversion cycle <span class="small muted">days; lower and falling is better${ccc.trend ? ` · trend: ${esc(ccc.trend)}` : ""}</span></h4>
    <div id="ef-ccc">${ccc.series.length ? "" : muted("Needs receivables, inventory and payables; not available for this company (common for banks and software).")}</div>`;
  if (rv.series.length) {
    const el = body.querySelector("#ef-rv"); bindChartTips(el);
    el.innerHTML = barChart({ categories: rv.series.map((x) => String(x.year)), height: 260,
      series: [{ name: "Revenue growth", values: rv.series.map((x) => x.revenue_growth) }, { name: "Receivables growth", values: rv.series.map((x) => x.receivables_growth) }],
      fmtY: (v) => `${(v * 100).toFixed(0)}%`, fmtTip: (v) => pct(v) });
  }
  if (ccc.series.length) {
    const el = body.querySelector("#ef-ccc"); bindChartTips(el);
    el.innerHTML = barChart({ categories: ccc.series.map((x) => String(x.year)), height: 240, kind: "line",
      series: [{ name: "Cash conversion cycle", values: ccc.series.map((x) => x.days), color: "#a855f7" }],
      fmtY: (v) => `${+v.toFixed(0)}`, fmtTip: (v) => (v == null ? "—" : `${v.toFixed(1)} days`), yLabel: "days" });
  }
}
