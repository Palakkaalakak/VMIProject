// Tiny dependency-free SVG line chart shared by the review and option-book views.
// lineChart({series: [{name, xs, ys, color, dash}], width, height, xLabel, yLabel, zero: true, vlines: [{x, label}]})
const COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2"];

export function lineChart({ series, width = 760, height = 320, xLabel = "", yLabel = "", zero = true, vlines = [], fmtX = (v) => v.toFixed(0), fmtY = (v) => v.toFixed(0) }) {
  const pad = { l: 64, r: 14, t: 12, b: 36 };
  const all = series.flatMap((s) => s.xs.map((x, i) => [x, s.ys[i]])).filter(([x, y]) => x != null && y != null);
  if (!all.length) return `<p class="muted">No data.</p>`;
  const xmin = Math.min(...all.map((p) => p[0])), xmax = Math.max(...all.map((p) => p[0]));
  let ymin = Math.min(...all.map((p) => p[1])), ymax = Math.max(...all.map((p) => p[1]));
  if (zero) { ymin = Math.min(ymin, 0); ymax = Math.max(ymax, 0); }
  if (ymin === ymax) { ymin -= 1; ymax += 1; }
  const X = (x) => pad.l + ((x - xmin) / (xmax - xmin || 1)) * (width - pad.l - pad.r);
  const Y = (y) => height - pad.b - ((y - ymin) / (ymax - ymin)) * (height - pad.t - pad.b);
  const ticks = (a, b, n) => Array.from({ length: n + 1 }, (_, i) => a + ((b - a) * i) / n);
  const grid = ticks(ymin, ymax, 5).map((v) => `<line x1="${pad.l}" x2="${width - pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="currentColor" opacity=".12"/>
    <text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="currentColor">${fmtY(v)}</text>`).join("");
  const xt = ticks(xmin, xmax, 6).map((v) => `<text x="${X(v)}" y="${height - pad.b + 16}" text-anchor="middle" font-size="11" fill="currentColor">${fmtX(v)}</text>`).join("");
  const zeroLine = zero ? `<line x1="${pad.l}" x2="${width - pad.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="currentColor" opacity=".55"/>` : "";
  const vl = vlines.map((v) => `<line x1="${X(v.x)}" x2="${X(v.x)}" y1="${pad.t}" y2="${height - pad.b}" stroke="#888" stroke-dasharray="4 3"/>
    <text x="${X(v.x) + 4}" y="${pad.t + 11}" font-size="11" fill="currentColor">${v.label || ""}</text>`).join("");
  const lines = series.map((s, k) => {
    const pts = s.xs.map((x, i) => (s.ys[i] == null ? null : `${X(x).toFixed(1)},${Y(s.ys[i]).toFixed(1)}`)).filter(Boolean).join(" ");
    return `<polyline fill="none" stroke="${s.color || COLORS[k % COLORS.length]}" stroke-width="2" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} points="${pts}"/>`;
  }).join("");
  const legend = series.map((s, k) => `<span style="margin-right:1rem"><span style="display:inline-block;width:14px;height:3px;background:${s.color || COLORS[k % COLORS.length]};vertical-align:middle"></span> ${s.name}</span>`).join("");
  return `<div class="small">${legend}</div><svg viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px;color:inherit" role="img">
    ${grid}${zeroLine}${vl}${lines}${xt}
    <text x="${(width + pad.l) / 2}" y="${height - 2}" text-anchor="middle" font-size="11" fill="currentColor">${xLabel}</text>
    <text x="12" y="${height / 2}" transform="rotate(-90 12 ${height / 2})" text-anchor="middle" font-size="11" fill="currentColor">${yLabel}</text></svg>`;
}

/** Heat colour for a P&L cell: green positive, red negative, intensity relative to the largest absolute value. */
export function heat(v, maxAbs) {
  if (v == null || !maxAbs) return "";
  const a = Math.min(1, Math.abs(v) / maxAbs) * 0.55;
  return `background:${v >= 0 ? `rgba(22,163,74,${a})` : `rgba(220,38,38,${a})`}`;
}

// ---------------------------------------------------------------------------------------------------------
// Period charts for the "More detailed overview" tab: grouped bars (or lines) per period with a hover tooltip,
// an optional right-axis price line, plus sparklines. Everything below the pure helpers builds SVG/HTML strings.
// ---------------------------------------------------------------------------------------------------------
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4", "#ef4444"];

