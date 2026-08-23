// Small shared helpers: the store hook, formatting, icons.

import { html, useLayoutEffect, useRef, useState } from "../vendor/htm-preact-standalone.module.js";
import { store, subscribe } from "./store.js";

// Re-render the calling component whenever the store changes. Subscribes synchronously
// after the first render (a layout effect), and catches up if the store already moved on
// — a fast snapshot can land before a deferred effect would have been listening.
export function useStore() {
  const [, tick] = useState(0);
  const seen = useRef(store.version);
  seen.current = store.version;
  useLayoutEffect(() => {
    const unsubscribe = subscribe(() => tick((t) => t + 1));
    if (seen.current !== store.version) tick((t) => t + 1);
    return unsubscribe;
  }, []);
}

export function fmtClock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function fmtAgo(iso) {
  if (!iso) return "no activity";
  const seconds = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function minutesSince(iso) {
  return iso ? (Date.now() - new Date(iso)) / 60000 : 0;
}

export function Dot({ status }) {
  return html`<span class="dot ${status ?? ""}" title=${status ?? ""} />`;
}

const PATHS = {
  mark: html`<rect x="3" y="3" width="18" height="18" rx="4" /><rect x="8.5" y="8.5" width="7" height="7" rx="1.5" />`,
  panel: html`<rect x="3" y="3" width="18" height="18" rx="3" /><path d="M9 3v18" />`,
  board: html`<rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" />`,
  agents: html`<circle cx="9" cy="7.5" r="3.5" /><path d="M2.5 20v-1.5a4.5 4.5 0 0 1 4.5-4.5h4a4.5 4.5 0 0 1 4.5 4.5V20" /><path d="M16 4.3a3.5 3.5 0 0 1 0 6.4" /><path d="M21.5 20v-1.5a4.5 4.5 0 0 0-3-4.2" />`,
  admin: html`<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" /><path d="M1.5 14h5M9.5 8h5M17.5 16h5" />`,
  send: html`<path d="M12 19V5M5 12l7-7 7 7" />`,
  sun: html`<circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />`,
  moon: html`<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />`,
};

export function Icon({ name, size = 20, width = 1.8 }) {
  return html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width=${width} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
}

export const COLORS = ["red", "orange", "yellow", "green", "teal", "blue", "purple", "pink"];

// The colour the hub would pick: least used among the current team, palette order on ties.
export function leastUsedColor(agents) {
  const used = new Map();
  for (const a of agents) if (a.color && !a.removed_at && a.type !== "human") used.set(a.color, (used.get(a.color) ?? 0) + 1);
  return [...COLORS].sort((a, b) => (used.get(a) ?? 0) - (used.get(b) ?? 0) || COLORS.indexOf(a) - COLORS.indexOf(b))[0];
}

export function CopyButton({ text }) {
  const [done, setDone] = useState(false);
  return html`<button class="btn" onClick=${() =>
    navigator.clipboard.writeText(text).then(() => {
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    })}>${done ? "copied ✓" : "copy"}</button>`;
}
