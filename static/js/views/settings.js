// Settings: edit every rule in vmi/rules.py (saved to config/rules_settings.json, applied immediately) and review
// all per-stock judgement overrides. Nothing here needs code or git; the server validates every value.
import { api } from "../api.js";
import { $, esc, loading, run, toast } from "../ui.js";

import { ruleInput as input, ruleTitle, show } from "../rule_fields.js";

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
      return `<details ${n ? "open" : ""}><summary><b>${esc(rows[0].section_title || sec)}</b> <span class="muted small">${esc(rows[0].section_help)}</span>${n ? ` <span class="badge">${n} changed</span>` : ""}</summary>
        <table class="compact"><tbody>${rows.map((s) => `<tr class="${s.changed ? "selected" : ""}">
          <td>${ruleTitle(s)}</td>
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

function ibCard(s) {
  const when = s.last_sync ? new Date(s.last_sync * 1000).toLocaleString() : "never";
  const busy = s.state === "running";
  return `<section class="card" id="ib-card"><h3>IB fundamentals (statements + analyst growth)</h3>
    <p class="small muted">Last synced: <b>${esc(when)}</b>${s.stale ? ' <span class="badge bad">stale</span>' : ' <span class="badge ok">fresh</span>'}.
      Needs IB Gateway running (live login) for new tickers. A browser window opens: sign in with your PAPER username.</p>
    <p class="small" id="ib-msg">${esc(s.message || "")}</p>
    <button id="ib-sync" ${busy ? "disabled" : ""}>${busy ? "Syncing ..." : "Sync IB fundamentals now"}</button></section>`;
}

const gb = (n) => (n / 1e9).toFixed(2);
function aiCard(a) {
  const b = a.builtin || {}, d = b.download || {};
  const state = a.backend === "ollama" ? `Using your running Ollama (${esc(a.model)}).`
    : b.ready ? `Built-in AI ready (${esc(b.model)}). It starts only when you ask for an opinion and stops after 10 idle minutes.`
    : d.running ? `Downloading ${esc(d.what)}: ${gb(d.done)} of ${d.total ? gb(d.total) : "?"} GB …`
    : b.supported === false ? "The built-in AI is for Windows + NVIDIA; on this system use Ollama (see the README)."
    : "Not downloaded. It needs about 7.5 GB of disk and an NVIDIA GPU with 8 GB or more (less works, slower, using normal RAM).";
  return `<section class="card" id="ai-card"><h3>AI helper (optional, runs on this PC)</h3>
    <p class="small muted">A second opinion on a company's moat on the moat page (Gemma 4 12B). It researches the company itself: its search words go to Bing and Wikipedia and it reads public web pages; nothing you type, your portfolio or your settings leave the PC. The one-time downloads (the llama.cpp program and the model file) also use the internet. Never saved, never a verdict.</p>
    <p class="small" id="ai-msg">${state}${d.error ? ` <span class="neg">${esc(d.error)}</span>` : ""}</p>
    <div class="inline"><button id="ai-dl" ${d.running || b.ready || b.supported === false ? "disabled" : ""}>Download the built-in AI (≈7.5 GB)</button>
      <button id="ai-rm" class="danger" ${b.server_present || b.model_present ? "" : "disabled"}>Remove it</button></div></section>`;
}

async function pollAi(root) {
  const tick = async () => {
    if (!document.body.contains(root) || !$("#ai-card", root)) return;
    const a = await api.aiStatus();
    $("#ai-card", root).outerHTML = aiCard(a);
    bindAi(root);
    if (a.builtin?.download?.running) setTimeout(tick, 2000);
  };
  setTimeout(tick, 2000);
}

function bindAi(root) {
  $("#ai-dl", root)?.addEventListener("click", (e) => run(e.target, async () => { await api.aiDownload(); pollAi(root); }));
  $("#ai-rm", root)?.addEventListener("click", (e) => run(e.target, async () => {
    if (!confirm("Delete the downloaded AI program and model (about 7.5 GB)?")) return;
    await api.aiRemove(); render(root);
  }));
}

async function pollIb(root) {
  const poll = async () => {
    if (!document.body.contains(root) || !$("#ib-card", root)) return;
    const s = await api.ibSync();
    $("#ib-card", root).outerHTML = ibCard(s);
    $("#ib-sync", root)?.addEventListener("click", () => startIb(root));
    if (s.state === "running") setTimeout(poll, 2000);
  };
  setTimeout(poll, 2000);
}

async function startIb(root) {
  const s = await api.startIbSync();
  $("#ib-card", root).outerHTML = ibCard(s);
  $("#ib-sync", root)?.addEventListener("click", () => startIb(root));
  pollIb(root);
}

export async function render(root) {
  root.innerHTML = loading();
  const [schema, all, ib, ai] = await Promise.all([api.settings(), api.overridesAll(), api.ibSync(), api.aiStatus().catch(() => ({}))]);
  root.innerHTML = ibCard(ib) + aiCard(ai) + rulesCard(schema) + overridesCard(all);
  bindAi(root);
  if (ai.builtin?.download?.running) pollAi(root);
  $("#ib-sync", root)?.addEventListener("click", () => startIb(root));
  if (ib.state === "running") pollIb(root);
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
