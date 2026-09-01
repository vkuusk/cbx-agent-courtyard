// Agents page (reworked in WP-D, items 4/8/15): the registry — list with liveness, rows
// with edit + remove only; the Edit Agent view holds the editable fields plus launch
// config and rotate token; removal offers directory cleanup. Clicking a row selects
// that agent for the input box at the bottom.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api, ApiError } from "../api.js";
import { store, select } from "../store.js";
import { useStore, fmtAgo, CopyButton, COLORS, leastUsedColor } from "../ui.js";

// The launch command; the agent's declared model rides along so nobody forgets to set it.
// The channels preview drifted twice in four days (feedback item 11): 2.1.241 stopped
// honouring this flag, 2.1.245 restored it — and made the two-flag workaround fail. This
// single-flag form is verified end-to-end by tests/communications/oper-agent1-oper.py.
const claudeLaunch = (agent) =>
  "claude --dangerously-load-development-channels server:courtyard" +
  (agent.model ? ` --model ${agent.model}` : "");

function dummyCommand(agent, token, behavior) {
  return [
    "uv run courtyard-dummy \\",
    `  --hub ${location.origin} \\`,
    `  --name ${agent.name} \\`,
    `  --token ${token} \\`,
    `  --behavior ${behavior}`,
  ].join("\n");
}

// L0 copy-paste launch for a real Claude Code agent (design §8/D8): the project-level
// MCP config, then the command that starts the session with the channel enabled.
function claudeConfig(agent, token, adapterCommand) {
  const config = {
    mcpServers: {
      courtyard: {
        command: adapterCommand,
        env: {
          COURTYARD_HUB_URL: location.origin,
          COURTYARD_AGENT_NAME: agent.name,
          COURTYARD_TOKEN: token,
        },
      },
    },
  };
  return JSON.stringify(config, null, 2);
}

// The agent-side profile (WP-A, D21): pre-approves the courtyard tools (no per-send
// permission prompt in the agent's terminal), sets the declared model, and a status line
// that names the agent so its terminal is recognisable.
function claudeSettings(agent) {
  const settings = {
    permissions: { allow: ["mcp__courtyard"] },
    ...(agent.model ? { model: agent.model } : {}),
    statusLine: { type: "command", command: `echo '⏺ ${agent.name} · courtyard'`, padding: 0 },
  };
  return JSON.stringify(settings, null, 2);
}

// The launch wrapper (item 35, D31) — must match install.py's start_script verbatim,
// marker comment included, so a hand-saved copy is still recognised by uninstall.
function claudeScript(agent) {
  return [
    "#!/bin/sh",
    `# Written by the courtyard for agent '${agent.name}'. Starts this agent's Claude Code`,
    "# session connected to the courtyard hub (the channel flag included).",
    "# Regenerated on every install; extra arguments are passed through to claude.",
    `cd "$(dirname "$0")" && exec ${claudeLaunch(agent)} "$@"`,
    "",
  ].join("\n");
}

// One-click install: ask the hub to write .mcp.json into the agent's workdir (dev mode,
// design §8/D8, 6d). The hub keeps the token (D19), so nothing secret crosses the browser.
function InstallButton({ agent }) {
  const [state, setState] = useState({});
  const workdir = agent.workdir;
  const run = async () => {
    setState({ busy: true });
    try {
      setState({ result: await api.installAgent(agent.name, workdir) });
    } catch (err) {
      setState({ error: err.message });
    }
  };
  return html`<div style="margin-top:.8rem">
    <button class="btn install" data-color=${agent.color}
      disabled=${!workdir || state.busy || state.result} onClick=${run}>
      ${workdir ? `write the files into ${workdir}` : "write the files (set a workdir first)"}</button>
    ${state.busy ? html`<div class="small muted">writing…</div>` : null}
    ${state.result
      ? html`<div class="small" style="margin-top:.4rem"><div>Wrote ${state.result.path}</div>
          ${state.result.backed_up ? html`<div class="muted">backed up to ${state.result.backed_up}</div>` : null}
          ${state.result.settings_path ? html`<div>Wrote ${state.result.settings_path}</div>` : null}
          ${state.result.settings_backed_up ? html`<div class="muted">backed up to ${state.result.settings_backed_up}</div>` : null}
          ${state.result.script_path ? html`<div>Wrote ${state.result.script_path}</div>` : null}
          ${state.result.script_backed_up ? html`<div class="muted">backed up to ${state.result.script_backed_up}</div>` : null}
          <div class="warn" style="margin-top:.3rem">${state.result.warning}</div></div>`
      : null}
    ${state.error ? html`<div class="error" style="margin-top:.4rem">${state.error}</div>` : null}
  </div>`;
}

