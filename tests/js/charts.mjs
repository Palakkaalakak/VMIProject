import { niceTicks, linearScale, fmtMillions, alignPrices, sparkPoints, barChart } from "../../static/js/charts.js";
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.log("FAIL", m, JSON.stringify(a), JSON.stringify(b)); process.exitCode = 1; } };

const t = niceTicks(0, 87, 5);
eq(t.ticks, [0, 20, 40, 60, 80, 100], "nice ticks 0..87"); eq([t.min, t.max], [0, 100], "nice range");
const n = niceTicks(-30, 120, 5);
eq(n.ticks.includes(0), true, "zero tick present when range straddles 0"); eq(n.min <= -30 && n.max >= 120, true, "covers data");
const flat = niceTicks(5, 5, 5);
eq(flat.min < 5 && flat.max > 5, true, "flat data still has a span");
eq(niceTicks(NaN, 1).ticks, [0, 1], "non-finite falls back");

const y = linearScale(0, 100, 200, 0);
eq([y(0), y(100), y(50)], [200, 0, 100], "y scale grows upwards");

eq(fmtMillions(1234), "$1.23B", "billions"); eq(fmtMillions(-45.6), "-$45.6M", "negative millions");
eq(fmtMillions(2500000), "$2.50T", "trillions"); eq(fmtMillions(null), "—", "null dash"); eq(fmtMillions(NaN), "—", "NaN dash");

const prices = [{ date: "2020-01-31", close: 10 }, { date: "2020-02-29", close: 12 }, { date: "2020-03-31", close: 9 }];
eq(alignPrices(prices, ["2019-12-31", "2020-02-29", "2020-03-15", "2021-01-01"]), [null, 12, 12, 9], "price at or before date");

eq(sparkPoints([1], 90, 24), "", "one point: no line");
const sp = sparkPoints([1, null, 3], 100, 20, 0).split(" ");
eq(sp.length, 2, "nulls skipped"); eq(sp[0], "0.0,20.0", "min at bottom"); eq(sp[1], "100.0,0.0", "max at top");

// the SVG builder: negative bar goes below the zero line, no NaN leaks into the markup
const svg = barChart({ categories: ["a", "b"], series: [{ name: "x", values: [10, -5] }], fmtY: (v) => String(v) });
eq(/NaN|undefined/.test(svg), false, "no NaN in svg");
const rects = [...svg.matchAll(/<rect x="[^"]*" y="([\d.]+)" width="[^"]*" height="([\d.]+)" fill=/g)].map((m) => [+m[1], +m[2]]);
eq(rects.length, 2, "two bars");
eq(rects[1][0] < rects[0][0] + rects[0][1] + 0.01 && rects[1][0] >= rects[0][0] + rects[0][1] - 0.01, true, "negative bar starts at the zero line");
eq(barChart({ categories: [], series: [] }).includes("No data"), true, "empty message");
console.log("done");
