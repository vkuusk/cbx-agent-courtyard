// Tiny DOM helpers. Strings become text nodes — message bodies are untrusted data and
// must never reach innerHTML.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function statusDot(status) {
  return el("span", { class: `dot ${status}`, title: status });
}

// Snapshot note-input values + focus before a re-render wipes them; returns a restore fn.
export function preserveInputs(root) {
  const saved = new Map();
  let focused = null;
  root.querySelectorAll("input[data-note-for]").forEach((input) => {
    saved.set(input.dataset.noteFor, input.value);
    if (document.activeElement === input) focused = input.dataset.noteFor;
  });
  return (newRoot) => {
    newRoot.querySelectorAll("input[data-note-for]").forEach((input) => {
      const id = input.dataset.noteFor;
      if (saved.has(id)) input.value = saved.get(id);
      if (focused === id) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
    });
  };
}

export function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour12: false });
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
