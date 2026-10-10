"""Static game data: what exists in the game (values live in settings)."""
from __future__ import annotations

BLOCK_TYPES = ("cobblestone", "gravel", "deepslate", "obsidian", "bedrock")  # rarest last
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
    "pickaxe": "Extra cobblestone each time you mine + chance to upgrade the block",
    "shovel": "Extra gravel when you mine gravel",
    "axe": "Chance to collect sticks while mining",
    "hoe": "More XP per message",
    "sword": "Higher maximum damage (duels, bosses, tournament)",
    "helmet": "Damage reduction in duels (capped)",
    "chestplate": "Damage reduction in duels (capped)",
    "leggings": "Damage reduction in duels (capped)",
    "boots": "Damage reduction in duels (capped)",
}
