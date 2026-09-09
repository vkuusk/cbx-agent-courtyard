// Admin: two sections (his feedback, 2026-08-26) — Status first (Hub, Courtyard: the
// facts), Settings below (Team, Terminal application, Defaults, Appearance). Settings
// rows are pulldowns, not button rows. 7c's original "housekeeping" list was absorbed
// elsewhere: removed agents' lines archive themselves (D20).

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store, isInactive, setTheme, effectiveTheme, applySettings, applyTeams } from "../store.js";
import { useStore } from "../ui.js";
import { DirPicker } from "./agents.js";

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
      options=${[...store.builtinTerminals.map((a) => [a, a]), ...customs.map((t) => [t.name, t.name])]}
      onChange=${(v) => { setDraft(null); save({ terminal_app: v }); }}
      hint="where Start shift opens the agents' windows" />
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
        <div class="small muted" style="margin:.2rem 0 0">A custom application only opens windows;
          End shift cannot close what it opened; the built-ins do both.</div>`
      : null}
    ${adding
      ? html`<form class="form-row" onSubmit=${addApp}>
          <input name="name" placeholder="name (e.g. kitty)" required />
          <input name="command" style="flex:1;min-width:16rem" required
            placeholder="start string, e.g. kitty --directory {dir} sh -c {command}" />
          <button class="btn primary">add</button>
          <button type="button" class="btn" onClick=${() => setAdding(false)}>cancel</button>
          <div class="small muted" style="flex-basis:100%">{command} is required; it becomes the agent's
            launch command as one quoted argument (most apps want it behind sh -c); {dir} is the
            agent's directory, optional.</div>
        </form>`
      : html`<div class="form-row"><button class="btn" onClick=${() => setAdding(true)}>+ add an application</button></div>`}
    ${error ? html`<div class="error" style="margin-top:.4rem">${error}</div>` : null}
  </div>`;
}

// The team charter registry (design team-charter.md, D33): the files are the source of
// truth; this section shows what the hub last loaded and reloads only on the operator's
// click — the hub never watches the filesystem, so "loaded at" says how stale the view is.
function TeamDetail({ team, refresh }) {
  const agents = team.charter?.agents ?? [];
  const links = team.charter?.links ?? [];
  const setWorkdir = (agent) => (dir) =>
    api.setTeamWorkdir(team.id, agent, dir).then(refresh).catch((e) => alert(e.message));
  return html`<div style="margin:.4rem 0 .6rem;padding-left:.8rem;border-left:2px solid var(--border)">
    <div class="small muted">${team.charter_dir} ·
      loaded ${team.loaded_at ? new Date(team.loaded_at).toLocaleString() : "never"} ·
      the files are the master; edit or pull them, then reload</div>
    ${team.load_report.length
      ? html`<div class="error" style="margin:.4rem 0;white-space:pre-wrap">${team.load_report.join("\n")}</div>`
      : null}
    ${agents.length
      ? html`<table style="margin:.4rem 0">
          <thead><tr><th>agent</th><th>type</th><th>model</th><th>what it is for</th><th>owns</th><th>not for</th><th>directory on this machine</th></tr></thead>
          <tbody>${agents.map((a) => html`<tr key=${a.name}>
            <td style="font-family:var(--mono)">${a.name}</td>
            <td>${a.type ?? "—"}</td><td>${a.model ?? "—"}</td>
            <td>${a.description ?? "—"}</td><td>${a.sme_domain ?? "—"}</td><td>${a.anti_scope ?? "—"}</td>
            <td>${a.workdir ?? html`<span class="muted">not set · </span>`}
              ${a.type !== "dummy"
                ? html`<${DirPicker} prompt=${`Choose the project directory for ${a.name}`}
                    onPick=${setWorkdir(a.name)} />`
                : null}</td>
          </tr>`)}</tbody>
        </table>`
      : team.charter
        ? html`<div class="small muted" style="margin:.4rem 0">No agents in this charter yet.</div>`
        : null}
    ${links.length || team.charter?.discovery
      ? html`<div class="small muted" style="margin:.4rem 0">
          ${team.charter?.discovery ? `discovery: ${team.charter.discovery} (declared) · ` : ""}
          links: ${links.length ? links.map(
            (l) => `${l.a} ↔ ${l.b}${l.mode ? ` (${l.mode.replace("_", "-")})` : ""}`).join(" · ") : "none"}</div>`
      : null}
    <div class="small muted" style="margin:.4rem 0">Project directories are per machine, kept in
      workdirs.local.yml beside the charter — never commit that file.
      ${team.is_current ? "Reloading this team also updates its registrations and lines." : ""}</div>
    <button class="btn" onClick=${() => api.reloadTeam(team.id).then(refresh).catch((e) => alert(e.message))}>
      ⟳ reload from disk</button>
  </div>`;
}

