// The one input box, at the bottom of every page. What you type goes to whatever is
// selected: an agent (a message on your line with it) or a line between two agents (a
// note). While a message is held at the gate, the box IS the verdict's comment — it
// leaves only with approve / return / reject on the held message (feedback 3.1/6c),
// and nothing sends from here on its own.

import { html, useRef, useState } from "../vendor/htm-preact-standalone.module.js";
import { api } from "./api.js";
import { store, setDraft, setUi, selectedAgent, selectedLine, teamAgents, agentName, isHuman } from "./store.js";
import { useStore, Icon } from "./ui.js";

const off = (chip, placeholder) => ({ chip: { text: chip }, placeholder, disabled: true, hint: "" });

function plan() {
  if (store.ui.page === "archive") return off("archive", "Archived conversations are read-only");
  if (!teamAgents().length) return off("nobody yet", "Add an agent first…");
  const sel = store.ui.selected;
  if (!sel) return off("pick an agent", "Click an agent to start…");

  if (sel.kind === "agent") {
    const agent = selectedAgent();
    if (!agent) return off("removed", "That agent was removed — pick another");
    const line = selectedLine();
    const theirTurn = line?.state === "awaiting_reply" && !isHuman(line.awaiting_from);
    return {
      chip: { dot: agent.status, text: agent.name, color: agent.color },
      placeholder: theirTurn
        ? `waiting for ${agent.name} to reply — one message at a time on a line`
        : `Message ${agent.name}…`,
      disabled: theirTurn,
      hint: "Enter to send · Shift+Enter for a new line",
      send: (body) => api.operatorSend(agent.name, body),
    };
  }

  const line = selectedLine();
  if (!line) return off("gone", "That line is gone — pick another");
  const a = agentName(line.agent_a);
  const b = agentName(line.agent_b);

  if (line.pending_count) {
    // A message is held at the gate: the box is the verdict's comment, nothing else.
    // The hub already routes it (board.decide): approve delivers it to the recipient
    // as an appended operator note; return / reject carries it back to the sender.
    return {
      chip: { text: "gate comment", gate: true },
      placeholder: "Comment for your verdict on the held message…",
      disabled: false,
      hint: "Your text goes only with approve / return / reject on the held message above",
      send: null,
    };
  }

  const target = store.ui.noteTarget;
  const targetName = target === "both" ? "both" : agentName(target);
  const cycle = () =>
    setUi({
      noteTarget: target === "both" ? line.agent_a : target === line.agent_a ? line.agent_b : "both",
    });
  return {
    chip: { text: `note → ${targetName}`, onClick: cycle, title: "click to change who gets the note" },
    placeholder: target === "both" ? `Add a note for ${a} and ${b}…` : `Add a note for ${targetName}…`,
    disabled: false,
    hint: "Enter sends a note into their line · Shift+Enter for a new line",
    send: (body) => api.addNote(line.id, target === "both" ? "both" : targetName, body),
  };
}

export function Composer() {
  useStore();
  const [error, setError] = useState(null);
  const ref = useRef();
  const p = plan();

  const submit = async () => {
    const body = store.ui.draft.trim();
    if (!body || p.disabled || !p.send) return;
    try {
      await p.send(body);
      setDraft("");
      setError(null);
      if (ref.current) ref.current.style.height = "auto";
    } catch (err) {
      setError(err.message);
    }
  };
  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };
  const onInput = (e) => {
    setDraft(e.target.value);
    setError(null);
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  };
  const chip = p.chip.onClick
    ? html`<button class="to pick" title=${p.chip.title} onClick=${p.chip.onClick}>${p.chip.text}<span class="caret">▾</span></button>`
    : html`<span class="to${p.chip.gate ? " gate" : ""}" data-color=${p.chip.color}>${p.chip.dot !== undefined ? html`<span class="dot ${p.chip.dot}" />` : null}${p.chip.text}</span>`;

  return html`<div class="composer">
    <div class="box ${p.disabled ? "off" : ""}">
      ${chip}
      <textarea ref=${ref} rows="1" value=${store.ui.draft} placeholder=${p.placeholder}
        disabled=${p.disabled} onInput=${onInput} onKeyDown=${onKeyDown} />
      <button class="send" aria-label="Send" disabled=${p.disabled || !p.send} onClick=${submit}>
        <${Icon} name="send" size=${18} width=${2.2} /></button>
    </div>
    <div class="hint ${error ? "error" : ""}">${error ?? p.hint}</div>
  </div>`;
}