function DummyPanel({ agent, token }) {
  const [behavior, setBehavior] = useState("manual");
  const cmd = dummyCommand(agent, token, behavior);
  return html`<div>
    <div class="form-row"><span class="small muted">behavior:</span>
      <select value=${behavior} onChange=${(e) => setBehavior(e.target.value)}>
        <option value="manual">manual: you type the replies</option>
        <option value="echo">echo: acknowledges everything</option>
      </select></div>
    <pre class="cmd">${cmd}</pre><${CopyButton} text=${cmd} />
  </div>`;
}

// Item 37: pick the agent's project directory by browsing instead of typing. The hub
// lists its own disk (dev-mode premise, same as install writing files): starts at the
// hub user's home, hidden directories excluded, directories only.
function DirPicker({ onPick }) {
  const [state, setState] = useState(null); // null = closed; {path, parent, dirs} = open
  const load = (path) => api.fsDirs(path).then(setState).catch((err) => alert(err.message));
  return html`<span>
    <button type="button" class="btn" title="browse the hub machine's directories"
      onClick=${() => load()}>browse…</button>
    ${state
      ? html`<div class="overlay" onClick=${(e) => e.target === e.currentTarget && setState(null)}
          onKeyDown=${(e) => e.key === "Escape" && setState(null)}>
          <div class="dialog" role="dialog" aria-modal="true" aria-label="Choose a directory"
            style="min-width:30rem;max-width:80vw">
            <h3 style="word-break:break-all;font-family:var(--mono);font-size:.9rem">${state.path}</h3>
            <div style="max-height:45vh;overflow:auto;display:flex;flex-direction:column;gap:.15rem">
              ${state.parent
                ? html`<button type="button" class="btn" style="text-align:left"
                    onClick=${() => load(state.parent)}>↰ ..</button>`
                : null}
              ${state.dirs.map((d) => html`<button type="button" class="btn" style="text-align:left"
                onClick=${() => load(`${state.path}/${d}`)}>${d}/</button>`)}
              ${!state.dirs.length ? html`<div class="small muted">no subdirectories</div>` : null}
            </div>
            <div class="form-row" style="margin-top:.6rem">
              <button type="button" class="btn primary"
                onClick=${() => { onPick(state.path); setState(null); }}>use this directory</button>
              <button type="button" class="btn" onClick=${() => setState(null)}>cancel</button>
            </div>
          </div>
        </div>`
      : null}
  </span>`;
}

// The pi adapter (item 36, D32) is one extension file, too long to copy-paste: the hub
// writes it (with the agent's token inside), and pi auto-discovers it from .pi/extensions/.
function PiPanel({ agent }) {
  return html`<div>
    <div class="small muted">The whole adapter is one file, <code>.pi/extensions/courtyard.ts</code>, written by
      the hub with this agent's token inside (chmod 600, keep it out of git). pi loads it
      automatically; there is no flag to remember, and starting the
      agent is <code>./start-with-courtyard.sh</code> (or plain <code>pi</code>) in its directory.</div>
    <${InstallButton} agent=${agent} />
    <div class="small muted" style="margin-top:.8rem">If the hub cannot see the directory (live
      mode), run <code>uv run courtyard-invite --register</code> for this agent on the machine that can.</div>
  </div>`;
}

function ClaudePanel({ agent, token, adapterCommand }) {
  const config = claudeConfig(agent, token, adapterCommand);
  const settings = claudeSettings(agent);
  const script = claudeScript(agent);
  return html`<div>
    <div class="small muted">1. Save as .mcp.json in ${agent.name}'s project directory:</div>
    <pre class="cmd">${config}</pre><${CopyButton} text=${config} />
    <div class="small muted" style="margin-top:.8rem">2. Save as .claude/settings.local.json there too; it pre-approves the
      courtyard tools (no permission prompt on every send), sets the model and a status line naming the agent:</div>
    <pre class="cmd">${settings}</pre><${CopyButton} text=${settings} />
    <div class="small muted" style="margin-top:.8rem">3. Save as start-with-courtyard.sh there too and make it
      executable (chmod +x start-with-courtyard.sh). Starting the agent is then ./start-with-courtyard.sh; the
      script carries the channel flag, needed while channels are in research preview (a bare claude session
      cannot hear the hub):</div>
    <pre class="cmd">${script}</pre><${CopyButton} text=${script} />
    <div class="small muted" style="margin-top:.8rem">…or let the hub write all three files for you (dev mode; the hub must share this machine's disk):</div>
    <${InstallButton} agent=${agent} />
  </div>`;
}

