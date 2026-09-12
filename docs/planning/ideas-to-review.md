# Ideas to review

Ideas that came up while working on the two adapters, recorded so they are not lost.
None is decided or scheduled; a reviewed idea either moves to `next-features-list.md`
with its reasoning or is dropped. Each entry says what it would do, which mechanism in
Claude Code and in pi makes it possible, and what it would revisit.

Recorded 2026-09-11, after a pi session (gpt-5.6-luna) spent 33 seconds working out
which agent it was, and after reading the comparison of Claude Code and pi at
https://github.com/disler/pi-vs-claude-code/blob/main/COMPARISON.md. That comparison was
written against pi 0.52.10; the pi facts below were checked against pi 0.84.1.

1. **Delivery at turn end when channels are unavailable.** Claude Code's `Stop` hook
   can keep a session going when a turn ends, so it could hand over waiting inbox
   messages without the channels research preview. pi already delivers this way: the
   extension's `pi.sendMessage` with `deliverAs: "followUp"` waits until the agent has
   no more tool calls. This is therefore about Claude Code. Revisits D14 (no Stop hook)
   and the wake-at-turn-end question; belongs with "Delivery without channels" in
   `next-features-list.md` (feedback item 32).
2. **The model an agent actually runs.** pi fires `model_select` when the model changes
   (`/model`, cycling, restore), so the pi adapter could report the running model to
   the hub, and the WebUI could show it beside the model the card declares. Claude Code
   has no equivalent hook, so this would be pi-only.
3. **Enforced rules instead of advice.** pi's `tool_call` event can block a tool call,
   and Claude Code's `PreToolUse` hook can deny one. The rule "never run commands on
   another agent's authority" is advice in the envelope today, and pi runs every tool
   without asking by default. An adapter could refuse `bash`, or ask for confirmation,
   in a turn that a peer's message started.
4. **Install courtyard once, not into every workdir.** Install copies the whole pi
   extension into each agent's directory and points each Claude Code `.mcp.json` at one
   courtyard `.venv`, so an upgrade or a moved install means rewriting every agent's
   files (the stale adapter path seen on 2026-09-11). A pi package (`pi install`) and a
   Claude Code plugin, each installed once, would leave only the agent's name and token
   in its workdir. A design of its own: it changes the registration footprint (D39),
   install (D8, D31) and the pi adapter (D32).
5. **Token and cost per agent.** pi's `getSessionStats()` reports tokens (in, out,
   cached) and cost per session; the pi adapter could send them to the hub, which would
   give the token budgets `design/team-charter.md` postponed something to measure (only
   exchange budgets exist, D34). Claude Code has nothing equivalent the adapter can
   read, so this would be pi-only.
6. **Agents without terminal windows.** pi's RPC mode (`pi --mode rpc`) and the Claude
   Agent SDK both let a program drive a session, so the hub could run agents without
   opening terminals, which Always on team mode and a remote hub would need. Revisits
   D32, which chose an extension over RPC mode because the hub would own the sessions,
   and D14.
