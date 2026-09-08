// The conversation pane: the history of whatever is selected — your line with an agent,
// or a line between two agents. A message held at the gate shows its three verdict
// buttons right here; the note they carry is whatever is typed in the box below.

import { html, useEffect, useLayoutEffect, useRef, useState } from "../vendor/htm-preact-standalone.module.js";
import { api } from "./api.js";
import {
  store, selectedAgent, selectedLine, agentName, operatorId,
  loadMessages, dropMessages, markLineSeen, threadsOn,
} from "./store.js";
import { useStore, fmtClock } from "./ui.js";

// The verdict strip on a held message (item 24): the comment box sits INLINE, between
// the message and the buttons — a plain square-cornered field, visually a form, not a
// chat. The bottom composer plays no part on a line any more.
function Decide({ message }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const act = (verdict) => async () => {
    try {
      await api.decide(message.id, verdict, note.trim() || null);
    } catch (err) {
      setError(err.message);
    }
  };
  const to = message.recipient_name ?? "the recipient";
  const from = message.sender_name ?? "the sender";
  return html`<div class="gate">
    <textarea class="gate-note" rows="1" placeholder="Comment for your verdict (optional)…"
      value=${note}
      onInput=${(e) => { setNote(e.target.value); setError(null); e.target.style.height = "auto"; e.target.style.height = `${e.target.scrollHeight}px`; }} />
    <div class="gate-actions">
      <button class="btn approve" onClick=${act("approve")}>approve</button>
      <button class="btn" onClick=${act("return")}>return to sender</button>
      <button class="btn danger" onClick=${act("drop")}>drop</button>
      <span class="uses">approve sends your comment to ${to} · return sends it to ${from} · drop sends it nowhere</span>
    </div>
    ${error ? html`<span class="error">${error}</span>` : null}
  </div>`;
}

const VERDICT = { approve: "approved", return: "returned to sender", drop: "dropped" };

export function Bubble({ m, readOnly }) {
  if (m.kind === "system") return html`<div class="msg sys">${m.body}</div>`;
  const mine = m.sender === operatorId();
  const cls = [
    "msg",
    mine ? "you" : "",
    m.kind === "operator_note" ? "note" : "",
    m.status === "pending_gate" ? "pending" : "",
    m.status === "returned" || m.status === "dropped" || m.status === "expired" ? "dropped" : "",
  ].join(" ");
  const target = m.kind === "operator_note" && m.recipient_name ? ` → ${m.recipient_name}` : "";
  const state =
    m.status === "pending_gate"
      ? html`<span class="state held"> · held at the gate</span>`
      : m.status === "queued"
        ? html`<span class="state"> · not yet delivered</span>`
        : m.status === "expired"
          ? html`<span class="state"> · expired</span>`
          : null;
  const showVerdict = m.gate_verdict && (m.gate_verdict !== "approve" || m.gate_note);
  return html`<div class=${cls}>
    <div class="who">${mine ? "you" : (m.sender_name ?? "hub")}${target} · ${fmtClock(m.created_at)}${state}</div>
    <div class="body">${m.body}</div>
    ${showVerdict ? html`<div class="verdict">${VERDICT[m.gate_verdict]}${m.gate_note ? `: ${m.gate_note}` : ""}</div>` : null}
    ${m.status === "pending_gate" && !readOnly ? html`<${Decide} message=${m} />` : null}
  </div>`;
}

// A thread boundary (D34 §5 item 4): a rule with a chip naming the thread's number,
// its opener and its state. The endings themselves (closed by whom, expired, locked)
// are already system lines in the history; the chip marks where each ask began.
function ThreadDivider({ thread, n }) {
  const opener = thread.opened_by === operatorId() ? "you" : (thread.opened_by_name ?? "?");
  return html`<div class="thread-sep ${thread.state}"><span class="rule" />
    <span class="chip">thread ${n} · ${opener} · ${thread.state}</span><span class="rule" /></div>`;
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
    // The header tells the truth about the turn (D24 — R3), not just "your line".
    const meta = !line
      ? "no messages yet"
      : line.state === "awaiting_reply"
        ? line.awaiting_from === agent.id
          ? `your line · ${agent.name} owes you a reply`
          : "your line · waiting for your reply"
        : "your line · never gated";
    // The close control (D34): the same hub operation the agents' close tool invokes,
    // rendered only when the open thread on this line is one YOU initiated.
    const open = line?.open_thread ? store.threads.get(line.id)?.get(line.open_thread) : null;
    const closable = open && open.opened_by === operatorId();
    const closeThread = () => {
      if (confirm(`Close this thread? ${agent.name} is told your ask is settled; your next message starts a new one.`)) {
        api.closeThread(agent.name).catch((err) => alert(err.message));
      }
    };
    return html`<div class="conv-head"><h2 class="mono">${agent.name}</h2>
      <span class="meta">${meta}</span>
      ${line
        ? html`<span class="act">
            ${closable ? html`<button class="btn" onClick=${closeThread}>close thread</button>` : null}
            ${line.state === "awaiting_reply" ? html`<button class="btn" onClick=${release}>release</button>` : null}
            <button class="btn" onClick=${archiveAction(line)}>archive</button></span>`
        : null}</div>`;
  }
  if (!line) return null;
  const supervised = line.mode === "supervised";
  const setMode = (mode) => () => {
    if (mode !== line.mode) api.setMode(line.id, mode).catch((err) => alert(err.message));
  };
  // Manual discovery (§5.8, D22): the line is the permission — unlinking removes both,
  // history archived first. Plain archive keeps its meaning: history cleared, line stays.
  const unlink = () => {
    const pair = `${agentName(line.agent_a)} ↔ ${agentName(line.agent_b)}`;
    if (confirm(`Unlink ${pair}? The history is archived first, then the line is removed; they can no longer message each other until you link them again.`)) {
      api.unlinkLine(line.id).catch((err) => alert(err.message));
    }
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
      ${store.settings?.discovery === "manual"
        ? html`<button class="btn danger" onClick=${unlink}>unlink</button>`
        : null}
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
      "Add an agent, let the hub write its .mcp.json, start it in its own terminal, and its dot turns green here.",
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
    // Group by thread (D34 §5 item 4): a divider where each ask begins. Messages older
    // than the threads migration carry no thread and stay ungrouped at the top.
    const order = new Map(threadsOn(lineId).map((t, i) => [t.id, { t, n: i + 1 }]));
    const marked = new Set();
    body = [];
    for (const m of msgs) {
      const entry = m.thread_id && !marked.has(m.thread_id) ? order.get(m.thread_id) : null;
      if (entry) {
        marked.add(m.thread_id);
        body.push(html`<${ThreadDivider} key=${`sep-${m.thread_id}`} thread=${entry.t} n=${entry.n} />`);
      }
      body.push(html`<${Bubble} key=${m.id} m=${m} />`);
    }
  }
  return html`<section class="conv"><${Header} line=${line} />
    <div class="history" ref=${ref} onScroll=${onScroll}>${body}</div></section>`;
}
