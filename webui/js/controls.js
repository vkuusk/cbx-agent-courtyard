// Operator actions shared across views: gate verdicts, the mode dial, line release.
// All failures surface the hub's message verbatim — the operator should see exactly
// what the hub said, not a softened paraphrase.

import { api } from "./api.js";
import { agentName } from "./store.js";
import { el } from "./ui.js";

async function run(action) {
  try {
    await action();
  } catch (err) {
    alert(err.message);
  }
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
