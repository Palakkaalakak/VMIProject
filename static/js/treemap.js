// Pure layout + colour helpers for the S&P 500 heatmap (no DOM, so tests/js can run them in Node).

/**
 * Squarified treemap (Bruls et al.): lay items [{key, value}] out in the rectangle {x, y, w, h}, area proportional to value,
 * tiles as close to square as possible. Returns [{key, x, y, w, h, value}] largest first; non-positive values are skipped.
 */
export function squarify(items, rect) {
  const list = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  const total = list.reduce((s, i) => s + i.value, 0);
  if (!list.length || rect.w <= 0 || rect.h <= 0) return [];
  const scale = (rect.w * rect.h) / total, out = [];
  let { x, y, w, h } = rect, row = [], i = 0;
  const worst = (r, side) => {
    const s = r.reduce((a, n) => a + n.area, 0), mx = Math.max(...r.map((n) => n.area)), mn = Math.min(...r.map((n) => n.area));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  const place = () => {                  // fix the row along the shorter side, then shrink the free rectangle
    const s = row.reduce((a, n) => a + n.area, 0);
    if (w >= h) {                        // column on the left, as tall as the free rectangle
      const cw = s / h; let cy = y;
      row.forEach((n) => { out.push({ key: n.key, value: n.value, x, y: cy, w: cw, h: n.area / cw }); cy += n.area / cw; });
      x += cw; w -= cw;
    } else {                             // row on top, as wide as the free rectangle
      const rh = s / w; let cx = x;
      row.forEach((n) => { out.push({ key: n.key, value: n.value, x: cx, y, w: n.area / rh, h: rh }); cx += n.area / rh; });
      y += rh; h -= rh;
    }
    row = [];
  };
  while (i < list.length) {
    const n = { key: list[i].key, value: list[i].value, area: list[i].value * scale };
    const side = Math.min(w, h);
    if (!row.length || worst([...row, n], side) <= worst(row, side)) { row.push(n); i++; } else place();
  }
  if (row.length) place();
  return out;
}

/** Group stocks into sectors, then lay out sectors and (inside each, below a header strip) the stocks.
 *  tiles: [{symbol, sector, market_cap}] -> [{sector, x, y, w, h, stocks: [{symbol, x, y, w, h}]}] */
export function sectorLayout(tiles, rect, header = 16) {
  const bySector = new Map();
  tiles.forEach((t) => { if (t.market_cap > 0) (bySector.get(t.sector) || bySector.set(t.sector, []).get(t.sector)).push(t); });
  const sectors = [...bySector].map(([key, ts]) => ({ key, value: ts.reduce((s, t) => s + t.market_cap, 0), ts }));
  return squarify(sectors, rect).map((s) => {
    const ts = sectors.find((x) => x.key === s.key).ts, top = Math.min(header, s.h / 3);
    const inner = { x: s.x, y: s.y + top, w: s.w, h: s.h - top };
    return { sector: s.key, x: s.x, y: s.y, w: s.w, h: s.h, header: top,
             stocks: squarify(ts.map((t) => ({ key: t.symbol, value: t.market_cap })), inner).map(({ key, x, y, w, h }) => ({ symbol: key, x, y, w, h })) };
  });
}

/** Diverging colour scale: red below zero, grey near zero, green above; `limit` is the value of full colour. null -> neutral grey. */
export function heatColor(v, limit) {
  if (v == null || !isFinite(v) || !limit) return "hsl(220 8% 30%)";
  const t = Math.min(1, Math.abs(v) / limit), sat = (8 + 57 * t).toFixed(0);
  return v >= 0 ? `hsl(142 ${sat}% 28%)` : `hsl(2 ${sat}% 38%)`;
}

/** Full-colour value of each metric (fractions): the colour saturates at +/- this. */
export const HEAT_LIMITS = { change_1d: 0.03, change_1m: 0.10, ytd: 0.30, discount_to_iv: 0.40 };
