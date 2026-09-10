// App frame: the collapsible rail and the page. The input box lives on the Courtyard
// page only (his feedback, 2026-08-26 — it does not belong on admin-ish pages).
// Hash router: #/board (default) · #/agents · #/archive · #/memory · #/admin.

import { html, render, useEffect, useState } from "../vendor/htm-preact-standalone.module.js";
import { store, connectEvents, refreshSnapshot, setUi, setTheme, effectiveTheme, totalUnread } from "./store.js";
import { useStore, Icon } from "./ui.js";
import { Composer } from "./composer.js";
import { Board } from "./views/board.js";
import { Agents } from "./views/agents.js";
import { Admin } from "./views/admin.js";
import { ArchivePage } from "./views/archive.js";
import { MemoryPage } from "./views/memory.js";

const PAGES = {
  board: { title: "Courtyard", view: Board, icon: "board" },
  agents: { title: "Agents", view: Agents, icon: "agents" },
  archive: { title: "Archive", view: ArchivePage, icon: "archive" },
  memory: { title: "Memory", view: MemoryPage, icon: "memory" },
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
      <${NavLink} page="archive" current=${current} /><${NavLink} page="memory" current=${current} /></nav>
    <nav class="bottom"><${ThemeButton} /><${NavLink} page="admin" current=${current} /></nav>
  </aside>`;
}

function Conn() {
  const state = store.sse;
  const text = state === "live" ? "live" : state === "lost" ? "reconnecting…" : "connecting…";
  return html`<div class="conn" title=${`hub connection: ${text}`}><span class="dot ${state}" /><span class="label">${text}</span></div>`;
}

// "Keep this in the Dock?" The install itself needs a click inside the browser (Chrome
// installs a site as an app only from a user gesture; Safari has no API at all), so the
// question lives here, where the click can happen. Chrome: the button opens its own
// install dialog. Safari and others: the menu path. Dismissed = remembered per browser;
// running as the installed app = never shown.
const DOCK_KEY = "courtyard-dock-dismissed";
let installPrompt = null; // Chrome's deferred beforeinstallprompt event, if it fired
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  notifyInstallable();
});
const installListeners = new Set();
function notifyInstallable() {
  for (const fn of installListeners) fn();
}

export function DockBanner() {
  const [, bump] = useState(0);
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DOCK_KEY) === "1"; } catch { return false; }
  });
  useEffect(() => {
    const fn = () => bump((n) => n + 1);
    installListeners.add(fn);
    return () => installListeners.delete(fn);
  }, []);
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  if (standalone || dismissed) return null;
  const dismiss = () => {
    try { localStorage.setItem(DOCK_KEY, "1"); } catch { /* private window */ }
    setDismissed(true);
  };
  const install = async () => {
    const e = installPrompt;
    installPrompt = null;
    await e.prompt();
    const { outcome } = await e.userChoice;
    if (outcome === "accepted") dismiss();
  };
  const isSafari = /safari/i.test(navigator.userAgent) && !/chrome|chromium|crios|edg/i.test(navigator.userAgent);
  return html`<div class="dock-banner" role="status">
    <span>Keep the courtyard in your Dock? It opens in its own window and its icon counts what waits for you.</span>
    ${installPrompt
      ? html`<button class="btn primary" onClick=${install}>Add to Dock</button>`
      : isSafari
        ? html`<span class="muted">Safari: <b>File › Add to Dock</b></span>`
        : html`<span class="muted">Chrome: the install icon at the right of the address bar</span>`}
    <button class="btn" onClick=${dismiss}>not now</button>
  </div>`;
}

function App() {
  useStore();
  const hash = useHash();
  const current = PAGES[hash.split("/")[1]] ? hash.split("/")[1] : "board";
  const { view: View } = PAGES[current];
  const attention = store.pending.size + totalUnread();
  useEffect(() => {
    document.title = attention ? `(${attention}) Agent Courtyard` : "Agent Courtyard";
    // Installed as a Dock app (Add to Dock / Install app), the badge is the same count
    // the tab title carries: messages held at the gate plus unread replies to you.
    try {
      if (attention) navigator.setAppBadge?.(attention);
      else navigator.clearAppBadge?.();
    } catch {
      /* not installed, or the browser has no badge API */
    }
  }, [attention]);
  useEffect(() => {
    if (store.ui.page !== current) setUi({ page: current });
  }, [current]);
  return html`<div class="app ${store.ui.collapsed ? "collapsed" : ""}">
    <${Rail} current=${current} />
    <div class="main">
      <${DockBanner} />
      <div class="page ${current}"><${View} /></div>
      ${current === "board" ? html`<${Composer} />` : null}
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
refreshSnapshot().catch((err) => console.error("first snapshot failed; the event stream will retry", err));
connectEvents();
