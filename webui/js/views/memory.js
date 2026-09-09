// Memory page (design hub-memory.md): the team's case files and notes. Search the way an
// agent's courtyard_recall does (the same endpoint family, the same ranking), filter by
// participant, read one record in full. Slice 2: agents' notes wait here for the
// operator's verdict, and the operator writes notes of their own.

import { html, useEffect, useState } from "../../vendor/htm-preact-standalone.module.js";
import { api } from "../api.js";
import { store, agentName } from "../store.js";
import { useStore, fmtWhen } from "../ui.js";
import { Bubble } from "../conversation.js";

function who(r) {
  return r.participants.map((p) => p.name).join(" ↔ ");
}

function scopeOf(r) {
  return r.scope === "team" ? "team-wide" : `for ${who(r)}`;
}

function verdictSummary(r) {
  const parts = [];
  if (r.approved) parts.push(`${r.approved} approved`);
  if (r.returned) parts.push(`${r.returned} returned`);
  if (r.dropped) parts.push(`${r.dropped} dropped`);
  return parts.join(", ");
}

// Agents' notes waiting for the operator: approve, return with a comment, or drop —
// the same three verdicts the gate gives a message.
function PendingNotes({ notes, refresh }) {
  const [comment, setComment] = useState({});
  if (!notes.length) return null;
  const decide = async (n, verdict) => {
    try {
      await api.decideNote(n.id, verdict, (comment[n.id] || "").trim() || null);
      refresh();
    } catch (err) {
      alert(err.message);
    }
  };
  return html`<div class="panel" style="margin-bottom:.8rem">
    <h3>Notes waiting for you (${notes.length})</h3>
    ${notes.map((n) => html`<div key=${n.id} class="pending-note" style="margin:.5rem 0 .8rem">
      <div class="small muted">${n.author_name} · ${scopeOf(n)} · ${fmtWhen(n.created_at)}</div>
      <div style="margin:.2rem 0 .4rem;white-space:pre-wrap">${n.body}</div>
      <div class="form-row">
        <input style="flex:1;min-width:14rem" placeholder="comment (travels back with a return)"
          value=${comment[n.id] || ""} onInput=${(e) => setComment({ ...comment, [n.id]: e.target.value })} />
        <button class="btn primary" onClick=${() => decide(n, "approve")}>approve</button>
        <button class="btn" onClick=${() => decide(n, "return")}>return to sender</button>
        <button class="btn danger" onClick=${() => decide(n, "drop")}>drop</button>
      </div>
    </div>`)}
  </div>`;
}

// The operator's own note: standing team guidance, team-wide unless scoped to a line.
function NoteForm({ onWritten }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState(null);
  const lines = [...store.lines.values()];
  const submit = async (e) => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const line = data.get("line");
    try {
      await api.writeNote({
        body: data.get("body").trim(),
        scope: line ? "line" : "team",
        line: line || null,
      });
      setOpen(false);
      setError(null);
      onWritten();
    } catch (err) {
      setError(err.message);
    }
  };
  if (!open) return html`<button class="btn" onClick=${() => setOpen(true)}>+ write a note</button>`;
  return html`<form class="panel" onSubmit=${submit} style="margin-bottom:.8rem">
    <h3>A note from you</h3>
    <textarea name="body" rows="3" required maxlength="2000" style="width:100%;box-sizing:border-box"
      placeholder="what the team should know (a rule, a decision, a fact); agents find it through courtyard_recall"></textarea>
    <div class="form-row" style="margin-top:.5rem">
      <select name="line">
        <option value="">team-wide (everyone)</option>
        ${lines.map((l) => html`<option key=${l.id} value=${l.id}>${agentName(l.agent_a)} ↔ ${agentName(l.agent_b)} only</option>`)}
      </select>
      <button class="btn primary">save note</button>
      <button type="button" class="btn" onClick=${() => setOpen(false)}>cancel</button>
    </div>
    ${error ? html`<div class="error small" style="margin-top:.4rem">${error}</div>` : null}
  </form>`;
}