function TeamsSection() {
  const [open, setOpen] = useState(null); // team id whose detail is expanded
  const [pendingDir, setPendingDir] = useState(null); // empty dir waiting for a name
  const [error, setError] = useState(null);
  const teams = store.teams;
  const refreshOne = (team) => applyTeams(teams.map((t) => (t.id === team.id ? team : t)));
  const add = (dir, name) => {
    setError(null);
    api.addTeam(dir, name)
      .then((team) => { applyTeams([...teams, team]); setPendingDir(null); setOpen(team.id); })
      .catch((e) => {
        // no team-definition.yml there: offer to initialize the directory instead of
        // erroring out (item 43 follow-up) — the typed name confirms, then the hub writes
        if (e.code === "charter_name_required") setPendingDir(dir);
        else setError(e.message);
      });
  };
  const remove = (team) => {
    if (!confirm(`Remove ${team.name ?? team.charter_dir} from the hub? The files stay.`)) return;
    api.removeTeam(team.id)
      .then(() => applyTeams(teams.filter((t) => t.id !== team.id)))
      .catch((e) => setError(e.message));
  };
  const nameOf = (t) => t.name ?? t.charter_dir.split("/").pop();
  return html`
    <div class="eyebrow" style="margin-top:1.2rem">Teams</div>
    <div class="panel"><h3>Team charters</h3>
      <div class="small muted" style="margin-bottom:.6rem">A team is a charter directory of files;
        the hub reads it when you add or reload it, never behind your back. One team is always
        current once chosen — agents cannot be registered before it, and the selection moves,
        it never clears.</div>
      ${teams.length
        ? html`<${Row} label="Current team" value=${currentId(teams)}
            options=${[...(currentId(teams) ? [] : [["", "none yet"]]), ...teams.map((t) => [t.id, nameOf(t)])]}
            onChange=${(v) => api.setCurrentTeam(v || null).then(applyTeams).catch((e) => setError(e.message))}
            hint="shown on the Courtyard page" />`
        : null}
      ${teams.map((t) => html`<div key=${t.id}>
        <div class="form-row">
          <button class="link" onClick=${() => setOpen(open === t.id ? null : t.id)}>
            ${open === t.id ? "▾" : "▸"} ${nameOf(t)}</button>
          ${t.is_current ? html`<span class="small muted">current</span>` : null}
          ${t.load_report.length ? html`<span class="error small">${t.load_report.length} problem${t.load_report.length > 1 ? "s" : ""}</span>` : null}
          <span class="small muted">${t.charter?.agents?.length ?? 0} agents</span>
          <button class="btn danger" style="margin-left:auto" disabled=${t.is_current}
            title=${t.is_current ? "the current team cannot be removed; select another first" : ""}
            onClick=${() => remove(t)}>remove</button>
        </div>
        ${open === t.id ? html`<${TeamDetail} team=${t} refresh=${refreshOne} />` : null}
      </div>`)}
      ${pendingDir
        ? html`<form class="form-row" onSubmit=${(e) => { e.preventDefault(); add(pendingDir, new FormData(e.currentTarget).get("name")); }}>
            <span class="small muted" style="flex-basis:100%"><code>${pendingDir}</code> has no
              team-definition.yml yet. Initialize it as a team charter?</span>
            <input name="name" placeholder="team name" required autofocus />
            <button class="btn primary">initialize</button>
            <button type="button" class="btn" onClick=${() => setPendingDir(null)}>cancel</button>
          </form>`
        : html`<div class="form-row"><span class="small muted">add a team:</span>
            <${DirPicker} prompt="Choose the team charter directory" onPick=${(dir) => add(dir)} /></div>`}
      ${error ? html`<div class="error" style="margin-top:.4rem">${error}</div>` : null}
    </div>`;
}

