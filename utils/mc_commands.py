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
    "rl",  # Bukkit/Spigot's short reload
)

_COLOR_CODES = re.compile(r"§[0-9a-fk-orA-FK-OR]")


def normalize(command: str) -> str:
    """'/Minecraft:Whitelist   OFF' -> 'whitelist off'"""
    words = command.strip().lstrip("/").split()
    if not words:
        return ""
    first = words[0].lower()
    if ":" in first:  # "minecraft:op", "bukkit:reload", "spigot:restart"…
        first = first.split(":", 1)[1]
    return " ".join([first] + [w.lower() for w in words[1:]])


def parts(command: str) -> list[str]:
    """The command itself and every command chained after `run` ("execute ... run op Steve")."""
    cmd = normalize(command)
    return [normalize(p) for p in re.split(r"\brun\b", cmd)] if " run " in f" {cmd} " else [cmd]


def blocked_by(command: str, blocked: list[str] | tuple[str, ...]) -> str | None:
    """The blocked entry matching this command (or a command it runs), or None if it is allowed."""
    whole = normalize(command)
    # A command block (or a block/entity carrying one) would run any command, the blocked ones included.
    if "command_block" in whole or "command:" in whole:
        return "command blocks"
    chain = parts(command)
    for i, cmd in enumerate(chain):
        # "execute as @e run kill @s" kills everything as surely as "kill @e".
        if (cmd == "kill" or cmd.startswith("kill ")) and any(t in " ".join(chain[:i + 1]) for t in ("@e", "@a")):
            if any(normalize(e) in ("kill @e", "kill @a") for e in blocked):
                return "kill @e"
    for cmd in chain:
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