export function MemoryPage() {
  useStore();
  const [q, setQ] = useState("");
  const [participant, setParticipant] = useState("");
  const [list, setList] = useState(null);
  const [pending, setPending] = useState([]);
  const [open, setOpen] = useState(null);
  const [tick, setTick] = useState(0);
  const [mode, setMode] = useState(""); // "" = the hub's default (hybrid with an encoder)
  const [encoder, setEncoder] = useState(null);
  const agents = [...store.agents.values()].filter((a) => a.type !== "human" && !a.removed_at);
  const refresh = () => setTick((t) => t + 1);

  useEffect(() => {
    api.memory({ q, participant, mode, limit: 20 }).then(setList).catch(() => setList([]));
    api.pendingNotes().then(setPending).catch(() => setPending([]));
    api.memoryEncoder().then(setEncoder).catch(() => setEncoder(null));
  }, [q, participant, mode, store.memoryVersion, tick]);
  const similarity = encoder && encoder.encoder !== "none";

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
      <${PendingNotes} notes=${pending} refresh=${refresh} />
      <form class="form-row" style="margin-bottom:.6rem" onSubmit=${(e) => { e.preventDefault(); setQ(new FormData(e.currentTarget).get("q").trim()); }}>
        <input name="q" placeholder="what has the team settled about…" style="flex:1;min-width:16rem" defaultValue=${q} />
        <select value=${participant} onChange=${(e) => setParticipant(e.target.value)}>
          <option value="">any participant</option>
          ${agents.map((a) => html`<option key=${a.id} value=${a.name}>${a.name}</option>`)}
        </select>
        ${similarity
          ? html`<select value=${mode} onChange=${(e) => setMode(e.target.value)} title="how the question is matched">
              <option value="">hybrid (default)</option>
              <option value="exact">full text only</option>
              <option value="vector">similarity only</option>
            </select>`
          : null}
        <button class="btn primary">search</button>
        ${q ? html`<button type="button" class="btn" onClick=${() => setQ("")}>clear</button>` : null}
      </form>
      <div style="margin-bottom:.6rem"><${NoteForm} onWritten=${refresh} /></div>
      ${list === null
        ? html`<div class="muted">Loading…</div>`
        : !list.length
          ? html`<div class="empty-conv"><h3>${q ? "Nothing matches" : "Nothing remembered yet"}</h3>
              <div>${q
                ? "Try fewer or different words; a participant's name or domain also counts."
                : "A case file is written each time an agent closes a thread: one closed ask, its resolution, and your verdicts on the way. Notes are what agents, or you, want the team to know."}</div></div>`
          : html`<div class="archive-list">${list.map((r) => html`<button key=${r.id} class="arch ${open?.id === r.id ? "selected" : ""}" onClick=${() => show(r)}>
              <span class="mono names">${r.kind === "note" ? html`note by ${r.author_name} <span class="muted">· ${scopeOf(r)}</span>` : who(r)}</span>
              <span class="small">${r.kind === "note" ? r.body : r.ask || html`<i class="muted">(no ask)</i>`}</span>
              <span class="muted small">${r.kind === "note"
                ? `written ${fmtWhen(r.created_at)}`
                : `closed ${fmtWhen(r.closed_at || r.created_at)} · ${r.message_count} message${r.message_count === 1 ? "" : "s"}${verdictSummary(r) ? ` · ${verdictSummary(r)}` : ""}`}</span>
            </button>`)}</div>`}
      <div class="small muted" style="margin-top:.5rem">${q ? "Best match first, the way courtyard_recall ranks: the ask, a note's body and the participants' domains weigh most." : "Newest first."}
        Agents see the same records through courtyard_recall${store.settings?.discovery === "manual" ? ", limited to the lines they are party to" : ""}; a line's note only reaches that line's two agents.
        ${encoder
          ? similarity
            ? html`<span class="similarity">Similarity search is on (${encoder.model}): ${encoder.embedded} of ${encoder.total} records have a vector${encoder.pending ? `, ${encoder.pending} waiting for the next sweep` : ""}.</span>`
            : html`<span class="similarity">Similarity search is off: recall is full text only. Set COURTYARD_EMBEDDINGS_URL to a local embeddings endpoint to turn it on.</span>`
          : null}</div>
    </div>
    ${open
      ? open.kind === "note"
        ? html`<section class="conv archived">
            <div class="conv-head"><h2 class="mono">note by ${open.author_name}</h2>
              <span class="meta">${scopeOf(open)} · written ${fmtWhen(open.created_at)} · ${open.status}${open.gate_note ? ` · your comment: ${open.gate_note}` : ""}</span>
              <span class="act"><span class="small muted mono" title="the handle an agent passes to courtyard_recall(case=…)">${open.id}</span></span></div>
            <div class="history"><div class="msg" style="white-space:pre-wrap">${open.body}</div></div>
          </section>`
        : html`<section class="conv archived">
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
        ? html`<div class="empty-conv small">Pick a record above to read it in full.</div>`
        : null}`;
}
