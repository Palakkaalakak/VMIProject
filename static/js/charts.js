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
