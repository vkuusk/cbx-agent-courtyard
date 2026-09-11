#!/bin/sh
# Agent Courtyard: the one-command install for macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/vkuusk/cbx-agent-courtyard/main/install.sh | sh
#
# What it does, in order, and nothing else: checks the prerequisites (macOS, Docker
# running, Python 3.14), downloads the newest release zip from GitHub, unpacks it into the
# current directory if that is empty (or into $COURTYARD_DIR), and runs `make install`
# there, which is the same as unzipping by hand and running it yourself. Prerequisites it
# finds missing are named with the command that installs them; it never installs them.
#
# Knobs, all optional:
#   COURTYARD_DIR=<dir>       where to unpack (default: the current directory, must be empty)
#   COURTYARD_VERSION=<tag>   a release tag instead of the newest (e.g. v0.1.0), or `main`
#   COURTYARD_ZIP=<path|url>  a zip to use instead of downloading (offline, or a checkout's
#                             `make zip-package` output)
#   COURTYARD_UNPACK_ONLY=1   stop after unpacking; run `make install` yourself
#
# Settings for the new .env, so a second, isolated instance is one command (the install
# writes them into the .env it creates; a .env already in the directory is kept as is,
# and is the other way to give settings ahead of the install):
#   COURTYARD_COMPOSE_PROJECT=<name>   compose project: its own volume and containers
#   COURTYARD_PG_PORT=<port>           the postgres host port (default 26432)
#   COURTYARD_PORT=<port>              the hub's port (default 2626)
#   also COURTYARD_ADMINER_PORT, COURTYARD_LOG_LEVEL and the COURTYARD_EMBEDDINGS_* knobs
#
#   curl -fsSL .../install.sh | COURTYARD_COMPOSE_PROJECT=courtyard-2 COURTYARD_PG_PORT=26433 COURTYARD_PORT=2627 sh
set -eu

REPO="vkuusk/cbx-agent-courtyard"
say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# -- prerequisites --------------------------------------------------------------------------
[ "$(uname -s)" = "Darwin" ] || die "this installer is for macOS (the hub itself runs anywhere with Docker)"
command -v curl >/dev/null || die "curl is required"
command -v unzip >/dev/null || die "unzip is required"
command -v make >/dev/null || die "make is required: xcode-select --install"
if ! command -v docker >/dev/null; then
  die "docker is required: install Docker Desktop (https://docker.com) or Colima (brew install colima docker), set it to start at login"
fi
docker info >/dev/null 2>&1 || die "docker is installed but not running: start it, and set it to start at login"
have_python=0
for py in python3.14 python3; do
  if command -v "$py" >/dev/null && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null; then
    have_python=1; break
  fi
done
[ "$have_python" = 1 ] || die "python 3.14 is required: brew install python@3.14"

# -- where -----------------------------------------------------------------------------------
dir="${COURTYARD_DIR:-$PWD}"
mkdir -p "$dir"
# "empty" allows a .env written ahead of the install (make install keeps an existing one,
# so the settings in it hold) and Finder's .DS_Store; anything else is somebody's files
if [ -n "$(ls -A "$dir" 2>/dev/null | grep -v -x -e .env -e .DS_Store)" ]; then
  die "$dir is not empty (a .env alone is fine); run this from an empty directory, or set COURTYARD_DIR=<empty dir>"
fi
[ -f "$dir/.env" ] && say "keeping the .env already in $dir"

# -- which version ---------------------------------------------------------------------------
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
zip="$tmp/courtyard.zip"
if [ -n "${COURTYARD_ZIP:-}" ]; then
  case "$COURTYARD_ZIP" in
    http://*|https://*) say "downloading $COURTYARD_ZIP"; curl -fsSL "$COURTYARD_ZIP" -o "$zip" ;;
    *) [ -f "$COURTYARD_ZIP" ] || die "COURTYARD_ZIP=$COURTYARD_ZIP: no such file"; cp "$COURTYARD_ZIP" "$zip" ;;
  esac
else
  version="${COURTYARD_VERSION:-}"
  if [ -z "$version" ]; then
    version="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
      | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)"
    [ -n "$version" ] || version="main"
  fi
  case "$version" in
    main) url="https://github.com/$REPO/archive/refs/heads/main.zip" ;;
    *) url="https://github.com/$REPO/archive/refs/tags/$version.zip" ;;
  esac
  say "downloading Agent Courtyard $version"
  curl -fsSL "$url" -o "$zip" || die "download failed: $url"
fi

# -- unpack, flattening the zip's single top-level directory ----------------------------------
unzip -q "$zip" -d "$tmp/unpacked"
top="$(find "$tmp/unpacked" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -n "$top" ] || die "the zip holds no directory"
# dotfiles too (.env.default, .python-version); `find -exec mv` moves each entry as is
find "$top" -mindepth 1 -maxdepth 1 -exec mv {} "$dir"/ \;
say "unpacked into $dir"

if [ "${COURTYARD_UNPACK_ONLY:-}" = "1" ]; then
  say "stopping here as asked; next: cd $dir && make install"
  exit 0
fi

# -- install ---------------------------------------------------------------------------------
cd "$dir"
say ""
say "running make install in $dir"
say ""
exec make install
