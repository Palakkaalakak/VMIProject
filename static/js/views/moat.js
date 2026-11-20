// Moat evaluation (#/moat/SYMBOL): everything needed to judge one company's moat in one place, and the form that
// records the verdict. The verdict is discretionary (Adam gives no formula): the code shows evidence, the reviewer
// decides. Saved as the overrides moat_grade / moat_sources / moat_score (+ date), which Step 3 reads.
import { api } from "../api.js";
import { $, badge, esc, fmt, loading, run, toast } from "../ui.js";
import { startGuide } from "../moat_guide.js";
import { mountChart } from "../chart_view.js";

const pctOrDash = (v) => (v == null ? "—" : fmt.pct(v, 1));
const SOURCE_NAMES = { brand: "1a. Brand", pricing_power: "1b. Pricing power (instead of brand)", switching_costs: "2. Switching costs",
  network_effect: "3. Network effect", barriers: "4. Barriers to entry", scale: "5. Economies of scale" };
const GRADES = ["", "wide", "narrow", "none"];

function showValue(v) {
  if (typeof v === "number") return fmt.num(v, 4);
  if (Array.isArray(v)) return v.map((x) => (typeof x === "number" && Math.abs(x) < 1 ? fmt.pct(x, 1) : showValue(x))).join(", ");
  if (v && typeof v === "object") return Object.entries(v).map(([k, x]) => `${k} ${typeof x === "number" && Math.abs(x) < 1 ? fmt.pct(x, 1) : fmt.big(x)}`).join(" · ");
  return v ?? "";
}

function header(sym, r, step) {
  const x = step.extra || {}, v = x.verdict, due = x.review?.due;
  return `<div class="card"><div class="inline"><h2>Moat evaluation — ${esc(sym)}</h2>
      <a href="#/analysis/${esc(sym)}">← back to the analysis</a><span class="spacer"></span>
      <button type="button" class="primary" id="moat-guide-start" title="Walk through Adam's Step 3 one question at a time, with what to search for">Guided evaluation</button></div>
    <p class="muted">${esc(r.name || "")} · ${esc(r.sector || "")} · ${esc(r.industry || "")}</p>
    <p>Step 3 result: ${badge(step.passed)} · current verdict: ${v ? `<b>${esc(v.grade)}</b>${v.score != null ? ` · score ${esc(v.score)}/10` : ""}${v.sources?.length ? ` · ${esc(v.sources.join(", "))}` : ""}`
      : "<b>not reviewed</b> (provisional result from Adam's two shortcuts: industry list and 10-year chart)"}${x.review?.reviewed_on ? ` · reviewed ${esc(x.review.reviewed_on)}` : ""}</p>
    ${due ? `<p class="note"><b>Review due:</b> ${esc(x.review.reasons.join("; "))}</p>` : ""}</div>`;
}

function testsAndEvidence(step) {
  const row = (c) => `<tr><td>${badge(c.passed)}</td><td><b>${esc(c.name.replaceAll("_", " "))}</b>${c.help ? `<div class="small muted" style="max-width:34rem">${esc(c.help)}</div>` : ""}</td><td>${esc(showValue(c.value))}</td>
    <td class="small muted">${esc(c.threshold ?? "")}</td><td class="small">${esc(c.note || "")}</td></tr>`;
  const tests = step.checks.filter((c) => c.passed !== null && c.passed !== undefined);
  const evidence = step.checks.filter((c) => c.passed === null || c.passed === undefined);
  return `<div class="card"><h3>Adam's tests</h3><table class="compact"><tbody>${tests.map(row).join("")}</tbody></table>
    ${(step.notes || []).filter((n) => !n.startsWith("moat_grade=")).map((n) => `<p class="note">${esc(n)}</p>`).join("")}</div>
    <div class="card"><h3>How to review the moat (Adam, Step 3)</h3><ol class="small">
      <li><b>Wide, narrow or none.</b> Wide: about 20 years of protection, no or insignificant competitors, can raise prices without losing customers, very high margins. Narrow: about 10 years, several significant competitors, limited pricing power, average margins. None: many competitors selling almost the same thing, price decides. He invests in wide (most of his stocks) and narrow; never in no-moat. <i>This list is set to WIDE only for our watchlists.</i></li>
      <li><b>Count the five sources</b> and tick the ones you can show with evidence: brand monopoly, switching costs, network effect, barriers to entry (patents, regulation), economies of scale. He wants at least 3 of 5.</li>
      <li><b>Be the customer.</b> Would you pick a competitor if it were cheaper? Compare the closest competitors (peer table below): they should be weaker, and the company should be the top dog of its niche. No clear leader = forget it.</li>
      <li><b>Look for trouble signs:</b> customers concentrated in a few buyers (for example 80% from 3 customers), margins falling for years, losing market share.</li>
      <li><b>Cross-check:</b> the 10-year chart (uptrend = sign of a moat) and, if you have Stock Oracle, its moat grade and AI moat score (he wants 7 to 9 out of 10; 6 is not strong enough).</li></ol></div>
    <div class="card" id="moat-first"><h3>At first sight</h3><p class="small muted">Loading the quick read …</p></div>
    <div class="card" id="moat-ai" hidden><h3>AI second opinion <span class="badge na">minor help</span></h3>
      <p class="small muted">A local model (runs on this PC) researches the company itself on the web and on this app's Analysis page, cites a source for every claim, applies Adam's rules for the next 10-20 years and reviews its own verdict (when unsure it grades lower). Its search words go to Bing and Wikipedia; nothing else leaves the PC. It can be wrong: treat it as a prompt to check, not a verdict. Not saved.</p>
      <button type="button" id="moat-ai-go">Ask the local AI</button> <button type="button" class="secondary" id="moat-ai-check" hidden>Run the checker (optional)</button>
      <div id="moat-ai-out" class="small"></div><div id="moat-ai-check-out" class="small"></div></div>
    <div class="card"><h3>Evidence <span class="muted small">(no pass/fail: Adam gives no numbers, you judge)</span></h3>
    <table class="compact"><tbody>${evidence.map(row).join("")}</tbody></table></div>`;
}