// The launch config for one agent: its .mcp.json block (or dummy command) with the token.
// Opens after registration, and again any time from the list — the hub keeps the token.
function LaunchPanel({ agent, token, note, adapterCommand, onClose }) {
  return html`<div class="panel ok">
    <div class="panel-head"><h3>${agent.name} · launch config</h3>
      <button class="link" onClick=${onClose}>close</button></div>
    ${note ? html`<div class="warn" style="margin-bottom:.6rem">${note}</div>` : null}
    ${agent.type === "claude-code"
      ? html`<${ClaudePanel} agent=${agent} token=${token} adapterCommand=${adapterCommand} />`
      : agent.type === "pi"
        ? html`<${PiPanel} agent=${agent} />`
        : html`<${DummyPanel} agent=${agent} token=${token} />`}
    <div class="small muted" style="margin-top:.8rem">The hub keeps this token; open this again any time with
      "launch config" in the list; "rotate token" replaces it.</div>
  </div>`;
}

function NoTokenPanel({ agent, onRotate, onClose }) {
  return html`<div class="panel">
    <div class="panel-head"><h3>${agent.name} · no stored token</h3>
      <button class="link" onClick=${onClose}>close</button></div>
    <div class="small" style="margin-bottom:.6rem">${agent.name} was registered before the hub kept tokens, so its
      launch config cannot be shown. Rotate its token to get one; its running session will then need the new
      .mcp.json and a restart.</div>
    <button class="btn" onClick=${() => onRotate(agent)}>rotate token</button>
  </div>`;
}

function AddForm({ onCreated, suggested }) {
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState(null); // null = take the hub's suggestion
  const [workdir, setWorkdir] = useState(""); // controlled so the picker can fill it
  const color = picked ?? suggested;
  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    const form = e.currentTarget;
    const data = new FormData(form);
    try {
      const created = await api.createAgent({
        name: data.get("name"),
        type: data.get("type"),
        description: data.get("description") || null,
        sme_domain: data.get("sme_domain") || null,
        workdir: data.get("workdir") || null,
        model: data.get("model") || null,
        color,
      });
      form.reset();
      setPicked(null);
      setWorkdir("");
      onCreated(created);
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "name_taken"
          ? "The name is taken: names are permanent identities (removed agents keep theirs)."
          : err.message,
      );
    }
  };
  // Item 4: identity first (name · type · directory · colour), then the two multiline
  // texts the peers actually read — room to write real sentences.
  return html`<form class="add-form" onSubmit=${submit}>
    <div class="form-row">
      <input name="name" placeholder="name (e.g. scout)" required
        pattern="[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}" title="letters, digits, dots, dashes, underscores" />
      <select name="type" title="claude-code and pi: real agents. dummy: a fake agent for testing.">
        <option value="claude-code">claude-code</option>
        <option value="pi">pi</option>
        <option value="dummy">dummy</option>
      </select>
      <input name="workdir" placeholder="project directory (optional)" value=${workdir}
        onInput=${(e) => setWorkdir(e.target.value)}
        title="the agent's project directory; lets the hub write its config there for you" />
      <${DirPicker} onPick=${setWorkdir} />
      <input name="model" placeholder="model (optional, e.g. sonnet)"
        title="the model its runtime should use; written into .claude/settings.local.json by install, and the launch command adds --model" />
      <div class="swatches" role="radiogroup" aria-label="colour on the board">
        <span class="small muted">colour:</span>
        ${COLORS.map((c) => html`<button type="button" class="swatch ${c === color ? "selected" : ""}" data-color=${c}
          title=${c} aria-label=${c} aria-pressed=${c === color} onClick=${() => setPicked(c)} />`)}
      </div>
    </div>
    <textarea name="description" rows="2" placeholder="what is this agent for? (shown to peers)"></textarea>
    <textarea name="sme_domain" rows="2"
      placeholder="what does it own? (e.g. the AWS estate); it raises its standing there when it messages peers"></textarea>
    <div class="form-row">
      <button class="btn primary">add agent</button>
      ${error ? html`<div class="error">${error}</div>` : null}
    </div>
  </form>`;
}

