// Archive page: archived line histories — read them again, export one as JSON, delete one.
// An archive is immutable; the input box at the bottom says so.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { useStore, fmtWhen } from "../ui.js";
import { Bubble } from "../conversation.js";

const REASON = { agent_removed: "agent removed", operator: "archived by you" };

function span(a) {
  if (!a.first_at) return "";
  const first = new Date(a.first_at).toLocaleDateString();
  const last = new Date(a.last_at).toLocaleDateString();
  return first === last ? first : `${first} – ${last}`;
}

export function ArchivePage() {
  useStore();
  const [list, setList] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    api.archives().then(setList).catch(() => setList([]));
  }, [store.archiveVersion]);

  const show = async (a) => {
    try {
      setOpen(await api.archive(a.id));
    } catch (err) {
      alert(err.message);
    }
  };
  const remove = async (a) => {
    const sure = confirm(
      `Delete this archive (${a.agent_a_name} ↔ ${a.agent_b_name}, ${a.message_count} messages)?\n\nThis cannot be undone — export it first if you want to keep it.`,
    );
    if (!sure) return;
    try {
      await api.deleteArchive(a.id);
      setList(list.filter((x) => x.id !== a.id));
      if (open?.id === a.id) setOpen(null);
    } catch (err) {
      alert(err.message);
    }
  };

  if (list === null) return html`<div class="muted">Loading…</div>`;
  if (!list.length) {
    return html`<div class="empty-conv"><h3>Nothing archived yet</h3>
      <div>Archive a conversation from its header on the Courtyard page, or remove an agent — its lines are
        archived by themselves.</div></div>`;
  }
  return html`
    <div class="board-panel panel-archive">
      <div class="eyebrow">Archived conversations</div>
      <div class="archive-list">${list.map((a) => html`<button key=${a.id} class="arch ${open?.id === a.id ? "selected" : ""}" onClick=${() => show(a)}>
        <span class="mono names">${a.agent_a_name} ↔ ${a.agent_b_name}</span>
        <span class="muted small">${REASON[a.reason]} · ${fmtWhen(a.archived_at)} · ${a.message_count} message${a.message_count === 1 ? "" : "s"}${a.first_at ? ` · ${span(a)}` : ""}</span>
      </button>`)}</div>
    </div>
    ${open
      ? html`<section class="conv archived">
          <div class="conv-head"><h2 class="mono">${open.agent_a_name} ↔ ${open.agent_b_name}</h2>
            <span class="meta">${REASON[open.reason]} · ${fmtWhen(open.archived_at)} · ${open.mode === "supervised" ? "was supervised" : "was auto-pass"}</span>
            <span class="act"><a class="btn" href=${api.archiveExportUrl(open.id)} download>export JSON</a>
              <button class="btn danger" onClick=${() => remove(open)}>delete</button></span></div>
          <div class="history">${open.transcript.length
            ? open.transcript.map((m) => html`<${Bubble} key=${m.id} m=${m} readOnly />`)
            : html`<div class="empty-conv">This line had no messages.</div>`}</div>
        </section>`
      : html`<div class="empty-conv small">Pick a conversation above to read it.</div>`}`;
}
