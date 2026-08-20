// Board view: every line at a glance — who talks to whom, mode, whose turn, counters.

import { store, agentName } from "../store.js";
import { el, statusDot, fmtAgo } from "../ui.js";
import { modeToggle } from "../controls.js";

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
      modeToggle(line),
      el("span", { class: "muted small" }, fmtAgo(line.last_activity_at)),
    ),
  );
}

export function mount(root) {
  const update = () => {
    const lines = [...store.lines.values()].sort((a, b) =>
      (b.last_activity_at ?? b.created_at).localeCompare(a.last_activity_at ?? a.created_at),
    );
    root.replaceChildren(
      el("h2", {}, "Lines"),
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
