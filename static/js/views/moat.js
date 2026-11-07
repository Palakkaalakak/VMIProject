// Moat evaluation (#/moat/SYMBOL): everything needed to judge one company's moat in one place, and the form that
// records the verdict. The verdict is discretionary (Adam gives no formula): the code shows evidence, the reviewer
// decides. Saved as the overrides moat_grade / moat_sources / moat_score (+ date), which Step 3 reads.
import { api } from "../api.js";
import { $, badge, esc, fmt, loading, run, toast } from "../ui.js";

const pctOrDash = (v) => (v == null ? "—" : fmt.pct(v, 1));
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
      <a href="#/analysis/${esc(sym)}">← back to the analysis</a></div>
    <p class="muted">${esc(r.name || "")} · ${esc(r.sector || "")} · ${esc(r.industry || "")}</p>
    <p>Step 3 result: ${badge(step.passed)} · current verdict: ${v ? `<b>${esc(v.grade)}</b>${v.score != null ? ` · score ${esc(v.score)}/10` : ""}${v.sources?.length ? ` · ${esc(v.sources.join(", "))}` : ""}`
      : "<b>not reviewed</b> (provisional result from Adam's two shortcuts: industry list and 10-year chart)"}${x.review?.reviewed_on ? ` · reviewed ${esc(x.review.reviewed_on)}` : ""}</p>
    ${due ? `<p class="note"><b>Review due:</b> ${esc(x.review.reasons.join("; "))}</p>` : ""}</div>`;
}

function testsAndEvidence(step) {
  const row = (c) => `<tr><td>${badge(c.passed)}</td><td>${esc(c.name)}</td><td>${esc(showValue(c.value))}</td>
    <td class="small muted">${esc(c.threshold ?? "")}</td><td class="small">${esc(c.note || "")}</td></tr>`;
  const tests = step.checks.filter((c) => c.passed !== null && c.passed !== undefined);
  const evidence = step.checks.filter((c) => c.passed === null || c.passed === undefined);
  return `<div class="card"><h3>Adam's tests</h3><table class="compact"><tbody>${tests.map(row).join("")}</tbody></table>
    ${(step.notes || []).filter((n) => !n.startsWith("moat_grade=")).map((n) => `<p class="note">${esc(n)}</p>`).join("")}</div>
    <div class="card"><h3>Evidence <span class="muted small">(no pass/fail: Adam gives no numbers, you judge)</span></h3>
    <table class="compact"><tbody>${evidence.map(row).join("")}</tbody></table></div>`;
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
        <b>${esc(k.replace("_", " "))}</b> — ${esc(d)}</label>`).join("")}
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
  root.innerHTML = `${header(sym, r, step)}<div class="cols"><div>${testsAndEvidence(step)}
      <div class="card"><h3>Competitors</h3><div id="moat-peers">${loading("Loading peers …")}</div></div>
      <div class="card"><h3>Annual report</h3><div id="moat-filing">${loading("Loading the latest annual report …")}</div></div>
    </div><div>${verdictForm(step, ov)}</div></div>`;

  api.moatEvidence(sym).then((e) => {
    if (!document.body.contains(root)) return;
    $("#moat-peers", root).innerHTML = peersTable(e.peers);
    $("#moat-filing", root).innerHTML = filingBlock(e.filing);
  }).catch((err) => {
    $("#moat-peers", root).innerHTML = $("#moat-filing", root).innerHTML = `<p class="small muted">Could not load: ${esc(err.message || err)}</p>`;
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
