"""Balancing values.

Every number of the game lives here. Server owners override any of them in
config.json under the "balance" key, without touching the code:

    "balance": {"daily": {"base_reward": 50}}
"""
from __future__ import annotations

import copy
import math
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS: dict[str, Any] = {
    "timezone": "Europe/Paris",
    "mining": {
        "cooldown_seconds": 30,
        "min_cooldown_seconds": 10,  # talents and the Efficiency enchant never go below this
        "xp_per_message": [5, 15],
        # Spam channels (config.json channels.spam): no blocks, XP or drops, only this many emeralds per message.
        "spam_reward": 0.01,
        # Each mining reward is a pile of 1 to 6 blocks (each size as likely): the smaller the pile,
        # the rarer the block can be. Weight of each block for each pile size (see talents for the bonuses).
        "odds_6_blocks": {"cobblestone": 100, "gravel": 0, "deepslate": 0, "obsidian": 0, "bedrock": 0},
        "odds_4_5_blocks": {"cobblestone": 70, "gravel": 30, "deepslate": 0, "obsidian": 0, "bedrock": 0},
        "odds_2_3_blocks": {"cobblestone": 70, "gravel": 20, "deepslate": 10, "obsidian": 0, "bedrock": 0},
        "odds_1_block": {"cobblestone": 70, "gravel": 20, "deepslate": 9, "obsidian": 3, "bedrock": 1},
    },
    "block_values": {"cobblestone": 1, "gravel": 3, "deepslate": 5, "obsidian": 7, "bedrock": 10},
    "market": {
        "stick_pack": {"amount": 4, "price": 1},
        "ingots": {"gold": 5, "iron": 10, "diamond": 60, "netherite": 300},
    },
    "talents": {
        "points_every_levels": 5,
        # Points beyond the cap would have no effect, so they cannot be bought.
        "caps": {"miner": 8, "trader": 10, "lucky": 5, "efficiency": 10},
        "trader_bonus_per_point": 0.02,
        "efficiency_seconds_per_point": 2,
        # Miner: weight added to gravel / deepslate per point (up to the max), and a chance of one
        # bonus block on piles of 4 blocks or more.
        "miner_gravel_4_5": 5, "miner_gravel_4_5_max": 40,
        "miner_gravel_2_3": 3, "miner_gravel_2_3_max": 30,
        "miner_deepslate_2_3": 2, "miner_deepslate_2_3_max": 30,
        "miner_bonus_block_chance": 0.05, "miner_bonus_block_max": 0.25,
        # Lucky: weight added to obsidian and to bedrock per point, on 1-block piles.
        "lucky_rare_weight": 1,
    },
    # XP to go from a level to the next: xp_first_level at level 1, then xp_increase_per_level more each level.
    "levels": {"xp_first_level": 100, "xp_increase_per_level": 25},
    "gear": {
        "tier": {"gold": 1, "iron": 2, "diamond": 3, "netherite": 4},
        "durability": {"gold": 60, "iron": 250, "diamond": 800, "netherite": 1500},
        # Pickaxe: extra cobblestone per mining event, and a chance per tier to
        # upgrade the mined block (cobblestone -> gravel -> deepslate -> obsidian -> bedrock).
        "pickaxe_extra_blocks_per_tier": 1,
        "pickaxe_upgrade_chance_per_tier": 0.05,
        # Shovel: extra blocks per tier when the mined block is gravel.
        "shovel_extra_gravel_per_tier": 2,
        # Axe: chance to find sticks while mining, sticks found = tier.
        "axe_stick_chance": 0.3,
        # Hoe: XP bonus per tier.
        "hoe_xp_bonus_per_tier": 0.10,
        # Maximum damage of a hit (duels, bosses, tournament): a better sword raises the maximum.
        "sword_max_damage": {"none": 6, "gold": 8, "iron": 10, "diamond": 12, "netherite": 14},
        "armor_points": {
            "gold": {"helmet": 2, "chestplate": 5, "leggings": 3, "boots": 1},
            "iron": {"helmet": 2, "chestplate": 6, "leggings": 5, "boots": 2},
            "diamond": {"helmet": 3, "chestplate": 8, "leggings": 6, "boots": 3},
            "netherite": {"helmet": 4, "chestplate": 9, "leggings": 7, "boots": 4},
        },
        "damage_reduction_per_armor_point": 0.012,
        "max_damage_reduction": 0.35,
    },
    # /repair: a piece with no durability left costs this % of its crafting value to repair.
    "repair": {"cost_percent": 60},
    "daily": {
        "base_reward": 30,
        "streak_bonus_per_day": 10,
        "streak_cap_days": 7,
        "weekly_bonus_item": "diamond",  # ingot given every 7th consecutive day
        "xp": 25,
    },
    "pay": {"min_amount": 1},
    "auction": {"tax_percent": 5, "max_listings": 10, "duration_days": 7},
    "duel": {
        "min_stake": 10,
        "hp": 20,
        # A hit deals between min_damage and the sword's maximum (gear.sword_max_damage).
        "min_damage": 1,
        "dodge_chance": 0.10,
        "crit_chance": 0.15,
        "crit_multiplier": 2.0,
        "second_player_bonus_hp": 2,  # makes up for not striking first
        "max_rounds": 40,
        "cooldown_seconds": 60,
        "request_timeout_seconds": 60,
        "xp_win": 30,
        "xp_loss": 10,
        "turn_seconds": 30,  # time to play a turn, then the bot attacks for the player
        "afk_turns": 2,  # turns missed in a row before the rest of the duel is played automatically
    },
    "potions": {
        # Duels only, one potion per turn, effect on that turn.
        "max_per_duel": 3,
        "strength_min_bonus": 5,  # this turn's attack: minimum damage +5 (never above the maximum)
        "speed_chance": 0.4,  # chance to strike twice...
        "speed_turns": 3,  # ...during this turn and the next 2 turns of the player
        "healing_hp": 3,
        "harming_damage": 3,  # direct damage, reduced by armor
        "boss_top": 3,  # the top 3 damage dealers of a defeated boss get a random potion
        "level2_multiplier": 2,  # reinforced potions (II, sold by the villager): effect x2, one per duel
        "value": 40,  # reference values in emeralds (fortune, fair prices)
        "value_ii": 120,
    },
    "drops": {
        "chance": 0.02,
        "min_interval_seconds": 900,
        "claim_seconds": 60,
        # weight, reward. A reward is {"emeralds": n} or {"ingot": material, "amount": n}
        # or {"block": type, "amount": n} or {"lapis": n} or {"book": true} (random book)
        # or {"potions": n} (random potions).
        "table": [
            {"weight": 40, "title": "An emerald pouch", "reward": {"emeralds": 50}},
            {"weight": 25, "title": "An iron vein", "reward": {"ingot": "iron", "amount": 3}},
            {"weight": 15, "title": "A bedrock cluster", "reward": {"block": "bedrock", "amount": 10}},
            {"weight": 12, "title": "A diamond vein", "reward": {"ingot": "diamond", "amount": 2}},
            {"weight": 8, "title": "Ancient debris", "reward": {"ingot": "netherite", "amount": 1}},
            {"weight": 12, "title": "A lapis vein", "reward": {"lapis": 4}},
            {"weight": 10, "title": "An enchanted book", "reward": {"book": True}},
            {"weight": 12, "title": "A witch's stash", "reward": {"potions": 2}},
        ],
    },
    "boss": {
        "auto_spawn_hours": 0,  # 0 = staff spawns bosses with /event boss
        "duration_hours": 24,
        "hp": 1000,
        "attack_cooldown_seconds": 60,
        "crit_chance": 0.1,
        "crit_multiplier": 2.0,
        "reward_pool": 600,  # emeralds shared proportionally to damage
        "top_damage_bonus": 150,
        "xp_reward": 150,
        "names": ["Wither", "Ender Dragon", "Elder Guardian", "Warden"],
    },
    "seasons": {"rewards": [300, 150, 75]},
    "teams": {
        "max_members": 5,
        "create_cost": 500,
        "min_members_ranked": 2,  # members who scored for the team, to be ranked in the team season
        "invite_hours": 48,
        # Mining XP bonus for each other member who mined today, capped.
        "xp_bonus_per_active_member": 0.05,
        "max_xp_bonus": 0.20,
        # Weekly team season: top teams' rewards, shared by contribution.
        "season_rewards": [600, 300, 150],
    },
    "enchants": {
        # Lapis lazuli: found while mining, spent to apply books.
        "lapis_chance": 0.025,  # per mining reward (1 in 40)
        "lapis_amount": [1, 2],
        "apply_cost": [2, 4, 8],  # lapis to apply a book of level I / II / III
        "book_weights": [60, 30, 10],  # chances of level I / II / III (drops, challenges)
        "boss_book_weights": [0, 70, 30],  # book of the top damage dealer
        "challenges_book": True,  # a random book for completing every weekly challenge
        # Effects for level I / II / III.
        "efficiency_seconds": [2, 4, 6],  # pickaxe: shorter mining cooldown
        "fortune_bonus": [1, 2, 3],  # pickaxe blocks, shovel gravel, axe sticks
        "fortune_hoe_xp": [0.05, 0.10, 0.15],
        "unbreaking_chance": [0.25, 0.40, 0.50],  # chance a use costs no durability
        "sharpness_damage": [1, 2, 3],
        "looting_boss_bonus": [0.10, 0.20, 0.30],
        "protection_points": [1, 2, 3],  # armor points per piece
        # Reference values in emeralds (fortune, fair auction prices).
        "lapis_value": 10,
        "book_values": [50, 150, 400],
    },
    "villager": {
        # Every day from arrive_hour to leave_hour (local time), 3 offers, one of each.
        "arrive_hour": 18,
        "leave_hour": 21,
        "sell_discount": 0.30,  # his goods are 30% below their value
        "buy_bonus": 0.50,  # he buys blocks 50% above the /sell price
        # What he can sell: an asset key (game/assets.py) and an amount.
        # "book" = a random level I/II book, "potion" = random potions.
        "goods": [
            {"asset": "ingot:iron", "amount": 8},
            {"asset": "ingot:diamond", "amount": 4},
            {"asset": "ingot:netherite", "amount": 1},
            {"asset": "lapis", "amount": 10},
            {"asset": "book", "amount": 1},
            {"asset": "potion", "amount": 2},
        ],
        # Blocks he can buy, and how many at once.
        "buys": {"gravel": 64, "deepslate": 48, "obsidian": 24, "bedrock": 16},
        # Exclusive offer: a level III book or a reinforced potion (II).
        "book_iii_price": 450,
        "potion_ii_price": 120,
    },
    "tournament": {
        "entry_fee": 50,
        "house_bonus": 200,  # emeralds the server adds to the pot
        "min_players": 4,
        "max_players": 32,
        # Local time. Days: 0 = Monday ... 6 = Sunday.
        "opens_day": 4, "opens_hour": 18,    # registrations open Friday 18:00
        "closes_day": 5, "closes_hour": 21,  # and close Saturday 21:00 (draw)
        "start_day": 6, "start_hour": 18,    # first round Sunday 18:00
        "round_minutes": 60,
        # % of the pot for the winner, the runner-up, and the semi-finalists (shared).
        "prize_split": [60, 25, 15],
        "xp_per_win": 20,
    },
    "moderation": {
        "warn_expire_days": 30,  # warnings older than this stop counting (0 = never)
        # Automatic mute when a member reaches N active warnings: {"N": "duration"}.
        "warn_mutes": {"3": "1h", "5": "1d", "7": "7d"},
    },
    "backups": {"hour": 4, "keep": 7},  # daily database copy at 04:00, 7 kept
    "challenges": {
        "per_week": 3,
        # The pool the weekly challenges are picked from: what to reach, and the emeralds it pays.
        "goals": {
            "mine_blocks": {"target": 500, "reward": 150},
            "find_bedrock": {"target": 5, "reward": 150},
            "sell_blocks": {"target": 1000, "reward": 150},
            "craft_gear": {"target": 3, "reward": 100},
            "win_duels": {"target": 3, "reward": 150},
            "claim_drops": {"target": 2, "reward": 100},
            "boss_damage": {"target": 100, "reward": 150},
            "daily_rewards": {"target": 5, "reward": 150},
            "trades": {"target": 2, "reward": 75},
        },
    },
    # Achievements: the emeralds each one pays once, and the goal of the ones that count something.
    "achievements": {
        "first_bedrock": {"reward": 25},
        "bedrock_100": {"goal": 100, "reward": 200},
        "first_obsidian": {"reward": 15},
        "miner_1k": {"goal": 1000, "reward": 100},
        "miner_10k": {"goal": 10000, "reward": 500},
        "miner_50k": {"goal": 50000, "reward": 1500},
        "first_craft": {"reward": 10},
        "blacksmith": {"goal": 25, "reward": 200},
        "iron_set": {"reward": 100},
        "diamond_set": {"reward": 300},
        "netherite_set": {"reward": 1000},
        "level_10": {"goal": 10, "reward": 50},
        "level_25": {"goal": 25, "reward": 150},
        "level_50": {"goal": 50, "reward": 400},
        "level_100": {"goal": 100, "reward": 1000},
        "first_blood": {"reward": 20},
        "gladiator": {"goal": 25, "reward": 300},
        "streak_7": {"goal": 7, "reward": 100},
        "streak_30": {"goal": 30, "reward": 500},
        "merchant": {"goal": 10, "reward": 100},
        "auctioneer": {"goal": 10, "reward": 100},
        "treasure_hunter": {"goal": 10, "reward": 150},
        "boss_slayer": {"reward": 100},
        "champion": {"reward": 250},
        "arena_champion": {"reward": 200},
        "team_champion": {"reward": 150},
        "tycoon": {"goal": 10000, "reward": 500},
        "wear_and_tear": {"reward": 10},
    },
}


