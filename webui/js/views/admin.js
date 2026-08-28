// Admin: two sections (his feedback, 2026-08-26) — Status first (Hub, Courtyard: the
// facts), Settings below (Team, Terminal application, Defaults, Appearance). Settings
// rows are pulldowns, not button rows. 7c's original "housekeeping" list was absorbed
// elsewhere: removed agents' lines archive themselves (D20).

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store, isInactive, setTheme, effectiveTheme, applySettings } from "../store.js";
import { useStore } from "../ui.js";

const BUILTIN_TERMINALS = ["Terminal", "iTerm2"];

// One settings row: label · pulldown · hint.
function Row({ label, value, options, onChange, hint }) {
  return html`<div class="form-row">
    <span class="small muted" style="min-width:10rem">${label}</span>
    <select value=${value} onChange=${(e) => onChange(e.target.value)}>
      ${options.map(([v, text, disabled]) => html`<option value=${v} disabled=${disabled ?? false}
        selected=${v === value}>${text}</option>`)}
    </select>
    ${hint ? html`<span class="small muted">${hint}</span>` : null}
  </div>`;
}

// Terminal application — its own group (his feedback): pick the app Start shift uses,
// see and edit a custom app's start string, add a new one. Built-ins open AND close
// windows with the shift; a custom application only opens them.
function TerminalSection({ settings, save, error }) {
  const customs = settings.custom_terminals ?? [];
  const selected = customs.find((t) => t.name === settings.terminal_app);
  const [draft, setDraft] = useState(null); // edited start string for the selected custom
  const [adding, setAdding] = useState(false);
  const addApp = (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const name = (data.get("name") || "").trim();
    const command = (data.get("command") || "").trim();
    save({ custom_terminals: [...customs, { name, command }] }).then((ok) => ok && setAdding(false));
  };
  const removeApp = (name) =>
    // removing the app in use falls back to Terminal in the same change
    save({ terminal_app: "Terminal", custom_terminals: customs.filter((t) => t.name !== name) });
  return html`<div class="panel"><h3>Terminal application</h3>
    <${Row} label="Application" value=${settings.terminal_app}
      options=${[...BUILTIN_TERMINALS.map((a) => [a, a]), ...customs.map((t) => [t.name, t.name])]}
      onChange=${(v) => { setDraft(null); save({ terminal_app: v }); }}
      hint="— where Start shift opens the agents' windows" />
    ${selected
      ? html`<div class="form-row">
          <span class="small muted" style="min-width:10rem">Start string</span>
          <input style="flex:1;min-width:16rem" value=${draft ?? selected.command}
            onInput=${(e) => setDraft(e.target.value)} />
          <button class="btn" disabled=${draft == null || draft === selected.command}
            onClick=${() => save({
              custom_terminals: customs.map((t) =>
                t.name === selected.name ? { name: t.name, command: draft } : t),
            }).then((ok) => ok && setDraft(null))}>save</button>
          <button class="btn danger" onClick=${() => removeApp(selected.name)}>remove app</button>
        </div>
        <div class="small muted" style="margin:.2rem 0 0">A custom application only opens windows —
          End shift cannot close what it opened; the built-ins do both.</div>`
      : null}
    ${adding
      ? html`<form class="form-row" onSubmit=${addApp}>
          <input name="name" placeholder="name (e.g. kitty)" required />
          <input name="command" style="flex:1;min-width:16rem" required
            placeholder="start string, e.g. kitty --directory {dir} sh -c {command}" />
          <button class="btn primary">add</button>
          <button type="button" class="btn" onClick=${() => setAdding(false)}>cancel</button>
          <div class="small muted" style="flex-basis:100%">{command} is required — it becomes the agent's
            launch command as one quoted argument (most apps want it behind sh -c); {dir} is the
            agent's directory, optional.</div>
        </form>`
      : html`<div class="form-row"><button class="btn" onClick=${() => setAdding(true)}>+ add an application</button></div>`}
    ${error ? html`<div class="error" style="margin-top:.4rem">${error}</div>` : null}
  </div>`;
}

function SettingsSection() {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.settings().then(setSettings).catch(() => {}); }, []);
  if (!settings) return null;
  const save = (patch) => {
    setError(null);
    return api.patchSettings(patch)
      .then((s) => { setSettings(s); applySettings(s); return true; })
      .catch((err) => { setError(err.message); return false; });
  };
  return html`
    <div class="eyebrow" style="margin-top:1.2rem">Settings</div>
    <div class="panel"><h3>Team</h3>
      <${Row} label="Team mode" value=${settings.team_mode}
        options=${[["on_shift", "On shift"], ["always_on", "Always on (not yet available)", true]]}
        onChange=${(v) => save({ team_mode: v })}
        hint="— agents start with your shift and stop when it ends" />
      <${Row} label="Discovery" value=${settings.discovery ?? "auto"}
        options=${[["auto", "auto"], ["manual", "manual"]]}
        onChange=${(v) => save({ discovery: v })}
        hint="— manual: agents reach only whom you link; lines are created from the Lines panel" />
    </div>
    <${TerminalSection} settings=${settings} save=${save} error=${error} />
    <div class="panel"><h3>Defaults</h3>
      <${Row} label="New lines start" value=${settings.default_line_mode}
        options=${[["supervised", "supervised"], ["auto_pass", "auto-pass"]]}
        onChange=${(v) => save({ default_line_mode: v })}
        hint="— the dial a brand-new line starts on; each line keeps its own switch, and your own lines are never gated" />
    </div>
    <div class="panel"><h3>Appearance</h3>
      <${Row} label="Theme" value=${store.ui.theme}
        options=${[["system", "follow the system"], ["light", "light"], ["dark", "dark"]]}
        onChange=${setTheme}
        hint=${store.ui.theme === "system" ? `— the system is ${effectiveTheme()} right now` : ""} />
    </div>`;
}

export function Admin() {
  useStore();
  const [health, setHealth] = useState(null);
  const [config, setConfig] = useState(null);
  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => setHealth({ status: "unreachable" }));
    api.config().then(setConfig).catch(() => {});
  }, []);
  // Registered team agents only (item 20 follow-up): not the operator record (you are
  // an agent by design, D9, but not "an agent" to yourself), not removed ones.
  const registered = [...store.agents.values()].filter(
    (a) => a.type !== "human" && !a.removed_at,
  ).length;
  const lines = [...store.lines.values()];
  const inactive = lines.filter(isInactive).length;
  return html`
    <div class="eyebrow">Status</div>
    <div class="panel"><h3>Hub</h3>
      <dl class="kv">
        <dt>status</dt><dd>${health ? `${health.status} · db ${health.db ?? "?"}` : "…"}</dd>
        <dt>address</dt><dd>${location.origin}</dd>
        ${config ? Object.entries(config).map(([k, v]) => html`<dt>${k}</dt><dd>${String(v)}</dd>`) : null}
      </dl></div>
    <div class="panel"><h3>Courtyard</h3>
      <dl class="kv">
        <dt>agents</dt><dd>${registered} registered</dd>
        <dt>lines</dt><dd>${lines.length - inactive} active · ${inactive} inactive</dd>
        <dt>held at the gate</dt><dd>${store.pending.size}</dd>
      </dl></div>
    <${SettingsSection} />`;
}
