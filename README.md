# Agent Courtyard

A team of specialized AI agents helping you — with a hub behind them that carries,
shows, and (when you want) gates every word they exchange.

Running one AI coding agent is easy; running a team of them is work. If you keep
several Claude Code sessions in parallel — each in its own project directory,
fine-tuned with its own memories and skills, each spending its full context window on
its own specialty — then cooperation means *you*, copy-pasting between terminals and
playing switchboard. And wiring agents to talk to each other directly doesn't fix it:
a few unsupervised exchanges is all it takes for two agents to run off with design
decisions nobody approved.

Agent Courtyard is a **local hub standing behind your agents**. Each agent stays
exactly what it already is — a Claude Code session in its own terminal and directory;
adding one to the team takes a minute (a name, a directory, two files the hub writes
for you). You keep working where you always did — in your main agent's terminal — and
when a task belongs to a specialist, your agent asks them **through the hub**. Every
conversation runs over a per-pair **line** with strict turn-taking, visible on the
hub's web board, and each line dials between **auto-pass** (messages flow, you read
along) and **supervised** (every message waits at a gate for your approve /
return-to-sender / drop). New team or risky ground: supervise. Proven team, good
guardrails: let it flow. One button starts the whole team's terminals for the day;
one button ends the shift and closes the books.

![Agent Courtyard — 30,000 ft view](docs/diagrams/courtyard-30k-view.png)

Everything runs on your machine: the hub binds `localhost` only — a personal,
on-your-laptop control plane. No accounts, no cloud.

## See it run first (two minutes, no agents needed)

Needs [uv](https://docs.astral.sh/uv/) and Docker (with compose).

```sh
git clone https://github.com/vkuusk/cbx-agent-courtyard.git
cd cbx-agent-courtyard
make demo
```

Open **http://127.0.0.1:2626** and keep the terminal visible — the demo narrates as it
goes. (Have Chrome? `make demo-chrome` opens the board in its own window for you.) Two scripted puppet agents register and talk through the hub: first a
conversation that flows on auto-pass, then a supervised pair whose messages **wait for
you at the gate** — click their amber line, type a comment under the held message, and
approve, return, or drop it; the puppets react to your verdicts. When you are done:

```sh
make demo-stop
```

## Run it with your own agents

Additionally needs [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
(`claude` on your PATH). The one-button team start opens Terminal/iTerm2 windows, so
this part is macOS-first; the hub itself is plain Python + Postgres.

```sh
make run-chrome     # postgres + hub + the board in its own Chrome window
```

(or just `make run` and open http://127.0.0.1:2626 in any browser)

Then, on the board:

1. **Agents** page → **+ Add an agent**: a name, type `claude-code`, and the project
   directory it should work in. Add a second agent the same way.
2. On each agent's launch panel click **write both files into ‹dir›** — the hub drops
   the MCP config and a settings profile into that directory; that is its whole
   footprint there.
3. **Courtyard** page → **▶ Start shift**: a terminal opens per agent, already in its
   directory, already connected. First launch only: accept Claude Code's two trust
   prompts in each terminal.
4. Click an agent's rectangle and, in the box at the bottom, ask it to ask the other
   agent for something. Their line appears on the board, the message stops at the gate,
   and the supervising is yours. **■ End shift** closes the day.

The same flow in full detail, every screen described:
[docs/quickstart.md](docs/quickstart.md).

## More documentation

How it actually works — the concepts (lines, turns, the gate, the shift, discovery),
the full design document with every decision and its reasons, developer setup, and the
testing runbook: **[docs/README.md](docs/README.md)**.
