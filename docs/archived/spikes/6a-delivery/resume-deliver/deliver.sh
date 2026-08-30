#!/bin/sh
# Spike 6a-C: vkuusk's subprocess-delivery scheme.
# Appends one headless turn to a named session:  ./deliver.sh <session-name-or-uuid> "<message>"
set -eu
NAME="$1"
shift
echo "delivering into session '$NAME'…"
OUT=$(time claude -p --resume "$NAME" --output-format json "$*") || {
  echo "claude failed:"
  echo "$OUT"
  exit 1
}
echo "$OUT" | python3 -c 'import json,sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    print("session_id:", d.get("session_id"))
    print("result:", str(d.get("result"))[:400])
except json.JSONDecodeError:
    print("non-JSON output from claude:")
    print(raw[:800])'
