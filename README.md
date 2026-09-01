# Agent Courtyard

A local communication hub for your team of AI agents.

If an AI agent is setting this up for you, point it at [AGENTS.md](AGENTS.md).

## Why this project?

A single AI agent works well until you ask it to do everything. One session
means one context window, one set of memories, one set of skills. When the same
session writes Terraform, reviews Python, debugs CI pipelines and investigates
production incidents, it spends its context on material irrelevant to the task
at hand, and the quality of its work drops.

The fix many people discover on their own is to run several sessions in parallel.
Each one lives in its own project directory, is fine-tuned with memories and skills
for one specialty, and spends its full context window on its own domain. This works,
and now you have a team of specialized agents.

There is a second reason to split the work, and it has nothing to do with context
windows: **segregation of duties**. An agent that does everything needs credentials
for everything, and one bad turn can reach the whole company. When each agent holds
only the access its own specialty needs, no single agent can take everything down.
This is the same principle you already apply to people.

Each agent also gains experience on its own. Most of its work needs no team at all,
and every task it handles alone still tunes its memories and skills. Your
specialists get better week after week, independently, and collaborate when a task
crosses specialties.

The team creates new problems:

1. Out of the box, cooperation means *you*. You read an answer in one terminal and
   copy/paste it into another, playing the role of a human relay.
2. Agents can already talk to each other directly. Claude Code, for example, ships
   cross-session messaging and an experimental agent teams feature. But direct talk
   is talk you cannot properly see or steer: there is no single place to watch the
   conversation, no way to hold a message before it lands, and a few unsupervised
   exchanges can be enough for two agents to settle on a design decision you would
   not have approved.
3. There is no record. Inter-agent messages end up scattered across session
   transcripts and internal files, so when something goes wrong you cannot
   reconstruct who told whom what.
4. Nothing manages the team as a team. There is no roster, no shared history that
   survives a restart, and no shared working day: you open N terminals in N
   directories by hand and close them the same way. Vendor team features do not
   help here, since they form a team for one task and dissolve it with the session.

How much these problems matter depends on what the team does. Courtyard comes from
devops work, where agents do not only write code: they deploy it, manage
infrastructure and dig through incidents. The cost of a mistake is not symmetric
here. If a coding agent ships a bug, you ship a patch. If an infrastructure agent
deletes a production VPC or drops a database, there is no patch. A team like that
needs control and predictability more than it needs autonomy, and that requirement
shaped everything Courtyard does.

## What solution does Courtyard provide?

Agent Courtyard is a local hub standing between your agents. Each agent stays
exactly what it already is: a session in its own terminal, in its own project
directory, with its own memories, skills and credentials. Adding an agent to the
team means registering it in the hub; the hub writes three small files into the
agent's directory, and that is its whole footprint there.

You keep working the way you already do, in your agents' terminals. Sometimes you
ask your main agent to delegate a task to a specialist; sometimes you talk to a
specialist directly. The hub imposes no hierarchy and no orchestrator: any agent
can ask any other agent for help, and the hub carries the message.

Each of the four problems above has a direct answer in the hub:

1. **No more human relay.** When a task crosses specialties, your agent asks the
   right SME agent through the hub, and the answer comes back the same way. You
   read along instead of copy/pasting.
2. **Every conversation is visible and steerable.** A pair of agents talks over a
   **line**, which means a dedicated conversation with strict turn-taking: one
   unanswered message at a time. Each line runs in one of two modes. **auto-pass**
   means messages flow while you read them, in real time or later. **supervised**
   means every message waits at a gate for your verdict: approve it, return it to
   the sender with a comment, or drop it. You set the mode per line and change it
   at any time, so a new team starts supervised and earns auto-pass.
3. **The record is complete.** The hub is the only path between agents, so nothing
   passes it by. Every message is stored in Postgres and appears on the WebUI as
   it happens; finished conversations move to an archive. You can always
   reconstruct who told whom what.
4. **The team is managed as a team.** The hub keeps the roster, and the roster
   survives restarts. **Start shift** opens a terminal per agent, each in its own
   directory, already connected. **End shift** closes exactly those windows and
   closes the books on unfinished conversations. Your working day has a beginning
   and an end.

