// Admin: the courtyard itself. For now the facts — hub health, configuration, counts.
// Housekeeping actions (clearing removed agents and their lines, defaults) come next (7c).

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store, isInactive, setTheme, effectiveTheme } from "../store.js";
import { useStore } from "../ui.js";

// Team mode + terminal app (design §8.1, D23). The mode changes only here; the Courtyard
// page's shift pill just shows it. `always_on` is a future mode — visible so the choice
// is documented, disabled because v1 does not implement it.
function TeamSection() {
  const [settings, setSettings] = useState(null);
  useEffect(() => { api.settings().then(setSettings).catch(() => {}); }, []);
  if (!settings) return null;
  const save = (patch) => api.patchSettings(patch).then(setSettings).catch(() => {});
  const MODES = [["on_shift", "On shift"], ["always_on", "Always on"]];
  const APPS = ["Terminal", "iTerm2"];
  return html`<div class="panel"><h3>Team</h3>
    <div class="form-row"><span class="small muted" style="min-width:9rem">Team mode</span>
      ${MODES.map(([mode, label]) => html`<button
        class="btn ${settings.team_mode === mode ? "primary" : ""}"
        disabled=${mode === "always_on"}
        title=${mode === "always_on" ? "not yet available — agents running without an operator is a future mode" : ""}
        onClick=${() => save({ team_mode: mode })}>${label}</button>`)}
      <span class="small muted">— agents start with your shift and stop when it ends</span></div>
    <div class="form-row"><span class="small muted" style="min-width:9rem">Terminal application</span>
      ${APPS.map((app) => html`<button class="btn ${settings.terminal_app === app ? "primary" : ""}"
        onClick=${() => save({ terminal_app: app })}>${app}</button>`)}
      <span class="small muted">— where Start shift opens the agents' windows</span></div></div>`;
}

export function Admin() {
  useStore();
  const [health, setHealth] = useState(null);
  const [config, setConfig] = useState(null);
  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => setHealth({ status: "unreachable" }));
    api.config().then(setConfig).catch(() => {});
  }, []);
  const agents = [...store.agents.values()];
  const active = agents.filter((a) => !a.removed_at).length;
  const lines = [...store.lines.values()];
  const inactive = lines.filter(isInactive).length;
  const THEMES = [["system", "follow the system"], ["light", "light"], ["dark", "dark"]];
  return html`
    <${TeamSection} />
    <div class="panel"><h3>Appearance</h3>
      <div class="form-row">${THEMES.map(([t, label]) => html`<button class="btn ${store.ui.theme === t ? "primary" : ""}"
        onClick=${() => setTheme(t)}>${label}</button>`)}
        <span class="small muted">${store.ui.theme === "system" ? `— the system is ${effectiveTheme()} right now` : ""}</span></div></div>
    <div class="panel"><h3>Hub</h3>
      <dl class="kv">
        <dt>status</dt><dd>${health ? `${health.status} · db ${health.db ?? "?"}` : "…"}</dd>
        <dt>address</dt><dd>${location.origin}</dd>
        ${config ? Object.entries(config).map(([k, v]) => html`<dt>${k}</dt><dd>${String(v)}</dd>`) : null}
      </dl></div>
    <div class="panel"><h3>Courtyard</h3>
      <dl class="kv">
        <dt>agents</dt><dd>${active} active · ${agents.length - active} removed</dd>
        <dt>lines</dt><dd>${lines.length - inactive} active · ${inactive} inactive</dd>
        <dt>held at the gate</dt><dd>${store.pending.size}</dd>
      </dl>
      <div class="small muted" style="margin-top:.8rem">Housekeeping — clearing removed agents and their lines, the default
        supervision mode — comes with the next page.</div></div>`;
}
