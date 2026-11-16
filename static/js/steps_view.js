// The 7-step card on the analysis page: every check in plain language (percentages as percentages, ratios as multiples,
// money as money), a one-line verdict per step, failures first, information-only rows grouped, raw values folded away.
import { esc, fmt, badge } from "./ui.js";

const P = (v, d = 1) => (v == null || isNaN(v) ? "—" : fmt.pct(v, d));
const X = (v, d = 2) => (v == null || isNaN(v) ? "—" : `${fmt.num(v, d)}×`);
const M = (v) => (v == null || isNaN(v) ? "—" : fmt.money(Math.abs(v) >= 1e6 ? v / 1e6 : v, Math.abs(v) >= 1e6 ? 0 : 2) + (Math.abs(v) >= 1e6 ? "M" : ""));
const B = (v) => (v == null || isNaN(v) ? "—" : fmt.big(v));
const arrow = (a, f) => (a || []).map(f).join(" → ");
const num = (v) => typeof v === "number";

/** label, what the test asks, and how to show the value. fmtV(value, check) -> text. */
const INFO = {
  revenue_consistent: ["Sales keep rising", "Sales up over 5-10 years (one or two down years are fine)", (v) => (num(v) ? `${P(v)} a year` : "—")],
  earnings_consistent: ["Profit keeps rising", "Net income (or operating income) up over 5-10 years", (v) => (num(v) ? `${P(v)} a year` : "—")],
  cfo_consistent: ["Operating cash flow keeps rising", "Cash from operations up over 5-10 years", (v) => (num(v) ? `${P(v)} a year` : "—")],
  gross_margin_stable: ["Gross margin holds", "Latest gross margin close to its 5-year average", (v) => P(v)],
  net_margin_stable: ["Net margin holds", "Latest net margin close to its 5-year average; falling 5 years in a row = avoid", (v) => P(v)],
  speculative_turned_positive: ["Turned profitable (speculative exception)", "Fast-growing company: latest quarter's cash flow and profit are positive",
    (v) => (v && typeof v === "object" ? `cash flow ${(v.cfo_q || []).map(B).join(", ")} · net income ${(v.ni_q || []).map(B).join(", ")} (last quarters)` : "—")],
  projected_growth_positive: ["Analysts expect growth", "Projected 5-year earnings growth is positive", (v) => (num(v) ? `${P(v)} a year` : "—")],
  next_year_growth: ["Next-year growth (info)", "Analysts' next-year earnings growth", (v) => P(v)],
  industry_structure: ["Not a no-moat industry", "Not commodities, airlines, autos, developers, construction, shipping, oil and gas", (v) => v || "—"],
  ten_year_chart: ["10-year chart trends up", "Clear uptrend over 10 years", (v) => (num(v) ? `${P(v, 0)} price return over 10 years` : "not enough history")],
  gross_margin: ["Gross margin (moat evidence)", "", (v) => P(v)], operating_margin: ["Operating margin (moat evidence)", "", (v) => P(v)],
  net_margin: ["Net margin (moat evidence)", "", (v) => P(v)], free_cash_flow_margin: ["Free-cash-flow margin (moat evidence)", "", (v) => P(v)],
  pricing_power_through_inflation: ["Pricing power through the 2021-23 inflation", "Margin held up when costs rose", (v) => (num(v) ? `worst year ${P(v)}` : "—")],
  recurring_revenue: ["Recurring revenue (switching costs)", "", (v) => (Array.isArray(v) ? v.map((x) => P(x)).join(", ") + " of sales" : "—")],
  reinvestment_intensity: ["Cost structure (economies of scale)", "", (v) => (v && typeof v === "object" ? Object.entries(v).map(([k, x]) => `${{ rd: "R&D", sga: "SG&A", capex: "capex" }[k] || k} ${P(x)}`).join(" · ") + " of sales" : "—")],
  scale: ["Size (top dog?)", "", (v) => (v && typeof v === "object" ? `sales ${B(v.revenue)} · market cap ${B(v.market_cap)}` : "—")],
  reviewer_verdict: ["Your moat verdict", "", (v) => v || "—"],
  roe: ["Return on equity", "How much profit per dollar of shareholders' equity", (v) => (num(v) ? P(v) : v || "—")],
  roe_not_declining: ["ROE not falling for years", "", (v) => (Array.isArray(v) ? arrow(v, (x) => P(x, 0)) : "—")],
  roic: ["Return on invested capital", "Profit per dollar of capital employed (provider figure; huge for cash-rich companies)", (v) => P(v)],
  revenue_vs_receivables: ["Sales grow faster than receivables", "Customers still pay promptly", (v) => (v && typeof v === "object" ? `sales ${P(v.rev_cagr)} a year vs receivables ${P(v.ar_cagr)}` : "—")],
  cash_conversion_cycle: ["Cash conversion cycle", "Days to turn stock into cash: not rising", (v) => (Array.isArray(v) ? arrow(v, (x) => fmt.num(x, 0)) + " days" : "—")],
  current_ratio: ["Current ratio", "Short-term assets cover short-term bills", (v) => X(v)], debt_to_ebitda: ["Debt vs earnings", "Years of operating earnings needed to repay debt", (v) => (num(v) ? `${fmt.num(v, 2)} years` : "—")],
  debt_servicing: ["Interest vs cash flow", "Share of operating cash flow that goes to interest", (v) => P(v)], interest_coverage: ["Interest coverage", "Operating profit / interest", (v) => X(v, 1)],
  gearing: ["Debt / assets (REIT)", "", (v) => P(v)], cet1: ["Capital ratio (bank)", "", (v) => P(v)],
  below_intrinsic_value: ["Price below intrinsic value", "A margin of safety", (v, c) => (num(v) ? `price ${fmt.money(v)} vs value ${fmt.money(c.threshold)}` : "—")],
  below_conservative_value: ["Price below the conservative value (info)", "", (v, c) => (num(v) ? `price ${fmt.money(v)} vs conservative ${fmt.money(c.threshold)}` : "—")],
  entry_signal: ["Chart entry signal", "Price dipping into support", (v) => v || "no signal"], not_parabolic: ["Not chasing a spike", "Never buy a wave up", () => ""],
};

