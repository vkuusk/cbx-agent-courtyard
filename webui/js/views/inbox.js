// Inbox view: everything addressed to the operator, newest first. Opening it marks
// everything seen (the unread badge is a local nudge, not server state).

import { store, markInboxSeen } from "../store.js";
import { el, fmtAgo } from "../ui.js";

function item(message) {
  return el(
    "div",
    { class: "panel inbox-item" },
    el(
      "div",
      { class: "gate-head" },
      el("span", { class: "who" }, message.sender_name ?? "hub"),
      message.kind !== "message" ? el("span", { class: "pill count" }, message.kind) : null,
      el("a", { href: `#/line/${message.line_id}`, class: "small" }, "open line"),
      el("span", { class: "muted small" }, fmtAgo(message.created_at)),
    ),
    el("div", { class: "inbox-body" }, message.body),
  );
}

export function mount(root) {
  const update = () => {
    const messages = [...store.inbox.values()].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    );
    root.replaceChildren(
      el("h2", {}, "Inbox"),
      messages.length
        ? el("div", {}, ...messages.map(item))
        : el(
            "div",
            { class: "empty" },
            "Nothing here yet — replies to your messages land in this inbox.",
          ),
    );
    markInboxSeen();
  };
  update();
  return update;
}
