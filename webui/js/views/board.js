// The Courtyard page: the team (one rectangle per agent), the lines between agents (two nodes,
// one colour-coded wire each), and the conversation pane for whatever is selected.

import { html, useEffect, useRef, useState } from "../../vendor/htm-preact-standalone.module.js";
import {
  store, select, setPanelMax, teamAgents, isOperatorLine, isInactive, hasNewActivity, unreadWith, agentName,
  operatorLineWith,
} from "../store.js";
import { useStore, fmtAgo, minutesSince } from "../ui.js";
import { Conversation } from "../conversation.js";
import { api, ApiError } from "../api.js";

const NO_REPLY_MINUTES = 15;

// What the wire says and which colour it takes; lower rank = needs you more.
export function wireStatus(line) {
  // `unknown` (D26) is not yet a claim either way — never render it as "offline".
  const offline = [line.agent_a, line.agent_b]
    .map((id) => store.agents.get(id))
    .find((a) => a && a.status !== "connected" && a.status !== "unknown");
  if (line.queued_count > 0 && offline) {
    return { cls: "trouble", rank: 0, label: `${offline.name} offline · ${line.queued_count} waiting` };
  }
  const waited = minutesSince(line.last_activity_at);
  if (line.state === "awaiting_reply" && waited > NO_REPLY_MINUTES) {
    return { cls: "trouble", rank: 0, label: `no reply from ${agentName(line.awaiting_from)} for ${Math.floor(waited)}m` };
  }
  if (line.pending_count > 0) {
    return { cls: "held", rank: 1, label: line.pending_count === 1 ? "held at the gate" : `${line.pending_count} held at the gate` };
  }
  if (hasNewActivity(line)) return { cls: "fresh", rank: 2, label: "new since you looked" };
  if (line.state === "awaiting_reply") {
    return { cls: "flowing", rank: 3, label: `waiting for ${agentName(line.awaiting_from)}` };
  }
  return { cls: "idle", rank: 4, label: "idle" };
}

const FOOT = { invited: "not started yet", stale: "not responding", gone: "offline", unknown: "checking…" };

function AgentCard({ agent }) {
  const sel = store.ui.selected;
  const selected = sel?.kind === "agent" && sel.id === agent.id;
  const unread = unreadWith(agent.id);
  const foot = FOOT[agent.status];
  // "Owes you a reply" (design §6.4, D24 — R3): your line with this agent is waiting on it.
  const mine = operatorLineWith(agent.id);
  const owes = mine && mine.state === "awaiting_reply" && mine.awaiting_from === agent.id;
  return html`<button class="agent ${selected ? "selected" : ""}" data-color=${agent.color}
      onClick=${() => select({ kind: "agent", id: agent.id })}>
    <span class="head"><span class="dot ${agent.status}" /><span class="name">${agent.name}</span>
      ${unread ? html`<span class="badge">${unread} new</span>` : null}
      ${owes ? html`<span class="badge owes">owes you a reply</span>` : null}</span>
    <span class="owns">${agent.sme_domain ?? agent.description ?? agent.type}</span>
    ${foot ? html`<span class="foot ${agent.status === "invited" || agent.status === "unknown" ? "" : "warn"}">${foot}</span>` : null}
  </button>`;
}

function Wire({ line }) {
  const sel = store.ui.selected;
  const selected = sel?.kind === "line" && sel.id === line.id;
  const s = wireStatus(line);
  const mode = line.mode === "supervised" ? "supervised" : "auto-pass";
  const node = (id, name) =>
    html`<span class="node" data-color=${store.agents.get(id)?.color}><span class="dot ${store.agents.get(id)?.status ?? ""}" />${name ?? agentName(id)}</span>`;
  return html`<button class="line ${selected ? "selected" : ""}"
      onClick=${() => select({ kind: "line", id: line.id })}>
    ${node(line.agent_a, line.agent_a_name)}
    <span class="wire ${s.cls}"><span class="tag">${s.label}</span>
      <span class="sub">${mode} · ${fmtAgo(line.last_activity_at ?? line.created_at)}</span></span>
    ${node(line.agent_b, line.agent_b_name)}
  </button>`;
}

