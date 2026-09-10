#!/bin/sh
# The LaunchAgent's program (scripts/install.py writes the plist that runs this).
# launchd starts with an almost empty environment, so: a PATH that finds docker and
# homebrew, this directory as cwd, the .env values, postgres up, then the hub itself
# from the project's own .venv (no uv needed at runtime). Exits are restarts: launchd
# has KeepAlive, so a crash, a `make hub-restart` or the Admin page's restart button
# all end here again a few seconds later.
set -eu
cd "$(dirname "$0")/.."

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Docker may still be starting at login: wait for it rather than fail (launchd would
# only restart us into the same wait).
until docker info >/dev/null 2>&1; do
  echo "$(date '+%H:%M:%S') waiting for docker..."
  sleep 5
done
docker compose up -d --wait postgres >/dev/null

exec .venv/bin/courtyard-hub
