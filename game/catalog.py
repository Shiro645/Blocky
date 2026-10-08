"""Static game data: what exists in the game (values live in settings)."""
from __future__ import annotations

BLOCK_TYPES = ("cobblestone", "gravel", "deepslate", "bedrock", "obsidian")  # rarest last
MATERIALS = ("gold", "iron", "diamond", "netherite")
TOOLS = ("sword", "pickaxe", "axe", "shovel", "hoe")
ARMOR = ("helmet", "chestplate", "leggings", "boots")
GEAR_ITEMS = TOOLS + ARMOR
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
}

TALENT_INFO = {
    "miner": "Better blocks (higher gravel/deepslate odds + bonus block chance).",
    "trader": "Bonus emeralds when you /sell.",
    "lucky": "Higher bedrock and obsidian chance on 1-block rolls.",
    "efficiency": "Shorter cooldown between two mining rewards.",
}

GEAR_EFFECTS = {
    "pickaxe": "More blocks per message + chance to upgrade the block",
    "shovel": "Extra gravel when you mine gravel",
    "axe": "Chance to collect sticks while mining",
    "hoe": "More XP per message",
    "sword": "Damage in duels and against bosses",
    "helmet": "Damage reduction in duels",
    "chestplate": "Damage reduction in duels",
    "leggings": "Damage reduction in duels",
    "boots": "Damage reduction in duels",
}
