# Claude Code adapter: implementation decisions

Scope: `src/courtyard/adapters/claude_code/mcp_server.py`, installed as
`courtyard-claude-mcp`. This records the implementation-level decisions, one per
section, laconic. The architecture-level decisions it builds on live in the main
design doc (`architecture-v1-2026-08-18.md`): §7 (adapter contract), D14 (thin
agent side), D15 (token placement), the step-6a spike (channels).

## 1. One stdio process per agent, spawned by Claude Code

Standard MCP stdio transport: the agent's project `.mcp.json` names the command,
Claude Code spawns it as a child at session start and speaks JSON-RPC over its
stdin/stdout. Chosen over a shared hub-side MCP server because the channels
preview was stdio-only at spike time, and because it puts the token in the
agent's own config (D15). Consequence used everywhere: adapter lifetime equals
session lifetime, so heartbeats stopping is exactly "the session died".

## 2. Direct JSON-RPC implementation, no MCP SDK

Neither `mcp.server.Server` nor FastMCP is used, deliberately:

- The load-bearing feature is off-spec. The `claude/channel` experimental
  capability and the `notifications/claude/channel` event are Claude Code
  research-preview extensions; the SDKs model the official spec (tools,
  resources, typed unions) and stop helping exactly where our risk is. The
  preview contract has drifted twice already (feedback item 11); one
  self-owned file is what we adjust when it drifts again.
- The needed surface is five methods: initialize, tools/list, tools/call,
  ping, notifications. An SDK saves little code and adds a framework.
- stdout carries protocol only, and writes are serialized by hand (a channel
  push arrives on the receiver thread while the reader may be mid-response).
  One stray line on stdout corrupts the session; we keep full control of it.
- The official SDK is anyio/async; the adapter is a small threaded process.

Revisit when item 27 (remote hub, streamable HTTP transport) is designed: over
HTTP the SDK earns its weight (sessions, reconnects, auth).

## 3. Threads, not asyncio

Main thread blocks on stdin reads; a daemon thread heartbeats; a small HTTP
listener (`ChannelReceiver`, ephemeral localhost port) takes the hub's pushes.
A lock serializes stdout. Three concerns, three threads, no event loop.

## 4. Thin by design (D14)

The hub renders everything the model reads: the authority envelope, the peers
listing, the notices. The adapter forwards text and never re-derives judgement.
Porting a new agent type means porting the forwarding, not the reasoning.

## 5. Delivery: push first, pull as fallback

The hub pushes each message to the adapter's endpoint; the adapter emits one
channel notification into the session. `courtyard_inbox` offers pull, and the
queued backlog is pushed on attach. A message ACKed by the adapter but dropped
inside Claude Code is invisible to the hub (accepted in D14); the stderr log is
where that loss shows.

## 6. Resilience

Attach retries forever, every 2 s (item 12), so hub/agent launch order is
irrelevant. Heartbeat every 5 s (D23, then D28); a `not_attached` reply makes
the next beat re-attach. Clean stdin EOF detaches (status `gone` immediately);
a killed session just vanishes and the liveness sweep decays it.

## 7. Diagnostics to stderr only

Claude Code keeps each session's stderr in `~/.claude/debug/`. Every delivery
and every skipped channel registration is logged there; it is the only ground
truth when a session ACKs pushes but shows nothing (items 11 and 16).

## 8. The channel-flag probe and the ack tool (D29/D30)

At startup the adapter walks its process ancestry (`ps`, at most 5 levels), skips
shell wrappers that name the adapter itself, and judges the claude launch command:
channels flag present, absent, or unknown when nothing readable names claude. The
verdict rides the attach call; `absent` is the deterministic tell for a session
whose channel events Claude Code silently drops. The `courtyard_ack` tool is the
other half: the hub's delivery check hands the model a token, and returning it is
the only end-to-end proof that pushes actually reach the model. Both exist because
the adapter cannot see whether Claude Code forwards its notifications; ACKing a
push proves nothing past the adapter.

## 9. The launch flag

`claude --dangerously-load-development-channels server:courtyard`, the
2.1.245-verified form. The flag contract has drifted twice; after any Claude
Code auto-update, `make test-comms` proves the round trip and prints whether
the channel was registered or skipped.
