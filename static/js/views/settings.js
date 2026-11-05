// Settings: edit every rule in vmi/rules.py (saved to config/rules_settings.json, applied immediately) and review
// all per-stock judgement overrides. Nothing here needs code or git; the server validates every value.
import { api } from "../api.js";
import { $, esc, loading, run, toast } from "../ui.js";

const KIND = { adam: ["Adam", "ok"], interpretation: ["interpretation", "na"], owner: ["owner", "na"],
  approved: ["approved", "na"], calibration: ["calibration", "na"], model: ["software", "na"], unspecified: ["UNSPECIFIED", "bad"] };
const badgeFor = (s) => `<span class="badge ${KIND[s.source_kind]?.[1] || "na"}" title="${esc(s.source_note)}">${esc(KIND[s.source_kind]?.[0] || s.source_kind)}</span>`;
const show = (v) => (Array.isArray(v) ? JSON.stringify(v) : String(v));

function input(s) {
  const name = `name="${esc(s.section)}.${esc(s.key)}"`;
  if (s.type === "choice") return `<select ${name}>${s.choices.map((c) => `<option ${c === s.value ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
  if (s.type === "bool") return `<select ${name}><option value="true" ${s.value ? "selected" : ""}>yes</option><option value="false" ${s.value ? "" : "selected"}>no</option></select>`;
  if (s.type === "int" || s.type === "float") return `<input ${name} type="number" step="any" value="${esc(s.value)}">`;
  return `<input ${name} value="${esc(show(s.value))}">`;
}

function rulesCard(schema) {
  const sections = [...new Set(schema.map((s) => s.section))];
  const changed = schema.filter((s) => s.changed).length;
  return `<section class="card"><div class="inline"><h3>Rules</h3><span class="muted small">${changed} changed from the course defaults</span>
      <span class="spacer"></span><button id="st-reset" class="danger" ${changed ? "" : "disabled"}>Reset all to defaults</button></div>
    <p class="small muted">Every threshold the analysis uses. Changes apply to all analyses immediately. Percent values are decimals
      (0.15 = 15%). The badge says where each number comes from: <b>Adam</b> = he states it in the course;
      <b>interpretation</b> = he gives words, we chose the number; <b>owner</b> / <b>calibration</b> = your rule or an
      approved fit to his published values; <b>software</b> = technical guard.</p>
    <form id="st-form">${sections.map((sec) => {
      const rows = schema.filter((s) => s.section === sec);
      const n = rows.filter((s) => s.changed).length;
      return `<details ${n ? "open" : ""}><summary><b>${esc(sec)}</b> <span class="muted small">${esc(rows[0].section_help)}</span>${n ? ` <span class="badge">${n} changed</span>` : ""}</summary>
        <table class="compact"><tbody>${rows.map((s) => `<tr class="${s.changed ? "selected" : ""}">
          <td title="${esc(s.help)}"><b>${esc(s.key)}</b> ${badgeFor(s)}<div class="small muted">${esc(s.source_note)}${s.help && s.help !== s.source_note ? ` — ${esc(s.help)}` : ""}</div></td>
          <td>${input(s)}</td>
          <td class="small muted">${s.changed ? `default ${esc(show(s.default))} <button type="button" class="link" data-reset="${esc(s.section)}.${esc(s.key)}">reset</button>` : ""}</td></tr>`).join("")}
        </tbody></table></details>`;
    }).join("")}
    <div class="inline"><button class="primary">Save changes</button></div></form></section>`;
}

function overridesCard(all) {
  const rows = Object.entries(all);
  return `<section class="card"><h3>Per-stock judgement overrides</h3>
    <p class="small muted">Edit them on each stock's Analysis page (Judgement overrides card). "judgement" = saved in config/judgements.json, "db" = saved in the app database.</p>
    ${rows.length ? `<table class="compact"><thead><tr><th>Ticker</th><th>Overrides</th><th>Why</th><th>Saved in</th><th></th></tr></thead><tbody>
      ${rows.map(([sym, o]) => `<tr><td><a href="#/analysis/${esc(sym)}"><b>${esc(sym)}</b></a></td>
        <td class="small">${esc(Object.entries(o.data || {}).map(([k, v]) => `${k}=${show(v)}`).join(" · "))}</td>
        <td class="small muted">${esc(o.note || "")}</td><td class="small">${esc(o.source || "")}</td>
        <td><button class="danger small" data-clear="${esc(sym)}" data-commit="${o.source === "judgement" ? "1" : ""}">Clear</button></td></tr>`).join("")}
    </tbody></table>` : `<p class="muted">No overrides yet.</p>`}</section>`;
}

export async function render(root) {
  root.innerHTML = loading();
  const [schema, all] = await Promise.all([api.settings(), api.overridesAll()]);
  root.innerHTML = rulesCard(schema) + overridesCard(all);
  const byName = Object.fromEntries(schema.map((s) => [`${s.section}.${s.key}`, s]));

  $("#st-form", root).addEventListener("submit", (e) => {
    e.preventDefault();
    const changes = {};
    for (const el of e.target.querySelectorAll("[name]")) {
      const s = byName[el.name];
      if (!s || el.value === show(s.value) || (s.type === "bool" && (el.value === "true") === s.value)) continue;
      (changes[s.section] ||= {})[s.key] = s.type === "list" && el.value.trim().startsWith("[") ? JSON.parse(el.value) : el.value;
    }
    if (!Object.keys(changes).length) return toast("Nothing changed", "info");
    run(e.submitter, async () => { await api.saveSettings(changes); toast("Settings saved", "ok"); render(root); });
  });
  root.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", () => {
    const [sec, key] = b.dataset.reset.split(".");
    run(b, async () => { await api.saveSettings({ [sec]: { [key]: null } }); toast(`${key} reset`, "ok"); render(root); });
  }));
  $("#st-reset", root)?.addEventListener("click", (e) => run(e.target, async () => { await api.resetSettings(); toast("All settings reset", "ok"); render(root); }));
  root.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () =>
    run(b, async () => { await api.clearOverride(b.dataset.clear, !!b.dataset.commit); toast(`${b.dataset.clear} overrides cleared`, "ok"); render(root); })));
}
