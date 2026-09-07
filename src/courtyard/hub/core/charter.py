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

from courtyard.common.models import AGENT_COLORS, Charter, CharterCard

CHARTER_FILE = "team-definition.yml"
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
    return Charter(name=name.strip(), agents=[c for c in cards if c]), report


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
