// Line view: the full history of one line, live. Renders every kind: messages as
// side-aligned bubbles, operator notes as centered amber cards, system entries as quiet
// centered text; returned/rejected greyed out with the gate comment.

import { store, agentName, loadMessages, dropMessages } from "../store.js";
import { el, statusDot, modePill, fmtTime } from "../ui.js";

const FINAL_STATUSES = new Set(["delivered"]);

function statusChip(message) {
  if (message.kind !== "message" || FINAL_STATUSES.has(message.status)) return null;
  const label = message.status === "pending_gate" ? "at the gate" : message.status;
  return el("span", { class: `status-chip ${message.status}` }, label);
}

function bubble(line, message) {
  const side = message.sender === line.agent_b ? "side-b" : "side-a";
  const classes = `msg kind-${message.kind} status-${message.status} ${side}`;
  const who =
    message.kind === "system"
      ? null
      : el("span", { class: "who" }, message.sender_name ?? "hub");
  const target =
    message.kind !== "message" && message.recipient_name
      ? el("span", {}, `→ ${message.recipient_name}`)
      : null;
  const verdictText = { approve: "approved", return: "returned", reject: "rejected" };
  const showVerdict =
    message.gate_verdict && (message.gate_verdict !== "approve" || message.gate_note);
  const gateNote = showVerdict
    ? el(
        "div",
        { class: `gate-note ${message.gate_verdict === "approve" ? "muted" : ""}` },
        `${verdictText[message.gate_verdict]} by the operator${
          message.gate_note ? `: ${message.gate_note}` : ""
        }`,
      )
    : null;
  return el(
    "div",
    { class: classes },
    el(
      "div",
      { class: "head" },
      who,
      target,
      el("span", {}, `#${message.seq}`),
      el("span", {}, fmtTime(message.created_at)),
      statusChip(message),
    ),
    el("div", { class: "body" }, message.body),
    gateNote,
  );
}

export function mount(root, lineId) {
  loadMessages(lineId);
  let firstRender = true;

  const update = () => {
    const line = store.lines.get(lineId);
    if (!line) {
      root.replaceChildren(el("div", { class: "empty" }, "Loading line…"));
      return;
    }
    const messages = [...(store.messages.get(lineId)?.values() ?? [])].sort(
      (a, b) => a.seq - b.seq,
    );
    const nearBottom =
      window.innerHeight + window.scrollY >= document.body.offsetHeight - 120;

    root.replaceChildren(
      el(
        "div",
        { class: "line-head" },
        el("a", { class: "back", href: "#/board", title: "back to the board" }, "←"),
        el(
          "div",
          { class: "line-pair" },
          statusDot(store.agents.get(line.agent_a)?.status ?? "invited"),
          line.agent_a_name ?? agentName(line.agent_a),
          el("span", { class: "vs" }, "↔"),
          statusDot(store.agents.get(line.agent_b)?.status ?? "invited"),
          line.agent_b_name ?? agentName(line.agent_b),
        ),
        modePill(line.mode),
        el(
          "span",
          { class: `line-state ${line.state}` },
          line.state === "awaiting_reply"
            ? `awaiting reply from ${agentName(line.awaiting_from)}`
            : line.state === "pending_gate"
              ? "held at the gate"
              : "idle",
        ),
      ),
      messages.length
        ? el("div", { class: "chat" }, ...messages.map((m) => bubble(line, m)))
        : el("div", { class: "empty" }, "No messages on this line yet."),
    );

    if (firstRender || nearBottom) window.scrollTo(0, document.body.scrollHeight);
    firstRender = false;
  };

  update();
  update.unmount = () => dropMessages(lineId);
  return update;
}