// The Edit Agent view (item 8): everything about one agent in one place — the editable
// fields (name and type are permanent identities), plus launch config and rotate token,
// which moved here from the list rows.
function EditPanel({ agent, onLaunch, onRotate, onClose }) {
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [picked, setPicked] = useState(agent.color);
  const [workdir, setWorkdir] = useState(agent.workdir ?? "");
  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    const data = new FormData(e.currentTarget);
    const text = (k) => (data.get(k) || "").trim() || null;
    try {
      const updated = await api.patchAgent(agent.name, {
        description: text("description"),
        sme_domain: text("sme_domain"),
        workdir: text("workdir"),
        model: text("model"),
        color: picked,
      });
      store.agents.set(updated.id, updated);
      setSaved(true);
    } catch (err) {
      setError(err.message);
    }
  };
  return html`<div class="panel ok">
    <div class="panel-head"><h3><span class="chip" data-color=${picked}>${agent.name}</span> · edit</h3>
      <button class="link" onClick=${onClose}>close</button></div>
    <form class="add-form" onSubmit=${submit}>
      <div class="form-row">
        <span class="small muted">${agent.type} · name and type are permanent</span>
        <input name="workdir" value=${workdir} placeholder="project directory"
          onInput=${(e) => setWorkdir(e.target.value)} />
        <${DirPicker} onPick=${setWorkdir} />
        <input name="model" defaultValue=${agent.model ?? ""} placeholder="model (e.g. sonnet)" />
        <div class="swatches" role="radiogroup" aria-label="colour on the board">
          <span class="small muted">colour:</span>
          ${COLORS.map((c) => html`<button type="button" class="swatch ${c === picked ? "selected" : ""}" data-color=${c}
            title=${c} aria-label=${c} aria-pressed=${c === picked} onClick=${() => setPicked(c)} />`)}
        </div>
      </div>
      <textarea name="description" rows="2" placeholder="what is this agent for? (shown to peers)"
        defaultValue=${agent.description ?? ""}></textarea>
      <textarea name="sme_domain" rows="2" placeholder="what does it own?"
        defaultValue=${agent.sme_domain ?? ""}></textarea>
      <div class="form-row">
        <button class="btn primary">save</button>
        <button type="button" class="btn" onClick=${() => onLaunch(agent)}>launch config</button>
        <button type="button" class="btn" onClick=${() => onRotate(agent)}>rotate token</button>
        ${saved ? html`<span class="small muted">saved; model and status-line changes reach the agent at its next install + restart</span>` : null}
        ${error ? html`<div class="error">${error}</div>` : null}
      </div>
    </form>
  </div>`;
}

// Removal asks about the agent's directory too (item 15): removing from the hub and
// leaving a dead token in the project is the half-done state that bit us after db-nuke.
function RemoveDialog({ agent, onClose }) {
  const [cleanup, setCleanup] = useState(Boolean(agent.workdir));
  const [busy, setBusy] = useState(false);
  const doRemove = async () => {
    setBusy(true);
    if (cleanup && agent.workdir) {
      try {
        await api.uninstallAgent(agent.name);
      } catch (err) {
        if (err.code !== "nothing_to_uninstall") {
          alert(`Directory cleanup failed: ${err.message}\n\nRemoving the agent anyway.`);
        }
      }
    }
    try {
      await api.removeAgent(agent.name);
      onClose(true);
    } catch (err) {
      alert(err.message);
      onClose(false);
    }
  };
  return html`<div class="overlay" onClick=${(e) => e.target === e.currentTarget && onClose(false)}
      onKeyDown=${(e) => e.key === "Escape" && onClose(false)}>
    <div class="dialog" role="alertdialog" aria-modal="true" aria-label="Remove ${agent.name}">
      <h3>Remove ${agent.name} from the courtyard?</h3>
      <p>Its token stops working at once; its conversations move to the Archive. The name
        stays taken; names are permanent identities.</p>
      ${agent.workdir
        ? html`<label class="small" style="display:flex;gap:.5rem;align-items:baseline">
            <input type="checkbox" checked=${cleanup} onChange=${(e) => setCleanup(e.target.checked)} />
            <span>also clean up its project directory: takes the courtyard pieces back out of
              <code>.mcp.json</code> and <code>.claude/settings.local.json</code> in ${agent.workdir}
              (a running session is not stopped; the dead token locks it out)</span></label>`
        : null}
      <div class="form-row" style="justify-content:flex-end">
        <button class="btn" onClick=${() => onClose(false)}>cancel</button>
        <button class="btn danger" disabled=${busy} ref=${(el) => el?.focus()}
          onClick=${doRemove}>${busy ? "removing…" : "remove"}</button>
      </div>
    </div>
  </div>`;
}

const HEADERS = ["agent", "type", "description", "owns", "status", "last seen", "actions"];

