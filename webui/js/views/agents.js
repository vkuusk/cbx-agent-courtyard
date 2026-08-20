// Agents view: the registry — list with liveness, add (shows the launch command with the
// once-only token), remove. The add form lives outside the data region so live SSE
// re-renders never wipe what the operator is typing.

import { api, ApiError } from "../api.js";
import { store } from "../store.js";
import { el, statusDot, fmtAgo } from "../ui.js";

function launchCommand(agent, token, behavior) {
  return [
    "uv run courtyard-puppet \\",
    `  --hub ${location.origin} \\`,
    `  --name ${agent.name} \\`,
    `  --token ${token} \\`,
    `  --behavior ${behavior}`,
  ].join("\n");
}

function tokenPanel(created) {
  const pre = el("pre", { class: "cmd" }, launchCommand(created.agent, created.token, "manual"));
  const select = el(
    "select",
    {
      onchange: () =>
        (pre.textContent = launchCommand(created.agent, created.token, select.value)),
    },
    el("option", { value: "manual" }, "manual — you type the replies"),
    el("option", { value: "echo" }, "echo — acknowledges everything"),
  );
  return el(
    "div",
    { class: "panel token-panel" },
    el("h3", {}, `${created.agent.name} is registered`),
    el(
      "div",
      { class: "warn" },
      "The token below is shown exactly once — copy the launch command now.",
    ),
    el("div", { class: "form-row" }, el("span", { class: "small muted" }, "behavior:"), select),
    pre,
    el(
      "button",
      { onclick: (e) => navigator.clipboard.writeText(pre.textContent).then(
          () => (e.target.textContent = "copied ✓"),
        ) },
      "copy command",
    ),
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
            type: "puppet",
            description: data.get("description") || null,
          });
          form.reset();
          feedback.replaceChildren(tokenPanel(created));
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
    el("input", { name: "description", placeholder: "what is this agent for? (shown to peers)" }),
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
            ...["agent", "type", "description", "status", "last seen", ""].map((h) =>
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
      el("h3", { class: "small", style: "margin:0 0 0.6rem" }, "Add an agent (puppet)"),
      form,
      feedback,
    ),
  );
  update();
  return update;
}