/** "Nice" axis ticks covering [min, max]: {ticks, min, max}. Always spans at least one step, so flat data still has an axis. */
export function niceTicks(min, max, count = 5) {
  if (!isFinite(min) || !isFinite(max)) return { ticks: [0, 1], min: 0, max: 1 };
  if (min === max) { const d = Math.abs(min) || 1; min -= d / 2; max += d / 2; }
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const lo = Math.floor(min / step + 1e-9) * step, hi = Math.ceil(max / step - 1e-9) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : +v.toPrecision(12));
  return { ticks, min: lo, max: hi };
}

/** Linear scale: value in [d0, d1] -> pixel in [r0, r1] (r0 > r1 for a y axis that grows upwards). */
export function linearScale(d0, d1, r0, r1) {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Money given in MILLIONS as "$1.23B" / "$456M" (T above a million millions); null -> "—". */
export function fmtMillions(v, digits = 2) {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v), s = v < 0 ? "-" : "";
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(digits)}T`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(digits)}B`;
  return `${s}$${a.toFixed(a >= 100 ? 0 : 1)}M`;
}

/** Pick, for every period end date, the last price on or before it (null when the prices start later). */
export function alignPrices(prices, ends) {
  const sorted = [...(prices || [])].sort((a, b) => (a.date < b.date ? -1 : 1));
  return ends.map((e) => {
    let best = null;
    for (const p of sorted) { if (p.date <= e) best = p.close; else break; }
    return best;
  });
}

/** Sparkline points "x,y x,y …" for a series (nulls skipped) inside a w x h box; "" when fewer than 2 points. */
export function sparkPoints(values, w = 90, h = 24, pad = 2) {
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null && isFinite(v));
  if (pts.length < 2) return "";
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const X = linearScale(0, values.length - 1, pad, w - pad), Y = linearScale(lo, hi === lo ? lo + 1 : hi, h - pad, pad);
  return pts.map(([i, v]) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
}

/** Tiny inline SVG line for a table cell. */
export function sparkline(values, { w = 90, h = 24, color = "var(--accent)" } = {}) {
  const pts = sparkPoints(values, w, h);
  return pts ? `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="trend"><polyline fill="none" stroke="${color}" stroke-width="1.6" points="${pts}"/></svg>` : `<span class="muted">—</span>`;
}

/**
 * Grouped bars (or lines, kind: "line") per period.
 *   categories: ["2019", …]; series: [{name, values (aligned, null ok), color?}]
 *   line: optional {name, values, color?, fmt?} drawn on a right axis (e.g. price)
 *   fmtY(v) formats axis ticks; fmtTip(v) the tooltip values (defaults to fmtY). Hover tooltips need bindChartTips(root) afterwards.
 */