export function Agents() {
  useStore();
  // {agent, token, note} = launch config · {agent, missing} = no stored token ·
  // {agent, edit} = the Edit Agent view (item 8)
  const [panel, setPanel] = useState(null);
  const [removing, setRemoving] = useState(null); // agent in the remove dialog (item 15)
  const [adapterCommand, setAdapterCommand] = useState("courtyard-claude-mcp");
  useEffect(() => {
    api.config().then((c) => setAdapterCommand(c.adapter_command)).catch(() => {});
  }, []);

  const agents = [...store.agents.values()]
    .filter((a) => !a.removed_at)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const sel = store.ui.selected;

  const open = async (agent) => {
    try {
      const { token } = await api.agentToken(agent.name);
      setPanel({ agent, token });
    } catch (err) {
      if (err.code === "no_stored_token") setPanel({ agent, missing: true });
      else alert(err.message);
    }
  };
  const rotate = async (agent) => {
    const sure = confirm(
      `Rotate ${agent.name}'s token?\n\nThe old one stops working at once: its running session ` +
        "can no longer reach the hub until you write the new .mcp.json (or restart the dummy " +
        "with the new command).",
    );
    if (!sure) return;
    try {
      const r = await api.rotateToken(agent.name);
      store.agents.set(r.agent.id, r.agent);
      setPanel({
        agent: r.agent,
        token: r.token,
        note: "Token rotated. The old one no longer works. Write the new .mcp.json and restart the agent.",
      });
    } catch (err) {
      alert(err.message);
    }
  };
  const closeRemove = (removed) => {
    if (removed && panel?.agent.id === removing?.id) setPanel(null);
    setRemoving(null);
  };
  const onCreated = (c) => {
    store.agents.set(c.agent.id, c.agent); // the SSE event follows; don't wait for it
    setPanel({ agent: c.agent, token: c.token, note: "Registered." });
    select({ kind: "agent", id: c.agent.id });
  };
  const stop = (fn) => (e) => {
    e.stopPropagation();
    fn();
  };

  return html`
    <table>
      <thead><tr>${HEADERS.map((h) => html`<th>${h}</th>`)}</tr></thead>
      <tbody>${agents.map((a) => {
        const pickable = a.type !== "human";
        const selected = sel?.kind === "agent" && sel.id === a.id;
        return html`<tr key=${a.id} class="${pickable ? "pick" : ""} ${selected ? "selected" : ""}"
            onClick=${pickable ? () => select({ kind: "agent", id: a.id }) : null}>
          <td><span class="dot ${a.status}" /><span class="name chip" data-color=${a.color}>${a.name}</span></td>
          <td class="muted">${a.type}</td>
          <td class="muted">${a.description ?? ""}</td>
          <td class="muted">${a.sme_domain ?? ""}</td>
          <td class="muted small">${a.status}</td>
          <td class="muted small">${fmtAgo(a.last_seen_at)}</td>
          <td>${pickable
            ? html`<div class="actions">
                <button class="btn" onClick=${stop(() => setPanel({ agent: a, edit: true }))}>edit</button>
                <button class="btn danger" onClick=${stop(() => setRemoving(a))}>remove</button></div>`
            : html`<span class="muted small">—</span>`}</td>
        </tr>`;
      })}</tbody>
    </table>
    <div class="small muted" style="margin:.5rem 0 0">Click an agent to select it; the Courtyard page's
      message box follows your selection.</div>
    ${panel?.missing
      ? html`<${NoTokenPanel} agent=${panel.agent} onRotate=${rotate} onClose=${() => setPanel(null)} />`
      : panel?.edit
        ? html`<${EditPanel} key=${panel.agent.id}
            agent=${store.agents.get(panel.agent.id) ?? panel.agent}
            onLaunch=${open} onRotate=${rotate} onClose=${() => setPanel(null)} />`
        : panel
          ? html`<${LaunchPanel} key=${`${panel.agent.id}:${panel.token}`}
              agent=${store.agents.get(panel.agent.id) ?? panel.agent} token=${panel.token}
              note=${panel.note} adapterCommand=${adapterCommand} onClose=${() => setPanel(null)} />`
          : null}
    ${removing ? html`<${RemoveDialog} agent=${removing} onClose=${closeRemove} />` : null}
    <${AddAgentPanel} onCreated=${onCreated} />`;
}

// Collapsed by default (his feedback, 2026-08-26): registering is occasional, the form
// was crowding the page.
function AddAgentPanel({ onCreated }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return html`<button class="btn" style="margin-top:.8rem" onClick=${() => setOpen(true)}>+ Add an agent</button>`;
  }
  return html`<div class="panel">
    <div class="panel-head"><h3>Add an agent</h3>
      <button class="link" onClick=${() => setOpen(false)}>close</button></div>
    <${AddForm} onCreated=${(c) => { setOpen(false); onCreated(c); }}
      suggested=${leastUsedColor([...store.agents.values()])} />
  </div>`;
}
