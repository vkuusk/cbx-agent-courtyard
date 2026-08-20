// Gate view: everything awaiting the operator's judgment, across all lines.

import { store } from "../store.js";
import { el, fmtTime, preserveInputs } from "../ui.js";
import { gateControls } from "../controls.js";

function pendingCard(message) {
  const line = store.lines.get(message.line_id);
  return el(
    "div",
    { class: "panel gate-card" },
    el(
      "div",
      { class: "gate-head" },
      el("span", { class: "who" }, `${message.sender_name} → ${message.recipient_name}`),
      el(
        "a",
        { href: `#/line/${message.line_id}`, class: "small" },
        line ? `${line.agent_a_name} ↔ ${line.agent_b_name}` : "open line",
      ),
      el("span", { class: "muted small" }, `#${message.seq} · ${fmtTime(message.created_at)}`),
    ),
    el("div", { class: "gate-body" }, message.body),
    gateControls(message),
  );
}

export function mount(root) {
  const update = () => {
    const restore = preserveInputs(root);
    const pending = [...store.pending.values()].sort((a, b) =>
      a.created_at.localeCompare(b.created_at),
    );
    root.replaceChildren(
      el("h2", {}, "Gate"),
      pending.length
        ? el("div", {}, ...pending.map(pendingCard))
        : el("div", { class: "empty" }, "The gate is clear — nothing awaits your judgment."),
    );
    restore(root);
  };
  update();
  return update;
}
