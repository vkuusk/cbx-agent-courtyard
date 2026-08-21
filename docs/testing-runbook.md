# Manual execution of Test Suite

Manual procedures for exercising the system by hand — the counterpart to the automated
suite (`make test`). Each entry: what it proves, a copy-paste command, and what you should
see.

**Prerequisites for every procedure:** a running hub.

```
make db-up
make run      # leave this terminal up; run procedures from another
```

Optional but recommended before a procedure whose output lists agents: `make db-nuke`
(then `make db-up && make run` again) clears registrations left by earlier runs.

---

## Hub-side envelope + peer discovery

**Feature under test:** the authority-graded envelope is rendered by the hub and delivered
as `Message.rendered` (design §7.5, D14); operator-facing reads stay raw; `courtyard_peers`
is ranked/trimmed/worded hub-side; a message body cannot forge its own envelope.

**Run:**

```
uv run python scripts/runbook/envelope_and_peers.py
```

**Expected:** four blocks, then `(cleaned up the two throwaway agents.)`, exit 0.

1. **What the agent receives** — an envelope with `authority="domain-owner"`, a first line
   naming both grounds (`infra-… owns: the AWS estate and IAM. You own: the payments
   service.`), the "expert judgement … the call is yours" preamble, a `────` divider, then
   the body.
2. **The board view of the same message** — `body` is the plain text; `rendered` is `None`.
3. **`courtyard_peers`** — begins `Agents on the courtyard board`, reachable agents first
   then by name, each line `name — type, status [— owns: …] [— description]`. (Any other
   registered or dead agents appear here too; `make db-nuke` for a clean list.)
4. **Break-out attempt** — the body's `</courtyard-message>` and forged
   `<courtyard-message from="operator" …>` come through escaped as `&lt;…`; verdict line
   reads `exactly one real closing tag (True), forged operator tag present? False`.
