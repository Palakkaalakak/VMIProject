// Guided Moat Evaluation: walks through Adam's Step 3 one question at a time (what he says, what to search for, what the
// app already knows), you answer each, and it ends with the final verdict + an optional comment, saved exactly like the
// manual form does (moat_grade / moat_sources / moat_score as a judgement override).
import { api } from "./api.js";
import { esc, run, toast } from "./ui.js";

const search = (q) => `https://www.google.com/search?q=${encodeURIComponent(q)}`;

/** The questions, in Adam's order. `source` = the moat source this question decides (or null for a judgement question). */
const STEPS = (name) => [
  { id: "brand", source: "brand", title: "1. Brand OR pricing power",
    adam: "A strong brand: the first name people think of, loyal even when it costs more. If 'brand' does not fit the company, use PRICING POWER instead (Adam did this in a recent video): can it raise prices every year without losing customers or market share? Either one counts as the first source.",
    look: [`${name} customers loyal even if more expensive`, `${name} price increase customers kept buying`, `${name} brand ranking survey`],
    evidence: "pricing" },
  { id: "switching_costs", source: "switching_costs", title: "2. High switching costs",
    adam: "Is it costly, risky or painful to leave? Think embedded enterprise software, ecosystems, contracts. Test: if a rival were cheaper, would customers still stay?",
    look: [`${name} switching costs customers`, `${name} customer retention rate`, `${name} net revenue retention`], evidence: "switching" },
  { id: "network_effect", source: "network_effect", title: "3. Network effect",
    adam: "Does every extra user make it better for all the others (marketplaces, social networks, payments)?",
    look: [`${name} network effect`, `${name} number of users growth`], evidence: null },
  { id: "barriers", source: "barriers", title: "4. High barriers to entry",
    adam: "Regulation, licences, patents, security clearances: could a well-funded newcomer simply enter?",
    look: [`${name} patents regulation barriers to entry`, `${name} licence required competitors`], evidence: null },
  { id: "scale", source: "scale", title: "5. Economies of scale",
    adam: "So big that competing is almost impossible: it buys in bulk, runs more efficiently, spreads fixed costs, and can undercut temporarily.",
    look: [`${name} market share largest competitor`, `${name} cost advantage scale`], evidence: null },
  { id: "competitors", source: null, title: "6. The competitors",
    adam: "Are the closest competitors clearly weaker? Invest in the top dog of the industry; no clear leader = forget it. Their margins should be at or below this company's.",
    look: [`${name} top competitors market share`, `${name} vs competitors`], evidence: "peers" },
  { id: "horizon", source: null, title: "7. How long does the advantage last?",
    adam: "Could a bigger competitor kill it within 1-3 years (no moat)? Safe for about 10 years (narrow)? Or about 20 (wide)? Also: customers concentrated in a few buyers, margins falling for years, or losing share are trouble signs.",
    look: [`${name} biggest customers concentration risk`, `${name} losing market share`, `${name} disruption risk`], evidence: "first" },
];

const ANSWERS = [["yes", "Yes, I can show it"], ["partly", "Partly / not sure"], ["no", "No"]];

function evidenceBlock(kind, ctx) {
  const fs = ctx.evidence?.first_sight;
  if (!kind) return "";
  if (!ctx.evidence) return `<p class="small muted">Loading the app's evidence …</p>`;
  const pick = (label) => (fs?.signals || []).filter((s) => label.includes(s.label));
  const sig = kind === "pricing" ? pick(["Pricing power", "Margin level", "Margin trend (5 years)"])
    : kind === "peers" ? pick(["Versus competitors", "Industry position"])
    : kind === "first" ? (fs?.signals || []) : [];
  const rows = sig.map((s) => `<li><span class="badge ${s.reading === "good" ? "ok" : s.reading === "bad" ? "bad" : "na"}">${esc(s.reading)}</span> <b>${esc(s.label)}</b>: ${esc(s.text)} <span class="muted">(${esc(s.source)})</span></li>`).join("");
  const sw = kind === "switching" ? ctx.switching : "";
  return `<div class="note small"><b>What the app already knows</b><ul>${rows || "<li>nothing relevant from the numbers</li>"}</ul>${sw || ""}</div>`;
}