const READ = { good: "ok", bad: "bad", unknown: "na" };
function firstSight(fs) {
  if (!fs) return `<h3>At first sight</h3><p class="small muted">Not available (no fundamentals).</p>`;
  return `<h3>At first sight <span class="badge ${fs.leaning === "wide-looking" ? "ok" : fs.leaning === "weak" ? "bad" : "na"}">${esc(fs.leaning)}</span></h3>
    <p>${esc(fs.paragraph)}</p>
    <table class="compact"><tbody>${fs.signals.map((s) => `<tr><td><span class="badge ${READ[s.reading]}">${esc(s.reading)}</span></td><td><b>${esc(s.label)}</b></td><td class="small">${esc(s.text)}</td>
      <td class="small muted" title="adam = a test or comparison Adam states; inferred = Adam gives no bar, read off his own examples">${esc(s.source)}</td></tr>`).join("")}</tbody></table>`;
}

function peersTable(p) {
  if (!p?.rows?.length) return `<p class="small muted">Peers: ${esc(p?.basis || "no data")}</p>`;
  const s = p.summary || {};
  return `<p class="small">${esc(p.basis)}, calendar ${p.year}${s.ranks ? ` — sales rank ${s.ranks.revenue}/${s.peers + 1}, operating-margin rank ${s.ranks.operating_margin}, growth rank ${s.ranks.growth_3y}${s.top_dog_hint ? " · <b>looks like the industry leader</b>" : ""}` : ""}</p>
    <table class="compact"><thead><tr><th>Ticker</th><th>Sales</th><th>Share</th><th>Gross</th><th>Operating</th><th>Net</th><th>3y sales growth</th></tr></thead><tbody>
    ${p.rows.map((r) => `<tr><td><a href="#/moat/${esc(r.symbol)}"><b>${esc(r.symbol)}</b></a> <span class="muted small">${esc(r.name)}</span></td><td>${fmt.money(r.revenue / 1e9, 1)}B</td><td>${pctOrDash(r.share)}</td>
      <td>${pctOrDash(r.gross_margin)}</td><td>${pctOrDash(r.operating_margin)}</td><td>${pctOrDash(r.net_margin)}</td><td>${pctOrDash(r.growth_3y)}</td></tr>`).join("")}</tbody></table>`;
}