const currentId = (teams) => teams.find((t) => t.is_current)?.id ?? "";

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
        hint="agents start with your shift and stop when it ends" />
      <${Row} label="Discovery" value=${settings.discovery ?? "auto"}
        options=${[["auto", "auto"], ["manual", "manual"]]}
        onChange=${(v) => save({ discovery: v })}
        hint="manual: agents reach only whom you link; lines are created from the Lines panel" />
    </div>
    <${TerminalSection} settings=${settings} save=${save} error=${error} />
    <div class="panel"><h3>Defaults</h3>
      <${Row} label="New lines start" value=${settings.default_line_mode}
        options=${[["supervised", "supervised"], ["auto_pass", "auto-pass"]]}
        onChange=${(v) => save({ default_line_mode: v })}
        hint="the dial a brand-new line starts on; each line keeps its own switch, and your own lines are never gated" />
      <div class="form-row">
        <span class="small muted" style="min-width:10rem">Thread budget</span>
        <input type="number" min="0" style="width:5rem" value=${settings.thread_budget}
          onChange=${(e) => { const n = parseInt(e.target.value, 10); if (n >= 0) save({ thread_budget: n }); }} />
        <span class="small muted">messages per thread before the hub locks it and tells both agents; 0 = no budget; your own threads are never locked</span>
      </div>
    </div>
    <div class="panel"><h3>Appearance</h3>
      <${Row} label="Theme" value=${store.ui.theme}
        options=${[["system", "follow the system"], ["light", "light"], ["dark", "dark"]]}
        onChange=${setTheme}
        hint=${store.ui.theme === "system" ? `the system is ${effectiveTheme()} right now` : ""} />
    </div>`;
}

// Item 29 (the visibility half): the exact texts the hub puts in front of the models,
// one block per case, fetched from the hub so what is shown is what render() produces.
// Read-only; whether the operator may edit the wording is a separate, open discussion.
function EnvelopeSection() {
  const [blocks, setBlocks] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => { api.envelope().then(setBlocks).catch(() => {}); }, []);
  if (!blocks) return null;
  return html`
    <div class="eyebrow" style="margin-top:1.2rem">Message envelope</div>
    <div class="panel"><h3>What the agents receive</h3>
      <div class="small muted" style="margin-bottom:.8rem">The hub wraps every delivery in one of these
        envelopes; the samples below are rendered by the same code that renders real deliveries.
        The wording ships with the hub and is not editable here. The token figure is what the
        envelope adds around the message body, estimated at about four characters per token.</div>
      ${blocks.map((b) => html`
        <div style="margin:.7rem 0">
          <button class="link" onClick=${() => setOpen(open === b.title ? null : b.title)}>
            ${open === b.title ? "▾" : "▸"} ${b.title}</button>
          <span class="small muted" style="margin-left:.5rem">${b.note} · ≈${b.overhead_tokens} tokens</span>
          ${open === b.title ? html`<pre class="cmd" style="margin-top:.35rem">${b.text}</pre>` : null}
        </div>`)}
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
    <${TeamsSection} />
    <${SettingsSection} />
    <${EnvelopeSection} />`;
}