const recency = (l) => l.last_activity_at ?? l.created_at;

// The stale-shift question (design §8.1, D25): the shift was left open — terminals
// closed by hand, a reboot — and the team is offline. A decision gets a question in
// your face, not a status pill; nothing happens until the operator answers.
function StaleShiftQuestion({ onDismiss }) {
  // Focus the default button so Escape lands inside the dialog: at commit via the ref
  // (synchronous on first mount) and again in the deferred effect (a re-opened dialog's
  // ref-time focus can lose to the click that opened it).
  const first = useRef();
  const focusOnce = (el) => {
    if (el && el !== first.current) {
      first.current = el;
      el.focus();
    }
  };
  useEffect(() => {
    first.current?.focus();
  }, []);
  const act = (fn) => async () => {
    try {
      await fn(); // the SSE shift event updates the board; stale clears, the dialog goes
    } catch (e) {
      alert(e.message);
    }
  };
  return html`<div class="overlay"
      onClick=${(e) => e.target === e.currentTarget && onDismiss()}
      onKeyDown=${(e) => e.key === "Escape" && onDismiss()}>
    <div class="dialog" role="alertdialog" aria-modal="true" aria-label="The last shift was never ended">
      <h3>The last shift was never ended</h3>
      <p>The team is offline, but the shift is still marked as running.</p>
      <div class="choice">
        <button class="btn default" ref=${focusOnce} onClick=${act(() => api.shiftEnd(true))}>■ End shift</button>
        <span class="hint">close it and nothing more — its unfinished messages expire (kept in history);
          start a new shift whenever you are ready</span>
      </div>
      <div class="choice">
        <button class="btn" onClick=${act(() => api.shiftStart())}>▶ Start new shift</button>
        <span class="hint">close the old shift, then start fresh, in one go</span>
      </div>
      <button class="btn later" onClick=${onDismiss}>Not now</button>
    </div>
  </div>`;
}

