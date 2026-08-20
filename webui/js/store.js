// Client state: snapshot fetched over REST, kept fresh by the SSE stream.
// On every (re)connect the snapshot is refetched, so missed events never matter.

import { api } from "./api.js";

export const store = {
  agents: new Map(), // id -> agent
  lines: new Map(), // id -> line
  messages: new Map(), // lineId -> Map(messageId -> message)
  pending: new Map(), // messageId -> message held at the gate
  inbox: new Map(), // messageId -> message addressed to the operator
  sse: "connecting", // connecting | live | lost
};

const INBOX_SEEN_KEY = "courtyard-inbox-seen";

export function isHuman(agentId) {
  return store.agents.get(agentId)?.type === "human";
}

export function operatorId() {
  for (const agent of store.agents.values()) {
    if (agent.name === "operator") return agent.id;
  }
  return null;
}

export function unreadInbox() {
  const seen = localStorage.getItem(INBOX_SEEN_KEY) ?? "";
  return [...store.inbox.values()].filter((m) => m.created_at > seen).length;
}

export function markInboxSeen() {
  const newest = [...store.inbox.values()].map((m) => m.created_at).sort().at(-1);
  if (newest) localStorage.setItem(INBOX_SEEN_KEY, newest);
}

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn();
}

export function agentName(id) {
  return store.agents.get(id)?.name ?? "?";
}

export async function refreshSnapshot() {
  const [agents, lines, pending, inbox] = await Promise.all([
    api.agents(),
    api.lines(),
    api.pending(),
    api.operatorInbox(),
  ]);
  store.agents = new Map(agents.map((a) => [a.id, a]));
  store.lines = new Map(lines.map((l) => [l.id, l]));
  store.pending = new Map(pending.map((m) => [m.id, m]));
  store.inbox = new Map(inbox.map((m) => [m.id, m]));
  await Promise.all([...store.messages.keys()].map(loadMessages));
  notify();
}

export async function loadMessages(lineId) {
  const messages = await api.lineMessages(lineId);
  store.messages.set(lineId, new Map(messages.map((m) => [m.id, m])));
  notify();
}

export function dropMessages(lineId) {
  store.messages.delete(lineId);
}

function onEvent(kind, data) {
  if (kind === "agent") store.agents.set(data.id, data);
  else if (kind === "line") store.lines.set(data.id, data);
  else if (kind === "message" || kind === "gate") {
    const perLine = store.messages.get(data.line_id);
    if (perLine) perLine.set(data.id, data);
    if (data.status === "pending_gate") store.pending.set(data.id, data);
    else store.pending.delete(data.id);
    if (data.recipient && data.recipient === operatorId()) store.inbox.set(data.id, data);
  }
  notify();
}

export function connectEvents() {
  const es = new EventSource("/api/events");
  for (const kind of ["agent", "line", "message", "gate"]) {
    es.addEventListener(kind, (e) => onEvent(kind, JSON.parse(e.data)));
  }
  es.onopen = () => {
    store.sse = "live";
    refreshSnapshot(); // catch up on anything missed while disconnected
  };
  es.onerror = () => {
    store.sse = "lost"; // EventSource retries by itself
    notify();
  };
}
