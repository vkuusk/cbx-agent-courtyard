"""Reading and bootstrapping a team charter directory (design team-charter.md, D33).

The loader is deliberately lenient: it reads everything it can and returns a report of
every problem it saw, because the WebUI's job is to display what the hub read — a broken
charter renders as a validation report, not an exception. Only the API layer decides
whether a directory can be registered at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from courtyard.common.models import AGENT_COLORS, Charter, CharterCard, CharterLink

CHARTER_FILE = "team-definition.yml"
# The per-machine overlay (D33): each agent's project directory on THIS machine. The
# charter travels between engineers; their project paths do not, so this file must never
# be committed — the hub writes it with that warning, and stays out of .gitignore
# (the operator's file, same stance as D15's token warning).
WORKDIRS_FILE = "workdirs.local.yml"
# Same shape registration enforces (api/agents.py); a charter must not smuggle in a
# name the form would refuse.
AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# `human` is not a charter type: the operator is on the roster by design (D9), never a file.
CARD_TYPES = ("claude-code", "pi", "dummy")
_PROSE_FILES = (
    ("description.md", "description"),
    ("owns.md", "sme_domain"),
    ("anti-scope.md", "anti_scope"),
)


def load_charter(charter_dir: Path) -> tuple[Charter | None, list[str]]:
    """Read the charter; return (what was read, problems found). Charter is None only
    when the index file itself is missing or unusable."""
    report: list[str] = []
    index = charter_dir / CHARTER_FILE
    if not index.is_file():
        return None, [f"no {CHARTER_FILE} in {charter_dir}"]
    try:
        doc = yaml.safe_load(index.read_text())
    except yaml.YAMLError as exc:
        return None, [f"{CHARTER_FILE} is not valid YAML: {exc}"]
    team = doc.get("team") if isinstance(doc, dict) else None
    if not isinstance(team, dict):
        return None, [f"{CHARTER_FILE} must have a single `team:` mapping at the root"]
    name = team.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, [f"{CHARTER_FILE}: `team.name` is missing or empty"]

    agents = team.get("agents") or {}
    if not isinstance(agents, dict):
        return Charter(name=name.strip()), ["`team.agents` must be a mapping of agent names"]
    cards = [
        _load_card(charter_dir, agent_name, entry, report) for agent_name, entry in agents.items()
    ]
    loaded = [c for c in cards if c]
    _apply_workdirs(charter_dir, loaded, report)
    links = _load_links(team.get("links"), {c.name for c in loaded}, report)
    discovery = team.get("discovery")
    if discovery is not None and discovery not in ("auto", "manual"):
        report.append(f"`team.discovery` must be auto or manual, got {discovery!r}")
        discovery = None
    return Charter(name=name.strip(), agents=loaded, links=links, discovery=discovery), report


def _load_card(
    charter_dir: Path, name: object, entry: object, report: list[str]
) -> CharterCard | None:
    if not isinstance(name, str) or not AGENT_NAME_RE.match(name):
        report.append(f"agent name {name!r} is not a valid agent name")
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("agent-config-dir"), str):
        report.append(f"agent {name}: needs an `agent-config-dir` entry")
        return CharterCard(name=name, config_dir="")
    rel = entry["agent-config-dir"]
    card = CharterCard(name=name, config_dir=rel)
    config_dir = (charter_dir / rel).resolve()
    if not config_dir.is_relative_to(charter_dir.resolve()):
        report.append(
            f"agent {name}: agent-config-dir {rel!r} points outside the charter directory"
        )
        return card
    if not config_dir.is_dir():
        report.append(f"agent {name}: agent-config-dir {rel!r} does not exist")
        return card
    _read_card_yml(config_dir, card, report)
    for filename, field in _PROSE_FILES:
        path = config_dir / filename
        if path.is_file():
            setattr(card, field, path.read_text().strip() or None)
    return card


def _read_card_yml(config_dir: Path, card: CharterCard, report: list[str]) -> None:
    path = config_dir / "card.yml"
    if not path.is_file():
        return
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        report.append(f"agent {card.name}: card.yml is not valid YAML: {exc}")
        return
    if doc is None:
        return
    if not isinstance(doc, dict):
        report.append(f"agent {card.name}: card.yml must be a mapping")
        return
    for key, value in doc.items():
        if key == "type":
            if value in CARD_TYPES:
                card.type = value
            else:
                report.append(
                    f"agent {card.name}: card.yml type {value!r} is not one of {CARD_TYPES}"
                )
        elif key == "model":
            card.model = str(value) if value is not None else None
        elif key == "color":
            if value in AGENT_COLORS:
                card.color = value
            else:
                report.append(
                    f"agent {card.name}: card.yml color {value!r} is not one of {AGENT_COLORS}"
                )
        else:
            report.append(f"agent {card.name}: card.yml key {key!r} is not a card field")


_LINK_MODES = ("supervised", "auto_pass")


def _load_links(entries: object, agent_names: set[str], report: list[str]) -> list[CharterLink]:
    """`team.links`: the declared topology (D33). Each entry is a mapping with `between`
    (two agent names of this charter) and an optional `mode`. Bad entries are reported
    and dropped; a bad mode is reported and the link kept without one."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        report.append("`team.links` must be a list of `between: [a, b]` entries")
        return []
    links: list[CharterLink] = []
    for entry in entries:
        between = entry.get("between") if isinstance(entry, dict) else None
        if (
            not isinstance(between, list)
            or len(between) != 2
            or not all(isinstance(n, str) for n in between)
        ):
            report.append(f"link {entry!r}: needs `between:` with exactly two agent names")
            continue
        a, b = between
        if a == b:
            report.append(f"link {entry!r}: cannot link an agent to itself")
            continue
        missing = [n for n in between if n not in agent_names]
        if missing:
            report.append(f"link {a} - {b}: {', '.join(missing)} is not an agent of this charter")
            continue
        mode = entry.get("mode")
        if mode is not None and mode not in _LINK_MODES:
            report.append(f"link {a} - {b}: mode {mode!r} is not one of {_LINK_MODES}")
            mode = None
        links.append(CharterLink(a=a, b=b, mode=mode))
    return links


