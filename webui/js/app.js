// App frame: the collapsible rail and the page. The input box lives on the Courtyard
// page only (his feedback, 2026-08-26 — it does not belong on admin-ish pages).
// Hash router: #/board (default) · #/agents · #/archive · #/admin.

import { html, render, useEffect, useState } from "../vendor/htm-preact-standalone.module.js";
import { store, connectEvents, refreshSnapshot, setUi, setTheme, effectiveTheme, totalUnread } from "./store.js";
import { useStore, Icon } from "./ui.js";
import { Composer } from "./composer.js";
import { Board } from "./views/board.js";
import { Agents } from "./views/agents.js";
import { Admin } from "./views/admin.js";
import { ArchivePage } from "./views/archive.js";

const PAGES = {
  board: { title: "Courtyard", view: Board, icon: "board" },
  agents: { title: "Agents", view: Agents, icon: "agents" },
  archive: { title: "Archive", view: ArchivePage, icon: "archive" },
  admin: { title: "Admin", view: Admin, icon: "admin" },
};

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const onChange = () => setHash(location.hash);
    addEventListener("hashchange", onChange);
    return () => removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

function NavLink({ page, current }) {
  const { title, icon } = PAGES[page];
  return html`<a href=${`#/${page}`} class=${page === current ? "active" : ""} title=${title}>
    <${Icon} name=${icon} /><span class="label">${title}</span></a>`;
}

function ThemeButton() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  return html`<button class="navbtn" title=${`Switch to the ${next} theme`} onClick=${() => setTheme(next)}>
    <${Icon} name=${next === "dark" ? "moon" : "sun"} /><span class="label">${next === "dark" ? "Dark theme" : "Light theme"}</span></button>`;
}

function Rail({ current }) {
  const collapsed = store.ui.collapsed;
  const label = collapsed ? "Expand the side bar" : "Collapse the side bar";
  return html`<aside class="rail">
    <div class="brand">
      <span class="mark"><img src="/icon.svg" alt="" width="22" height="22" /></span>
      <span class="name">Agent Courtyard</span>
      <button class="toggle" title=${label} aria-label=${label} onClick=${() => setUi({ collapsed: !collapsed })}>
        <${Icon} name="panel" /></button>
    </div>
    <${Conn} />
    <nav><${NavLink} page="board" current=${current} /><${NavLink} page="agents" current=${current} />
      <${NavLink} page="archive" current=${current} /></nav>
    <nav class="bottom"><${ThemeButton} /><${NavLink} page="admin" current=${current} /></nav>
  </aside>`;
}

function Conn() {
  const state = store.sse;
  const text = state === "live" ? "live" : state === "lost" ? "reconnecting…" : "connecting…";
  return html`<div class="conn" title=${`hub connection: ${text}`}><span class="dot ${state}" /><span class="label">${text}</span></div>`;
}

function App() {
  useStore();
  const hash = useHash();
  const current = PAGES[hash.split("/")[1]] ? hash.split("/")[1] : "board";
  const { view: View } = PAGES[current];
  const attention = store.pending.size + totalUnread();
  useEffect(() => {
    document.title = attention ? `(${attention}) Agent Courtyard` : "Agent Courtyard";
  }, [attention]);
  useEffect(() => {
    if (store.ui.page !== current) setUi({ page: current });
  }, [current]);
  return html`<div class="app ${store.ui.collapsed ? "collapsed" : ""}">
    <${Rail} current=${current} />
    <div class="main">
      <div class="page ${current}"><${View} /></div>
      ${current === "board" ? html`<${Composer} />` : null}
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
refreshSnapshot().catch((err) => console.error("first snapshot failed; the event stream will retry", err));
connectEvents();
