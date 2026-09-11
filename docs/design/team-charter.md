# Team charter: the team defined as files

Status: accepted and implemented (origin: feedback item 41; decision D33 in
`architecture-v1.md` §13). All slices are in: the read path (teams registry,
loader, Admin Teams section, reload, current selection); projection into
registrations and lines (section 6, with the mechanics settled at
implementation recorded in section 3); write-back from the agent forms (the
mechanics likewise in section 3); and the required current team (refusal,
adoption, the team-first board flow, `courtyard-invite --team-dir`). This
document holds the charter design in one place; other documents reference it
rather than repeating it.

## 1. The problem

Three observations started this:

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

## 3. Decisions taken

**Files are the source of truth.** The charter directory is the single master; the
WebUI becomes an editor and viewer over the same content, and an edit made in the
WebUI is written back to the files. There is deliberately no two-master
bidirectional sync: designs with two writable masters spend their complexity
budget on conflict resolution. This is the same team-as-code instinct as the rest
of the project: team design becomes reviewable in a pull request, and git is the
charter's version history and review mechanism for free.

**The charter lives in its own directory, chosen by the operator.** Anywhere on
disk, typically the root of its own small git repository; the hub is pointed at
the path. Never inside an agent's workdir:
beyond the fact that the team spans workdirs, an agent has write access to its
own workdir, and a charter placed there would hand one team member the power
to rewrite the team's rules of engagement (the hub refusing a charter path
inside any registered workdir is an enforcement candidate at implementation).
The driving use case: a dedicated repository makes team setups shareable
between engineers; publishing the charter repo lets another operator
clone it and initialize the same team on their own hub. The directory's name
is the operator's choice; `team-charter/` is only the convention the docs use.
A complete worked example ships in `examples/team-charters/aws-devops/`.

**The hub keeps a registry of teams, one of them current.** A team is a set of
agents that talk to each other and work together; each team is one charter
directory, and several can be registered
with the hub. The directories can be subdirectories of one repository, for
example `my-agent-teams/devops-team/` and `my-agent-teams/k8s-team/`, so one
repo can carry an engineer's whole collection of teams. The hub stores the
registered directories and which one is current. The WebUI shows the current
team's name on the Courtyard page; Admin gets a Teams section: add a team by
directory (the browse dialog from the workdir picker, reused) and a pulldown
selecting the current team. In v1 this is registration and selection only:
what switching the current team does to a running hub (agents, lines, history)
is postponed past v1 (recorded in `../next-features-list.md`). The hub stays
git-agnostic: it reads and writes charter files; commits, history and review
are the operator's.

**A current team is required** (revised after live use). The
courtyard's team always has a charter directory: files are the source of
truth, so the truth needs a home before the first agent exists. The
requirement is deliberately cheap - one directory, chosen once, outside every
agent's workdir - and it gives the team definition a filesystem backup (and a
git home) from day one. The hub refuses agent registration while no team is
current, with the 409 idiom (`no_team`). An empty courtyard asks for the team
directory first: a directory already holding a charter is loaded, an empty one
is initialized (the existing name-prompt flow). When the first team is chosen
on a hub that already holds agents, they are adopted: written into the charter
as cards, explicitly, at that moment. There is always exactly one current
team; "no current team" survives only as the transient state of a hub whose
team has not been chosen yet, in which only team registration itself is
possible.

**The team defines itself in `team-definition.yml`.** Inside the charter
directory, one YAML index defines one team (single team root, matching one
directory per team) and lists its agents; each agent entry
points, by relative path, at a subdirectory holding the files that fill that
agent's registration:

```yaml
team:
  name: <team-name>
  discovery: manual    # optional: auto | manual; omitted = the Admin dial stays
  agents:
    <agent-name>:
      agent-config-dir: <relative dirname>
  links:
    - between: [<agent-name>, <agent-name>]
      mode: auto_pass    # optional; omitted = the hub's default for new lines
```