function filingBlock(f) {
  if (!f?.url) return `<p class="small muted">Annual report: not available.</p>`;
  return `<p class="small">Latest ${esc(f.form)}, filed ${esc(f.filed)} (<a href="${esc(f.url)}" target="_blank" rel="noopener">open the filing</a>)</p>
    ${f.competition ? `<p class="small"><b>Competition:</b> ${esc(f.competition)}</p>` : `<p class="small muted">No competition passage found.</p>`}
    ${(f.customer_concentration || []).length ? `<p class="small"><b>Customer concentration:</b></p><ul class="small">${f.customer_concentration.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="small muted">No customer-concentration sentences found.</p>`}`;
}

function verdictForm(step, ov) {
  const x = step.extra || {}, have = new Set(ov.moat_sources || []);
  return `<div class="card"><h3>Your verdict</h3>
    <form id="moat-form">
      <p class="small"><b>Moat sources present</b> (Adam: at least 3 of 5 to invest; 4+ suggests wide)</p>
      ${Object.entries(x.sources || {}).map(([k, d]) => `<label class="small" style="display:block"><input type="checkbox" name="src" value="${esc(k)}" ${have.has(k) ? "checked" : ""}>
        <b>${esc(SOURCE_NAMES[k] || k.replace("_", " "))}</b> — ${esc(d)}</label>`).join("")}
      <p class="small muted">Brand and pricing power are the same, first source: tick whichever fits (ticking both still counts once).</p>
      <p class="small"><b>Questions to answer</b></p>
      <ul class="small muted">${(x.questions || []).map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
      <div class="inline">
        <label>Verdict <select name="grade">${GRADES.map((g) => `<option value="${g}" ${(ov.moat_grade || "") === g ? "selected" : ""}>${g || "—"}</option>`).join("")}</select></label>
        <label>Score /10 <input name="score" type="number" min="0" max="10" step="0.5" value="${esc(ov.moat_score ?? "")}" style="width:5rem"></label>
        <label class="small"><input type="checkbox" name="commit"> save to config/judgements.json (shared, committed)</label>
      </div>
      <label class="small" style="display:block">Why (kept with the verdict)<textarea name="note" rows="3" style="width:100%">${esc(ov.note || "")}</textarea></label>
      <button type="submit">Save verdict</button>
    </form></div>`;
}

export async function render(root, params) {
  const sym = (params.symbol || "").toUpperCase();
  if (!sym) { root.innerHTML = `<div class="card">Open this page from a stock's Step 3 (Moat evaluation button).</div>`; return; }
  root.innerHTML = loading(`Loading ${sym} …`);
  const [r, ovBox] = await Promise.all([api.analyse(sym, false), api.override(sym).catch(() => ({}))]);
  const step = (r.steps || []).find((s) => s.step === 3);
  if (!step) { root.innerHTML = `<div class="card">No Step 3 result for ${esc(sym)}.</div>`; return; }
  const ov = ovBox?.data || ovBox || {};
  root.innerHTML = `${header(sym, r, step)}<div id="moat-guide"></div><div class="cols"><div>${testsAndEvidence(step)}
      <div class="card"><h3>Competitors</h3><div id="moat-peers">${loading("Loading peers …")}</div></div>
      <div class="card"><h3>Annual report</h3><div id="moat-filing">${loading("Loading the latest annual report …")}</div></div>
    </div><div>${verdictForm(step, ov)}<div class="card"><h3>Chart</h3><div id="moat-chart"></div></div></div></div>`;
  mountChart($("#moat-chart", root), sym).catch(() => {});

  api.aiStatus().then((a) => {
    if (!a.available || !document.body.contains(root)) return;
    const card = $("#moat-ai", root); card.hidden = false;
    $("#moat-ai-go", root).addEventListener("click", (e) => run(e.target, async () => {
      $("#moat-ai-out", root).textContent = `Researching and thinking (${a.model}) … usually 2-4 minutes`;
      $("#moat-ai-check-out", root).textContent = "";
      const br = (t) => esc(t || "").replaceAll("\n", "<br>");
      try {
        const res = await api.aiOpinion(sym);
        $("#moat-ai-out", root).innerHTML = (res.grade ? `<p><b>AI grade: ${esc(res.grade)}</b>${res.first_grade && res.first_grade !== res.grade ? ` (first draft said ${esc(res.first_grade)}; its own review lowered it)` : ""}</p>` : "")
          + `<p>${br(res.opinion)}</p>`
          + (res.notes ? `<details><summary>Research notes with sources</summary><p>${br(res.notes)}</p></details>` : "")
          + `<p class="muted">AI opinion from ${esc(res.model)}</p>`;
        $("#moat-ai-check", root).hidden = !res.can_check;
      } catch (err) { $("#moat-ai-out", root).innerHTML = `<span class="neg">${esc(err.message)}</span>`; }
    }));
    $("#moat-ai-check", root).addEventListener("click", (e) => run(e.target, async () => {
      $("#moat-ai-check-out", root).textContent = "Checking every claim against its source … about a minute";
      try {
        const c = await api.aiCheck(sym);
        $("#moat-ai-check-out", root).innerHTML = `<p><b>After the checker: ${esc(c.grade || "?")}</b> (the checker judged every claim against its sources; it can raise or lower the AI grade)</p><p>${esc(c.check).replaceAll("\n", "<br>")}</p>`;
      } catch (err) { $("#moat-ai-check-out", root).innerHTML = `<span class="neg">${esc(err.message)}</span>`; }
    }));
  }).catch(() => {});
  const gctx = { sym, name: r.name, ov, evidence: null, onDone: () => render(root, params) };
  let guide = null;
  $("#moat-guide-start", root).addEventListener("click", () => { guide = startGuide($("#moat-guide", root), gctx); window.scrollTo({ top: 0, behavior: "smooth" }); });
  api.moatEvidence(sym).then((e) => {
    if (!document.body.contains(root)) return;
    gctx.evidence = e;
    $("#moat-first", root).innerHTML = firstSight(e.first_sight);
    if (guide && $("#moat-guide", root).innerHTML) guide.refresh();
    $("#moat-peers", root).innerHTML = peersTable(e.peers);
    $("#moat-filing", root).innerHTML = filingBlock(e.filing);
  }).catch((err) => {
    $("#moat-peers", root).innerHTML = $("#moat-filing", root).innerHTML = $("#moat-first", root).innerHTML = `<p class="small muted">Could not load: ${esc(err.message || err)}</p>`;
  });

  $("#moat-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target;
    const score = f.score.value === "" ? null : Number(f.score.value);
    const data = { moat_grade: f.grade.value || null, moat_score: score,
      moat_sources: [...f.querySelectorAll("[name=src]:checked")].map((c) => c.value) };
    run(e.submitter, async () => {
      await api.setOverride(sym, { data, note: f.note.value, commit: f.commit.checked });
      toast(`${sym}: moat verdict saved`, "ok");
      render(root, params);
    });
  });
}
