// Board view: every line at a glance — who talks to whom, mode, whose turn, counters —
// plus the operator's "start a conversation" entry point.

import { api } from "../api.js";
import { store, agentName } from "../store.js";
import { el, statusDot, fmtAgo } from "../ui.js";
import { modeControl } from "../controls.js";

function stateLabel(line) {
  if (line.state === "pending_gate") return "held at the gate";
  if (line.state === "awaiting_reply")
    return `awaiting reply from ${agentName(line.awaiting_from)}`;
  return "idle";
}

function participant(line, id, name) {
  const agent = store.agents.get(id);
  return el("span", {}, statusDot(agent?.status ?? "invited"), " ", name ?? agentName(id));
}

function lineCard(line) {
  const counters = [];
  if (line.pending_count) {
    counters.push(el("span", { class: "pill count" }, `${line.pending_count} at gate`));
  }
  if (line.queued_count) {
    counters.push(el("span", { class: "pill queued" }, `${line.queued_count} queued`));
  }
  return el(
    "div",
    { class: "line-card", onclick: () => (location.hash = `#/line/${line.id}`) },
    el(
      "div",
      { class: "line-pair" },
      participant(line, line.agent_a, line.agent_a_name),
      el("span", { class: "vs" }, "↔"),
      participant(line, line.agent_b, line.agent_b_name),
    ),
    el("div", { class: `line-state ${line.state}` }, stateLabel(line)),
    el(
      "div",
      { class: "line-meta" },
      ...counters,
      modeControl(line),
      el("span", { class: "muted small" }, fmtAgo(line.last_activity_at)),
    ),
  );
}

function composePanel() {
  const select = el("select", { "data-note-for": "compose-to" });
  const input = el("textarea", {
    class: "compose-input",
    rows: "2",
    placeholder: "your opening message… (Ctrl/Cmd+Enter to send)",
    "data-note-for": "compose-new",
  });
  const panel = el(
    "div",
    { class: "panel", hidden: "" },
    el(
      "div",
      { class: "form-row" },
      el("span", { class: "small muted" }, "to:"),
      select,
    ),
    el("div", { class: "composer" }, input, el(
      "button",
      {
        class: "primary",
        onclick: async () => {
          const body = input.value.trim();
          if (!body) return;
          try {
            const message = await api.operatorSend(select.value, body);
            input.value = "";
            location.hash = `#/line/${message.line_id}`;
          } catch (err) {
            alert(err.message);
          }
        },
      },
      "send",
    )),
  );
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) panel.querySelector("button").click();
  });
  const rank = { connected: 0, stale: 1, invited: 2, gone: 3 };
  const refreshTargets = () => {
    const current = select.value;
    const agents = [...store.agents.values()]
      .filter((a) => !a.removed_at && a.type !== "human")
      .sort(
        (a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name),
      );
    select.replaceChildren(
      ...agents.map((a) => el("option", { value: a.name }, `${a.name} — ${a.status}`)),
    );
    if (agents.some((a) => a.name === current)) select.value = current;
  };
  return { panel, refreshTargets };
}

export function mount(root) {
  const { panel, refreshTargets } = composePanel();
  const list = el("div", {});
  root.replaceChildren(
    el(
      "div",
      { class: "view-head" },
      el("h2", {}, "Lines"),
      el(
        "button",
        { class: "small", onclick: () => (panel.hidden = !panel.hidden) },
        "message an agent…",
      ),
    ),
    panel,
    list,
  );

  const update = () => {
    refreshTargets();
    const lines = [...store.lines.values()].sort((a, b) =>
      (b.last_activity_at ?? b.created_at).localeCompare(a.last_activity_at ?? a.created_at),
    );
    list.replaceChildren(
      lines.length
        ? el("div", {}, ...lines.map(lineCard))
        : el(
            "div",
            { class: "empty" },
            "No lines yet — a line appears when two agents first talk to each other.",
          ),
    );
  };
  update();
  return update;
}
