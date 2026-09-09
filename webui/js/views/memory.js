// Memory page (design hub-memory.md): the team's case files — one per closed thread,
// read-only in slice 1. Search the way an agent's courtyard_recall does (the same
// endpoint family, the same ranking), filter by participant, read one in full.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { useStore, fmtWhen } from "../ui.js";
import { Bubble } from "../conversation.js";

function who(r) {
  return r.participants.map((p) => p.name).join(" ↔ ");
}

function verdictSummary(r) {
  const parts = [];
  if (r.approved) parts.push(`${r.approved} approved`);
  if (r.returned) parts.push(`${r.returned} returned`);
  if (r.dropped) parts.push(`${r.dropped} dropped`);
  return parts.join(", ");
}

export function MemoryPage() {
  useStore();
  const [q, setQ] = useState("");
  const [participant, setParticipant] = useState("");
  const [list, setList] = useState(null);
  const [open, setOpen] = useState(null);
  const agents = [...store.agents.values()].filter((a) => a.type !== "human" && !a.removed_at);

  useEffect(() => {
    api.memory({ q, participant, limit: 20 }).then(setList).catch(() => setList([]));
  }, [q, participant, store.memoryVersion]);

  const show = async (r) => {
    try {
      setOpen(await api.memoryRecord(r.id));
    } catch (err) {
      alert(err.message);
    }
  };

  return html`
    <div class="board-panel panel-memory">
      <div class="eyebrow">The team's memory</div>
      <form class="form-row" style="margin-bottom:.6rem" onSubmit=${(e) => { e.preventDefault(); setQ(new FormData(e.currentTarget).get("q").trim()); }}>
        <input name="q" placeholder="what has the team settled about…" style="flex:1;min-width:16rem" defaultValue=${q} />
        <select value=${participant} onChange=${(e) => setParticipant(e.target.value)}>
          <option value="">any participant</option>
          ${agents.map((a) => html`<option key=${a.id} value=${a.name}>${a.name}</option>`)}
        </select>
        <button class="btn primary">search</button>
        ${q ? html`<button type="button" class="btn" onClick=${() => setQ("")}>clear</button>` : null}
      </form>
      ${list === null
        ? html`<div class="muted">Loading…</div>`
        : !list.length
          ? html`<div class="empty-conv"><h3>${q ? "Nothing matches" : "Nothing remembered yet"}</h3>
              <div>${q
                ? "Try fewer or different words; a participant's name or domain also counts."
                : "A case file is written each time an agent closes a thread: one closed ask, its resolution, and your verdicts on the way."}</div></div>`
          : html`<div class="archive-list">${list.map((r) => html`<button key=${r.id} class="arch ${open?.id === r.id ? "selected" : ""}" onClick=${() => show(r)}>
              <span class="mono names">${who(r)}</span>
              <span class="small">${r.ask || html`<i class="muted">(no ask)</i>`}</span>
              <span class="muted small">closed ${fmtWhen(r.closed_at || r.created_at)} · ${r.message_count} message${r.message_count === 1 ? "" : "s"}${verdictSummary(r) ? ` · ${verdictSummary(r)}` : ""}</span>
            </button>`)}</div>`}
      <div class="small muted" style="margin-top:.5rem">${q ? "Best match first, the way courtyard_recall ranks: the ask and the participants' domains weigh most." : "Newest first."}
        Agents see the same records through courtyard_recall${store.settings?.discovery === "manual" ? ", limited to the lines they are party to" : ""}.</div>
    </div>
    ${open
      ? html`<section class="conv archived">
          <div class="conv-head"><h2 class="mono">${who(open)}</h2>
            <span class="meta">opened by ${open.opened_by_name ?? "?"} · closed ${fmtWhen(open.closed_at || open.created_at)} by ${open.document?.closed_by ?? "?"}${verdictSummary(open) ? ` · ${verdictSummary(open)}` : ""}</span>
            <span class="act"><span class="small muted mono" title="the handle an agent passes to courtyard_recall(case=…)">${open.id}</span></span></div>
          ${open.verdicts?.length
            ? html`<div class="small" style="margin:.4rem 0 .6rem"><b>Verdicts:</b> ${open.verdicts.map((v) => html`<div class="muted">${v}</div>`)}</div>`
            : null}
          <div class="history">${(open.document?.messages ?? []).length
            ? open.document.messages.map((m) => html`<${Bubble} key=${m.id} m=${m} readOnly />`)
            : html`<div class="empty-conv">This thread had no messages.</div>`}</div>
        </section>`
      : list?.length
        ? html`<div class="empty-conv small">Pick a case file above to read it in full.</div>`
        : null}`;
}
