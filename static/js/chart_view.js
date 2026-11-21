// A small TradingView-style chart: candles with an O/H/L/C readout, Adam's moving averages, Bollinger bands, volume,
// timeframes, ranges and simple drawing tools. Built on the vendored TradingView lightweight-charts (Apache 2.0).
//
// Adam's set (master document §6.2-6.4): SMA 50 blue, 100 orange, 150 green, 200 red (thick); EMA 20 red, 40 blue (thin).
// Daily charts use the SMAs only; the 20/40 EMAs "come into service" on weekly and monthly candles, so they start ON there
// and OFF on daily. Bollinger bands are NOT from Adam (neither course document mentions them): shown as an owner extra, off by default.
import { api } from "./api.js";
import { esc } from "./ui.js";

const LIB = "/static/vendor/lightweight-charts.standalone.production.js";
export const TIMEFRAMES = [["5m", "5m"], ["15m", "15m"], ["1h", "1h"], ["1d", "Daily"], ["1wk", "Weekly"], ["1mo", "Monthly"]];
const RANGES = [["3M", 92], ["6M", 183], ["1Y", 365], ["5Y", 1826], ["All", 0]];
const SMAS = [[50, "#3b82f6", 3], [100, "#f59e0b", 3], [150, "#22c55e", 3], [200, "#ef4444", 3]];
const EMAS = [[20, "#ef4444", 1], [40, "#3b82f6", 1]];

let loading = null;
function ensureLib() {
  if (window.LightweightCharts) return Promise.resolve();
  loading ||= new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = LIB; s.onload = res; s.onerror = () => rej(new Error("could not load the chart library"));
    document.head.appendChild(s);
  });
  return loading;
}

// ---- indicators (pure; exported for the Node tests) ---------------------------------------------------------------
export function sma(values, n) {
  const out = []; let sum = 0;
  values.forEach((v, i) => { sum += v; if (i >= n) sum -= values[i - n]; out.push(i >= n - 1 ? sum / n : null); });
  return out;
}
export function ema(values, n) {
  const k = 2 / (n + 1), out = []; let prev = null;
  values.forEach((v, i) => {
    if (i < n - 1) { out.push(null); return; }
    prev = i === n - 1 ? values.slice(0, n).reduce((a, b) => a + b, 0) / n : v * k + prev * (1 - k);
    out.push(prev);
  });
  return out;
}
export function bollinger(values, n = 20, mult = 2) {
  const mid = sma(values, n);
  return values.map((_, i) => {
    if (mid[i] == null) return null;
    const w = values.slice(i - n + 1, i + 1), sd = Math.sqrt(w.reduce((a, v) => a + (v - mid[i]) ** 2, 0) / n);
    return { mid: mid[i], up: mid[i] + mult * sd, lo: mid[i] - mult * sd };
  });
}
/** Stochastic oscillator (owner spec, not Adam): raw %K over `k` bars, %K smoothed by `smoothK`, %D = SMA of %K over `d`. Returns [{k, d}|null]. */
export function stochastic(highs, lows, closes, k = 5, smoothK = 3, d = 3) {
  const raw = closes.map((c, i) => {
    if (i < k - 1) return null;
    const hi = Math.max(...highs.slice(i - k + 1, i + 1)), lo = Math.min(...lows.slice(i - k + 1, i + 1));
    return hi === lo ? 50 : ((c - lo) / (hi - lo)) * 100;
  });
  const smooth = (xs, n) => xs.map((_, i) => {
    const w = xs.slice(i - n + 1, i + 1);
    return i < n - 1 || w.some((v) => v == null) ? null : w.reduce((a, b) => a + b, 0) / n;
  });
  const kk = smooth(raw, smoothK), dd = smooth(kk, d);
  return kk.map((v, i) => (v == null ? null : { k: v, d: dd[i] }));
}
const STOCH_HIGH = 80, STOCH_LOW = 20;
const pairs = (bars, vals) => bars.map((b, i) => (vals[i] == null ? null : { time: b.time, value: vals[i] })).filter(Boolean);

