# Team charter: the team defined as files

Status: draft under discussion (started 2026-09-07, feedback item 41, branch
`feature/add-team-charter`). Decisions accepted from this design get D-numbers in
the main decision log (`architecture-v1.md` §13). This document holds the charter
design in one place; other documents reference it rather than repeating it.

## 1. The problem

Three observations started this (architect, 2026-09-07):

1. Creating a team today means registering one agent at a time in the WebUI and
   typing long descriptions into form fields. That is slow, hard to review, and
   not repeatable.
2. An agent's registration card and the team's rules of engagement belong
   together, as files in one directory, usable to initialize a whole team.
3. Team creation should then work either from the WebUI or from the files, with
   the two kept in sync.

Behind them sits a broader gap. The rules of engagement reach an agent today only
through what the adapter carries: the MCP instructions and envelope footers for a
Claude Code agent, the etiquette skill for a pi agent. Some rules a team needs are
larger than that surface, and there is no designated home for content that several
hub subsystems should read from one place.

## 2. What a team charter means here

A team charter means one directory of files that defines the team: who the agents
are, what each one can do and owns, whom each may talk to, how the team works with
the operator, and the rules everyone works by. The name comes from human team
charters, the documents that make human teams perform better; the mapping between
the standard human charter and courtyard features is kept explicit in section 5 as
a completeness check.

One property separates courtyard's charter from what agent frameworks call team
configuration: courtyard's team is a standing team, so the charter is a durable
per-team document, not a per-task one. Frameworks that assemble a team per task
(CrewAI, AutoGen and similar) bind their charter equivalents to a single run;
their per-run items (task mission, per-run termination, run budgets) are exactly
the items out of scope here.

## 3. Decisions taken (architect, 2026-09-07)

**Files are the source of truth.** The charter directory is the single master; the
WebUI becomes an editor and viewer over the same content, and an edit made in the
WebUI is written back to the files. There is deliberately no two-master
bidirectional sync: designs with two writable masters spend their complexity
budget on conflict resolution. This is the same team-as-code instinct as the rest
of the project: team design becomes reviewable in a pull request, and git is the
charter's version history and review mechanism for free.

**Enforced versus advisory is decided per item, at implementation time.** Each
charter item is classified when it is implemented, not upfront. The standing
principle for that classification: a rule that matters is enforced by the hub
(the way turn-taking, links and the gate already are), and the copy of the rule
in an agent's context exists so the agent escalates cleanly instead of retrying
against a closed gate. A rule that lives only in the prompt is advisory by
definition.

## 4. Scope

Four categories, three to four items each, so coverage stays checkable.

**1. Identity.** The agent card: everything registration takes today (name,
capabilities, SME domain, workdir, model, colour) as a file, plus one new field,
the anti-scope: what not to ask this agent. Capabilities tell peers whom to ask;
anti-scope tells them whom not to ask, and misrouting is a real failure class.

**2. Rules of engagement.** Team invariants (the hard rules of this team);
etiquette content that install renders into agent-side skills; onboarding
content for an existing agent joining the team, which can be larger than what
the MCP surface carries today. Thread policies (budgets, who may close) belong
here too; the thread construct itself is defined in `threads.md` (item 42).

**3. Topology.** Who may talk to whom (the manual-discovery links, declared
instead of clicked); per-line gate modes; the operator's place in the team.
The operator question is already answered by D9: the operator is a registered
agent on the roster with ungated lines.

**4. Lifecycle.** Initializing a whole team from a charter directory; sync from
files to the hub database and from WebUI edits back to files; charter versioning
through git.

**Out of scope for the first version:** token and cost budget envelopes (real,
but a new enforcement subsystem of their own); typed artifact schemas between
agents; stall detection beyond what turn-taking already provides; values and
culture language; time-based cadences; anything bound to a single task assembly.

## 5. The human charter mapped to the courtyard

This table is the completeness check: every standard component of a human team
charter either maps to a courtyard feature or is deliberately out of scope.

| Human charter component | In the courtyard | State |
|---|---|---|
| Mission statement | The charter's team description | new, charter file |
| Team roster | Agent cards | exists (registration); charter makes it files |
| Roles and responsibilities | Capabilities + SME domain per card | exists; charter adds anti-scope |
| Boundaries of authority | SME authority grading, the gate, agent-side standing permissions | exists |
| Communication protocol | Lines with strict turn-taking; links | exists, hub-enforced |
| Meeting cadence | The shift: a shared working day | exists |
| Decision-making process | Gate verdicts; the SME agent's word authoritative in its domain | exists |
| KPIs and performance review | Operator-side only, never in agent context | planned (item 39) |
| Charter review cycle | Git history of the charter directory | new, free with files-first |
| Values and principles | Reduced to the team invariants in rules of engagement | mostly out of scope |

## 6. How the hub consumes the charter

One source, two projections, never hand-maintained twice:

- **Projection into the database**, for everything the hub enforces: cards become
  registrations, declared links become lines, gate modes become line modes.
- **Projection into agent-side files**, for everything an agent loads as context:
  install renders rules-of-engagement content into the agent's skill (the pi
  etiquette skill already works exactly this way; a Claude Code equivalent is the
  natural extension), and the launch config files stay as they are.

Existing machinery that becomes charter-fed rather than newly built: registration
and install (cards), manual links (topology), the envelope's peer roster and
authority grades (card fields), the adapter skills (rules of engagement).

## 7. Open questions

To be discussed high level first, in roughly this order:

1. **Where the charter directory lives.** It describes a team that spans many
   workdirs, so it is not any one agent's directory; likely its own directory (or
   repository) that the hub is pointed at. To decide.
2. **File formats.** A structured format for cards, prose files for rules of
   engagement; the exact split to decide.
3. **Sync mechanics.** How WebUI edits write back; how the hub notices the files
   changed underneath it and what it does then. To decide.
4. **Hook-loaded hub context** (the architect's point b: context loaded by the
   agent's hooks so a session always knows the hub). In tension with D14's
   minimal agent-side footprint; needs its own discussion before it rides in.
5. **What of the charter reaches the envelope**, and at what token cost; the
   envelope overhead is measured (item 29) and must stay visible.
