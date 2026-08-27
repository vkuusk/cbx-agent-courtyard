// Client state: a snapshot fetched over REST, kept fresh by the SSE stream, plus the
// little UI state the whole screen shares (what is selected, what is typed). Components
// re-render from it through useStore() (ui.js). On every (re)connect the snapshot is
// refetched, so missed events never matter.

import { api } from "./api.js";

const RAIL_KEY = "courtyard-rail";
const SEEN_KEY = "courtyard-seen"; // { [lineId]: created_at of the newest entry seen }
const THEME_KEY = "courtyard-theme"; // light | dark; absent = follow the system
const PANELS_KEY = "courtyard-panels"; // { team: px, lines: px } — dragged panel heights

export const store = {
  agents: new Map(), // id -> agent
  lines: new Map(), // id -> line
  messages: new Map(), // lineId -> Map(messageId -> message), only for lines on screen
  pending: new Map(), // messageId -> message held at the gate
  inbox: new Map(), // messageId -> message addressed to the operator
  shift: null, // ShiftStatus from the hub (design §8.1) — the Team panel pill renders it
  sse: "connecting", // connecting | live | lost
  version: 0, // bumped on every change; lets a component catch up if it subscribed late
  archiveVersion: 0, // bumped when an archive is created (the Archive page refetches)
  ui: {
    page: "board", // which page is on screen (the input box adapts)
    selected: null, // {kind: "agent", id} = your line with it · {kind: "line", id} = a line
    draft: "", // what is typed for the CURRENT selection (drafts holds the others)
    drafts: {}, // per-selection drafts — text stays with what it was typed for
    noteTarget: "both", // when a line is selected: both | <participant id>
    shiftQuestionDismissed: false, // D25: "Not now" on the stale-shift question (per page load)
    collapsed: localStorage.getItem(RAIL_KEY) === "collapsed",
    showInactive: false,
    theme: localStorage.getItem(THEME_KEY) || "system", // system | light | dark
    panels: readPanels(),
  },
};

function readPanels() {
  try {
    return JSON.parse(localStorage.getItem(PANELS_KEY) || "{}");
  } catch {
    return {};
  }
}

// A dragged height for the Team or Lines panel (null = back to the default).
export function setPanelMax(panel, px) {
  const panels = { ...store.ui.panels };
  if (px) panels[panel] = Math.round(px);
  else delete panels[panel];
  localStorage.setItem(PANELS_KEY, JSON.stringify(panels));
  setUi({ panels });
}

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  store.version += 1;
  for (const fn of listeners) fn();
}

export function setUi(patch) {
  Object.assign(store.ui, patch);
  if ("collapsed" in patch) localStorage.setItem(RAIL_KEY, patch.collapsed ? "collapsed" : "open");
  notify();
}

const selKey = (s) => (s ? `${s.kind}:${s.id}` : "none");

export function select(selected) {
  // The draft belongs to what it was typed for (feedback 9, 2026-08-24): stash it under
  // the old selection, bring back whatever was typed for the new one, reset the target.
  store.ui.drafts[selKey(store.ui.selected)] = store.ui.draft;
  setUi({ selected, noteTarget: "both", draft: store.ui.drafts[selKey(selected)] ?? "" });
}

export function setDraft(draft) {
  store.ui.drafts[selKey(store.ui.selected)] = draft;
  setUi({ draft });
}

// ---- theme ------------------------------------------------------------------------

const darkSystem = matchMedia("(prefers-color-scheme: dark)");
darkSystem.addEventListener("change", () => notify());

export function setTheme(theme) {
  if (theme === "system") {
    localStorage.removeItem(THEME_KEY);
    delete document.documentElement.dataset.theme;
  } else {
    localStorage.setItem(THEME_KEY, theme);
    document.documentElement.dataset.theme = theme;
  }
  setUi({ theme });
}

// What is on screen right now: the chosen theme, or the system's when following it.
export function effectiveTheme() {
  const t = store.ui.theme;
  return t === "system" ? (darkSystem.matches ? "dark" : "light") : t;
}

// ---- agents & lines ------------------------------------------------------------

export function isHuman(agentId) {
  return store.agents.get(agentId)?.type === "human";
}

export function operatorId() {
  for (const agent of store.agents.values()) {
    if (agent.type === "human") return agent.id;
  }
  return null;
}

export function agentName(id) {
  return store.agents.get(id)?.name ?? "?";
}

const RANK = { connected: 0, stale: 1, invited: 2, gone: 3 };

// The current team: every registered, non-removed agent except you — reachable first.
export function teamAgents() {
  return [...store.agents.values()]
    .filter((a) => !a.removed_at && a.type !== "human")
    .sort((a, b) => RANK[a.status] - RANK[b.status] || a.name.localeCompare(b.name));
}

