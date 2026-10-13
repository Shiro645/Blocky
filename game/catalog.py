"""Static game data: what exists in the game (values live in settings)."""
from __future__ import annotations

from game import settings

BLOCK_TYPES = ("cobblestone", "gravel", "deepslate", "obsidian", "bedrock")  # rarest last
MATERIALS = ("gold", "iron", "diamond", "netherite")
TOOLS = ("sword", "pickaxe", "axe", "shovel", "hoe")
ARMOR = ("helmet", "chestplate", "leggings", "boots")
SHIELD = "shield"
GEAR_ITEMS = TOOLS + ARMOR + (SHIELD,)
# Items made of only some materials (the others: every material).
ITEM_MATERIALS = {SHIELD: ("iron",)}


def materials_for(item: str) -> tuple[str, ...]:
    return ITEM_MATERIALS.get(item, MATERIALS)
TALENT_BRANCHES = ("miner", "trader", "lucky", "efficiency")

# item -> (ingots, sticks)
RECIPES = {
    "sword": (2, 1),
    "pickaxe": (3, 2),
    "axe": (3, 2),
    "shovel": (1, 2),
    "hoe": (2, 2),
    "helmet": (5, 0),
    "chestplate": (8, 0),
    "leggings": (7, 0),
    "boots": (4, 0),
    "shield": (6, 0),  # iron only
}

TALENT_INFO = {
    "miner": "Better blocks (higher gravel/deepslate odds + bonus block chance).",
    "trader": "Bonus emeralds when you /sell.",
    "lucky": "Higher bedrock and obsidian chance on 1-block rolls.",
    "efficiency": "Shorter cooldown between two mining rewards.",
}

GEAR_EFFECTS = {
    "pickaxe": "Extra cobblestone each time you mine + chance to upgrade the block",
    "shovel": "Extra gravel when you mine gravel",
    "axe": "Chance to collect sticks while mining",
    "hoe": "More XP per message",
    "sword": "Higher maximum damage (duels, tournament, bosses, the dungeon)",
    "helmet": "Damage reduction in duels, the tournament and the dungeon (capped)",
    "chestplate": "Damage reduction in duels, the tournament and the dungeon (capped)",
    "leggings": "Damage reduction in duels, the tournament and the dungeon (capped)",
    "boots": "Damage reduction in duels, the tournament and the dungeon (capped)",
    "shield": "In duels: \"Attack + block\" blocks the opponent's next attack, {blocks} per duel",
}


def gear_effect(item: str) -> str:
    """What a piece of gear does, with the current numbers."""
    blocks = int(settings.get()["gear"]["shield_blocks_per_fight"])
    return GEAR_EFFECTS[item].format(blocks="once" if blocks == 1 else "twice" if blocks == 2 else f"{blocks} times")
