// The one input box at the bottom of the Courtyard page — for DIRECT chats only: what
// you type goes to the selected agent, on your line with it. A line between two agents
// has no bottom box (item 24): the only thing the operator writes on a line is the
// verdict's comment, and that box lives inline with the held message (conversation.js).

import { html, useRef, useState } from "../vendor/htm-preact-standalone.module.js";
import { api } from "./api.js";
import { store, setDraft, selectedAgent, selectedLine, teamAgents, isHuman } from "./store.js";
import { useStore, Icon } from "./ui.js";

const off = (chip, placeholder) => ({ chip: { text: chip }, placeholder, disabled: true, hint: "" });

function plan() {
  if (store.ui.page === "archive") return off("archive", "Archived conversations are read-only");
  if (!teamAgents().length) return off("nobody yet", "Add an agent first…");
  const sel = store.ui.selected;
  if (!sel) return off("pick an agent", "Click an agent to start…");
  if (sel.kind !== "agent") return null; // a line: no box — the verdict comment is inline

  const agent = selectedAgent();
  if (!agent) return off("removed", "That agent was removed; pick another");
  const line = selectedLine();
  const theirTurn = line?.state === "awaiting_reply" && !isHuman(line.awaiting_from);
  return {
    chip: { dot: agent.status, text: agent.name, color: agent.color },
    placeholder: theirTurn
      ? `waiting for ${agent.name} to reply; one message at a time on a line`
      : `Message ${agent.name}…`,
    disabled: theirTurn,
    hint: "Enter to send · Shift+Enter for a new line",
    send: (body) => api.operatorSend(agent.name, body),
  };
}

export function Composer() {
  useStore();
  const [error, setError] = useState(null);
  const ref = useRef();
  const p = plan();
  if (!p) return null;

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
  const chip = html`<span class="to" data-color=${p.chip.color}>${p.chip.dot !== undefined ? html`<span class="dot ${p.chip.dot}" />` : null}${p.chip.text}</span>`;

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
