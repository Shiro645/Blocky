"""Where each player command works: every command has one place.

- 🎰 the casino (channels.casino): the games of chance;
- 🌀 the portal (channels.portal): the dungeon, the gate bosses and travelling between dimensions;
- 💬 the commands channel (channels.commands): every other player command (/rob too: only the robbery the bot
  posts goes to channels.robberies).

A place that isn't set lets its commands work anywhere. Staff commands and /help work anywhere, and so does
everything in a player's private guide channel. Buttons aren't commands: they work where their message is.
"""
from __future__ import annotations

from typing import Any

from utils.config import channel_ids

CASINO = ("luckyblock", "wheel", "blackjack", "mines")
PORTAL = ("pve", "boss", "portal", "dimensions")
ANYWHERE = ("help",)

PLACES = {
    "casino": ("🎰", "the casino", CASINO),
    "portal": ("🌀", "the portal", PORTAL),
    "commands": ("💬", "the commands channel", ()),
}


def place_of(command: str, staff: bool = False) -> str | None:
    """The place of a command (its root name), or None when it works anywhere."""
    if staff or command in ANYWHERE:
        return None
    for place, (_, _, commands) in PLACES.items():
        if command in commands:
            return place
    return "commands"


def channels_of(place: str) -> set[int]:
    """The channels of a place (empty: not set, its commands work anywhere)."""
    return channel_ids(place)


def allowed(place: str | None, channel_id_: int | None, parent_id: int | None = None) -> bool:
    if place is None:
        return True
    ids = channels_of(place)
    return not ids or bool({channel_id_, parent_id} & ids)


def refusal(command: str, place: str) -> str:
    emoji, name, _ = PLACES[place]
    links = ", ".join(f"<#{c}>" for c in sorted(channels_of(place)))
    return f"{emoji} `/{command}` is used in {name}: {links}."


def migrate(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The old "games" channels (every mini-game) become the casino. Returns the new config, or None."""
    channels = cfg.get("channels") or {}
    if "games" not in channels:
        return None
    new = {k: v for k, v in channels.items() if k != "games"}
    if not new.get("casino"):
        new["casino"] = channels["games"]
    return {**cfg, "channels": new}