const STEP_ASK = {
  1: "Has the business grown sales, profit and cash flow steadily for 5-10 years?", 2: "Do analysts expect it to keep growing?",
  3: "Does it have a moat? Until you review it, only Adam's two shortcuts count (industry list, 10-year chart).",
  4: "Does it earn good returns on its capital?", 5: "Is its debt safe?", 6: "Is the price below what the business is worth?", 7: "Is the chart giving a good place to buy?",
};

const label = (c) => (INFO[c.name]?.[0] || c.name.replaceAll("_", " "));
function valueText(c) {
  const f = INFO[c.name]?.[2];
  if (f) return f(c.value, c);
  const v = c.value;
  if (v == null) return "—";
  if (num(v)) return fmt.num(v, 3);
  return Array.isArray(v) ? v.map((x) => (num(x) ? fmt.num(x, 3) : x)).join(", ") : typeof v === "object" ? Object.entries(v).map(([k, x]) => `${k} ${num(x) ? fmt.num(x, 3) : x}`).join(" · ") : String(v);
}
const needText = (c) => (c.threshold == null || c.threshold === "" || num(c.threshold) ? "" : String(c.threshold));

function rowHtml(c) {
  const ask = INFO[c.name]?.[1];
  const info = c.passed == null;
  return `<tr class="${c.passed === false ? "fail" : ""}"><td style="white-space:nowrap">${badge(c.passed, "PASS", "FAIL", "info")}</td>
    <td><b>${esc(label(c))}</b>${ask ? `<div class="small muted">${esc(ask)}</div>` : ""}${c.help ? `<div class="small muted" style="max-width:36rem">${esc(c.help)}</div>` : ""}</td>
    <td>${esc(valueText(c))}${needText(c) ? `<div class="small muted">needs: ${esc(needText(c))}</div>` : ""}</td>
    <td class="small ${info ? "muted" : ""}">${esc(c.note || "")}</td></tr>`;
}

function summary(s) {
  const judged = s.checks.filter((c) => c.passed != null);
  const failed = judged.filter((c) => c.passed === false);
  const verdict = s.passed ? "Passes" : "Fails";
  const why = failed.length ? ` Failing: ${failed.map(label).join(", ")}.` : "";
  return `${verdict}: ${judged.length - failed.length} of ${judged.length} tests ok.${why}`;
}

export function stepsCard(r, moatChecklist) {
  const passed = (r.steps || []).filter((s) => s.step <= 5 && s.passed).length;
  return `<div class="card"><h3>The 7 steps <span class="muted small">steps 1-5 pass = a great business (${passed}/5 now); step 6 price, step 7 chart entry</span></h3>${(r.steps || []).map((s) => {
    const judged = s.checks.filter((c) => c.passed != null).sort((a, b) => (a.passed === b.passed ? 0 : a.passed ? 1 : -1));
    const info = s.checks.filter((c) => c.passed == null);
    return `<details ${s.passed ? "" : "open"}><summary>${badge(s.passed)} <b>Step ${s.step}</b> · ${esc(s.title)}
        ${s.extra?.normalised ? ` <b class="badge na" title="average of the last ${s.extra.normalised} fiscal years">(NORMALISED)</b>` : ""}</summary>
      <p class="small"><i>${esc(STEP_ASK[s.step] || "")}</i><br><b>${esc(summary(s))}</b></p>
      ${judged.length ? `<table class="compact"><tbody>${judged.map(rowHtml).join("")}</tbody></table>` : ""}
      ${info.length ? `<details><summary class="small muted">${info.length} information-only rows (no pass/fail)</summary><table class="compact"><tbody>${info.map(rowHtml).join("")}</tbody></table></details>` : ""}
      ${(s.notes || []).filter((n) => !n.startsWith("moat_grade=")).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
      ${s.step === 3 && s.extra?.sources && moatChecklist ? moatChecklist(s.extra, r.ticker) : ""}
      <details><summary class="small muted">raw data</summary><pre class="small">${esc(JSON.stringify(s.checks.map((c) => ({ name: c.name, passed: c.passed, value: c.value, threshold: c.threshold })), null, 1))}</pre></details>
    </details>`;
  }).join("")}</div>`;
}
