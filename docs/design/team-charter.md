# Team charter: the team defined as files

Status: design accepted 2026-09-07 (feedback item 41, branch
`feature/add-team-charter`, decision D33 in `architecture-v1.md` §13).
Implementation slice 1, the read path (teams registry, loader, Admin Teams
section, reload, current selection), landed 2026-09-07; projection into
registrations and write-back are next. This document holds the charter design
in one place; other documents reference it rather than repeating it.

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

**The charter lives in its own directory, chosen by the operator** (decided
2026-09-07). Anywhere on disk, typically the root of its own small git
repository; the hub is pointed at the path. Never inside an agent's workdir:
beyond the fact that the team spans workdirs, an agent has write access to its
own workdir, and a charter placed there would hand one team member the power
to rewrite the team's rules of engagement (the hub refusing a charter path
inside any registered workdir is an enforcement candidate at implementation).
The architect's driving use case: a dedicated repository makes team setups
shareable between engineers; publishing the charter repo lets another operator
clone it and initialize the same team on their own hub. The directory's name
is the operator's choice; `team-charter/` is only the convention the docs use.

**The hub keeps a registry of teams, one of them current** (decided
2026-09-07). A team is a set of agents that talk to each other and work
together; each team is one charter directory, and several can be registered
with the hub. The directories can be subdirectories of one repository, for
example `my-agent-teams/devops-team/` and `my-agent-teams/k8s-team/`, so one
repo can carry an engineer's whole collection of teams. The hub stores the
registered directories and which one is current. The WebUI shows the current
team's name on the Courtyard page; Admin gets a Teams section: add a team by
directory (the browse dialog from the workdir picker, reused) and a pulldown
selecting the current team. In v1 this is registration and selection only:
what switching the current team does to a running hub (agents, lines, history)
is postponed past v1 (recorded in `../next-features-list.md`). No team
registered means the hub behaves exactly as today, so the charter is opt-in
and an existing hub migrates at no cost. The hub stays git-agnostic: it reads
and writes charter files; commits, history and review are the operator's.

**The team defines itself in `team-definition.yml`** (decided 2026-09-07).
Inside the charter directory, one YAML index defines one team (single team
root, matching one directory per team) and lists its agents; each agent entry
points, by relative path, at a subdirectory holding the files that fill that
agent's registration:

```yaml
team:
  name: <team-name>
  agents:
    <agent-name>:
      agent-config-dir: <relative dirname>
```

The key is deliberately named `agent-config-dir` to keep it distinct from the
agent's project directory (the workdir): the configuration directory is
charter content and travels with the repo; the project directory is
engineer-machine specific and never goes into the shared charter. An agent's
configuration directory can hold multiple files, so long prose (the
description shown to peers, what the agent owns, the anti-scope) separates
into its own files instead of living inside YAML strings. The hub's team
registry reads the team name from this file and caches it for display: adding
a team to the hub is pointing at a directory, nothing more, and the name
travels with the repo when the charter is shared.

**The agent's project directory has its own per-machine change point**
(decided 2026-09-07). Workdirs are never written into shared charter files; a
separate per-machine entry holds each agent's project directory on this
machine. The exact mechanism (a gitignored overlay file in the charter
directory, values filled by asking the operator at team initialization) is
settled at implementation time.

**The agent configuration directory's file set** (decided 2026-09-07). The
agent's name exists only as its key in `team-definition.yml`, so no file
repeats it; `card.yml` holds the short structured facts (type, model, colour);
the prose fields are markdown files of their own: `description.md` (what the
agent is for, shown to peers), `owns.md` (the SME domain, backing authority
grading), `anti-scope.md` (what not to ask this agent). Team-level rules of
engagement live as sibling files beside the agents; their exact set is settled
when rules of engagement are implemented, since prose directories grow files
naturally.

**Team creation and reload are explicit, in an Admin Teams subpage** (decided
2026-09-07). Adding a team picks a directory; the hub reads it and displays
what it read. If the directory has no `team-definition.yml`, the WebUI offers
to initialize it as a team charter (the architect's refinement after live use:
an offer, not a refusal, non-empty directories included); the operator's typed
team name is the confirmation, and only then does the hub create the index
with no agents, existing files untouched: the first instance of the decided
write-back direction, so the files are the master from the first second of a
team's life. The edit view shows what the hub loaded and
carries a reload button; the hub never watches the filesystem. The operator
declares when disk is ready, which avoids loading half-saved edits and makes
the sharing workflow exactly git pull, then reload. Attached points: the edit
view shows when the charter was loaded, so staleness is visible instead of
silent; a non-empty but broken directory (missing or invalid YAML, dangling
`agent-config-dir`) renders as a readable validation report in the same view;
and reloading the current team while a shift is on needs a guard, since it
changes registrations under live agents (lean, to confirm at implementation:
refuse with the existing 409 idiom, end the shift first; a cousin of the
postponed team switching).

**Agent edits write back to the charter** (decided 2026-09-07). When the team
has a charter, the WebUI's add and edit agent forms write the card files and
the yml, not only the database; the database stays the projection of section
6. Removal necessarily follows the same rule: an agent removed only from the
database would come back at the next reload. With no team registered the
forms write the database only, exactly as today.

**Hook-loaded hub context is postponed from v1** (decided 2026-09-07, recorded
in `../next-features-list.md`). Everything a session-start hook would deliver
is covered by a channel that already works: the MCP instructions load at
session start even in a bare `claude` (only the delivery channel needs the
flag, and D29 catches that); larger rules-of-engagement content rides the
skill, loaded when relevant instead of paid by every session; live team state
comes from the envelope, per message and always current, where a hook's
snapshot goes stale at the first charter reload. The deciding evidence is how
protocol behavior gets taught: the thread-close instruction, for example,
rides the envelope footer rendered only to the thread's initiator on a
delivered reply, naming the actual peer, plus the close tool's own
description; instructions attached to the moment of action have worked live
(reply path, relay clause, scoped closing footer) where session-start prose
would sit thousands of tokens from the decision. A hook is also agent-side
behavior rather than configuration (the D14 and D21 instinct), one more trust
surface, and a second copy of the rules to keep in sync with the skill. Hooks
return if acceptance runs show sessions acting ignorant of the hub in ways
instructions plus skill do not fix.

**What reaches the envelope: one short anti-scope line per peer, nothing
more** (decided 2026-09-07). The peer roster and authority grades the envelope
already carries become charter-fed rather than growing. The anti-scope is the
one new field that earns envelope space: whom not to ask helps only at the
moment of choosing whom to ask, and misrouting is a real failure class. Rules
of engagement never enter the envelope (that is the skill's job), and the
thread footers are accounted for in `threads.md`. The Admin envelope panel's
token estimates (item 29) remain the instrument that keeps the cost visible.

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

None remaining as of 2026-09-07; every question raised in the design
discussion is either decided in section 3 or postponed with its reasoning in
`../next-features-list.md` (team switching, hook-loaded context).
