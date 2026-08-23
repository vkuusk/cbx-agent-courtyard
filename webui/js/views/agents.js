// Agents page: the registry — list with liveness, add (shows the launch config with the
// once-only token and the install button), remove. Clicking a row selects that agent for
// the input box at the bottom.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api, ApiError } from "../api.js";
import { store, select } from "../store.js";
import { useStore, fmtAgo, CopyButton, COLORS, leastUsedColor } from "../ui.js";

const CLAUDE_LAUNCH = "claude --dangerously-load-development-channels server:courtyard";

function puppetCommand(agent, token, behavior) {
  return [
    "uv run courtyard-puppet \\",
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
    <button class="btn" disabled=${!workdir || state.busy || state.result} onClick=${run}>
      ${workdir ? `write .mcp.json into ${workdir}` : "write .mcp.json (set a workdir first)"}</button>
    ${state.busy ? html`<div class="small muted">writing…</div>` : null}
    ${state.result
      ? html`<div class="small" style="margin-top:.4rem"><div>Wrote ${state.result.path}</div>
          ${state.result.backed_up ? html`<div class="muted">backed up to ${state.result.backed_up}</div>` : null}
          <div class="warn" style="margin-top:.3rem">${state.result.warning}</div></div>`
      : null}
    ${state.error ? html`<div class="error" style="margin-top:.4rem">${state.error}</div>` : null}
  </div>`;
}

function PuppetPanel({ agent, token }) {
  const [behavior, setBehavior] = useState("manual");
  const cmd = puppetCommand(agent, token, behavior);
  return html`<div>
    <div class="form-row"><span class="small muted">behavior:</span>
      <select value=${behavior} onChange=${(e) => setBehavior(e.target.value)}>
        <option value="manual">manual — you type the replies</option>
        <option value="echo">echo — acknowledges everything</option>
      </select></div>
    <pre class="cmd">${cmd}</pre><${CopyButton} text=${cmd} />
  </div>`;
}

function ClaudePanel({ agent, token, adapterCommand }) {
  const config = claudeConfig(agent, token, adapterCommand);
  return html`<div>
    <div class="small muted">1. Save as .mcp.json in ${agent.name}'s project directory:</div>
    <pre class="cmd">${config}</pre><${CopyButton} text=${config} />
    <div class="small muted" style="margin-top:.8rem">2. Start the agent from that directory (the flag is needed while channels are in research preview):</div>
    <pre class="cmd">${CLAUDE_LAUNCH}</pre><${CopyButton} text=${CLAUDE_LAUNCH} />
    <div class="small muted" style="margin-top:.8rem">…or let the hub write it for you (dev mode — the hub must share this machine's disk):</div>
    <${InstallButton} agent=${agent} />
  </div>`;
}

// The launch config for one agent: its .mcp.json block (or puppet command) with the token.
// Opens after registration, and again any time from the list — the hub keeps the token.
function LaunchPanel({ agent, token, note, adapterCommand, onClose }) {
  return html`<div class="panel ok">
    <div class="panel-head"><h3>${agent.name} — launch config</h3>
      <button class="link" onClick=${onClose}>close</button></div>
    ${note ? html`<div class="warn" style="margin-bottom:.6rem">${note}</div>` : null}
    ${agent.type === "claude-code"
      ? html`<${ClaudePanel} agent=${agent} token=${token} adapterCommand=${adapterCommand} />`
      : html`<${PuppetPanel} agent=${agent} token=${token} />`}
    <div class="small muted" style="margin-top:.8rem">The hub keeps this token — open this again any time with
      "launch config" in the list; "rotate token" replaces it.</div>
  </div>`;
}

function NoTokenPanel({ agent, onRotate, onClose }) {
  return html`<div class="panel">
    <div class="panel-head"><h3>${agent.name} — no stored token</h3>
      <button class="link" onClick=${onClose}>close</button></div>
    <div class="small" style="margin-bottom:.6rem">${agent.name} was registered before the hub kept tokens, so its
      launch config cannot be shown. Rotate its token to get one — its running session will then need the new
      .mcp.json and a restart.</div>
    <button class="btn" onClick=${() => onRotate(agent)}>rotate token</button>
  </div>`;
}

function AddForm({ onCreated, suggested }) {
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState(null); // null = take the hub's suggestion
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
        color,
      });
      form.reset();
      setPicked(null);
      onCreated(created);
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "name_taken"
          ? "The name is taken — names are permanent identities (removed agents keep theirs)."
          : err.message,
      );
    }
  };
  return html`<form class="form-row" onSubmit=${submit}>
    <input name="name" placeholder="name (e.g. scout)" required
      pattern="[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}" title="letters, digits, dots, dashes, underscores" />
    <select name="type" title="claude-code: a real agent. puppet: a fake agent for testing.">
      <option value="claude-code">claude-code</option>
      <option value="puppet">puppet</option>
    </select>
    <input name="description" placeholder="what is this agent for? (shown to peers)" />
    <input name="sme_domain" placeholder="what does it own? (e.g. the AWS estate)"
      title="its domain of responsibility — raises its standing there when it messages peers" />
    <input name="workdir" placeholder="project dir (claude-code, optional)"
      title="the agent's project directory — lets the hub write .mcp.json there for you" />
    <div class="swatches" role="radiogroup" aria-label="colour on the board">
      <span class="small muted">colour:</span>
      ${COLORS.map((c) => html`<button type="button" class="swatch ${c === color ? "selected" : ""}" data-color=${c}
        title=${c} aria-label=${c} aria-pressed=${c === color} onClick=${() => setPicked(c)} />`)}
    </div>
    <button class="btn primary">add agent</button>
    ${error ? html`<div class="error" style="flex-basis:100%">${error}</div>` : null}
  </form>`;
}

const HEADERS = ["agent", "type", "description", "owns", "status", "last seen", "actions"];

export function Agents() {
  useStore();
  const [panel, setPanel] = useState(null); // {agent, token, note} | {agent, missing: true}
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
        "can no longer reach the hub until you write the new .mcp.json (or restart the puppet " +
        "with the new command).",
    );
    if (!sure) return;
    try {
      const r = await api.rotateToken(agent.name);
      store.agents.set(r.agent.id, r.agent);
      setPanel({
        agent: r.agent,
        token: r.token,
        note: "Token rotated — the old one no longer works. Write the new .mcp.json and restart the agent.",
      });
    } catch (err) {
      alert(err.message);
    }
  };
  const remove = async (agent) => {
    if (!confirm(`Remove ${agent.name} from the courtyard?\n\nIts token stops working; history is kept.`)) return;
    try {
      await api.removeAgent(agent.name);
      if (panel?.agent.id === agent.id) setPanel(null);
    } catch (err) {
      alert(err.message);
    }
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
                <button class="btn" onClick=${stop(() => open(a))}>launch config</button>
                <button class="btn" onClick=${stop(() => rotate(a))}>rotate token</button>
                <button class="btn danger" onClick=${stop(() => remove(a))}>remove</button></div>`
            : html`<span class="muted small">—</span>`}</td>
        </tr>`;
      })}</tbody>
    </table>
    <div class="small muted" style="margin:.5rem 0 0">Click an agent to talk to it from the box below.</div>
    ${panel?.missing
      ? html`<${NoTokenPanel} agent=${panel.agent} onRotate=${rotate} onClose=${() => setPanel(null)} />`
      : panel
        ? html`<${LaunchPanel} agent=${store.agents.get(panel.agent.id) ?? panel.agent} token=${panel.token}
            note=${panel.note} adapterCommand=${adapterCommand} onClose=${() => setPanel(null)} />`
        : null}
    <div class="panel"><h3>Add an agent</h3>
      <${AddForm} onCreated=${onCreated} suggested=${leastUsedColor([...store.agents.values()])} /></div>`;
}