The `links` list (settled at implementation, slice 2) is the declared topology:
who may talk to whom, each entry naming two agents of this charter and,
optionally, the line's gate mode. A link without a mode gets the Admin default
when its line is created and then keeps whatever the operator sets; a declared
mode is reasserted on every reload, because the files are the master for what
they state. Pairs the charter does not link get no line, which under manual
discovery means they cannot reach each other.

`discovery` (settled at implementation, slice 2) lets the charter declare the
team's discovery regime, projected onto the hub's Settings dial. The point is
honesty about what the links mean: only `manual` makes a link the permission
to talk (D22), so a charter that declares its topology almost always wants
`manual`; under `auto` the links are mode presets and any pair still forms a
line on first message. Left out, the dial stays whatever the operator set in
Admin; declared, it is reasserted on every reload like the line modes. The
charter never infers `manual` from the presence of links: a silent behavior
change from a yml edit would be worse than the explicit key.

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

**The agent's project directory has its own per-machine change point.**
Workdirs are never written into shared charter files; a
separate per-machine entry holds each agent's project directory on this
machine. Mechanism settled at implementation (slice 2): `workdirs.local.yml`
beside the index, a `workdirs:` mapping of agent name to absolute path,
written by the hub when the operator answers an agent's directory question in
the Teams view (the native folder dialog, item 43). The file starts with a
never-commit warning; the hub does not edit the operator's `.gitignore`, the
same stance D15 took for the token file. A charter agent without an answer
simply registers without a workdir, exactly the state the shift already skips
and the Agents page already explains.

**The agent configuration directory's file set.** The agent's name exists only
as its key in `team-definition.yml`, so no file repeats it; `card.yml` holds the
short structured facts (type, model, colour);
the prose fields are markdown files of their own: `description.md` (what the
agent is for, shown to peers), `owns.md` (the SME domain, backing authority
grading), `anti-scope.md` (what not to ask this agent). Team-level rules of
engagement live as sibling files beside the agents; their exact set is settled
when rules of engagement are implemented, since prose directories grow files
naturally.

**Team creation and reload are explicit, in an Admin Teams subpage.** Adding a
team picks a directory; the hub reads it and displays what it read. If the
directory has no `team-definition.yml`, the WebUI offers
to initialize it as a team charter (a refinement after live use: an offer, not
a refusal, non-empty directories included); the operator's typed
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
changes registrations under live agents (implemented lean, slice 2: reloading
or selecting the current team during a shift is refused with the 409 idiom,
code `shift_active`, end the shift first; a cousin of the postponed team
switching).

**Agent edits write back to the charter.** When the team
has a charter, the WebUI's add and edit agent forms write the card files and
the yml, not only the database; the database stays the projection of section
6. Removal necessarily follows the same rule: an agent removed only from the
database would come back at the next reload. While no team is current, agent
registration is refused (`no_team`, see "A current team is required" above):
write-back has nowhere to write until the charter has its home.

Mechanics settled at implementation (slice 3). Write-back hooks
the registration endpoints, not the WebUI, so `courtyard-invite` and any other
API client follow the same rule; it is bound to the current team only, and it
runs after the database change, through the same file formats the loader
reads, so a reload right after finds nothing to disagree with. Adding an agent
writes its yml entry and a configuration directory named after it (a suffix on
a clash), `card.yml` with type and model, the prose files, and the workdir
into the per-machine overlay; the colour goes into `card.yml` only when the
request declared one, mirroring how projection treats an undeclared colour as
the hub's own nicety. Editing touches only the patched fields, and a cleared
field deletes its file, the exact inverse of the loader's
missing-file-clears-the-field rule. Removing a charter agent takes out its yml
entry, the links naming it, its overlay entry and its configuration directory
(kept when another entry shares the directory); git history preserves the
prose. An agent outside the current charter (it belongs to another registered
team) is edited in the database only: its master is elsewhere, and a charter
never adopts an agent silently - adoption happens once, explicitly, when the
first team is chosen on a hub that already holds agents. Two honesty rules
round it off: a current
team whose charter did not load refuses agent changes (`charter_not_loaded`)
before the database is touched, since the hub can neither read the membership
nor write the files; and the yml rewrite goes through a yaml round-trip that
keeps unknown keys but not comments, which the hub-written header states, so
review of a hand-annotated charter belongs to git. Single-agent edits stay
allowed during a shift, as they always were; only reload and selection carry
the shift guard.

