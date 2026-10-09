"""Balancing values.

Every number of the game lives here. Server owners override any of them in
config.json under the "balance" key, without touching the code:

    "balance": {"daily": {"base_reward": 50}}
"""
from __future__ import annotations

import copy
from typing import Any

DEFAULTS: dict[str, Any] = {
    "timezone": "Europe/Paris",
    "mining": {
        "cooldown_seconds": 30,
        "min_cooldown_seconds": 5,
        "xp_per_message": [5, 15],
    },
    "block_values": {"cobblestone": 1, "gravel": 3, "deepslate": 5, "obsidian": 7, "bedrock": 10},
    "market": {
        "stick_pack": {"amount": 4, "price": 1},
        "ingots": {"gold": 5, "iron": 10, "diamond": 25, "netherite": 100},
    },
    "talents": {
        "points_every_levels": 5,
        # Points beyond the cap would have no effect, so they cannot be bought.
        "caps": {"miner": 8, "trader": 10, "lucky": 5, "efficiency": 10},
        "trader_bonus_per_point": 0.02,
        "efficiency_seconds_per_point": 2,
    },
    "gear": {
        "tier": {"gold": 1, "iron": 2, "diamond": 3, "netherite": 4},
        "durability": {"gold": 60, "iron": 250, "diamond": 800, "netherite": 1500},
        # Pickaxe: extra blocks per mining event, and a chance per tier to
        # upgrade the mined block (cobblestone -> gravel -> deepslate -> obsidian -> bedrock).
        "pickaxe_extra_blocks_per_tier": 1,
        "pickaxe_upgrade_chance_per_tier": 0.05,
        # Shovel: extra blocks per tier when the mined block is gravel.
        "shovel_extra_gravel_per_tier": 2,
        # Axe: chance to find sticks while mining, sticks found = tier.
        "axe_stick_chance": 0.3,
        # Hoe: XP bonus per tier.
        "hoe_xp_bonus_per_tier": 0.10,
        "sword_damage": {"none": 1, "gold": 4, "iron": 6, "diamond": 7, "netherite": 8},
        "armor_points": {
            "gold": {"helmet": 2, "chestplate": 5, "leggings": 3, "boots": 1},
            "iron": {"helmet": 2, "chestplate": 6, "leggings": 5, "boots": 2},
            "diamond": {"helmet": 3, "chestplate": 8, "leggings": 6, "boots": 3},
            "netherite": {"helmet": 4, "chestplate": 9, "leggings": 7, "boots": 4},
        },
        "damage_reduction_per_armor_point": 0.03,
        "max_damage_reduction": 0.8,
    },
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
        "crit_chance": 0.1,
        "crit_multiplier": 1.5,
        "max_rounds": 40,
        "cooldown_seconds": 60,
        "request_timeout_seconds": 60,
        "xp_win": 30,
        "xp_loss": 10,
    },
    "drops": {
        "chance": 0.02,
        "min_interval_seconds": 900,
        "claim_seconds": 60,
        # weight, reward. A reward is {"emeralds": n} or {"ingot": material, "amount": n}
        # or {"block": type, "amount": n} or {"lapis": n} or {"book": true} (random book).
        "table": [
            {"weight": 40, "title": "An emerald pouch", "reward": {"emeralds": 50}},
            {"weight": 25, "title": "An iron vein", "reward": {"ingot": "iron", "amount": 3}},
            {"weight": 15, "title": "A bedrock cluster", "reward": {"block": "bedrock", "amount": 10}},
            {"weight": 12, "title": "A diamond vein", "reward": {"ingot": "diamond", "amount": 2}},
            {"weight": 8, "title": "Ancient debris", "reward": {"ingot": "netherite", "amount": 1}},
            {"weight": 12, "title": "A lapis vein", "reward": {"lapis": 4}},
            {"weight": 10, "title": "An enchanted book", "reward": {"book": True}},
        ],
    },
    "boss": {
        "auto_spawn_hours": 0,  # 0 = staff spawns bosses with /boss_spawn
        "duration_hours": 24,
        "hp": 1000,
        "attack_cooldown_seconds": 60,
        "damage_variance": 0.25,
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
        "create_cost": 0,
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
    "backups": {"hour": 4, "keep": 7},  # daily database copy at 04:00, 7 kept
    "challenges": {"per_week": 3},
}


_current: dict[str, Any] = copy.deepcopy(DEFAULTS)


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
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