// The shift pill (design §8.1, D23): one element that is both the Team-mode display and
// the daily control — start the whole team, watch it come up, end the working day.
function ShiftPill() {
  const shift = store.shift;
  const [, bump] = useState(0);
  const left = (iso) => (iso ? Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 1000)) : 0);
  const graceLeft = left(shift?.grace_until);
  const checkLeft = left(shift?.checking_until); // D26: liveness being verified after a restart
  useEffect(() => {
    // While a countdown shows, tick the numbers locally — the hub never streams a clock.
    if (!graceLeft && !checkLeft) return undefined;
    const t = setInterval(() => bump((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [Boolean(graceLeft), Boolean(checkLeft)]);
  if (!shift) return null;
  if (!shift.stale) store.ui.shiftQuestionDismissed = false; // a resolved episode must not mute the next
  if (shift.mode === "always_on") return html`<span class="shift-pill tag">always on</span>`;
  const anyUnknown = teamAgents().some((a) => a.status === "unknown");
  if (checkLeft || (anyUnknown && shift.state === "on")) {
    // No claims yet (D26): neither "n/n on shift" nor the stale question until verified.
    return html`<span class="shift-pill busy"
      title="the hub just restarted — waiting one heartbeat before trusting any status">Checking the team${checkLeft ? ` · ${checkLeft}` : "…"}</span>`;
  }

  const targets = teamAgents().filter((a) => a.type === "claude-code" && a.workdir);
  const up = targets.filter((a) => a.status === "connected").length;
  const endShift = async () => {
    const windows = shift.spawns.length;
    const what = windows ? ` The ${windows} terminal window${windows === 1 ? "" : "s"} it opened will close.` : "";
    if (!confirm(`End the shift?${what}`)) return;
    try {
      await api.shiftEnd(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === "shift_busy") {
        const text = `${e.message} — end the shift anyway?\n\nUnfinished messages are closed as expired (kept in history); the lines start the next shift clear.`;
        if (confirm(text)) await api.shiftEnd(true);
      }
    }
  };

  if (shift.state === "off") {
    return html`<button class="shift-pill start" onClick=${() => api.shiftStart()}>▶ Start shift</button>`;
  }
  if (shift.stale) {
    // D25: the shift was left open and nobody is home — ask, don't guess. "Not now"
    // leaves this amber tag; clicking it brings the question back.
    const dismissed = store.ui.shiftQuestionDismissed;
    const setDismissed = (v) => {
      store.ui.shiftQuestionDismissed = v;
      bump((n) => n + 1);
    };
    return html`<span class="shift-group">
      <button class="shift-pill busy" title="the team is offline but the shift was never ended — click to decide"
        onClick=${() => setDismissed(false)}>shift left open</button>
      ${dismissed ? null : html`<${StaleShiftQuestion} onDismiss=${() => setDismissed(true)} />`}
    </span>`;
  }
  if (shift.state === "starting") {
    const label = graceLeft ? `Waiting for the team · ${graceLeft}` : `Starting · ${up}/${targets.length}`;
    return html`<span class="shift-pill busy"
      title="checking who is already up before opening terminals">${label}</span>`;
  }
  // Running: the status and the stop control are separate — a square stop button beside
  // the pill, mirroring `▶ Start shift` (his feedback, 2026-08-26: a bare clickable
  // status was not discoverable as the way to stop). With part of the team down,
  // ▶ Resume shift starts the missing agents — Resume exists exactly when someone is
  // still reporting (D25 amended by the architect, 2026-08-26); a window that is
  // merely stuck on a first-run dialog is never doubled.
  return html`<span class="shift-group">
    <span class="shift-pill on"><span class="dot connected" /> ${up}/${targets.length} on shift</span>
    ${up < targets.length && targets.length > 0
      ? html`<button class="shift-pill start" title="open terminals for the agents that are down"
          onClick=${() => api.shiftResume().catch((e) => alert(e.message))}>▶ Resume shift</button>`
      : null}
    <button class="shift-pill stop" title="close the terminals this shift opened"
      onClick=${endShift}><span class="square" /> End shift</button>
  </span>`;
}

// The smallest a panel may be dragged to: one row of cards for the team, two lines for
// the lines — measured from the real rows, so card heights and fonts never need guessing.
function minHeight(panel, which) {
  const rows = which === "team" ? [panel.querySelector(".agent")] : [...panel.querySelectorAll(".lines .line")];
  const ref = rows[Math.min(rows.length - 1, which === "team" ? 0 : 1)];
  if (!ref) return 0;
  const bottom = ref.getBoundingClientRect().bottom - panel.getBoundingClientRect().top;
  return Math.ceil(bottom + parseFloat(getComputedStyle(panel).paddingBottom));
}

// A grip under a panel: drag to set its height, double-click to reset. The conversation
// always keeps at least a third of the page.
function Resizer({ which }) {
  const onDown = (e) => {
    const grip = e.currentTarget;
    const panel = grip.previousElementSibling;
    const page = grip.closest(".page");
    const other = page.querySelector(`.board-panel.${which === "team" ? "panel-lines" : "panel-team"}`);
    const startY = e.clientY;
    const startH = panel.getBoundingClientRect().height;
    const lo = minHeight(panel, which);
    const grips = [...page.querySelectorAll(".resizer")].reduce((n, g) => n + g.offsetHeight, 0);
    const pageStyle = getComputedStyle(page);
    const avail = page.clientHeight - parseFloat(pageStyle.paddingTop) - parseFloat(pageStyle.paddingBottom);
    const hi = Math.max(lo, (avail * 2) / 3 - (other?.getBoundingClientRect().height ?? 0) - grips);
    grip.setPointerCapture(e.pointerId);
    const onMove = (ev) => {
      const h = Math.min(hi, Math.max(lo, startH + ev.clientY - startY));
      panel.style.maxHeight = `${h}px`;
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      setPanelMax(which, parseFloat(panel.style.maxHeight));
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
  };
  return html`<div class="resizer" title="drag to resize · double-click to reset"
    onPointerDown=${onDown} onDblClick=${() => setPanelMax(which, null)}><span /></div>`;
}

const panelStyle = (which) => (store.ui.panels[which] ? `max-height:${store.ui.panels[which]}px` : "");

// Manual discovery (§5.8, D22): the operator wires the team here. Collapsed to a small
// square '+' in the bottom-left of the Lines panel (his call, 2026-08-28) — a help
// bubble appears on hover; clicking it expands the two-agent picker in its place.
function LinkAgents() {
  const [open, setOpen] = useState(false);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const team = teamAgents();
  if (team.length < 2) return null;
  const link = () => {
    api.linkAgents(a, b)
      .then((line) => { setOpen(false); setA(""); setB(""); select({ kind: "line", id: line.id }); })
      .catch((err) => alert(err.message));
  };
  if (!open) {
    return html`<div class="link-corner">
      <button class="link-add" aria-label="link two agents" onClick=${() => setOpen(true)}>+</button>
      <span class="link-bubble">link two agents — an idle line opens between them</span>
    </div>`;
  }
  const pick = (value, onChange, exclude) => html`
    <select value=${value} onChange=${(e) => onChange(e.target.value)}>
      <option value="" selected=${value === ""}>choose an agent…</option>
      ${team.filter((t) => t.name !== exclude).map((t) =>
        html`<option value=${t.name} selected=${t.name === value}>${t.name}</option>`)}
    </select>`;
  return html`<div class="form-row link-corner" style="margin:.3rem 0 0">
    ${pick(a, setA, b)}
    <span class="small muted">↔</span>
    ${pick(b, setB, a)}
    <button class="btn primary" disabled=${!a || !b} onClick=${link}>link</button>
    <button class="btn" onClick=${() => setOpen(false)}>cancel</button>
  </div>`;
}

export function Board() {
  useStore();
  const team = teamAgents();
  // D26: while any status is unverified after a hub restart, dim the Team panel — the
  // liveness claims are what's unknown; lines and history below are database truth.
  const checking = team.some((a) => a.status === "unknown");
  const manual = store.settings?.discovery === "manual";
  // Lines of removed agents are archived (design §5.7), so every line here is live.
  const active = [...store.lines.values()]
    .filter((l) => !isOperatorLine(l) && !isInactive(l))
    .map((l) => ({ l, rank: wireStatus(l).rank }))
    .sort((x, y) => x.rank - y.rank || recency(y.l).localeCompare(recency(x.l)))
    .map((x) => x.l);

  return html`
    <div class="board-panel panel-team ${checking ? "checking" : ""}" style=${panelStyle("team")}>
      <div class="eyebrow-row"><div class="eyebrow">Team</div><${ShiftPill} /></div>
      <div class="team">
        ${team.map((a) => html`<${AgentCard} key=${a.id} agent=${a} />`)}
        <a class="agent add" href="#/agents"><span class="plus">+</span><span>${team.length ? "add" : "add your first agent"}</span></a>
      </div>
    </div>
    <${Resizer} which="team" />
    <div class="board-panel panel-lines" style=${panelStyle("lines")}>
      <div class="eyebrow">Lines</div>
      ${active.length
        ? html`<div class="lines">${active.map((l) => html`<${Wire} key=${l.id} line=${l} />`)}</div>`
        : html`<div class="small muted" style="padding:.2rem 0 .4rem">${manual
            ? "No lines yet — link two agents to open a line."
            : "No lines between agents yet — a line appears when two agents first message each other."}</div>`}
      ${manual ? html`<${LinkAgents} />` : null}
    </div>
    <${Resizer} which="lines" />
    <${Conversation} />`;
}