**Hooks: allowed, each one justified.** Hooks are not forbidden on the agent
side. The rule is the one behind D14 and D21: everything registration writes
into a workdir earns its place with a concrete need the hub cannot meet, and a
hook is judged like any other item. Rules of engagement do not qualify: they
ride the skill, loaded when relevant instead of paid by every session, and
protocol behavior is taught at the moment of action (the thread-close footer
rendered to the initiator on a delivered reply, the tool descriptions), which
has worked live where session-start prose would sit thousands of tokens from
the decision. Live team state does not qualify either: it comes from the
envelope, per message and always current, where a hook's snapshot goes stale
at the first reload.

**One hook is justified: membership (D40).** A session in a fresh directory
has nothing on its own side saying that it belongs to a team. Its host wraps
every channel event as untrusted external data, and the MCP server's
instructions are the hub describing itself through the same door. Seen live
(2026-09-10, Claude Code 2.1.268, Sonnet 5): a fresh session read the
delivery check as prompt injection, refused it, then refused a peer's
question for the same reason, while the agent whose operator had typed "ask
the terraform agent" used the tools without hesitation. What was missing is
user-side context, once. So registration writes one `SessionStart` hook into
the `.claude/settings.local.json` it already writes (matchers: startup,
resume, clear, compact, fork, so a compacted session is told again). The
hook runs the adapter's context command, which asks the hub for the text and
falls back to the same text without the team's name when the hub is down; a
session start never waits on the hub. The text is light and says three
things: you are configured as part of a team of agents who communicate
through a hub called courtyard, registered as agent so-and-so of team
such-and-such; the hub sends messages from other agents and from your
operator, notices about your own messages, and at the start of a shift a
delivery check, which is expected; all of it arrives through the channel
named courtyard, and the courtyard tools are yours to use. After the first
reply the block is part of the transcript like anything else the session was
told. Hooks in that file run without a trust prompt, so the two first-launch
questions stay two. The delivery check itself no longer says "tell no one,
do nothing else"; it names the shift the operator started and says the one
tool call completes it.

**What reaches the envelope: one short anti-scope line per peer, nothing
more.** The peer roster and authority grades the envelope
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

The database projection is implemented (slice 2) with these semantics. It runs
whenever the current team's charter is loaded: on selecting a team as current
(the initialization gesture) and on every reload of the
current team; adding or reloading a non-current team only refreshes what the
hub displays. A declared `discovery` is written onto the Settings dial first. Projection is additive and idempotent: it registers charter
agents that are missing, mirrors the charter-owned fields onto the ones that
exist (description, owns, anti-scope and model follow the files exactly, so a
deleted file clears the field; the colour is hub-assigned unless the card
declares one; the workdir comes only from the per-machine overlay), and
creates declared lines that are missing. It never removes an agent or a line:
removal is the write-back direction, an agent leaves the team by leaving the
files, and since slice 3 a removal through the hub edits the files too, so the
two directions meet. The courtyard's permanent identities win
over what a charter claims: a name that is already registered with another
type keeps its type, a removed name stays removed, and the operator is never a
charter agent (D9); each such conflict, like a card without a type, is
reported in the team's load report rather than raised, because the WebUI's job
is to show what happened. Projection goes through the same registry and board
operations the operator's own gestures use, so events, colour picking and the
operator-line invariants all apply unchanged.

The anti-scope reaches the models as decided in section 3: one line per peer,
appended to the hub-rendered roster entry as `not for: ...`, collapsed to a
single line however `anti-scope.md` was wrapped. The field also joined the
agent add and edit forms and `courtyard-invite --anti-scope`, so charterless
hubs get it too.

## 7. Open questions

None remaining; every question raised in the design
discussion is either decided in section 3 or postponed with its reasoning in
`../next-features-list.md` (team switching, hook-loaded context).
