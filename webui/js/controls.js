// Operator actions shared across views: gate verdicts, the mode dial, line release.
// All failures surface the hub's message verbatim — the operator should see exactly
// what the hub said, not a softened paraphrase.

import { api } from "./api.js";
import { agentName, isHuman } from "./store.js";
import { el } from "./ui.js";

async function run(action) {
  try {
    await action();
  } catch (err) {
    alert(err.message);
  }
}

// Clear a composer field by its stable identity: live re-renders may have replaced the
// element (preserveInputs carries values across), so a kept reference would be stale.
function clearField(key) {
  document.querySelectorAll(`[data-note-for="${CSS.escape(key)}"]`).forEach((field) => {
    field.value = "";
  });
}

export function gateControls(message) {
  const note = el("input", {
    class: "gate-input",
    placeholder: "optional note (approve: sent as an operator note; return/reject: the reason)",
    "data-note-for": message.id,
  });
  const act = (verdict) => () => run(() => api.decide(message.id, verdict, note.value.trim()));
  return el(
    "div",
    { class: "gate-controls" },
    note,
    el("button", { class: "approve", onclick: act("approve") }, "approve"),
    el("button", { onclick: act("return") }, "return to sender"),
    el("button", { class: "danger", onclick: act("reject") }, "reject"),
  );
}

export function modeControl(line) {
  // Operator lines are never gated (design §5.6): a fixed marker, not a dial.
  if (isHuman(line.agent_a) || isHuman(line.agent_b)) {
    return el(
      "span",
      { class: "pill auto_pass", title: "operator lines are never gated" },
      "no gate",
    );
  }
  return modeToggle(line);
}

export function modeToggle(line) {
  const next = line.mode === "supervised" ? "auto_pass" : "supervised";
  return el(
    "button",
    {
      class: `pill ${line.mode} mode-toggle`,
      title: `switch this line to ${next === "auto_pass" ? "auto-pass" : "supervised"}`,
      onclick: (e) => {
        e.stopPropagation();
        run(() => api.setMode(line.id, next));
      },
    },
    line.mode === "auto_pass" ? "auto" : "supervised",
  );
}

export function messageComposer(line) {
  // Compose box on the operator's own lines. Normal turn rules apply: while the peer
  // owes the reply, say so instead of inviting a doomed send.
  const peerId = isHuman(line.agent_a) ? line.agent_b : line.agent_a;
  const peer = agentName(peerId);
  if (line.state === "awaiting_reply" && !isHuman(line.awaiting_from)) {
    return el(
      "div",
      { class: "composer waiting muted" },
      `waiting for ${peer} to reply — one message at a time on a line`,
    );
  }
  const input = el("textarea", {
    class: "compose-input",
    rows: "2",
    placeholder: `message ${peer}… (Ctrl/Cmd+Enter to send)`,
    "data-note-for": `compose-${line.id}`,
  });
  const submit = () => {
    const body = input.value.trim();
    if (!body) return;
    run(async () => {
      await api.operatorSend(peer, body);
      clearField(`compose-${line.id}`);
    });
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
  });
  return el(
    "div",
    { class: "composer" },
    input,
    el("button", { class: "primary", onclick: submit }, "send"),
  );
}

export function noteComposer(line) {
  // Insert an operator note into an inter-agent line: correct/clarify in transit,
  // no turn effect. Default target: both participants (design §5.6).
  const nameA = line.agent_a_name ?? agentName(line.agent_a);
  const nameB = line.agent_b_name ?? agentName(line.agent_b);
  const target = el(
    "select",
    { "data-note-for": `note-target-${line.id}`, title: "who receives the note" },
    el("option", { value: "both" }, "to both"),
    el("option", { value: nameA }, `to ${nameA}`),
    el("option", { value: nameB }, `to ${nameB}`),
  );
  const input = el("input", {
    class: "compose-input",
    placeholder: "insert an operator note into this conversation…",
    "data-note-for": `note-${line.id}`,
  });
  const submit = () => {
    const body = input.value.trim();
    if (!body) return;
    run(async () => {
      await api.addNote(line.id, target.value, body);
      clearField(`note-${line.id}`);
    });
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
  return el(
    "div",
    { class: "composer" },
    target,
    input,
    el("button", { onclick: submit }, "add note"),
  );
}

export function releaseButton(line) {
  return el(
    "button",
    {
      class: "small",
      title: "give up waiting and reset this line to idle",
      onclick: () => {
        const owes = agentName(line.awaiting_from);
        if (confirm(`Release this line to idle? ${owes} still owes a reply.`)) {
          run(() => api.release(line.id));
        }
      },
    },
    "release",
  );
}
