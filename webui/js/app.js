// App shell: hash router + store wiring. Views mount once per navigation and return an
// update() the store calls on every change; update.unmount() runs on leaving the view.

import { store, subscribe, connectEvents, refreshSnapshot } from "./store.js";
import * as board from "./views/board.js";
import * as line from "./views/line.js";
import * as agents from "./views/agents.js";
import * as gate from "./views/gate.js";

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
  else currentUpdate = board.mount(view);
}

function renderGateBadge() {
  const count = store.pending.size;
  const badge = document.getElementById("gate-badge");
  badge.hidden = !count;
  badge.textContent = count;
  document.title = count ? `(${count}) Agent Courtyard` : "Agent Courtyard";
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
  renderGateBadge();
  currentUpdate?.();
});
window.addEventListener("hashchange", route);

await refreshSnapshot();
connectEvents();
route();
