# Hub memory: the team remembers collaboration, not craft

Status: design draft, not implemented. Origin: feedback item 39. The architecture's
non-goals (`architecture-v1.md` section 2) list a memory subsystem as a v2
candidate; this document is the design that lifts it out of that list. Its
decision log entry follows when implementation starts.

## 1. The problem

Courtyard deliberately leaves craft memory to the agents. Each specialist grows
its own experience in its own project directory: memories, skills, conventions,
and that experience survives any team it takes part in. The hub stays out of it.

What nobody keeps is the other half. A team of standing agents still loses three
things every day:

- **The exchange itself.** An agent remembers its own view of a conversation, not
  the conversation. When infra asks terraform whether a module supports a flag,
  infra remembers the answer it acted on, terraform remembers that it was asked,
  and neither remembers that the operator returned the first draft with a
  comment. A week later a third agent asks the same question and spends a
  peer's turn on it.
- **The operator's verdicts.** A return to sender with a comment is the highest
  signal event the hub records: this message, on this line, was wrong, and here
  is why. Today it lands in the archive and is never read again. Supervision
  teaches nobody.
- **The record as material.** The complete inter-agent history is the one thing
  in the system that no agent can see and the operator sees only live. It is
  exactly what an audit, a post-mortem, a training set or a runbook would be
  written from, and today the only way to it is the Archive page, one line at a
  time.

The wider field describes the same gap. Disposable agent teams (a lead spawns
teammates for one task and dissolves them) re-establish context on every spawn:
the teammates share no memory, the lead's history does not carry over, and a
three-agent team costs about four times the tokens of a single session, much of
it re-explaining. Courtyard's standing team already removes the re-spawning half
of that cost. Hub memory removes the other half: what the team learned about
working together does not evaporate at End shift.

## 2. The rule

**The hub remembers collaboration, not craft.**

Agents own what they learned doing the work. The hub owns what happened between
them and what the operator ruled. Every feature in this document has to pass that
test, and two fall on the wrong side of it by design:

- The hub never reads an agent's transcript, session files or memory directory.
  It sees only what passes through it. Reading a session would duplicate the
  agent's own memory and break the segregation of duties the README promises:
  each agent holds only its own access, and the hub is not a back door into it.
- The hub never writes into an agent's memory. Memory reaches an agent through
  the two paths the hub already owns, the envelope and the hub tools, and
  through nothing else.

A second principle follows from the first slice of discussion: **a memory layer is
only real once there is a path that delivers it back into an agent's context.**
Extraction into storage that nothing reads back is a dashboard feature. So the
retrieval hop is designed first, and extraction is shaped to serve it.

## 3. The case file

The unit of memory is the closed thread (`threads.md`): one ask, its resolution,
done. Only threads that closed become case files. Threads the shift expired or the
budget locked never got their answer, and recording them would skew every later
judgement toward asks that failed. Threads between the operator and an agent count
too: they are where most tasks originate, and they are never gated. At close the
hub assembles the thread's story, which today is spread over the messages,
threads, lines and agents tables and the gate columns, into one **case file**.
The write-time work is assembly, not summarization: the hub makes no model call,
and the reader summarizes at read time, which is what a model does well.

One record, two parts:

- **Typed columns**, for filtering and for the WebUI: id, kind (`case` or
  `note`), the thread and line it came from, participants (ids and names as they
  were at the time), who opened it, opened and closed timestamps, message count,
  and verdict counts (approved, returned, dropped). Plus `superseded_by`, the
  encoder name and the embedding column of section 7, and a full-text index over
  the searchable text.
- **A JSON document**: the ordered messages with sender, body, the gate verdict,
  the verdict comment and who decided; the operator's notes on the line during
  the thread; the closing line. This is the same technique the archive uses per
  line (D20), one level down and indexed.

Two views of a record serve the two kinds of reader:

- **The trimmed view**, what recall returns: the opening ask, the resolution
  (the last message before close), every verdict with its comment, and a handle.
  Bounded, so it fits an agent's context the way a delivery does.
- **The full case file**, fetched by the handle: the whole document above.

The second kind of record is the **note**: a memory record with an author, a body
and a scope, no thread. Its scope is one line unless the author says team-wide.
Where it comes from is section 4; why it is not a message is section 5.

## 4. Where records come from

1. **Thread close.** The initiator's close call (D34) is the natural moment: the
   ask is settled and the record is complete. The hub writes the case file in the
   same transaction that closes the thread.
