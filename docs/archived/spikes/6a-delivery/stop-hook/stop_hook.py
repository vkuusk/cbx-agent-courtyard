#!/usr/bin/env python3
"""Spike 6a-B: Stop-hook delivery — the fallback / busy-agent backstop (design §7.2, 6c).

When Claude is about to go idle, check the "inbox" (messages.txt beside this file).
If it holds anything, block the stop and hand the content to Claude; the file is
consumed so the next stop passes. `stop_hook_active` guards against loops.
"""

import json
import sys
from pathlib import Path

INBOX = Path(__file__).parent / "messages.txt"


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        return  # a previous block is already being processed; let this stop through

    if not INBOX.exists():
        return
    body = INBOX.read_text().strip()
    if not body:
        return
    INBOX.write_text("")  # consume (the real adapter dedups by message id instead)

    text = (
        "Unread courtyard message(s) arrived while you were working — "
        f"process them before stopping:\n{body}"
    )
    # `systemMessage` is the documented field on 2.1.x; `reason` was the older name.
    # Emitting both is harmless and lets the spike report which one surfaced.
    print(json.dumps({"decision": "block", "systemMessage": text, "reason": text}))


if __name__ == "__main__":
    main()