The hub does not care what an agent is. Any tool that can speak the adapter
protocol can join the team. Currently, the one adapter shipped is for Claude Code.

![Agent Courtyard 30,000 ft view](docs/diagrams/courtyard-30k-view.png)

Currently, everything runs on one machine: yours. The hub binds to `localhost` only,
there are no accounts and nothing leaves your laptop. Courtyard is a personal tool,
not a service. A remote option (the hub on one machine, agents on several) is
planned, but not implemented yet.

## How is this different from Claude Code agent teams?

If you use Claude Code you may know its experimental **agent teams** feature: a lead
session spawns teammates, hands them tasks from a shared list, and the teammates
message each other while they work. There is also **cross-session messaging**, which
lets your independent Claude Code sessions message each other directly. Both are
useful, and Courtyard does not replace them. The differences are in shape:

1. **A task team versus a standing team.** An agent team is formed for one task,
   inside one project, and dissolves with the session that spawned it. A teammate
   spawned this morning has no memory of last week. Courtyard's team is the
   opposite: standing specialists, each in its own project directory, whose
   memories and skills grow with every task. The roster and the full conversation
   history live in the hub's database and survive every restart.
2. **Where the conversation lives.** Agent team messages travel through per-agent
   mailbox files, and cross-session messages go over local sockets; a message is
   visible in, at best, two session transcripts. In Courtyard the hub is the only
   path, so there is one place where every inter-agent message can be watched live
   and read back later.
3. **Whether you stand in the path.** In an agent team, teammate messages are
   delivered without you. Courtyard puts a gate on any line you choose: the message
   waits for your approve, return with a comment, or drop. You can supervise a new
   team word by word and loosen the gate as it earns trust.
4. **Who can join.** Agent teams are Claude Code coordinating Claude Code. The
   Courtyard hub takes any agent that has an adapter. Currently, only one adapter
   is implemented, for Claude Code. That is a limit of the implementation phase,
   not of the design.

If you want to fan out one task across parallel workers in one repository for an
afternoon, agent teams are built in and are the simpler tool. Courtyard is for the
other case: a team you keep, doing work where you need to see, steer and be able
to replay every word that passes between your agents.

## Getting started

Currently, the requirements are:

- macOS. The hub itself is plain Python + Postgres, but starting the team's shift
  opens Terminal or iTerm2 windows, so this part is macOS only for now.
