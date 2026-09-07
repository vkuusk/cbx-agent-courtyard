# Threads: the quant of conversation

Status: draft under discussion (started 2026-09-07, feedback item 42). Decisions
accepted from this design get D-numbers in the main decision log
(`architecture-v1.md` §13). Threads are a basic construct of inter-agent
communication in the courtyard, so they get their own document; the team charter
(`team-charter.md`) references thread policies but does not define threads.

## 1. The problem

Running the courtyard on real work showed that it is difficult to control how
agents talk about one task: the thing the operator asked for. The hub's
hierarchy today jumps from the line (unbounded, lives as long as the pairing)
straight down to the message and the turn (too fine to carry a task). There is
no tier in between, and the recent pain points are all symptoms of that gap:

- Trailing questions that start unrelated exchanges (item 3.3): a boundary
  violation the envelope could only word around.
- The "no reply is owed" footer: closure expressed as prose because the protocol
  has no close.
- Two capable agents exchanging messages without end (item 29): an exchange
  nobody can end, because "enough" is not a protocol event.
- End shift expires unfinished messages (D24): what it is really doing is
  closing what the day left open, stated at the wrong granularity.
- The team-memory digests (item 39) lacked a natural unit to distill.

One concept unifies all five.

## 2. What a thread means

A thread means one bounded exchange about one ask: it starts with an
independent question or request, and it ends when the sender is satisfied,
meaning the answer is accepted or the task is verifiably done, or when the
system closes it. Every message belongs to exactly one thread. A conversation
on a line consists of threads, one after another.

Vocabulary is kept rigid: **line** owns the outer tier (the standing pairing),
**thread** owns the quant. Neither word is ever used for the other tier, in
docs, schema or telemetry. (Some ecosystems use "thread" for the outer
container; here it never leaks upward.)

## 3. Decisions taken (architect, 2026-09-07)

**Serial in v1: one open thread per line.** A line holds at most one open
thread; a new independent ask begins only when the previous thread is closed.
Reason: courtyard agents change infrastructure, and parallel threads on one
line would need proof that the two exchanges are not touching the same piece of
infrastructure. Serial threads also leave the proven turn machine untouched:
turn-taking stays a per-line rule, and the thread adds lifecycle and
bookkeeping on top. Concurrency stays adoptable later; a serial thread history
migrates trivially.

**Threads get their own design document** (this one), as a basic construct of
the communication model, not a feature of any other subsystem.

## 4. Lifecycle

States, and who moves a thread into them:

| State | Meaning | Moved by |
|---|---|---|
| `open` | an ask is in flight or under clarification | the first message of a new exchange |
| `closed` | the initiator is satisfied; the answer was accepted | the initiator |
| `expired` | the shift ended with the thread still open | end shift (extends D24) |
| `locked` | the system ended it: budget exhausted or stall | the hub |

`closed` is the healthy ending. `expired` keeps its existing meaning from D24:
nothing is deleted, history keeps the thread with its state. `locked` is
distinct from both because it records that an authority other than the
participants ended the exchange; that difference matters when reading history
later.

## 5. What the hub can enforce

Candidates, each classified as enforced or advisory when it is implemented
(the same rule as the charter's: a rule that matters is enforced by the hub,
the agent-context copy exists for clean escalation):

1. **Closure as protocol, not prose.** The initiator closes the thread
   ("answer accepted") through a real signal on the reply path; the envelope's
   closing wording becomes a rendering of a state instead of a request.
2. **Per-thread budgets.** A maximum number of exchanges per thread; reaching
   it locks the thread and tells both sides, the way turn violations are
   refused today. This is the structural answer to item 29: turn-taking is
   backpressure per message, the thread budget is backpressure per task.
3. **Shift end closes threads.** End shift marks open threads `expired`,
   subsuming the message-level expiry of D24.
4. **Visible boundaries.** The conversation pane groups messages by thread; the
   board can say "3 threads today, 1 open" instead of an undifferentiated
   scroll. Later, possibly gate policy per thread (supervise thread openings,
   auto-pass inside one).

## 6. Relations to other designs

- **Team charter** (`team-charter.md`): thread policies (budget, who may
  close) are rules of engagement and belong in the charter; the construct
  itself is defined here.
- **Team memory** (item 39): a closed thread is the unit a digest distills:
  one ask, its resolution, done.
- **Turn machine** (§5): unchanged in v1; threads sit above it.

## 7. Open questions

1. **New ask versus clarification.** How the hub knows a message opens a new
   thread rather than continuing the open one: the sender declares it
   (cheapest, honest) or the hub infers it. To decide.
2. **The close signal.** What exactly the initiator does to close: a flag on a
   message, a dedicated tool call, or both. To decide.
3. **"Verifiably done".** Out of v1: initiator-accepted is the v1 close;
   verifiable completion needs typed artifacts, which are out of scope
   (see `team-charter.md` §4).
4. **Operator threads.** D9 makes operator lines ungated; presumably operator
   threads are also unbudgeted. To confirm.
5. **Existing history.** Whether old messages are backfilled into
   reconstructed threads or threads start with the migration. To decide.