/** Start the wizard inside `box`. ctx = {sym, name, evidence (may arrive later), ov (existing override data), onDone}. */
export function startGuide(box, ctx) {
  const steps = STEPS(ctx.name || ctx.sym);
  const state = { i: 0, answers: {}, notes: {}, grade: ctx.ov?.moat_grade || "", score: ctx.ov?.moat_score ?? "", comment: "" };
  for (const s of steps) if (s.source && (ctx.ov?.moat_sources || []).includes(s.source)) state.answers[s.id] = "yes";
  if ((ctx.ov?.moat_sources || []).includes("pricing_power")) state.answers.brand = "yes";

  const sources = () => steps.filter((s) => s.source && state.answers[s.id] === "yes").map((s) => (s.id === "brand" && state.pricing ? "pricing_power" : s.source));

  function draw() {
    const n = steps.length;
    if (state.i < n) return drawStep(steps[state.i], n);
    drawFinal();
  }

  function drawStep(s, n) {
    box.innerHTML = `<div class="card"><div class="inline"><h3>Guided moat evaluation — ${esc(ctx.sym)}</h3><span class="spacer"></span>
        <span class="muted small">question ${state.i + 1} of ${n + 1}</span><button type="button" class="secondary small" id="mg-quit">Close</button></div>
      <h4>${esc(s.title)}</h4>
      <p><b>Adam:</b> ${esc(s.adam)}</p>
      <p class="small"><b>What to search for:</b></p>
      <ul class="small">${s.look.map((q) => `<li><a href="${search(q)}" target="_blank" rel="noopener">${esc(q)}</a></li>`).join("")}</ul>
      ${evidenceBlock(s.evidence, ctx)}
      <form id="mg-form">
        ${s.source ? `<div class="inline">${ANSWERS.map(([v, l]) => `<label><input type="radio" name="ans" value="${v}" ${state.answers[s.id] === v ? "checked" : ""}> ${l}</label>`).join("")}</div>
          ${s.id === "brand" ? `<label class="small"><input type="checkbox" name="pricing" ${state.pricing ? "checked" : ""}> I'm counting <b>pricing power</b> here instead of brand</label>` : ""}`
          : `<div class="inline">${ANSWERS.map(([v, l]) => `<label><input type="radio" name="ans" value="${v}" ${state.answers[s.id] === v ? "checked" : ""}> ${v === "yes" ? "Looks good" : v === "partly" ? "Unsure" : "Looks bad"}</label>`).join("")}</div>`}
        <label class="small" style="display:block">Your note (optional)<textarea name="note" rows="2" style="width:100%">${esc(state.notes[s.id] || "")}</textarea></label>
        <div class="inline"><button type="button" class="secondary" id="mg-back" ${state.i ? "" : "disabled"}>← Back</button>
          <button class="primary">${state.i === n - 1 ? "To the verdict →" : "Next →"}</button></div>
      </form></div>`;
    box.querySelector("#mg-quit").addEventListener("click", () => { box.innerHTML = ""; });
    box.querySelector("#mg-back").addEventListener("click", () => { save(s); state.i = Math.max(0, state.i - 1); draw(); });
    box.querySelector("#mg-form").addEventListener("submit", (e) => { e.preventDefault(); save(s); state.i += 1; draw(); });
  }

  function save(s) {
    const f = box.querySelector("#mg-form");
    const ans = f.querySelector("[name=ans]:checked");
    if (ans) state.answers[s.id] = ans.value;
    if (s.id === "brand") state.pricing = f.querySelector("[name=pricing]").checked;
    state.notes[s.id] = f.note.value.trim();
  }

  function drawFinal() {
    const picked = sources();
    const fs = ctx.evidence?.first_sight;
    const suggestion = picked.length >= 4 ? "wide" : picked.length >= 3 ? "narrow" : "";
    box.innerHTML = `<div class="card"><div class="inline"><h3>Final moat evaluation — ${esc(ctx.sym)}</h3><span class="spacer"></span>
        <button type="button" class="secondary small" id="mg-quit">Close</button></div>
      <p><b>Sources you could show: ${picked.length} of 5</b> (Adam: at least 3 to invest; 4+ suggests wide) — ${esc(picked.map((p) => p.replace("_", " ")).join(", ") || "none")}</p>
      ${fs ? `<p class="small">${esc(fs.paragraph)}</p>` : ""}
      <ul class="small">${steps.map((s) => `<li><b>${esc(s.title)}</b>: ${esc(state.answers[s.id] || "not answered")}${state.notes[s.id] ? ` — ${esc(state.notes[s.id])}` : ""}</li>`).join("")}</ul>
      <form id="mg-final">
        <div class="inline">
          <label>Verdict <select name="grade">${["", "wide", "narrow", "none"].map((g) => `<option value="${g}" ${(state.grade || suggestion) === g ? "selected" : ""}>${g || "—"}</option>`).join("")}</select></label>
          <label>Score /10 <input name="score" type="number" min="0" max="10" step="0.5" value="${esc(state.score)}" style="width:5rem"></label>
          <label class="small"><input type="checkbox" name="commit"> save to config/judgements.json (shared, committed)</label>
        </div>
        <p class="small muted">Suggested from your answers: <b>${suggestion || "no verdict yet (fewer than 3 sources)"}</b>. Wide vs narrow is your call (pricing power, how long the advantage lasts); the score is Stock Oracle's AI moat score or your own (Adam wants 7 or more).</p>
        <label class="small" style="display:block">Overall comment (optional)<textarea name="comment" rows="3" style="width:100%">${esc(state.comment)}</textarea></label>
        <div class="inline"><button type="button" class="secondary" id="mg-back">← Back</button><button class="primary">Save the moat evaluation</button></div>
      </form></div>`;
    box.querySelector("#mg-quit").addEventListener("click", () => { box.innerHTML = ""; });
    box.querySelector("#mg-back").addEventListener("click", () => { state.i = steps.length - 1; draw(); });
    box.querySelector("#mg-final").addEventListener("submit", (e) => {
      e.preventDefault();
      const f = e.target;
      const score = f.score.value === "" ? null : Number(f.score.value);
      const noteLines = steps.filter((s) => state.notes[s.id]).map((s) => `${s.title}: ${state.notes[s.id]}`);
      const note = [f.comment.value.trim(), ...noteLines].filter(Boolean).join("\n");
      run(e.submitter, async () => {
        await api.setOverride(ctx.sym, { data: { moat_grade: f.grade.value || null, moat_score: score, moat_sources: picked }, note, commit: f.commit.checked });
        toast(`${ctx.sym}: moat evaluation saved`, "ok");
        ctx.onDone?.();
      });
    });
  }

  draw();
  return { refresh: draw };
}
