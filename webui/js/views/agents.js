// Agents view: the registry — list with liveness, add (shows the launch command with the
// once-only token), remove. The add form lives outside the data region so live SSE
// re-renders never wipe what the operator is typing.

import { api, ApiError } from "../api.js";
import { store } from "../store.js";
import { el, statusDot, fmtAgo } from "../ui.js";

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

const CLAUDE_LAUNCH = "claude --dangerously-load-development-channels server:courtyard";

function copyButton(getText) {
  return el(
    "button",
    {
      onclick: (e) => {
        const label = e.target;
        navigator.clipboard.writeText(getText()).then(() => {
          label.textContent = "copied ✓";
          setTimeout(() => (label.textContent = "copy"), 1500);
        });
      },
    },
    "copy",
  );
}

function puppetPanel(created) {
  const pre = el("pre", { class: "cmd" }, puppetCommand(created.agent, created.token, "manual"));
  const select = el(
    "select",
    {
      onchange: () => (pre.textContent = puppetCommand(created.agent, created.token, select.value)),
    },
    el("option", { value: "manual" }, "manual — you type the replies"),
    el("option", { value: "echo" }, "echo — acknowledges everything"),
  );
  return el(
    "div",
    {},
    el("div", { class: "form-row" }, el("span", { class: "small muted" }, "behavior:"), select),
    pre,
    copyButton(() => pre.textContent),
  );
}

function claudePanel(created, adapterCommand) {
  const configText = claudeConfig(created.agent, created.token, adapterCommand);
  const config = el("pre", { class: "cmd" }, configText);
  const launch = el("pre", { class: "cmd" }, CLAUDE_LAUNCH);
  return el(
    "div",
    {},
    el(
      "div",
      { class: "small muted" },
      `1. Save as .mcp.json in ${created.agent.name}'s project directory:`,
    ),
    config,
    copyButton(() => configText),
    el(
      "div",
      { class: "small muted", style: "margin-top:0.8rem" },
      "2. Start the agent from that directory (the flag is needed while channels are in " +
        "research preview):",
    ),
    launch,
    copyButton(() => CLAUDE_LAUNCH),
  );
}

function tokenPanel(created, adapterCommand) {
  const body =
    created.agent.type === "claude-code"
      ? claudePanel(created, adapterCommand)
      : puppetPanel(created);
  return el(
    "div",
    { class: "panel token-panel" },
    el("h3", {}, `${created.agent.name} is registered`),
    el(
      "div",
      { class: "warn" },
      "The token below is shown exactly once — copy it now.",
    ),
    body,
  );
}

async function removeAgent(agent) {
  const sure = confirm(
    `Remove ${agent.name} from the courtyard?\n\nIts token stops working; history is kept.`,
  );
  if (!sure) return;
  try {
    await api.removeAgent(agent.name);
  } catch (err) {
    alert(err.message);
  }
}

function agentRow(agent) {
  return el(
    "tr",
    {},
    el("td", {}, statusDot(agent.status), agent.name),
    el("td", { class: "muted" }, agent.type),
    el("td", { class: "muted" }, agent.description ?? ""),
    el("td", { class: "muted" }, agent.sme_domain ?? ""),
    el("td", { class: "muted small" }, agent.status),
    el("td", { class: "muted small" }, fmtAgo(agent.last_seen_at)),
    el(
      "td",
      {},
      agent.name === "operator"
        ? el("span", { class: "muted small" }, "—")
        : el("button", { class: "danger", onclick: () => removeAgent(agent) }, "remove"),
    ),
  );
}

export function mount(root) {
  const list = el("div", {});
  const feedback = el("div", {});
  let errorBanner = null;
  let adapterCommand = "courtyard-claude-mcp";
  api.config().then((c) => (adapterCommand = c.adapter_command));

  const form = el(
    "form",
    {
      class: "form-row",
      onsubmit: async (e) => {
        e.preventDefault();
        errorBanner?.remove();
        const data = new FormData(form);
        try {
          const created = await api.createAgent({
            name: data.get("name"),
            type: data.get("type"),
            description: data.get("description") || null,
            sme_domain: data.get("sme_domain") || null,
          });
          form.reset();
          feedback.replaceChildren(tokenPanel(created, adapterCommand));
        } catch (err) {
          const message =
            err instanceof ApiError && err.code === "name_taken"
              ? `The name is taken — names are permanent identities (removed agents keep theirs).`
              : err.message;
          errorBanner = el("div", { class: "error-banner" }, message);
          feedback.replaceChildren(errorBanner);
        }
      },
    },
    el("input", {
      name: "name",
      placeholder: "name (e.g. scout)",
      required: "",
      pattern: "[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}",
      title: "letters, digits, dots, dashes, underscores",
    }),
    el(
      "select",
      { name: "type", title: "puppet: a fake agent for testing. claude-code: a real agent." },
      el("option", { value: "puppet" }, "puppet"),
      el("option", { value: "claude-code" }, "claude-code"),
    ),
    el("input", { name: "description", placeholder: "what is this agent for? (shown to peers)" }),
    el("input", {
      name: "sme_domain",
      placeholder: "what does it own? (e.g. the AWS estate)",
      title: "its domain of responsibility — raises its standing there when it messages peers",
    }),
    el("button", { class: "primary" }, "add agent"),
  );

  const update = () => {
    const agents = [...store.agents.values()]
      .filter((a) => !a.removed_at)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    list.replaceChildren(
      el(
        "table",
        {},
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            ...["agent", "type", "description", "owns", "status", "last seen", ""].map((h) =>
              el("th", {}, h),
            ),
          ),
        ),
        el("tbody", {}, ...agents.map(agentRow)),
      ),
    );
  };

  root.replaceChildren(
    el("h2", {}, "Agents"),
    list,
    el(
      "div",
      { class: "panel" },
      el("h3", { class: "small", style: "margin:0 0 0.6rem" }, "Add an agent"),
      form,
      feedback,
    ),
  );
  update();
  return update;
}
