# Next features

Postponed features, kept as a list without assigning them a version. Each entry
points at the document that records the reasoning.

- **Switching the current team.** The hub registers several team charter
  directories and selects one as current; what switching does to a running hub
  (agents, lines, history) is not implemented. See
  `design/team-charter.md` section 3.
- **Parallel threads on one line.** Threads are serial in v1; concurrency needs
  proof that two exchanges do not touch the same infrastructure. See
  `design/threads.md` section 3.
- **"Verifiably done" thread close.** The v1 close is initiator-accepted;
  verifiable completion needs typed artifacts. See `design/threads.md`
  section 7.
- **Hook-loaded hub context.** A session-start hook injecting courtyard
  context into every agent session; postponed because the MCP instructions,
  the agent-side skill and the envelope cover its uses at lower cost. Returns
  if acceptance runs show sessions acting ignorant of the hub. See
  `design/team-charter.md` section 3.
- **Always on team mode.** The team runs without shifts; today the option is
  visible but disabled in Admin. See `design/architecture-v1.md` D23.
- **Remote hub deployment.** Hub on a server, agents local and remote. See
  feedback item 27 in `planning/feedback-items.md`.
- **Delivery without channels: a queue the agent pulls from.** Today the only thing
  that wakes an idle session is the adapter's channel notification, a Claude Code
  research preview whose flag contract has drifted before; `courtyard_inbox` is pull,
  but a model pulls only when it already has a turn. The question is a fallback
  delivery path when channels are unavailable, and with it whether queue handling
  should move to a small pub-sub queue (its own container, or postgres-backed) rather
  than the hub's own tables. A design of its own, touching the delivery model
  (`design/architecture-v1.md` section 6) and the wake-at-turn-end question. See
  feedback item 32 in `planning/feedback-items.md`.
- **Hub memory, slice 4.** Case files, notes and similarity search are in (D37,
  `design/hub-memory.md`). Still open there: the JSON Lines export, the operator's
  supersede control, retention (a case file deleted with its archive), and the
  envelope hint. See `design/hub-memory.md` sections 10 and 11.