// ---- the widget ---------------------------------------------------------------------------------------------------
/** Mount a chart for `symbol` into `box`. Returns { destroy }. */
export async function mountChart(box, symbol, { interval = "1d", levels = [] } = {}) {
  box.innerHTML = `<p class="small muted">Loading the chart …</p>`;
  try { await ensureLib(); } catch (e) { box.innerHTML = `<p class="small neg">${esc(e.message)}</p>`; return { destroy() {} }; }
  const L = window.LightweightCharts;
  const st = { interval, tool: null, pending: null, indicators: { sma: new Set([50, 100, 150, 200]), ema: new Set(), bb: true, vol: true, stoch: true }, lines: [] };
  const KEY = () => `vmi.chart.draw.${symbol}.${st.interval}`;

  box.innerHTML = `<div class="chart-bar inline">
      <span class="seg" id="ch-tf">${TIMEFRAMES.map(([v, l]) => `<button type="button" class="small secondary" data-tf="${v}">${l}</button>`).join("")}</span>
      <span class="seg" id="ch-rg">${RANGES.map(([l, d]) => `<button type="button" class="small secondary" data-rg="${d}">${l}</button>`).join("")}</span>
      <span class="seg"><button type="button" class="small secondary" data-tool="trend" title="Click two points on the chart">Trend line</button>
        <button type="button" class="small secondary" data-tool="hline" title="Click a price level">Horizontal line</button>
        <button type="button" class="small secondary" data-tool="clear">Clear drawings</button></span>
      <span class="spacer"></span><span class="small muted" id="ch-src"></span>
      <button type="button" class="small secondary" id="ch-full" title="Fill the whole screen (Esc to leave)">⛶ Fullscreen</button></div>
    <div class="chart-ind small inline">
      ${SMAS.map(([n, c]) => `<label><input type="checkbox" data-sma="${n}" ${st.indicators.sma.has(n) ? "checked" : ""}> <b style="color:${c}">SMA ${n}</b></label>`).join(" ")}
      ${EMAS.map(([n, c]) => `<label><input type="checkbox" data-ema="${n}"> <b style="color:${c}">EMA ${n}</b></label>`).join(" ")}
      <label title="Not from Adam (neither course document mentions Bollinger bands): an owner extra. SMA basis, length 20, 2 standard deviations"><input type="checkbox" id="ch-bb" checked> Bollinger (SMA 20, 2σ) <span class="muted">(owner)</span></label>
      <label title="Not from Adam: an owner extra. Period 5, %K smoothing 3, %D 3, overbought 80, oversold 20"><input type="checkbox" id="ch-stoch" checked> Stochastic (5, 3, 3) <span class="muted">(owner)</span></label>
      <label><input type="checkbox" id="ch-vol" checked> Volume</label>
      </div>
    <div class="small muted">Adam: the 50/100/150/200 SMAs are his daily set; the 20 and 40 EMAs are meant for weekly and monthly charts only (they are allowed here on every timeframe).</div>
    <div class="chart-read small" id="ch-read">&nbsp;</div>
    <div id="ch-canvas" style="height:420px;position:relative"></div>
    <div class="small" id="ch-stoch-read">&nbsp;</div>
    <div id="ch-stoch-box" style="height:130px;position:relative"></div>`;
  const canvas = box.querySelector("#ch-canvas");
  const chart = L.createChart(canvas, { autoSize: true, layout: { background: { color: "transparent" }, textColor: getComputedStyle(document.body).color },
    grid: { vertLines: { color: "rgba(128,128,128,.15)" }, horzLines: { color: "rgba(128,128,128,.15)" } }, crosshair: { mode: 0 }, rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false } });
  const candles = chart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", wickUpColor: "#22c55e", wickDownColor: "#ef4444", borderVisible: false });
  const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", color: "rgba(128,128,128,.4)" });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  const sbox = box.querySelector("#ch-stoch-box");
  const sc = L.createChart(sbox, { autoSize: true, layout: { background: { color: "transparent" }, textColor: getComputedStyle(document.body).color },
    grid: { vertLines: { color: "rgba(128,128,128,.15)" }, horzLines: { visible: false } }, rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
    timeScale: { visible: false }, crosshair: { mode: 0 } });
  const kLine = sc.addLineSeries({ color: "#38bdf8", lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "%K",
    autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
  const dLine = sc.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "%D",
    autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
  kLine.createPriceLine({ price: STOCH_HIGH, color: "#ef4444", lineWidth: 1, lineStyle: 2, title: "80" });
  kLine.createPriceLine({ price: STOCH_LOW, color: "#22c55e", lineWidth: 1, lineStyle: 2, title: "20" });
  let syncing = false;                                   // keep the two charts on the same time window
  const link = (from, to) => from.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (!r || syncing) return; syncing = true; to.timeScale().setVisibleLogicalRange(r); syncing = false; });
  link(chart, sc); link(sc, chart);
  let stochData = [];
  const stochWord = (v) => (v == null ? "" : v >= STOCH_HIGH ? "overbought" : v <= STOCH_LOW ? "oversold" : "neutral");
  const stochRead = (i) => { const x = stochData[i]; box.querySelector("#ch-stoch-read").innerHTML = x ? `Stochastic (5,3,3) · %K <b>${x.k.toFixed(1)}</b> · %D <b>${x.d == null ? "—" : x.d.toFixed(1)}</b> · ${stochWord(x.k)}` : "Stochastic (5,3,3)"; };
  sc.subscribeCrosshairMove((p) => { if (p.time) { const i = bars.findIndex((b) => b.time === p.time); if (i >= 0) stochRead(i); } });
  let bars = [], overlays = [], drawn = [];

  const readout = (b, prev) => {
    if (!b) return "&nbsp;";
    const chg = prev ? (b.close / prev.close - 1) : null, cls = b.close >= b.open ? "pos" : "neg";
    return `<b>${esc(symbol)}</b> · O <b>${b.open.toFixed(2)}</b> H <b>${b.high.toFixed(2)}</b> L <b>${b.low.toFixed(2)}</b> C <b class="${cls}">${b.close.toFixed(2)}</b>${chg == null ? "" : ` <span class="${chg >= 0 ? "pos" : "neg"}">${(chg * 100).toFixed(2)}%</span>`} · vol ${Math.round(b.volume).toLocaleString()}`;
  };
  const lastBar = () => { const r = box.querySelector("#ch-read"); r.innerHTML = readout(bars[bars.length - 1], bars[bars.length - 2]); };
  chart.subscribeCrosshairMove((p) => {
    if (!p.time || !bars.length) return lastBar();
    const i = bars.findIndex((b) => b.time === p.time);
    if (i >= 0) box.querySelector("#ch-read").innerHTML = readout(bars[i], bars[i - 1]);
  });

  function drawIndicators() {
    overlays.forEach((s) => chart.removeSeries(s)); overlays = [];
    const closes = bars.map((b) => b.close);
    const add = (vals, color, w, title) => { const s = chart.addLineSeries({ color, lineWidth: w, priceLineVisible: false, lastValueVisible: false, title }); s.setData(pairs(bars, vals)); overlays.push(s); };
    for (const [n, c, w] of SMAS) if (st.indicators.sma.has(n)) add(sma(closes, n), c, w, `SMA ${n}`);
    for (const [n, c, w] of EMAS) if (st.indicators.ema.has(n)) add(ema(closes, n), c, w, `EMA ${n}`);
    if (st.indicators.bb) {
      const bb = bollinger(closes);
      add(bb.map((x) => x && x.up), "#a78bfa", 1, "BB up"); add(bb.map((x) => x && x.mid), "#a78bfa80", 1, "BB mid"); add(bb.map((x) => x && x.lo), "#a78bfa", 1, "BB low");
    }
    volume.applyOptions({ visible: st.indicators.vol });
    stochData = stochastic(bars.map((b) => b.high), bars.map((b) => b.low), closes);
    kLine.setData(stochData.map((x, i) => (x ? { time: bars[i].time, value: x.k } : null)).filter(Boolean));
    dLine.setData(stochData.map((x, i) => (x && x.d != null ? { time: bars[i].time, value: x.d } : null)).filter(Boolean));
    sbox.parentElement.querySelector("#ch-stoch-read").hidden = sbox.hidden = !st.indicators.stoch;
    stochRead(bars.length - 1);
  }

  // ---- drawings: kept per symbol and timeframe in this browser -----------------------------------------------------
  const loadDrawings = () => { try { return JSON.parse(localStorage.getItem(KEY()) || "[]"); } catch { return []; } };
  const saveDrawings = () => { try { localStorage.setItem(KEY(), JSON.stringify(st.lines)); } catch { /* private window */ } };
  function renderDrawings() {
    drawn.forEach((d) => (d.series ? chart.removeSeries(d.series) : candles.removePriceLine(d.line))); drawn = [];
    for (const d of st.lines) {
      if (d.kind === "hline") drawn.push({ line: candles.createPriceLine({ price: d.price, color: "#eab308", lineWidth: 1, lineStyle: 2, title: d.price.toFixed(2) }) });
      else { const s = chart.addLineSeries({ color: "#eab308", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }); s.setData([{ time: d.a.time, value: d.a.price }, { time: d.b.time, value: d.b.price }].sort((x, y) => (x.time > y.time ? 1 : -1))); drawn.push({ series: s }); }
    }
  }
  // tranche buy levels (set for this stock): one green dotted line each, T1 = highest price
  let levelLines = [];
  function renderLevels() {
    levelLines.forEach((l) => candles.removePriceLine(l)); levelLines = [];
    levels.forEach((b, i) => { if (b && b.price > 0) levelLines.push(candles.createPriceLine({ price: b.price, color: "#22c55e", lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `T${b.tranche ?? i + 1}` })); });
  }
  chart.subscribeClick((p) => {
    if (!st.tool || !p.point) return;
    const price = candles.coordinateToPrice(p.point.y);
    if (price == null) return;
    if (st.tool === "hline") { st.lines.push({ kind: "hline", price }); st.tool = null; }
    else if (st.tool === "trend" && p.time) {
      if (!st.pending) { st.pending = { time: p.time, price }; return; }
      st.lines.push({ kind: "trend", a: st.pending, b: { time: p.time, price } }); st.pending = null; st.tool = null;
    } else return;
    saveDrawings(); renderDrawings(); markTool();
  });
  const markTool = () => box.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("primary", b.dataset.tool === st.tool));

  // ---- data ---------------------------------------------------------------------------------------------------------
  async function load() {
    box.querySelector("#ch-read").textContent = "Loading …";
    let res;
    try { res = await api.bars(symbol, st.interval); } catch (e) { box.querySelector("#ch-read").innerHTML = `<span class="neg">${esc(e.message)}</span>`; return; }
    bars = res.bars || [];
    box.querySelector("#ch-src").textContent = `${res.source} · ${bars.length} bars`;
    candles.setData(bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    volume.setData(bars.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? "rgba(34,197,94,.35)" : "rgba(239,68,68,.35)" })));
    // Adam: the 20/40 EMAs are for weekly and monthly. They start ON there (and off elsewhere) but can be switched on for any timeframe.
    const higher = st.interval === "1wk" || st.interval === "1mo";
    st.indicators.ema = new Set(higher ? [20, 40] : []);
    box.querySelectorAll("[data-ema]").forEach((c) => { c.checked = st.indicators.ema.has(+c.dataset.ema); });
    st.lines = loadDrawings();
    drawIndicators(); renderDrawings(); renderLevels(); lastBar();
    setRange(365);
    box.querySelectorAll("[data-tf]").forEach((b) => b.classList.toggle("primary", b.dataset.tf === st.interval));
  }
  function setRange(days) {
    if (!bars.length) return;
    if (!days || typeof bars[0].time !== "string") return chart.timeScale().fitContent();
    const last = new Date(bars[bars.length - 1].time), from = new Date(last.getTime() - days * 864e5).toISOString().slice(0, 10);
    const first = bars.find((b) => b.time >= from) || bars[0];
    chart.timeScale().setVisibleRange({ from: first.time, to: bars[bars.length - 1].time });
  }

  // Fullscreen: the chart box becomes a fixed full-window layer (CSS .chart-full); both charts autoSize, so they refill by themselves.
  const fullBtn = box.querySelector("#ch-full");
  const setFull = (on) => { box.classList.toggle("chart-full", on); fullBtn.textContent = on ? "✕ Exit fullscreen" : "⛶ Fullscreen"; document.body.classList.toggle("chart-full-open", on); };
  const onEsc = (e) => { if (e.key === "Escape" && box.classList.contains("chart-full")) setFull(false); };
  fullBtn.addEventListener("click", () => setFull(!box.classList.contains("chart-full")));
  document.addEventListener("keydown", onEsc);
  box.querySelectorAll("[data-tf]").forEach((b) => b.addEventListener("click", () => { st.interval = b.dataset.tf; load(); }));
  box.querySelectorAll("[data-rg]").forEach((b) => b.addEventListener("click", () => setRange(+b.dataset.rg)));
  box.querySelectorAll("[data-sma]").forEach((c) => c.addEventListener("change", () => { c.checked ? st.indicators.sma.add(+c.dataset.sma) : st.indicators.sma.delete(+c.dataset.sma); drawIndicators(); }));
  box.querySelectorAll("[data-ema]").forEach((c) => c.addEventListener("change", () => { c.checked ? st.indicators.ema.add(+c.dataset.ema) : st.indicators.ema.delete(+c.dataset.ema); drawIndicators(); }));
  box.querySelector("#ch-bb").addEventListener("change", (e) => { st.indicators.bb = e.target.checked; drawIndicators(); });
  box.querySelector("#ch-stoch").addEventListener("change", (e) => { st.indicators.stoch = e.target.checked; drawIndicators(); });
  box.querySelector("#ch-vol").addEventListener("change", (e) => { st.indicators.vol = e.target.checked; drawIndicators(); });
  box.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.tool === "clear") { st.lines = []; st.pending = null; st.tool = null; saveDrawings(); renderDrawings(); markTool(); return; }
    st.tool = st.tool === b.dataset.tool ? null : b.dataset.tool; st.pending = null; markTool();
  }));
  await load();
  return { destroy() { document.removeEventListener("keydown", onEsc); document.body.classList.remove("chart-full-open"); chart.remove(); sc.remove(); } };
}
