// App shell: hash router + store wiring. Views mount once per navigation and return an
// update() the store calls on every change; update.unmount() runs on leaving the view.

import { store, subscribe, connectEvents, refreshSnapshot, unreadInbox } from "./store.js";
import * as board from "./views/board.js";
import * as line from "./views/line.js";
import * as agents from "./views/agents.js";
import * as gate from "./views/gate.js";
import * as inbox from "./views/inbox.js";

const view = document.getElementById("view");
let currentUpdate = null;

function route() {
  currentUpdate?.unmount?.();
  const [, page, arg] = (location.hash || "#/board").split("/");
  document
    .querySelectorAll("[data-nav]")
    .forEach((a) => a.classList.toggle("active", a.dataset.nav === (page || "board")));
  if (page === "line" && arg) currentUpdate = line.mount(view, arg);
  else if (page === "agents") currentUpdate = agents.mount(view);
  else if (page === "gate") currentUpdate = gate.mount(view);
  else if (page === "inbox") currentUpdate = inbox.mount(view);
  else currentUpdate = board.mount(view);
}

function renderBadges() {
  const pending = store.pending.size;
  const unread = unreadInbox();
  const gateBadge = document.getElementById("gate-badge");
  gateBadge.hidden = !pending;
  gateBadge.textContent = pending;
  const inboxBadge = document.getElementById("inbox-badge");
  inboxBadge.hidden = !unread;
  inboxBadge.textContent = unread;
  const total = pending + unread;
  document.title = total ? `(${total}) Agent Courtyard` : "Agent Courtyard";
}

function renderConn() {
  const state = store.sse;
  document.getElementById("conn-dot").className =
    `dot ${state === "live" ? "live" : state === "lost" ? "lost" : ""}`;
  document.getElementById("conn-label").textContent =
    state === "live" ? "live" : state === "lost" ? "reconnecting…" : "connecting…";
}

subscribe(() => {
  renderConn();
  renderBadges();
  currentUpdate?.();
});
window.addEventListener("hashchange", route);

await refreshSnapshot();
connectEvents();
route();