export function barChart({ categories, series, kind = "bar", line = null, width = 1100, height = 320, fmtY = (v) => String(v), fmtTip = fmtY, fmtLine = (v) => String(v), yLabel = "" }) {
  const all = series.flatMap((s) => s.values).filter((v) => v != null && isFinite(v));
  if (!categories.length || !all.length) return `<p class="muted">No data.</p>`;
  const pad = { l: 66, r: line ? 58 : 14, t: 12, b: 30 };
  const lo = Math.min(...all, kind === "bar" ? 0 : Infinity), hi = Math.max(...all, kind === "bar" ? 0 : -Infinity);
  const ax = niceTicks(lo, hi, 5);
  const Y = linearScale(ax.min, ax.max, height - pad.b, pad.t);
  const plotW = width - pad.l - pad.r, band = plotW / categories.length;
  const cx = (i) => pad.l + band * (i + 0.5);
  const colorOf = (s, k) => s.color || PALETTE[k % PALETTE.length];
  const grid = ax.ticks.map((v) => `<line x1="${pad.l}" x2="${width - pad.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="currentColor" opacity="${v === 0 ? 0.5 : 0.12}"/>
    <text x="${pad.l - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="11" fill="currentColor">${esc(fmtY(v))}</text>`).join("");
  const step = Math.max(1, Math.ceil(categories.length / Math.max(2, Math.floor(plotW / 54))));
  const xl = categories.map((c, i) => (i % step === 0 ? `<text x="${cx(i)}" y="${height - pad.b + 16}" text-anchor="middle" font-size="11" fill="currentColor">${esc(c)}</text>` : "")).join("");
  let marks = "";
  if (kind === "bar") {
    const inner = band * 0.78, bw = inner / series.length;
    marks = series.map((s, k) => s.values.map((v, i) => {
      if (v == null || !isFinite(v)) return "";
      const x = cx(i) - inner / 2 + k * bw, y0 = Y(0), y1 = Y(v);
      return `<rect x="${x.toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${Math.max(0.5, Math.abs(y1 - y0)).toFixed(1)}" fill="${colorOf(s, k)}" opacity=".9"/>`;
    }).join("")).join("");
  } else {
    marks = series.map((s, k) => {
      const pts = s.values.map((v, i) => (v == null || !isFinite(v) ? null : [cx(i), Y(v)]));
      // break the line at gaps so a missing year is not bridged
      const runs = []; let cur = [];
      pts.forEach((p) => { if (p) cur.push(p); else { if (cur.length) runs.push(cur); cur = []; } });
      if (cur.length) runs.push(cur);
      const c = colorOf(s, k);
      return runs.map((r) => `<polyline fill="none" stroke="${c}" stroke-width="2" points="${r.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ")}"/>`).join("")
        + pts.filter(Boolean).map((p) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.6" fill="${c}"/>`).join("");
    }).join("");
  }
  let overlay = "", axisR = "";
  if (line) {
    const lv = line.values.filter((v) => v != null && isFinite(v));
    if (lv.length) {
      const ay = niceTicks(Math.min(...lv), Math.max(...lv), 5), Y2 = linearScale(ay.min, ay.max, height - pad.b, pad.t);
      const c = line.color || "#f59e0b";
      const pts = line.values.map((v, i) => (v == null ? null : `${cx(i).toFixed(1)},${Y2(v).toFixed(1)}`)).filter(Boolean);
      overlay = `<polyline fill="none" stroke="${c}" stroke-width="2" stroke-dasharray="5 3" points="${pts.join(" ")}"/>`;
      axisR = ay.ticks.map((v) => `<text x="${width - pad.r + 6}" y="${Y2(v) + 4}" font-size="11" fill="${c}">${esc(fmtLine(v))}</text>`).join("");
    }
  }
  // one transparent hit area per period; bindChartTips() shows data-tip on hover
  const hits = categories.map((c, i) => {
    const rows = series.map((s, k) => `<i style="background:${colorOf(s, k)}"></i>${esc(s.name)}: <b>${esc(fmtTip(s.values[i]))}</b>`);
    if (line && line.values[i] != null) rows.push(`<i style="background:${line.color || "#f59e0b"}"></i>${esc(line.name)}: <b>${esc(fmtLine(line.values[i]))}</b>`);
    return `<rect class="chart-hit" x="${(cx(i) - band / 2).toFixed(1)}" y="${pad.t}" width="${band.toFixed(1)}" height="${height - pad.t - pad.b}" fill="transparent" data-tip="${esc(`<strong>${esc(c)}</strong><br>${rows.join("<br>")}`)}"/>`;
  }).join("");
  const legend = [...series.map((s, k) => [s.name, colorOf(s, k), false]), ...(line ? [[line.name + " (right axis)", line.color || "#f59e0b", true]] : [])]
    .map(([n, c, dash]) => `<span class="lg"><i style="background:${dash ? "transparent" : c};border-top:${dash ? `2px dashed ${c}` : "0"}"></i>${esc(n)}</span>`).join("");
  return `<div class="chart-legend small">${legend}</div><div class="chart-box"><svg viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px" role="img">
    ${grid}${marks}${overlay}${xl}${axisR}${hits}
    ${yLabel ? `<text x="12" y="${height / 2}" transform="rotate(-90 12 ${height / 2})" text-anchor="middle" font-size="11" fill="currentColor">${esc(yLabel)}</text>` : ""}</svg></div>`;
}

/** Shared hover tooltip for every `.chart-hit[data-tip]` under root (tooltip text is already escaped HTML). */
export function bindChartTips(root) {
  root.style.position ||= "relative";
  const tipEl = () => {
    let t = root.querySelector(":scope > .chart-tip");     // re-created when a redraw replaced the root's content
    if (!t) { t = document.createElement("div"); t.className = "chart-tip"; t.hidden = true; root.appendChild(t); }
    return t;
  };
  root.addEventListener("mousemove", (e) => {
    const tip = tipEl(), hit = e.target.closest?.(".chart-hit");
    if (!hit) { tip.hidden = true; return; }
    tip.innerHTML = hit.dataset.tip; tip.hidden = false;
    const box = root.getBoundingClientRect();
    tip.style.left = `${Math.max(0, Math.min(e.clientX - box.left + 14, box.width - tip.offsetWidth - 4))}px`;
    tip.style.top = `${Math.max(0, e.clientY - box.top - tip.offsetHeight - 10)}px`;
  });
  root.addEventListener("mouseleave", () => { tipEl().hidden = true; });
}

// ---------------------------------------------------------------------------------------------------------
// Donut chart: pure arc geometry (testable in Node) + the SVG/HTML builder with hover values and a legend.
// ---------------------------------------------------------------------------------------------------------
export const PIE_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4", "#ef4444", "#84cc16", "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#eab308"];
const FIXED_PIE = { Cash: "#94a3b8", Options: "#c084fc", Unknown: "#64748b", Untagged: "#64748b" };
const pt = (cx, cy, r, a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];        // angle 0 = 12 o'clock, clockwise

/** Donut slice geometry from weights (any positive numbers): [{index, frac, start, end, path}] with angles in radians clockwise
 *  from 12 o'clock. A single 100% slice is drawn as two half arcs (one SVG arc cannot close a circle). */
export function pieArcs(weights, { cx = 100, cy = 100, r = 90, r0 = 55 } = {}) {
  const total = weights.reduce((s, w) => s + (w > 0 ? w : 0), 0);
  if (!(total > 0)) return [];
  let a = 0;
  return weights.map((w, index) => {
    if (!(w > 0)) return null;
    const frac = w / total, start = a, end = a + frac * 2 * Math.PI;
    a = end;
    const f = (n) => n.toFixed(2), P = (rad, ang) => pt(cx, cy, rad, ang).map(f).join(" ");
    let path;
    if (frac > 0.9999) {
      path = `M ${P(r, 0)} A ${r} ${r} 0 1 1 ${P(r, Math.PI)} A ${r} ${r} 0 1 1 ${P(r, 0)} M ${P(r0, 0)} A ${r0} ${r0} 0 1 0 ${P(r0, Math.PI)} A ${r0} ${r0} 0 1 0 ${P(r0, 0)} Z`;
    } else {
      const large = end - start > Math.PI ? 1 : 0;
      path = `M ${P(r, start)} A ${r} ${r} 0 ${large} 1 ${P(r, end)} L ${P(r0, end)} A ${r0} ${r0} 0 ${large} 0 ${P(r0, start)} Z`;
    }
    return { index, frac, start, end, path };
  }).filter(Boolean);
}

/** Donut + legend. slices: [{label, value, weight}]; fmtValue(v) formats money. Needs bindChartTips(root) for the hover values. */
export function pieChart({ slices, fmtValue = (v) => String(v), size = 220, centre = "" }) {
  const live = slices.filter((s) => s.value > 0);
  if (!live.length) return `<p class="muted">Nothing to show yet.</p>`;
  let k = 0;
  const colors = live.map((s) => FIXED_PIE[s.label] || PIE_COLORS[k++ % PIE_COLORS.length]);
  const arcs = pieArcs(live.map((s) => s.value));
  const paths = arcs.map((a) => {
    const s = live[a.index];
    return `<path class="chart-hit pie-slice" d="${a.path}" fill="${colors[a.index]}" fill-rule="evenodd" data-tip="${esc(`<strong>${esc(s.label)}</strong><br>${esc(fmtValue(s.value))} · ${(a.frac * 100).toFixed(1)}%`)}"/>`;
  }).join("");
  const legend = live.map((s, i) => `<li><i style="background:${colors[i]}"></i><span class="pie-l">${esc(s.label)}</span><span class="pie-v">${(s.value / live.reduce((t, x) => t + x.value, 0) * 100).toFixed(1)}%</span></li>`).join("");
  return `<div class="pie-wrap"><svg viewBox="0 0 200 200" width="${size}" height="${size}" role="img" aria-label="breakdown">${paths}
    ${centre ? `<text x="100" y="104" text-anchor="middle" font-size="13" fill="currentColor" pointer-events="none">${esc(centre)}</text>` : ""}</svg><ul class="pie-legend plain">${legend}</ul></div>`;
}