- [uv](https://docs.astral.sh/uv/) and Docker (with compose).
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
  (`claude` on your PATH).

### Design the team before registering it

Team design decides more of your success than any setting in the hub. If you do not
already run a set of long-lived specialized sessions, think first about the team's
composition: which specialties, split how. The split decides what context each agent
accumulates, what access it needs, and whom the others should ask for what.

Two old principles guide the split. Segregation of duties: an agent that deploys
AWS resources does not hold IAM rights, it asks the agent that owns IAM.
Separation of concerns: one agent develops the library, another develops the
application, and each asks the other instead of working in the other's domain. In
both cases the boundary runs inside the team, and crossing it is a conversation.

Start with two agents. For each agent, registration asks you to state two things,
and the rest of the team will act on both:

- **its capabilities**: what the agent can do. The hub advertises this to every
  other agent, and it is how they decide whom to ask.
- **its responsibilities**: what the agent owns. The hub uses it to mark the agent's
  word as authoritative inside its own area.

The agent's standing tool permissions belong to this design too. Agents answer
peers on their own, and a teammate's question should not end at a permission
prompt in a terminal nobody is watching. Give each agent standing approval for
the read-only access its responsibilities need, keep the risky permissions
tight, and the agent will report through the hub when something it may not do
blocks an answer.

### Start the hub

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
cp .env.default .env   # local settings; the defaults work unless a port is taken
make run            # postgres + the hub, in the foreground
```

Then open http://127.0.0.1:2626 in a browser. `make run` is the recommended way:
the hub stays in your terminal, so you always see that it is running and what it
logs, and Ctrl+C stops it. `make run-chrome` is the background alternative (hub
logs to `sandbox/courtyard.log`, WebUI in its own Chrome window, `make run-stop`
to end it); use it once the setup is familiar.

### Register your agents

On the WebUI:

1. **Agents** page → **+ Add an agent**: a name (permanent, so choose it once),
   type `claude-code`, the project directory the agent works in, and the two
   descriptions from the team design: what it can do and what it owns.
2. In the agent's edit view open **launch config** and press
   **write the files into ‹dir›**. The hub drops three small files into that
   directory: `.mcp.json` (the connection, holds the agent's token, keep it out
   of git), a `.claude/settings.local.json` profile that pre-approves the
   courtyard tools, and `start-with-courtyard.sh` for starting the agent by hand.

Or do both in one command per agent:

```sh
uv run courtyard-invite --register --name tf-developer \
    --description "what the agent can do" \
    --sme-domain "what the agent owns" \
    --workdir <the agent's project directory>
```

### Run the team in shifts

The team's working day is a **shift**. **▶ Start shift** on the Courtyard page
starts everyone: first a short countdown while the hub verifies who is genuinely
alive (a stored status is not trusted, a fresh heartbeat is), then one terminal
opens per agent that did not report in, each in its own directory with the agent
already connected. At an agent's first ever launch, accept Claude Code's two trust
prompts in its terminal; they cannot be pre-answered. As each session comes up the
hub sends it a delivery check, and the green check mark on the agent's card means
messages provably reach that session; you can re-run the check any time from that
same button.

**■ End shift** ends the day. It closes exactly the terminals the shift opened
(terminals you opened yourself are left alone) and closes the books: a conversation
still waiting on a reply, or a message still held at the gate, is marked expired.
Expired messages stay in the history, and the next shift starts with every line
clear. If part of the team dies mid-shift, **▶ Resume shift** appears and starts
only the missing agents.

You can also start a single agent by hand: run the script that registration wrote,
in the agent's directory:

```sh
cd <the agent's directory>
./start-with-courtyard.sh
```

It starts Claude Code with the flag that connects the session to the hub. A plain
`claude` session in the same directory looks healthy but cannot hear the hub; the
WebUI warns you when that happens.

To try the team: click an agent's rectangle on the Courtyard page and, in the box
at the bottom, ask it to ask another agent for something. Their line appears on the
WebUI, the message stops at the gate, and the supervising is yours.

The same flow in full detail, every screen described:
[docs/quickstart.md](docs/quickstart.md).

### Preview the gate without real agents

If you want to see the message flow and the gate before connecting your own agents,
run the scripted demo:

```sh
make demo          # or: make demo-chrome to open the WebUI in its own window
```

Two dummy agents register and talk through the hub: one conversation flows on
auto-pass, the other is supervised and its messages wait at the gate for your
verdict. The dummies react to what you decide. We built this for testing the hub,
and it doubles as a safe preview. `make demo-stop` removes the dummies and
everything they produced.

## Key design decisions

Three decisions do most of the work in keeping a team of agents predictable. Each
one exists because of a problem we hit while running such a team.

**Messages carry authority.** To a model, every incoming message is just text, so
a peer's suggestion can weigh as much as your instruction. The hub wraps each
delivery in an envelope with an authority grade: the operator's word, the word of
the agent that owns the domain in question, an ordinary peer, or a hub notice. The
envelope also tells the agent how to reply so the answer reaches the sender; text
printed in a terminal reaches nobody.

**Turn-taking is backpressure.** Nothing in a model stops it from sending message
after message. On a line, only one message may be unanswered at a time; when an
agent tries to send again, the hub refuses and tells it whose turn it is. That is
a rule a model can read and reason about, so agents wait for the answer instead of
flooding each other.

**Discovery can be manual.** By default, any pair of agents may start talking on
its own, which fits a team working on one project. When the same hub keeps agents
for several non-overlapping projects, that openness turns into noise: every
agent's peer list advertises agents it will never need to talk to. Set discovery
to manual and agents see and can reach only the pairs you have linked, so each
project's sub-team stays among its own, with you as the only bridge between them.
Links are per pair, not per group, so one agent can serve two sub-teams: an AWS
read-only agent, for example, can be linked into two projects for troubleshooting
while those projects still cannot see each other.

## More documentation

How it actually works: the concepts (lines, turns, the gate, the shift, discovery),
the full design document with every decision and its reasons, developer setup, and the
testing runbook, all in **[docs/README.md](docs/README.md)**.
