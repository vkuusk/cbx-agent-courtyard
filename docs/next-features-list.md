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
- **Hub-side memory.** The hub learning from what only it sees: the complete
  inter-agent record and the operator's verdicts. Candidates, ranked: conversation
  digests distilled at End shift and pulled by a hub tool, verdict lessons from
  return-to-sender comments, evidence-based routing suggestions, operator-side
  patterns. Design the retrieval hop before the extraction; no embedding or vector
  store to start. The closed thread is the unit a digest distills from. See
  feedback item 39 in `planning/feedback-items.md` and `design/threads.md`
  section 6; the architecture's non-goals list it as a v2 candidate.
