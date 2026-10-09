"""Emoji names used by the bot, and how they are resolved.

The bot looks up its application emojis (Developer Portal > Emojis) by name
at startup. config.json "emojis" can override any of them.
"""
from __future__ import annotations

import re

from game.catalog import BLOCK_TYPES, GEAR_ITEMS, MATERIALS

# Fallbacks when no custom emoji is set for a block.
BLOCK_FALLBACK = {"cobblestone": "🪨", "gravel": "🟫", "deepslate": "⬛", "bedrock": "🟪", "obsidian": "🟣"}

_CUSTOM_EMOJI = re.compile(r"^<a?:\w{2,32}:\d{15,25}>$")


def gear_key(item: str, material: str) -> str:
    return f"{material}_{item}"


EXPECTED_NAMES: tuple[str, ...] = (
    ("emerald", "stick", "xp", "lapis", "enchanted_book")
    + MATERIALS
    + BLOCK_TYPES
    + tuple(gear_key(item, material) for material in MATERIALS for item in GEAR_ITEMS)
)


def is_usable(code: str | None) -> bool:
    """A real custom emoji code, or a plain unicode emoji. Placeholders don't count."""
    if not code or not code.strip():
        return False
    code = code.strip()
    if code.startswith("<"):
        return bool(_CUSTOM_EMOJI.match(code))
    return True


def resolve(config_emojis: dict[str, str], app_emojis: dict[str, str]) -> dict[str, str]:
    """Application emojis by name, overridden by usable values from config.json."""
    out = {name: code for name, code in app_emojis.items() if is_usable(code)}
    out.update({name: code.strip() for name, code in config_emojis.items() if is_usable(code)})
    return out


def missing(emojis: dict[str, str]) -> list[str]:
    return [name for name in EXPECTED_NAMES if not emojis.get(name)]
