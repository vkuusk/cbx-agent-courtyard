// The Courtyard page: the team (one rectangle per agent), the lines between agents (two nodes,
// one colour-coded wire each), and the conversation pane for whatever is selected.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import {
  store, select, setPanelMax, teamAgents, isOperatorLine, isInactive, hasNewActivity, unreadWith, agentName,
} from "../store.js";
import { useStore, fmtAgo, minutesSince } from "../ui.js";
import { Conversation } from "../conversation.js";
import { api, ApiError } from "../api.js";

const NO_REPLY_MINUTES = 15;

// What the wire says and which colour it takes; lower rank = needs you more.
export function wireStatus(line) {
  const offline = [line.agent_a, line.agent_b]
    .map((id) => store.agents.get(id))
    .find((a) => a && a.status !== "connected");
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

const FOOT = { invited: "not started yet", stale: "not responding", gone: "offline" };

function AgentCard({ agent }) {
  const sel = store.ui.selected;
  const selected = sel?.kind === "agent" && sel.id === agent.id;
  const unread = unreadWith(agent.id);
  const foot = FOOT[agent.status];
  return html`<button class="agent ${selected ? "selected" : ""}" data-color=${agent.color}
      onClick=${() => select({ kind: "agent", id: agent.id })}>
    <span class="head"><span class="dot ${agent.status}" /><span class="name">${agent.name}</span>
      ${unread ? html`<span class="badge">${unread} new</span>` : null}</span>
    <span class="owns">${agent.sme_domain ?? agent.description ?? agent.type}</span>
    ${foot ? html`<span class="foot ${agent.status === "invited" ? "" : "warn"}">${foot}</span>` : null}
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

// The shift pill (design §8.1, D23): one element that is both the Team-mode display and
// the daily control — start the whole team, watch it come up, end the working day.
function ShiftPill() {
  const shift = store.shift;
  const [, bump] = useState(0);
  const graceLeft = shift?.grace_until
    ? Math.max(0, Math.ceil((new Date(shift.grace_until) - Date.now()) / 1000))
    : 0;
  useEffect(() => {
    // While the countdown shows, tick the numbers locally — the hub never streams a clock.
    if (!graceLeft) return undefined;
    const t = setInterval(() => bump((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [Boolean(graceLeft)]);
  if (!shift) return null;
  if (shift.mode === "always_on") return html`<span class="shift-pill tag">always on</span>`;

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
        if (confirm(`${e.message} — end the shift anyway?`)) await api.shiftEnd(true);
      }
    }
  };

  if (shift.state === "off") {
    return html`<button class="shift-pill start" onClick=${() => api.shiftStart()}>▶ Start shift</button>`;
  }
  if (shift.state === "starting") {
    const label = graceLeft ? `Waiting for the team · ${graceLeft}` : `Starting · ${up}/${targets.length}`;
    return html`<span class="shift-pill busy"
      title="checking who is already up before opening terminals">${label}</span>`;
  }
  // Running: the status and the stop control are separate — a square stop button beside
  // the pill, mirroring `▶ Start shift` (his feedback, 2026-08-26: a bare clickable
  // status was not discoverable as the way to stop).
  return html`<span class="shift-group">
    <span class="shift-pill on"><span class="dot connected" /> ${up}/${targets.length} on shift</span>
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

export function Board() {
  useStore();
  const team = teamAgents();
  // Lines of removed agents are archived (design §5.7), so every line here is live.
  const active = [...store.lines.values()]
    .filter((l) => !isOperatorLine(l) && !isInactive(l))
    .map((l) => ({ l, rank: wireStatus(l).rank }))
    .sort((x, y) => x.rank - y.rank || recency(y.l).localeCompare(recency(x.l)))
    .map((x) => x.l);

  return html`
    <div class="board-panel panel-team" style=${panelStyle("team")}>
      <div class="eyebrow-row"><div class="eyebrow">Team</div><${ShiftPill} /></div>
      <div class="team">
        ${team.map((a) => html`<${AgentCard} key=${a.id} agent=${a} />`)}
        <a class="agent add" href="#/agents"><span class="plus">+</span><span>${team.length ? "add" : "add your first agent"}</span></a>
      </div>
    </div>
    <${Resizer} which="team" />
    ${active.length
      ? html`<div class="board-panel panel-lines" style=${panelStyle("lines")}>
          <div class="eyebrow">Lines</div>
          <div class="lines">${active.map((l) => html`<${Wire} key=${l.id} line=${l} />`)}</div>
        </div>
        <${Resizer} which="lines" />`
      : null}
    <${Conversation} />`;
}
