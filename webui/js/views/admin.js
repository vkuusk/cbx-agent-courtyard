// Admin: the courtyard itself. For now the facts — hub health, configuration, counts.
// Housekeeping actions (clearing removed agents and their lines, defaults) come next (7c).

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store, isInactive, setTheme, effectiveTheme } from "../store.js";
import { useStore } from "../ui.js";

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