_current: dict[str, Any] = copy.deepcopy(DEFAULTS)


def _merge(base: dict, override: dict, path: tuple[str, ...] = ()) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        here = path + (key,)
        # A dict with free keys (see _FREE_KEYS) is replaced as a whole: keys can be removed.
        if isinstance(value, dict) and isinstance(out.get(key), dict) and here not in _FREE_KEYS:
            out[key] = _merge(out[key], value, here)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replace the active settings with DEFAULTS merged with `overrides`."""
    global _current
    _current = _merge(DEFAULTS, overrides or {})
    return _current


def get() -> dict[str, Any]:
    return _current


# ---------------- validation ----------------
# Dicts whose keys are free (not fixed by DEFAULTS): their values must look like the defaults' values.
_FREE_KEYS = {("moderation", "warn_mutes"), ("villager", "buys")}
# Lists that can have any length (the others have one value per level and keep their length).
_FREE_LENGTH = {
    ("seasons", "rewards"), ("teams", "season_rewards"), ("boss", "names"),
    ("drops", "table"), ("villager", "goods"),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(default: Any, value: Any, path: tuple[str, ...], problems: list[str]) -> Any:
    """Validate `value` against the shape of `default`. Returns the cleaned value (or _INVALID)."""
    name = "balance." + ".".join(path)
    if isinstance(default, dict):
        if not isinstance(value, dict):
            problems.append(f"`{name}` must be a section {{ ... }}.")
            return _INVALID
        out = {}
        free = path in _FREE_KEYS
        sample = next(iter(default.values()), None)
        for key, sub in value.items():
            if free:
                checked = _check(sample, sub, path + (str(key),), problems)
            elif key not in default:
                problems.append(f"`{name}.{key}` doesn't exist (typo?).")
                continue
            else:
                checked = _check(default[key], sub, path + (key,), problems)
            if checked is not _INVALID:
                out[key] = checked
        return out
    if isinstance(default, bool):
        if not isinstance(value, bool):
            problems.append(f"`{name}` must be true or false.")
            return _INVALID
        return value
    if _is_number(default):
        if not _is_number(value) or not math.isfinite(value):
            problems.append(f"`{name}` must be a number.")
            return _INVALID
        if isinstance(default, int) and not float(value).is_integer():
            problems.append(f"`{name}` must be a whole number.")
            return _INVALID
        if value < 0:
            problems.append(f"`{name}` can't be negative.")
            return _INVALID
        if path[-1].endswith("chance") and value > 1:
            problems.append(f"`{name}` is a chance: between 0 and 1.")
            return _INVALID
        return int(value) if isinstance(default, int) else float(value)
    if isinstance(default, str):
        if not isinstance(value, str) or not value.strip():
            problems.append(f"`{name}` must be a text.")
            return _INVALID
        return value
    if isinstance(default, list):
        if not isinstance(value, list):
            problems.append(f"`{name}` must be a list [ ... ].")
            return _INVALID
        if path not in _FREE_LENGTH and len(value) != len(default):
            problems.append(f"`{name}` must have {len(default)} values.")
            return _INVALID
        if not value and path in _FREE_LENGTH and path != ("seasons", "rewards") and path != ("teams", "season_rewards"):
            problems.append(f"`{name}` can't be empty.")
            return _INVALID
        sample = default[0] if default else None
        out = []
        for i, item in enumerate(value):
            if isinstance(sample, dict):
                # Entries like drop table rows: the default's keys must be there, extra ones are free.
                if not isinstance(item, dict) or any(k not in item for k in sample):
                    problems.append(f"`{name}[{i}]` must have: {', '.join(sample)}.")
                    return _INVALID
                for k, v in sample.items():
                    if _is_number(v) and (not _is_number(item[k]) or not math.isfinite(item[k]) or item[k] < 0):
                        problems.append(f"`{name}[{i}].{k}` must be a positive number.")
                        return _INVALID
                out.append(item)
            else:
                checked = _check(sample, item, path + (str(i),), problems)
                if checked is _INVALID:
                    return _INVALID
                out.append(checked)
        return out
    return value


_INVALID = object()


def _cross_checks(merged: dict) -> list[tuple[str, list[tuple[str, ...]]]]:
    """Rules between settings: [(problem, paths to drop)]."""
    out = []
    try:
        ZoneInfo(merged["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        out.append((f"`balance.timezone` \"{merged['timezone']}\" is not a time zone (e.g. Europe/Paris).", [("timezone",)]))

    t = merged["tournament"]
    hours = {k: t[k] for k in ("opens_hour", "closes_hour", "start_hour")}
    days = {k: t[k] for k in ("opens_day", "closes_day", "start_day")}
    schedule = [("tournament", k) for k in (*hours, *days)]
    if any(h > 23 for h in hours.values()) or any(d > 6 for d in days.values()):
        out.append(("Tournament days go from 0 (Monday) to 6 (Sunday) and hours from 0 to 23.", schedule))
    else:
        opens = t["opens_day"] * 24 + t["opens_hour"]
        closes = t["closes_day"] * 24 + t["closes_hour"]
        starts = t["start_day"] * 24 + t["start_hour"]
        if not opens < closes <= starts:
            out.append(("Tournament schedule: registrations must open before they close, and close before the first round.", schedule))
    if t["min_players"] < 2 or t["min_players"] > t["max_players"]:
        out.append(("Tournament: the minimum number of players must be at least 2 and not above the maximum.",
                    [("tournament", "min_players"), ("tournament", "max_players")]))
    if sum(t["prize_split"]) > 100:
        out.append(("`balance.tournament.prize_split` adds up to more than 100%.", [("tournament", "prize_split")]))

    v = merged["villager"]
    from game.catalog import BLOCK_TYPES  # catalog has no dependencies

    if any(block not in BLOCK_TYPES for block in v["buys"]):
        out.append((f"`balance.villager.buys` keys must be blocks: {', '.join(BLOCK_TYPES)}.", [("villager", "buys")]))
    elif not v["buys"] or any(int(n) < 1 for n in v["buys"].values()):
        out.append(("`balance.villager.buys` needs at least one block, each with a pile of 1 or more.", [("villager", "buys")]))
    if not v["goods"] or any(not _good_ok(g) for g in v["goods"]):
        out.append(("`balance.villager.goods`: each good is an item (book, potion, lapis, ingot:iron…) and an amount of 1 or more.",
                    [("villager", "goods")]))
    if v["arrive_hour"] > 23 or v["leave_hour"] > 23 or v["arrive_hour"] == v["leave_hour"]:
        out.append(("Villager: hours go from 0 to 23, and he must leave at another hour than he arrives.",
                    [("villager", "arrive_hour"), ("villager", "leave_hour")]))
    if merged["backups"]["hour"] > 23:
        out.append(("`balance.backups.hour` goes from 0 to 23.", [("backups", "hour")]))

    if merged["daily"]["weekly_bonus_item"] not in merged["gear"]["tier"]:
        out.append(("`balance.daily.weekly_bonus_item` must be gold, iron, diamond or netherite.", [("daily", "weekly_bonus_item")]))

    m = merged["mining"]
    for pile in ("odds_6_blocks", "odds_4_5_blocks", "odds_2_3_blocks", "odds_1_block"):
        if sum(float(w) for w in m[pile].values()) <= 0:
            out.append((f"`balance.mining.{pile}`: at least one block needs a weight above 0.", [("mining", pile)]))
    if merged["levels"]["xp_first_level"] < 1:
        out.append(("`balance.levels.xp_first_level` must be at least 1.", [("levels", "xp_first_level")]))
    for code, goal in merged["challenges"]["goals"].items():
        if goal["target"] < 1:
            out.append((f"`balance.challenges.goals.{code}.target` must be at least 1.", [("challenges", "goals", code, "target")]))
    for code, achievement in merged["achievements"].items():
        if achievement.get("goal", 1) < 1:
            out.append((f"`balance.achievements.{code}.goal` must be at least 1.", [("achievements", code, "goal")]))
    lo, hi = m["xp_per_message"]
    if lo > hi:
        out.append(("`balance.mining.xp_per_message`: the first value is the minimum, the second the maximum.", [("mining", "xp_per_message")]))
    lo, hi = merged["enchants"]["lapis_amount"]
    if lo > hi:
        out.append(("`balance.enchants.lapis_amount`: the first value is the minimum, the second the maximum.", [("enchants", "lapis_amount")]))

    if sum(float(e["weight"]) for e in merged["drops"]["table"]) <= 0:
        out.append(("`balance.drops.table` needs at least one drop with a weight above 0.", [("drops", "table")]))
    for i, e in enumerate(merged["drops"]["table"]):
        reward = e.get("reward")
        known = isinstance(reward, dict) and any(k in reward for k in ("emeralds", "ingot", "block", "lapis", "book", "potions"))
        if not known:
            out.append((f"`balance.drops.table[{i}].reward` is not a known reward.", [("drops", "table")]))
            break

    # Imported here: moderation depends on this module.
    from game import moderation
    from game.errors import GameError

    for count, rule in merged["moderation"]["warn_mutes"].items():
        try:
            if not str(count).isdigit():
                raise GameError("")
            moderation.parse_duration(str(rule))  # "perm" is allowed
        except GameError:
            out.append((f"`balance.moderation.warn_mutes`: \"{count}\": \"{rule}\" must be a number of warnings and a duration like 1h.",
                        [("moderation", "warn_mutes")]))
            break
    return out


def _good_ok(good: Any) -> bool:
    """A villager good: {"asset": key, "amount": n}; "book" and "potion" are random ones."""
    from game import assets  # assets depends on this module
    from game.errors import GameError

    if not isinstance(good, dict) or not isinstance(good.get("amount"), int) or good["amount"] < 1:
        return False
    asset = good.get("asset")
    if asset in ("book", "potion"):
        return True
    try:
        return isinstance(asset, str) and assets.parse(asset)[0] not in ("emeralds", "gear")
    except GameError:
        return False


def _drop(overrides: dict, path: tuple[str, ...]) -> None:
    node = overrides
    for part in path[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            return
    node.pop(path[-1], None)


def clean(overrides: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Keep the valid part of the overrides. Returns (valid overrides, problems)."""
    problems: list[str] = []
    valid = _check(DEFAULTS, copy.deepcopy(overrides or {}), (), problems)
    if valid is _INVALID:
        return {}, problems
    for problem, paths in _cross_checks(_merge(DEFAULTS, valid)):
        problems.append(problem)
        for path in paths:
            _drop(valid, path)
    return valid, problems


def merged(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """What the bot uses for these overrides: DEFAULTS with their valid part."""
    return _merge(DEFAULTS, clean(overrides)[0])


def is_free_dict(path: tuple[str, ...]) -> bool:
    """A dict whose keys aren't fixed (it is replaced as a whole by an override)."""
    return tuple(path) in _FREE_KEYS


def problems(overrides: dict[str, Any] | None) -> list[str]:
    """What is wrong with these overrides (empty list = fine)."""
    return clean(overrides)[1]
