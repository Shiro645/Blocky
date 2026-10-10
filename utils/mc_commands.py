"""Rules for the Minecraft console commands staff can send from Discord."""
from __future__ import annotations

import re

# Commands refused by /mc unless config.json minecraft.blocked_commands says otherwise.
# An entry blocks the command itself and anything starting with it
# ("whitelist off ...", "kill @e[...]").
DEFAULT_BLOCKED = (
    "stop",
    "restart",
    "reload",
    "op",
    "deop",
    "ban-ip",
    "pardon-ip",
    "whitelist off",
    "save-off",
    "kill @e",
    "kill @a",
)

_COLOR_CODES = re.compile(r"§[0-9a-fk-orA-FK-OR]")


def normalize(command: str) -> str:
    """'/Minecraft:Whitelist   OFF' -> 'whitelist off'"""
    words = command.strip().lstrip("/").split()
    if not words:
        return ""
    first = words[0].lower()
    if first.startswith("minecraft:"):
        first = first[len("minecraft:"):]
    return " ".join([first] + [w.lower() for w in words[1:]])


def parts(command: str) -> list[str]:
    """The command itself and every command chained after `run` ("execute ... run op Steve")."""
    cmd = normalize(command)
    return [normalize(p) for p in re.split(r"\brun\b", cmd)] if " run " in f" {cmd} " else [cmd]


def blocked_by(command: str, blocked: list[str] | tuple[str, ...]) -> str | None:
    """The blocked entry matching this command (or a command it runs), or None if it is allowed."""
    for cmd in parts(command):
        for entry in blocked:
            rule = normalize(entry)
            # "kill @e" also blocks "kill @e[type=...]"
            if rule and (cmd == rule or cmd.startswith(rule + " ") or cmd.startswith(rule + "[")):
                return entry
    return None


def clean_output(text: str, limit: int = 1500) -> str:
    """Remove Minecraft color codes and keep the answer short enough for Discord."""
    text = _COLOR_CODES.sub("", text or "").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text or "(no output)"