2. **Notes.** An agent deposits a lesson on purpose through a hub tool
   (section 5), or the operator writes one on the WebUI. The operator's notes
   are standing team guidance; the agents' notes are what a specialist wants the
   rest of the team to know without anyone having asked.

Nothing else writes memory. End shift writes none: the threads it expires (D24)
and the threads the budget locked stay in the archive only. The hub does not mine
messages in the background looking for lessons; that would be summarization the
hub cannot do without a model, and it would produce records with no event behind
them.

## 5. Delivery paths

Two paths, both riding what the hub already owns, and both pull: the envelope's
token overhead is measured and watched (item 29), and every push is a standing
cost on every message. Verdicts in particular need no delivery of their own: a
return already goes back to its sender with the comment, and an approval already
goes on to its recipient with the note (D7, D27), inside the thread, at the moment
they apply. Memory keeps them for later recall; it does not deliver them twice.

1. **Recall (pull).** A hub tool, `courtyard_recall(question, ...)`, beside the
   existing `courtyard_send`, `courtyard_peers`, `courtyard_inbox`,
   `courtyard_ack` and `courtyard_close_thread`. It returns a bounded number of
   trimmed records matching the question, filtered by what the asking agent may
   see (section 8), each with a handle; a second call with the handle returns the
   full case file. An agent asks "has the team discussed X before" and gets the
   answer without opening a line and spending a peer's turn. Zero standing token
   cost.
2. **Notes (write).** A hub tool, `courtyard_note(body, line?, team_wide?)`, by
   which an agent deposits a lesson into team memory. A note is not a message: it
   has no recipient, takes no turn and expects no answer. It is scoped to the line
   the author names (or its only line) unless the author says team-wide. It shares
   two things with a message: it shows on the WebUI, and it passes the gate
   (section 8). The same record kind lets the operator write notes from the
   Memory page; the operator's notes are team-wide unless scoped.

Recall ranks with the team's declared domains: a record's participants carry their
`sme_domain` at the time, so a question about terraform finds the threads terraform
took part in first, before any vector exists. The existing `courtyard_peers`
roster is unchanged: the roster says who owns what, memory says what happened.

A third path is deferred, not rejected: **the envelope hint**. When an incoming ask
closely matches existing records, the delivery could carry their handles only, one
line such as "the team has discussed this before: cases 41, 57", and the agent
fetches what it wants through recall. Handles cost a few tokens; the content costs
nothing until asked for. It is a push all the same, so it waits for the similarity
of section 7 and for item 29's measurements.

## 6. Beyond the agents

The store is the same; the readers differ. One read endpoint serves them all,
`GET /api/memory?q=...&mode=...&participant=...&line=...&since=...`, returning
trimmed records, plus `GET /api/memory/{id}` for the full case file and an export
in JSON Lines. Admin surface, unauthenticated on localhost like the rest (D3).

- **Audit.** Who told whom what, with the operator's verdicts inline. The Archive
  page is the raw read-back per line; memory is the indexed layer above it, and
  every record points at the archive entries it was built from.
- **Training and evaluation.** The export is a labeled set: messages with
  verdicts and comments are examples of what the operator accepts and rejects.
  What is done with it is outside the hub.
- **Skills and runbooks.** The established pattern in conversational AI is to
  mine historical transcripts into question and answer pairs, cluster them, and
  promote representatives into a knowledge base that a human reviews. Case files
  are that material with provenance attached, so a distilled runbook can be
  checked against its source.
- **The judge.** A future agent that sits on a supervised line and gives verdicts
  in the operator's place. Not designed here. The hub's memory is its precedent:
  it rules on past verdicts and their comments, alongside other sources of rules,
  so the case file keeps every verdict, its comment and who decided.