export function isOperatorLine(line) {
  return isHuman(line.agent_a) || isHuman(line.agent_b);
}

export function peerOf(line) {
  return isHuman(line.agent_a) ? line.agent_b : line.agent_a;
}

export function operatorLineWith(agentId) {
  for (const line of store.lines.values()) {
    if (isOperatorLine(line) && (line.agent_a === agentId || line.agent_b === agentId)) return line;
  }
  return null;
}

// A line is inactive when a participant was removed from the courtyard (not merely
// offline — a closed terminal is still part of the team).
export function isInactive(line) {
  return Boolean(store.agents.get(line.agent_a)?.removed_at || store.agents.get(line.agent_b)?.removed_at);
}

// Resolve the selection to a line: an agent selection means your line with it, which may
// not exist yet (null until the first message).
export function selectedLine() {
  const s = store.ui.selected;
  if (!s) return null;
  if (s.kind === "line") return store.lines.get(s.id) ?? null;
  return operatorLineWith(s.id);
}

export function selectedAgent() {
  const s = store.ui.selected;
  if (s?.kind !== "agent") return null;
  const agent = store.agents.get(s.id);
  return agent && !agent.removed_at ? agent : null;
}

function ensureSelection() {
  const s = store.ui.selected;
  const stillValid =
    s && (s.kind === "line" ? store.lines.has(s.id) : Boolean(selectedAgent()));
  if (stillValid) return;
  const first = teamAgents()[0];
  store.ui.selected = first ? { kind: "agent", id: first.id } : null;
}

// ---- seen / unread ---------------------------------------------------------------

function seenMap() {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || "{}");
  } catch {
    return {};
  }
}

export function lastSeen(lineId) {
  return seenMap()[lineId] ?? "";
}

function newestOn(lineId) {
  const loaded = [...(store.messages.get(lineId)?.values() ?? [])].map((m) => m.created_at);
  const inbox = [...store.inbox.values()].filter((m) => m.line_id === lineId).map((m) => m.created_at);
  return [...loaded, ...inbox, store.lines.get(lineId)?.last_activity_at ?? ""].sort().at(-1) || "";
}

// Called while a line is on screen: everything on it up to now counts as seen.
export function markLineSeen(lineId) {
  const newest = newestOn(lineId);
  if (!newest) return;
  const seen = seenMap();
  if ((seen[lineId] ?? "") >= newest) return;
  seen[lineId] = newest;
  localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
  notify();
}

// Replies to you on a line that you have not looked at yet.
export function unreadOnLine(lineId) {
  const seen = lastSeen(lineId);
  return [...store.inbox.values()].filter(
    (m) => m.line_id === lineId && m.kind !== "system" && m.created_at > seen,
  ).length;
}

export function unreadWith(agentId) {
  const line = operatorLineWith(agentId);
  return line ? unreadOnLine(line.id) : 0;
}

// Anything happened on this line since you last had it on screen?
export function hasNewActivity(line) {
  return (line.last_activity_at ?? "") > lastSeen(line.id);
}

export function totalUnread() {
  let n = 0;
  for (const line of store.lines.values()) if (isOperatorLine(line)) n += unreadOnLine(line.id);
  return n;
}

// ---- data loading -----------------------------------------------------------------

export async function refreshSnapshot() {
  const [agents, lines, pending, inbox, shift] = await Promise.all([
    api.agents(),
    api.lines(),
    api.pending(),
    api.operatorInbox(),
    api.shift(),
  ]);
  store.agents = new Map(agents.map((a) => [a.id, a]));
  store.lines = new Map(lines.map((l) => [l.id, l]));
  store.pending = new Map(pending.map((m) => [m.id, m]));
  store.inbox = new Map(inbox.map((m) => [m.id, m]));
  store.shift = shift;
  await Promise.all([...store.messages.keys()].map(loadMessages));
  ensureSelection();
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
  else if (kind === "shift") store.shift = data;
  else if (kind === "archive") {
    // A history moved out: lines, counters and open transcripts all change at once —
    // the snapshot is the simplest truth.
    store.archiveVersion += 1;
    refreshSnapshot();
    return;
  }
  else if (kind === "message" || kind === "gate") {
    const perLine = store.messages.get(data.line_id);
    if (perLine) perLine.set(data.id, data);
    if (data.status === "pending_gate") store.pending.set(data.id, data);
    else store.pending.delete(data.id);
    if (data.recipient && data.recipient === operatorId()) store.inbox.set(data.id, data);
  }
  ensureSelection();
  notify();
}

export function connectEvents() {
  const es = new EventSource("/api/events");
  for (const kind of ["agent", "line", "message", "gate", "archive", "shift"]) {
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
