import { api } from "../api.js";
import { $, esc, loading, run, toast } from "../ui.js";

const gb = (n) => (n / 1e9).toFixed(2);

function modelCard(status) {
  const b = status.builtin, d = b.download;
  const active = status.backend === "ollama" ? `Active model: Ollama (${esc(status.model)}).`
    : status.backend === "builtin" ? `Active model: built-in (${esc(status.model)}).` : "No model is ready yet.";
  const state = d.running ? `Downloading ${esc(d.what)}: ${gb(d.done)} of ${d.total ? gb(d.total) : "?"} GB …`
    : b.ready ? `Built-in model ${b.running ? "running" : "ready to start"}.`
    : b.supported ? "Built-in model not downloaded (about 7.5 GB)." : "The built-in download is Windows-only; use Ollama on this system.";
  return `<section class="card" id="ai-model"><h3>Model setup</h3>
    <p>${active} ${state}</p>
    <p class="small muted">Prompts stay on this PC with the built-in model, or go to the configured Ollama server. Research sends public company search terms to web services and reads public pages. Verify AI claims before relying on them.</p>
    ${b.safety_stop ? `<p class="neg small">Last safety stop: ${esc(b.safety_stop)}.</p>` : ""}
    ${d.error ? `<p class="neg small">${esc(d.error)}</p>` : ""}
    <div class="inline"><button id="ai-dl" ${d.running || b.ready || !b.supported ? "disabled" : ""}>Download built-in model</button>
    <button id="ai-rm" class="danger" ${!d.running && (b.server_present || b.model_present) ? "" : "disabled"}>Remove built-in model</button></div></section>`;
}

function settingsForm(s) {
  const limit = (name, label, min, max, step = 1) => `<label>${label} <input name="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${esc(s[name])}" required></label>`;
  return `<form id="ai-settings-form"><section class="card"><h3>Company overview defaults</h3>
    <div class="inline"><label>Default depth <select name="overview_depth">${["quick", "standard", "deep"].map((depth) =>
      `<option ${s.overview_depth === depth ? "selected" : ""}>${depth}</option>`).join("")}</select></label>
    <label><input type="checkbox" name="cache_overviews" ${s.cache_overviews ? "checked" : ""}> Reuse locally cached overviews for up to 3 days</label></div></section>
    <section class="card"><h3>Built-in AI safety</h3>
    <p class="small muted">Built-in model only. The guard checks about once a second. After a stop, you can retry as soon as the current readings allow it; there is no fixed cooldown. The model shuts down after 10 idle minutes.</p>
    <div class="inline">${limit("max_run_minutes", "Maximum runtime (minutes)", 5, 40)}
    ${limit("max_gpu_temp_c", "Maximum GPU temperature (°C)", 65, 85)}
    ${limit("min_free_ram_mb", "Minimum free RAM (MB)", 1536, 8192)}</div>
    <p><label><input type="checkbox" name="override_ram_guard" ${s.override_ram_guard ? "checked" : ""}> Override system RAM guard (advanced)</label></p>
    <p class="small neg">This bypasses startup and running system RAM checks. Low memory can freeze the PC or crash the model. GPU temperature, GPU memory, and maximum runtime protections stay on.</p></section>
    <button class="primary">Save AI settings</button></form>`;
}

export async function render(root) {
  root.innerHTML = loading();
  const [status, settings] = await Promise.all([api.aiStatus(), api.aiSettings()]);
  root.innerHTML = `<h2>AI Settings</h2><div id="ai-model-slot"></div>${settingsForm(settings)}`;
  const slot = $("#ai-model-slot", root);
  function show(status) {
    if (!slot.isConnected) return;
    slot.innerHTML = modelCard(status);
    if (status.builtin.download.running) {
      setTimeout(() => {
        if (slot.isConnected) api.aiStatus().then(show).catch((e) => toast(e.message, "error"));
      }, 2000);
    }
    $("#ai-dl", slot).onclick = (e) => run(e.target, async () => {
      await api.aiDownload();
      show(await api.aiStatus());
    });
    $("#ai-rm", slot).onclick = (e) => run(e.target, async () => {
      if (!confirm("Delete the built-in AI runtime and its downloaded model?")) return;
      await api.aiRemove();
      show(await api.aiStatus());
    });
  }
  show(status);
  $("#ai-settings-form", root).onsubmit = (e) => {
    e.preventDefault();
    const fields = e.currentTarget.elements;
    run(e.submitter, async () => {
      if (fields.override_ram_guard.checked && !settings.override_ram_guard &&
          !confirm("Bypass system RAM safeguards? The PC may freeze or the model may crash when memory is low.")) return;
      await api.saveAiSettings({ overview_depth: fields.overview_depth.value, cache_overviews: fields.cache_overviews.checked,
        max_run_minutes: fields.max_run_minutes.valueAsNumber, max_gpu_temp_c: fields.max_gpu_temp_c.valueAsNumber,
        min_free_ram_mb: fields.min_free_ram_mb.valueAsNumber, override_ram_guard: fields.override_ram_guard.checked });
      settings.override_ram_guard = fields.override_ram_guard.checked;
      toast("AI settings saved", "ok");
    });
  };
}