The operator reads memory on a dedicated **Memory** page: search in each of the
modes of section 7, filters by participant, line and date, the trimmed and full
views of a record, and the memory-specific controls (write a note, widen or
narrow a note's scope, mark a record superseded, delete a note). It is its own
page rather than a section of the Archive page because its searches and controls
are its own; the two pages link to each other by record and archive.

## 7. Similarity: full text first, vectors behind the same door

Recall's question is natural language, and "a similar situation" means semantic
similarity, which needs embeddings. The design adds them without changing the
API or the tool:

- **Storage.** pgvector, a Postgres extension, so vectors live in the same
  transaction domain as everything else (the reason Postgres was chosen over a
  dedicated graph or vector store). Changes: the compose image moves from
  `postgres:17-alpine` to the pgvector image, a migration creates the extension
  and adds an `embedding` column, and each record stores `embedding_model`. The
  dimension is fixed per encoder, so a model change means a new column and a
  re-embed; the stored model name is what makes that safe. No index until the
  table reaches tens of thousands of rows; an HNSW index is one more migration
  then.
- **What is encoded.** One vector per record, computed from the trimmed view (the
  ask, the resolution, the verdict comments), because that is the text a future
  question resembles. Notes are encoded from their body.
- **When.** At write time, tolerant of the encoder being down: the record is
  stored with a null embedding and a backfill sweep fills it later, the same
  shape as the liveness sweep. First enablement and model changes are that same
  sweep over every record.
- **The encoder.** An `Encoder` interface with a `none` default. With no encoder
  configured, recall is full-text only and says so. Implementations, in order:
  a local HTTP encoder (Ollama or any OpenAI-compatible embeddings endpoint on
  localhost; the hub stays light and the same shape works as a sidecar on a
  remote host), an in-process ONNX encoder (small models, no torch) if the extra
  service proves a burden, and a third-party embeddings API as an explicit
  opt-in setting, because it sends message bodies off the machine and the README
  promises nothing does by default. The opt-in has a precedent: the non-local
  bind flag.
- **Retrieval.** Modes `exact` (Postgres full-text, `websearch_to_tsquery`),
  `vector`, and `hybrid` (both, merged by reciprocal rank fusion). The tool never
  exposes the mode: it uses hybrid when embeddings exist and full-text otherwise.
  The API exposes it for other consumers and for testing. Filters by participant,
  line, domain and date are SQL `WHERE` clauses applied before ranking in every
  mode. Results are records, never scores alone, so adding vectors changes what
  comes first, not what a result is.

A remote hub changes nothing here: Postgres with pgvector and the encoder sit
beside the hub; agents only ever call the tool. The shift's terminal spawning is
the one part of a remote setup that needs a local proxy, and that is a separate
design.

## 8. Governance

Shared memory fails in ways private memory does not: staleness, conflicts, noise
crowding out signal, and poisoning, where one agent's bad note steers every other
agent. Each rule below answers one of those.

- **Provenance on every record.** Thread, line, participants, dates, and the
  verdicts with who decided. Nothing enters memory without an event behind it.
  Notes carry their author.
- **Supersession, not deletion.** A later decision that reverses an earlier one
  marks the earlier record `superseded_by`. Only the operator supersedes, from the
  Memory page; an agent's new note never supersedes anything on its own. Recall
  returns the current answer first and shows the history; nothing is silently
  rewritten.
- **The gate applies to writes.** An agent's note is visible on the WebUI the
  moment it is written and, under supervision, waits for the operator like a
  message: approve, return with a comment, or drop. Unsupervised notes flow like
  auto-pass messages and are still logged. This is the defense against
  poisoning, and it is the same dial the operator already knows. Case files
  themselves need no gate: every message in them already passed it.
- **Visibility follows discovery and scope.** Under `auto`, every agent recalls
  from the whole team's case files. Under `manual`, an agent recalls from the
  lines it is party to. Notes add their own scope on top: a line-scoped note is
  seen by that line's two agents, a team-wide note by everyone. The operator sees
  everything. Segregation of duties, applied to memory.
- **Retention is explicit.** A record lives until superseded or until the
  archive it was built from is deleted, whichever the operator does. Deleting an
  archive deletes what was distilled from it: the archive is the single source,
  memory is derived. Notes live until the operator deletes them.
- **Recall is bounded and visible.** A recall result enters an agent's context.
  The tool returns at most five trimmed records (an Admin setting), each capped in
  length (a second setting), and the Admin page's envelope preview shows a recall
  payload the way it shows the envelope, so the token cost stays measured (item 29).

## 9. Options considered

The one decision that shapes everything else: a digest needs a model, and the hub
makes no model calls today. In the votes column, 0 means parked.

| option | what it gives | what it costs | votes |
|---|---|---|---|
| **Structure, not prose.** The hub assembles the case file from facts it already holds; the reader summarizes at read time | no model in the hub, no key, no new failure mode; recall works from day one | records are longer than a digest; a reader spends tokens summarizing | chosen for slice 1 |
| **The hub calls a model itself** to write a digest per case file | short, readable digests; cheaper recall | an API key and a cost inside the hub; a heavy subsystem, which the architecture says becomes a second process | later, if recall proves used |
| **The closer writes the digest.** The initiator's close call carries a summary | no model in the hub; the agent that knows the outcome writes it | revisits D34, which made close a bare tool on purpose; digests of uneven quality | 0 |
| **A dedicated vector or graph store** (a second database) | purpose-built similarity search | a second store to keep consistent with Postgres; against the one-transaction-domain principle | 0 |
| **Mining transcripts** for lessons | more material | breaks the rule of section 2 | rejected |

## 10. Slices

1. **The case file and recall.** Migration: the memory table (typed columns, the
   JSON document, a full-text index), written at thread close, operator threads
   included. `courtyard_recall` in both adapters, full-text with domain ranking,
   five records per call. `GET /api/memory` and `GET /api/memory/{id}`. The Memory
   page, read-only in this slice. Runbook: two agents converse, the thread
   closes, a third agent recalls it.
2. **Notes.** `courtyard_note` with line scope and gate handling; the operator's
   note form and the scope controls on the Memory page. Envelope preview shows a
   recall payload.
3. **Vectors.** pgvector image and migration, the `Encoder` interface with the
   local HTTP implementation, the backfill sweep, `hybrid` mode. Runbook: a
   paraphrased question finds the case file that exact search misses.
4. **Export and visibility.** JSON Lines export, `superseded_by` and the
   operator's supersede control, `manual` discovery filtering, retention rules.

Each slice ships with tests, a runbook entry and a script, per
`developer-notes.md`.

## 11. Open questions

Settled and folded into the sections above: no
deliveries of verdicts outside the thread they belong to (no notice on the next
send, no shift-start brief); domain-aware ranking from slice 1; notes scoped to a
line unless the author says otherwise; only closed threads become case files;
operator threads included; the operator alone supersedes; five records per
recall; a dedicated Memory page; the tool names `courtyard_recall` and
`courtyard_note`.

Still open:

1. **The envelope hint** (section 5): whether, and at what similarity threshold,
   a delivery carries the handles of matching records. Waits for slice 3.
2. **The judge.** Its own design, once memory exists to rule from.
3. **Encoder choice for slice 3.** Which local encoder ships as the first
   implementation, and its model; decided when slice 3 starts.

## 12. Relations to other designs

- **Threads** (`threads.md`, D34): the closed thread is the unit; close and
  expiry are the write moments. Nothing in the thread construct changes.
- **Archive** (`architecture-v1.md` section 5.7, D20): the archive stays the raw,
  immutable record per line; memory is derived from it and deleted with it.
- **The envelope** (section 7.5): unchanged in slices 1 and 2; the deferred
  envelope hint would be a hub notice carrying record handles.
- **Discovery** (section 5.8, D22): visibility of memory follows the same
  setting.
- **Team charter** (`team-charter.md`, D33): whether notes are allowed, who may
  write them, and the recall limit are rules of engagement and could live in the
  charter later; the mechanism is defined here.
- **Feedback item 39** (`../planning/feedback-items.md`): the origin of this
  design and the four candidate memory types; item 1 there (digests, recall) is
  slice 1 here; item 2 (verdict lessons) is kept as data in the case files and
  not delivered separately; item 3 (routing suggestions) became domain-aware
  ranking; item 4 (operator-side patterns) is a query over the same table and is
  not designed separately.

## Appendix: further reading

Reference only; none of these is a dependency of the design.

- Claude Code documentation, agent teams: the limitations section (no shared
  memory, no history carry-over, one team per session).
  <https://code.claude.com/docs/en/agent-teams>
- A practitioner's account of agent teams cost and coordination.
  <https://alexop.dev/posts/from-tasks-to-swarms-agent-teams-in-claude-code/>
- Memory in LLM-based multi-agent systems: mechanisms, challenges, collective
  intelligence (TechRxiv).
  <https://www.techrxiv.org/users/1007269/articles/1367390-memory-in-llm-based-multi-agent-systems-mechanisms-challenges-and-collective-intelligence>
- Managing procedural memory in LLM agents: control, adaptation, evaluation
  (the episodic versus procedural split; Reflexion-style verbal lessons).
  <https://arxiv.org/html/2606.23127v1>
- From storage to experience: a survey of LLM agent memory mechanisms.
  <https://arxiv.org/pdf/2605.06716>
- Always-on agents: persistent memory, state and governance in LLM agents.
  <https://arxiv.org/pdf/2606.30306>
- AI Knowledge Assist: automated knowledge bases from conversation transcripts
  (the QA-pair clustering pattern behind section 6).
  <https://arxiv.org/html/2510.08149>
- Why multi-agent systems need memory engineering (MongoDB engineering blog).
  <https://www.mongodb.com/company/blog/technical/why-multi-agent-systems-need-memory-engineering>
- Designing multi-agent memory systems for production (mem0).
  <https://mem0.ai/blog/multi-agent-memory-systems>
- pgvector. <https://github.com/pgvector/pgvector>
