import { pieArcs } from "../../static/js/charts.js";
import { squarify, sectorLayout, heatColor, HEAT_LIMITS } from "../../static/js/treemap.js";
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.log("FAIL", m, JSON.stringify(a), JSON.stringify(b)); process.exitCode = 1; } };
const near = (a, b, m, tol = 1e-6) => { if (Math.abs(a - b) > tol) { console.log("FAIL", m, a, b); process.exitCode = 1; } };

// --- pie arcs: fractions, angles close the circle, no NaN, single slice closes, zero weights skipped
const arcs = pieArcs([50, 25, 25]);
eq(arcs.map((a) => a.frac), [0.5, 0.25, 0.25], "fractions");
near(arcs[0].start, 0, "starts at 12 o'clock"); near(arcs[2].end, 2 * Math.PI, "closes the circle");
near(arcs[1].start, arcs[0].end, "slices touch");
eq(/NaN|undefined/.test(arcs.map((a) => a.path).join()), false, "no NaN in path");
const big = pieArcs([75, 25]);
eq(big[0].path.includes("A 90 90 0 1 1"), true, "slice over 180 degrees uses the large-arc flag");
const one = pieArcs([10]);
eq(one.length, 1, "single slice"); eq((one[0].path.match(/A /g) || []).length, 4, "full circle drawn as four half arcs (outer + inner)");
eq(pieArcs([0, 5, -1, 5]).map((a) => a.index), [1, 3], "non-positive weights skipped, indexes kept");
eq(pieArcs([]), [], "empty"); eq(pieArcs([0, 0]), [], "all zero");
const first = pieArcs([1, 1], { cx: 100, cy: 100, r: 90, r0: 55 })[0].path;
eq(first.startsWith("M 100.00 10.00"), true, "first slice starts at the top of the outer ring");

// --- squarify: areas proportional, inside the rect, no overlap-by-area (sum equals the rect), skips <= 0
const rect = { x: 10, y: 20, w: 600, h: 400 };
const items = [6, 6, 4, 3, 2, 2, 1].map((v, i) => ({ key: "k" + i, value: v }));
const out = squarify([...items, { key: "zero", value: 0 }], rect);
eq(out.length, 7, "zero skipped");
const sum = items.reduce((s, i) => s + i.value, 0);
out.forEach((t) => {
  near(t.w * t.h, (t.value / sum) * rect.w * rect.h, `area of ${t.key}`, 1e-6 * rect.w * rect.h);
  eq(t.x >= rect.x - 1e-9 && t.y >= rect.y - 1e-9 && t.x + t.w <= rect.x + rect.w + 1e-9 && t.y + t.h <= rect.y + rect.h + 1e-9, true, `${t.key} inside`);
});
near(out.reduce((s, t) => s + t.w * t.h, 0), rect.w * rect.h, "tiles fill the rectangle", 1e-6);
const worstAspect = Math.max(...out.map((t) => Math.max(t.w / t.h, t.h / t.w)));
eq(worstAspect < 3, true, "tiles are close to square");
const overlap = out.some((a, i) => out.some((b, j) => j > i && a.x < b.x + b.w - 1e-6 && b.x < a.x + a.w - 1e-6 && a.y < b.y + b.h - 1e-6 && b.y < a.y + a.h - 1e-6));
eq(overlap, false, "no overlapping tiles");
eq(squarify([], rect), [], "empty"); eq(squarify([{ key: "a", value: 5 }], { x: 0, y: 0, w: 0, h: 10 }), [], "zero-size rect");
const solo = squarify([{ key: "a", value: 5 }], rect);
eq([solo[0].x, solo[0].y, solo[0].w, solo[0].h], [10, 20, 600, 400], "one item fills the rect");

// --- sector layout: groups by sector, header strip reserved, stocks inside their sector
const tiles = [["A", "Tech", 300], ["B", "Tech", 200], ["C", "Energy", 100], ["D", "Energy", 0], ["E", "Health", 50]]
  .map(([symbol, sector, market_cap]) => ({ symbol, sector, market_cap }));
const lay = sectorLayout(tiles, { x: 0, y: 0, w: 800, h: 500 }, 16);
eq(lay.map((s) => s.sector).sort(), ["Energy", "Health", "Tech"], "three sectors");
const tech = lay.find((s) => s.sector === "Tech");
eq(tech.stocks.map((s) => s.symbol).sort(), ["A", "B"], "stocks grouped");
eq(lay.find((s) => s.sector === "Energy").stocks.map((s) => s.symbol), ["C"], "zero-cap stock dropped");
tech.stocks.forEach((s) => eq(s.y >= tech.y + tech.header - 1e-9 && s.x >= tech.x - 1e-9 && s.x + s.w <= tech.x + tech.w + 1e-9 && s.y + s.h <= tech.y + tech.h + 1e-9, true, "stock inside its sector"));
near(lay.reduce((a, s) => a + s.w * s.h, 0), 800 * 500, "sectors fill the area", 1e-6);

// --- colours
eq(heatColor(null, 0.1), heatColor(NaN, 0.1), "missing is the neutral grey");
eq(heatColor(0.05, 0.1).startsWith("hsl(142"), true, "up is green"); eq(heatColor(-0.05, 0.1).startsWith("hsl(2 "), true, "down is red");
eq(heatColor(0.5, 0.1), heatColor(0.1, 0.1), "colour saturates at the limit");
eq(Object.keys(HEAT_LIMITS), ["change_1d", "change_1m", "ytd", "price_vs_iv"], "one limit per metric");
console.log("done");
{
  const { fmt } = await import("../../static/js/ui.js");
  const chk = (a, b, m) => { if (a !== b) { console.log("FAIL", m, a, b); process.exitCode = 1; } };
  chk(fmt.gap(0.2), "−20.0%", "IV 100, price 80 -> -20% (undervalued)");
  chk(fmt.gap(-0.2), "+20.0%", "IV 100, price 120 -> +20% (overvalued)");
  chk(fmt.gap(0), "0.0%", "at IV");
  chk(fmt.gap(null), "—", "missing");
}
