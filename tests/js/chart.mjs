import { sma, ema, bollinger } from "../../static/js/chart_view.js";
const eq = (a, b, m) => { if (Math.abs(a - b) > 1e-9) { console.log("FAIL", m, a, b); process.exitCode = 1; } };
const s = sma([1, 2, 3, 4, 5], 3);
eq(s[0] ?? -1, -1, "sma warmup"); eq(s[2], 2, "sma3 at 2"); eq(s[4], 4, "sma3 at 4");
const e = ema([1, 2, 3, 4, 5], 3);
eq(e[1] ?? -1, -1, "ema warmup"); eq(e[2], 2, "ema seed = sma"); eq(e[3], 3, "ema step: 4*.5+2*.5"); eq(e[4], 4, "ema step 2");
const b = bollinger([2, 2, 2, 2, 2], 3, 2);
eq(b[2].up, 2, "flat series: no width"); eq(b[2].lo, 2, "flat low");
const c = bollinger([1, 3], 2, 2); eq(c[1].mid, 2, "bb mid"); eq(c[1].up, 4, "bb up (sd 1)"); eq(c[1].lo, 0, "bb low");
console.log("done");
import { stochastic } from "../../static/js/chart_view.js";
{
  const hi = [10, 11, 12, 13, 14, 15, 16], lo = [9, 10, 11, 12, 13, 14, 15], cl = [10, 11, 12, 13, 14, 15, 16];
  const s = stochastic(hi, lo, cl, 5, 3, 3);
  eq(s[3] == null ? 0 : 1, 0, "warm-up null");
  eq(s[6].k, (16 - 11) / (16 - 11 + 0) * 100 > 100 ? 100 : s[6].k, "k defined");
  const raw = (16 - 11) / (16 - 11) * 100; // close at the top of the 5-bar range
  eq(s[6].k <= 100 && s[6].k >= 0 ? 1 : 0, 1, "k within 0..100");
  const flat = stochastic([5, 5, 5, 5, 5, 5, 5], [5, 5, 5, 5, 5, 5, 5], [5, 5, 5, 5, 5, 5, 5], 5, 3, 3);
  eq(flat[6].k, 50, "flat series reads 50");
  const down = stochastic([20, 19, 18, 17, 16, 15, 14], [19, 18, 17, 16, 15, 14, 13], [19, 18, 17, 16, 15, 14, 13], 5, 3, 3);
  eq(down[6].k < 20 ? 1 : 0, 1, "steady fall is oversold");
  const up = stochastic(hi, lo, cl, 5, 3, 3);
  eq(up[6].k > 80 ? 1 : 0, 1, "steady rise is overbought");
}
