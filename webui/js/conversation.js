// The conversation pane: the history of whatever is selected — your line with an agent,
// or a line between two agents. A message held at the gate shows its three verdict
// buttons right here; the note they carry is whatever is typed in the box below.

import { html, useEffect, useLayoutEffect, useRef, useState } from "../vendor/htm-preact-standalone.module.js";
import { api } from "./api.js";
import {
  store, setDraft, selectedAgent, selectedLine, agentName, operatorId,
  loadMessages, dropMessages, markLineSeen,
} from "./store.js";
import { useStore, fmtClock } from "./ui.js";

function Decide({ message }) {
  const [error, setError] = useState(null);
  const act = (verdict) => async () => {
    try {
      await api.decide(message.id, verdict, store.ui.draft.trim() || null);
      setDraft("");
    } catch (err) {
      setError(err.message);
    }
  };
  const note = store.ui.draft.trim();
  const to = message.recipient_name ?? "the recipient";
  const from = message.sender_name ?? "the sender";
  return html`<div class="gate">
    <button class="btn approve" onClick=${act("approve")}>approve</button>
    <button class="btn" onClick=${act("return")}>return to sender</button>
    <button class="btn danger" onClick=${act("reject")}>reject</button>
    <span class="uses">${note
      ? `— with your comment below: approve → ${to} · return / reject → ${from}`
      : `— type below to add a comment: approve → ${to} · return / reject → ${from}`}</span>
    ${error ? html`<span class="error">${error}</span>` : null}
  </div>`;
}

const VERDICT = { approve: "approved", return: "returned to sender", reject: "rejected" };

export function Bubble({ m, readOnly }) {
  if (m.kind === "system") return html`<div class="msg sys">${m.body}</div>`;
  const mine = m.sender === operatorId();
  const cls = [
    "msg",
    mine ? "you" : "",
    m.kind === "operator_note" ? "note" : "",
    m.status === "pending_gate" ? "pending" : "",
    m.status === "returned" || m.status === "rejected" ? "dropped" : "",
  ].join(" ");
  const target = m.kind === "operator_note" && m.recipient_name ? ` → ${m.recipient_name}` : "";
  const state =
    m.status === "pending_gate"
      ? html`<span class="state held"> · held at the gate</span>`
      : m.status === "queued"
        ? html`<span class="state"> · not yet delivered</span>`
        : null;
  const showVerdict = m.gate_verdict && (m.gate_verdict !== "approve" || m.gate_note);
  return html`<div class=${cls}>
    <div class="who">${mine ? "you" : (m.sender_name ?? "hub")}${target} · ${fmtClock(m.created_at)}${state}</div>
    <div class="body">${m.body}</div>
    ${showVerdict ? html`<div class="verdict">${VERDICT[m.gate_verdict]}${m.gate_note ? `: ${m.gate_note}` : ""}</div>` : null}
    ${m.status === "pending_gate" && !readOnly ? html`<${Decide} message=${m} />` : null}
  </div>`;
}

// Archive the history so far (design §5.7): a confirm that says exactly what goes with it.
function archiveAction(line) {
  return () => {
    let text = "Archive this conversation?\n\nIts history moves to the Archive page and the line starts empty.";
    if (line.state === "pending_gate") text += "\n\nThe line is released: the message held at the gate is archived as it stands.";
    else if (line.state === "awaiting_reply") text += "\n\nThe line is released: the message awaiting a reply is archived as it stands.";
    if (line.queued_count) text += `\n${line.queued_count} undelivered message${line.queued_count === 1 ? " is" : "s are"} archived undelivered.`;
    if (confirm(text)) api.archiveLine(line.id).catch((err) => alert(err.message));
  };
}

function Header({ line }) {
  const agent = selectedAgent();
  // The release valve applies to ANY stuck line, the operator's own included (§5.4
  // rule 6) — an agent that never answers you must not lock your line forever.
  const release = () => {
    if (confirm(`Release this line to idle? ${agentName(line.awaiting_from)} still owes a reply.`)) {
      api.release(line.id).catch((err) => alert(err.message));
    }
  };
  if (agent) {
    return html`<div class="conv-head"><h2 class="mono">${agent.name}</h2>
      <span class="meta">${line ? "your line · never gated" : "no messages yet"}</span>
      ${line
        ? html`<span class="act">
            ${line.state === "awaiting_reply" ? html`<button class="btn" onClick=${release}>release</button>` : null}
            <button class="btn" onClick=${archiveAction(line)}>archive</button></span>`
        : null}</div>`;
  }
  if (!line) return null;
  const supervised = line.mode === "supervised";
  const setMode = (mode) => () => {
    if (mode !== line.mode) api.setMode(line.id, mode).catch((err) => alert(err.message));
  };
  return html`<div class="conv-head">
    <h2 class="mono">${agentName(line.agent_a)} ↔ ${agentName(line.agent_b)}</h2>
    <span class="meta">${supervised ? "you approve each message" : "messages flow, you watch"}</span>
    <span class="act">
      <span class="mode-switch" role="group" aria-label="supervision" title="how much of this line you approve">
        <button class="sup ${supervised ? "on" : ""}" aria-pressed=${supervised} onClick=${setMode("supervised")}>supervised</button>
        <button class="auto ${supervised ? "" : "on"}" aria-pressed=${!supervised} onClick=${setMode("auto_pass")}>auto-pass</button>
      </span>
      ${line.state === "awaiting_reply" ? html`<button class="btn" onClick=${release}>release</button>` : null}
      <button class="btn" onClick=${archiveAction(line)}>archive</button>
    </span></div>`;
}

const empty = (title, text) =>
  html`<div class="empty-conv">${title ? html`<h3>${title}</h3>` : null}<div>${text}</div></div>`;

export function Conversation() {
  useStore();
  const agent = selectedAgent();
  const line = selectedLine();
  const lineId = line?.id ?? null;

  useEffect(() => {
    if (!lineId) return undefined;
    loadMessages(lineId);
    return () => dropMessages(lineId);
  }, [lineId]);

  const msgs = [...(store.messages.get(lineId)?.values() ?? [])].sort((a, b) => a.seq - b.seq);
  const lastId = msgs.at(-1)?.id;
  useEffect(() => {
    if (lineId && msgs.length) markLineSeen(lineId);
  }, [lineId, lastId, msgs.length]);

  // Keep the newest message in view unless you scrolled up to read.
  const ref = useRef();
  const stick = useRef(true);
  const onScroll = (e) => {
    const el = e.target;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };
  useLayoutEffect(() => {
    stick.current = true;
  }, [lineId]);
  useLayoutEffect(() => {
    if (ref.current && stick.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lineId, lastId]);

  let body;
  if (!store.ui.selected) {
    body = empty(
      "Your courtyard is empty",
      "Add an agent, let the hub write its .mcp.json, start it in its own terminal — its dot turns green here.",
    );
  } else if (agent && !line) {
    body = empty(null, `No messages between you and ${agent.name} yet. Write below to start the line.`);
  } else if (!line) {
    body = empty(null, "Nothing selected.");
  } else if (!store.messages.has(lineId)) {
    body = empty(null, "Loading…");
  } else if (!msgs.length) {
    body = empty(null, "No messages on this line yet.");
  } else {
    body = msgs.map((m) => html`<${Bubble} key=${m.id} m=${m} />`);
  }
  return html`<section class="conv"><${Header} line=${line} />
    <div class="history" ref=${ref} onScroll=${onScroll}>${body}</div></section>`;
}
