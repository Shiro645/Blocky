"""Biomes of the week (/biome): one biome for the whole server, from Monday to Sunday.

Each biome has a bonus and a malus that fit it (the Mountains have emerald ore: /sell pays more, but the slopes
slow the mining down) and a challenge of its own (game/progress.py), paid apart from the weekly challenges.
Percent effects are +biomes.bonus / -biomes.malus; effects on a chance (rare blocks, drops, the highest bet)
are ×biomes.odds_bonus / ×biomes.odds_malus.

The biome is drawn the first time it's needed in a week, among the enabled ones, never the one of the week
before, and kept (bot_state "biome:<week>"). The staff can set this week's with /event biome.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from game import botstate, settings
from game.db import Ctx, week_id_of
from game.errors import GameError


@dataclass(frozen=True)
class Effect:
    label: str
    lower_is_better: bool = False  # a bonus lowers it (cooldown, prices, damage taken)
    odds: bool = False  # a chance: ×odds_bonus / ×odds_malus instead of a percent


EFFECTS: dict[str, Effect] = {
    "gamble_bet": Effect("highest bet of the games of chance", odds=True),
    "mining_xp": Effect("mining XP"),
    "sell": Effect("/sell of blocks"),
    "cooldown": Effect("mining cooldown", lower_is_better=True),
    "rare_odds": Effect("rare blocks when mining", odds=True),
    "market": Effect("/market prices", lower_is_better=True),
    "rob_loot": Effect("/rob loot"),
    "damage_taken": Effect("damage taken in the dungeon and against gate bosses", lower_is_better=True),
    "dungeon_loot": Effect("dungeon rewards"),
    "potions": Effect("potion effects (duels, dungeon, gate bosses)"),
    "drops": Effect("drop chance", odds=True),
}


@dataclass(frozen=True)
class Biome:
    key: str
    name: str
    emoji: str
    bonus: str  # an effect of EFFECTS
    bonus_why: str
    malus: str
    malus_why: str
    challenge: str  # a challenge code (game/progress.py)

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


BIOMES: dict[str, Biome] = {b.key: b for b in (
    Biome("desert", "Desert", "🏜️", "gamble_bet", "Desert temples", "mining_xp", "Heat", "lucky_blocks"),
    Biome("mountains", "Mountains", "⛰️", "sell", "Emerald ore (only here!)", "cooldown", "Steep slopes",
          "sell_blocks"),
    Biome("badlands", "Badlands", "🏔️", "rare_odds", "Mineshafts in the open", "sell", "Worthless terracotta",
          "find_bedrock"),
    Biome("forest", "Forest", "🌲", "market", "Wood everywhere", "rare_odds", "Trees in the way", "craft_gear"),
    Biome("dark_forest", "Dark Forest", "🌑", "rob_loot", "In the shadows", "damage_taken", "Illager mansions",
          "robs"),
    Biome("jungle", "Jungle", "🌴", "dungeon_loot", "Jungle temples", "mining_xp", "Thick undergrowth",
          "pve_waves"),
    Biome("swamp", "Swamp", "🌿", "potions", "Witch huts", "drops", "Slimes", "win_duels"),
    Biome("ocean", "Ocean", "🌊", "drops", "Shipwrecks and buried treasure", "cooldown", "Mining underwater",
          "claim_drops"),
    Biome("mushroom", "Mushroom Fields", "🍄", "damage_taken", "No monster spawns here", "market",
          "An island lost at sea", "dummy"),
    Biome("tundra", "Tundra", "❄️", "cooldown", "Ice roads", "drops", "Powder snow", "mine_blocks"),
)}


def _cfg() -> dict:
    return settings.get()["biomes"]


def enabled() -> list[str]:
    on = _cfg()["enabled"]
    return [k for k in BIOMES if on.get(k, True)]


def factor(key: str, good: bool) -> float:
    """What an effect multiplies, as the biome's bonus (good) or malus."""
    c, effect = _cfg(), EFFECTS[key]
    if effect.odds:
        return float(c["odds_bonus"] if good else c["odds_malus"])
    change = float(c["bonus"]) if good else -float(c["malus"])
    return 1 - change if effect.lower_is_better else 1 + change


def _key(week: str) -> str:
    return f"biome:{week}"


def current(ctx: Ctx) -> Biome | None:
    """This week's biome (None when every biome is disabled)."""
    week = ctx.week_id
    saved = botstate.get(ctx, _key(week))
    if saved in BIOMES:
        return BIOMES[saved]
    keys = enabled()
    if not keys:
        return None
    before = botstate.get(ctx, _key(week_id_of(ctx.local_now - timedelta(days=7))))
    rng = random.Random(f"blocky-biome-{week}")
    pick = rng.choice([k for k in keys if k != before] or keys)
    botstate.put(ctx, _key(week), pick)
    return BIOMES[pick]


def multiplier(ctx: Ctx, effect: str) -> float:
    """What this week's biome multiplies `effect` by (1.0 when it doesn't touch it)."""
    biome = current(ctx)
    if biome is None:
        return 1.0
    if biome.bonus == effect:
        return factor(effect, True)
    if biome.malus == effect:
        return factor(effect, False)
    return 1.0


def describe(key: str, good: bool) -> str:
    """'/sell of blocks +15%', 'rare blocks when mining ×1.5'…"""
    f, effect = factor(key, good), EFFECTS[key]
    if effect.odds:
        return f"{effect.label} ×{f:g}"
    return f"{effect.label} {'+' if f > 1 else '-'}{abs(f - 1) * 100:g}%"


def force(ctx: Ctx, key: str) -> Biome:
    """Staff: this week's biome."""
    if key not in BIOMES:
        raise GameError("Unknown biome.")
    botstate.put(ctx, _key(ctx.week_id), key)
    return BIOMES[key]


def to_announce(ctx: Ctx) -> Biome | None:
    """This week's biome once, when the week starts (or the first time the bot runs that week)."""
    if botstate.get(ctx, "biome_announced") == ctx.week_id:
        return None
    botstate.put(ctx, "biome_announced", ctx.week_id)
    return current(ctx)


def week_ends(ctx: Ctx) -> int:
    """Next Monday 00:00, local time."""
    start = ctx.local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((start + timedelta(days=7 - start.weekday())).timestamp())