def _apply_workdirs(charter_dir: Path, cards: list[CharterCard], report: list[str]) -> None:
    path = charter_dir / WORKDIRS_FILE
    if not path.is_file():
        return
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        report.append(f"{WORKDIRS_FILE} is not valid YAML: {exc}")
        return
    workdirs = doc.get("workdirs") if isinstance(doc, dict) else None
    if not isinstance(workdirs, dict):
        report.append(f"{WORKDIRS_FILE} must have a `workdirs:` mapping of agent name to path")
        return
    by_name = {c.name: c for c in cards}
    for agent_name, workdir in workdirs.items():
        card = by_name.get(agent_name)
        if card is None:
            report.append(f"{WORKDIRS_FILE} names {agent_name!r}, not an agent of this charter")
        elif not isinstance(workdir, str) or not workdir.strip():
            report.append(f"{WORKDIRS_FILE}: {agent_name} needs a path, got {workdir!r}")
        else:
            card.workdir = workdir


def set_workdir(charter_dir: Path, agent_name: str, workdir: str) -> None:
    """Record one agent's per-machine project directory in the overlay, keeping the
    other entries. Hub-written like the index, so the file exists the moment the
    operator answers the workdir question (ask-at-init, D33)."""
    path = charter_dir / WORKDIRS_FILE
    workdirs: dict[str, str] = {}
    if path.is_file():
        try:
            doc = yaml.safe_load(path.read_text())
            if isinstance(doc, dict) and isinstance(doc.get("workdirs"), dict):
                workdirs = doc["workdirs"]
        except yaml.YAMLError:
            pass  # unreadable overlay: rewrite it clean; load_charter reported the damage
    workdirs[agent_name] = workdir
    path.write_text(
        "# Written by the courtyard (design docs/design/team-charter.md). Per-machine\n"
        "# project directories for this charter's agents. Never commit this file:\n"
        "# every engineer's machine has its own paths.\n"
        + yaml.safe_dump({"workdirs": workdirs}, default_flow_style=False, sort_keys=True)
    )


def create_charter(charter_dir: Path, name: str) -> None:
    """Bootstrap an empty directory into a charter: the first instance of the WebUI's
    write-back direction — the hub writes the index, then reads its own file back."""
    (charter_dir / CHARTER_FILE).write_text(
        "# Written by the courtyard (team charter, design docs/design/team-charter.md).\n"
        "# One directory = one team; agents map to subdirectories of configuration files.\n"
        "team:\n"
        f"  name: {json.dumps(name)}\n"  # a JSON string is a valid YAML scalar, any name
        "  agents: {}\n"
    )
