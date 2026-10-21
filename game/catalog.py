"""Static game data: what exists in the game (values live in settings)."""
from __future__ import annotations

from game import settings

# Dimensions, in the order they unlock. Each one has its blocks (most common first, rarest last) and pays
# more per message than the one before (see the block values and odds in settings).
DIMENSIONS = ("overworld", "nether", "end", "deep_dark", "shimmer")
DIMENSION_NAMES = {"overworld": "Overworld", "nether": "Nether", "end": "End", "deep_dark": "Deep Dark",
                   "shimmer": "Shimmer"}
DIMENSION_ICONS = {"overworld": "🌳", "nether": "🔥", "end": "🌌", "deep_dark": "🦇", "shimmer": "✨"}
DIMENSION_BLOCKS = {
    "overworld": ("dirt", "cobblestone", "gravel", "deepslate", "obsidian", "bedrock"),
    "nether": ("netherrack", "blackstone", "nether_bricks", "gilded_blackstone"),
    "end": ("end_stone", "end_bricks", "purpur"),
    "deep_dark": ("sculk", "sculk_shrieker"),
    "shimmer": ("shimmer_stone",),
}
BLOCK_TYPES = tuple(b for d in DIMENSIONS for b in DIMENSION_BLOCKS[d])
BLOCK_DIMENSION = {b: d for d in DIMENSIONS for b in DIMENSION_BLOCKS[d]}
# The overworld's dirt is extra flavour (worth as much as cobblestone): the other ranks are the same in every
# dimension. Rank 0 = the common block (pickaxe bonus), 1 = gravel's rank (shovel, Miner), 2 = deepslate's
# (Miner), 3-4 = the rare ones (Lucky). A dimension with fewer blocks gives the missing ranks to its rarest one.
RANKS = 5


def rank_block(dimension: str, rank: int) -> str:
    blocks = [b for b in DIMENSION_BLOCKS[dimension] if b != "dirt"]
    return blocks[min(rank, len(blocks) - 1)]


def block_name(block: str) -> str:
    return block.replace("_", " ")


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
    "lucky": "Higher chance of the rarest blocks (obsidian and bedrock in the overworld) on 1-block rolls.",
    "efficiency": "Shorter cooldown between two mining rewards.",
}

GEAR_EFFECTS = {
    "pickaxe": "Extra common blocks each time you mine (cobblestone, netherrack…) + chance to upgrade the block",
    "shovel": "Extra gravel when you mine gravel (or the block of its rank in other dimensions)",
    "axe": "Chance to collect sticks while mining",
    "hoe": "More XP per message",
    "sword": "Higher maximum damage (duels, tournament, gate bosses, the dungeon)",
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
