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
        # bonus block on big piles (miner_bonus_min_pile blocks or more).
        "miner_gravel_4_5": 5, "miner_gravel_4_5_max": 40,
        "miner_gravel_2_3": 3, "miner_gravel_2_3_max": 30,
        "miner_deepslate_2_3": 2, "miner_deepslate_2_3_max": 30,
        "miner_bonus_block_chance": 0.05, "miner_bonus_block_max": 0.25,
        "miner_bonus_min_pile": 4,  # the bonus block only comes on piles of at least this many blocks (1-6)
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
        # Shield (iron only, /craft), duels only: "Attack + block" blocks the opponent's next attack,
        # up to shield_blocks_per_fight times per duel. Each block uses shield_wear_per_block durability;
        # at 0 it stays, unusable until /repair.
        "shield_blocks_per_fight": 2,
        "shield_durability": 100,
        "shield_wear_per_block": 10,
    },
    # /repair, on an anvil (crafted with anvil_iron iron ingots), with ingots of the piece's material:
    # one ingot gives back durability_per_ingot of its durability, divided by (1 + penalty_per_repair x the
    # repairs it already had): 4 ingots for a first full repair, then 5, 6, 7… Each use of the
    # anvil (repair, combining books) has anvil_damage_chance to wear it: new → chipped → damaged → broken.
    "repair": {
        "durability_per_ingot": 0.25,
        "penalty_per_repair": 0.25,
        "anvil_iron": 22,
        "anvil_damage_chance": 0.12,
    },
    "daily": {
        "base_reward": 30,
        "streak_bonus_per_day": 10,
        "streak_cap_days": 7,
        "weekly_bonus_item": "diamond",  # ingot given every bonus_every_days consecutive days
        "bonus_every_days": 7,
        "xp": 25,
    },
    "pay": {"min_amount": 1},
    "trade": {"offer_minutes": 5},  # a /trade proposal waits this long for an answer
    "auction": {"tax_percent": 5, "max_listings": 10, "duration_days": 7},
    "duel": {
        "min_stake": 10,
        "hp": 20,
        # A hit deals between min_damage and the sword's maximum (gear.sword_max_damage).
        "min_damage": 1,
        "min_hit_after_armor": 0.5,  # armor never lowers a hit below this
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
        "boss_top": 3,  # the top 3 damage dealers of a defeated boss get boss_potions random potions
        "boss_potions": 1,
        "level2_multiplier": 2,  # reinforced potions (II, sold by the villager): effect x2...
        "strong_per_fight": 1,  # ...and only this many per duel or dungeon run
        # Random potions (drops, bosses, the villager's goods): how often each kind comes (0 = never).
        "random_weights": {"strength": 1, "speed": 1, "healing": 1, "harming": 1},
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
        "space_cost": 1000,  # unlocking the team's private category (/team category)
        "max_channels": 5,  # channels in a team category
        # Team score = the best earner in full, then less and less for the others
        # (n members earning the same: ×(1 + ln n), so 5 members ≈ ×2.6, not ×5). False = the sum.
        "log_score": True,
    },
    "enchants": {
        # Lapis lazuli: found while mining, spent to apply books.
        "lapis_chance": 0.025,  # per mining reward (1 in 40)
        "lapis_amount": [1, 2],
        "apply_cost": [2, 4, 8],  # lapis to apply a book of level I / II / III
        "book_weights": [60, 30, 10],  # chances of level I / II / III (drops, challenges)
        "boss_book_weights": [0, 70, 30],  # book of the top damage dealers (boss_book_top)
        "boss_book_top": 1,
        "challenges_book": True,  # a random book for completing every weekly challenge
        # Effects for level I / II / III.
        "efficiency_seconds": [2, 4, 6],  # pickaxe: shorter mining cooldown
        "fortune_bonus": [1, 2, 3],  # pickaxe blocks, shovel gravel, axe sticks
        "fortune_hoe_xp": [0.05, 0.10, 0.15],
        "unbreaking_chance": [0.25, 0.40, 0.50],  # chance a use costs no durability
        "sharpness_damage": [1, 2, 3],
        "looting_boss_bonus": [0.10, 0.20, 0.30],
        "protection_points": [1, 2, 3],  # armor points per piece
        # Mending (one level, any gear): the XP a player gains repairs their equipped Mending pieces first,
        # this much durability per XP; only the XP left goes to the player.
        "mending_durability_per_xp": 2,
        "mending_value": 600,  # the most valuable book (fortune, fair prices, the villager's price)
        "boss_mending_chance": 0.05,  # the top damage dealer's book is Mending this often
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
        # Exclusive offer: a level III book (exclusive_book_chance) or else a reinforced potion (II).
        "book_iii_price": 450,
        "potion_ii_price": 120,
        "exclusive_book_chance": 0.5,
        "exclusive_mending_chance": 0.1,  # ...but first, this often, the exclusive offer is a Mending book
        "mending_price": 600,
        # A "book" in his goods: weights of a level I and a level II book.
        "book_weights": [70, 30],
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
    # /rob: the victim has minutes_to_stop minutes to stop the thief, else the thief takes the loot.
    "rob": {
        "risky_min": 200, "risky_max": 500,  # risky: the victim is pinged, big loot
        "discreet_min": 50, "discreet_max": 100,  # discreet: no ping, small loot
        "minutes_to_stop": 60,
        "fine_percent": 10,  # stopped in time: the thief pays the victim this % of the loot he aimed at
        "cooldown_hours": 6,  # between two robberies of a thief
        "victim_protection_hours": 12,  # a robbed player can't be robbed again for this long
        "min_victim_level": 5,  # players below this level can't be robbed
    },
    # PVE dungeon (/pve): 5 waves, alone or in a group. Health isn't restored between waves; the loot of
    # every wave cleared adds up but is lost on death. Monsters' health and damage: x strength of the
    # difficulty, +wave_growth every wave. Wave rewards (emeralds, waves 1 to 5) are multiplied by the
    # difficulty's reward; clearing wave 5 adds clear_bonus.
    "pve": {
        "hp": 20,
        "max_players": 4,
        "cooldown_minutes": 60,
        "lobby_minutes": 5,  # a group not started by then is cancelled (entries refunded)
        "decision_minutes": 5,  # between waves: no decision by then = everyone leaves with their loot
        "max_potions": 3,  # per player and per run (reinforced II ones: potions.strong_per_fight)
        "wave_growth": 0.10,
        # Each extra player in the group adds this share of every wave's monsters (1 = a whole wave more).
        "group_monsters": 1.0,
        "min_hit_after_armor": 0.1,  # armor never lowers a monster's hit below this
        # Health and damage of each monster at strength 1 (Normal); difficulty and wave_growth multiply them.
        "monsters": {
            "zombie": {"hp": 3.2, "min_damage": 0.18, "max_damage": 0.59},
            "skeleton": {"hp": 2.6, "min_damage": 0.18, "max_damage": 0.59},
            "spider": {"hp": 2.6, "min_damage": 0.14, "max_damage": 0.36},
            "creeper": {"hp": 2.6, "min_damage": 1.3, "max_damage": 2.1},
            "ravager": {"hp": 8.5, "min_damage": 0.36, "max_damage": 0.95},
        },
        "clear_bonus": 0.5,
        "xp_per_wave": 15,
        "wave_rewards": [5, 8, 12, 18, 27],
        # Calibrated (solo, no potions, all 5 waves): Easy ~98% with iron gear; Normal ~90% diamond;
        # Hard ~80% netherite; Hardcore ~80% enchanted netherite; Nightmare ~35% enchanted netherite.
        "difficulties": {
            "easy": {"entry": 30, "strength": 0.85, "reward": 1.0},
            "normal": {"entry": 75, "strength": 1.0, "reward": 2.5},
            "hard": {"entry": 200, "strength": 1.13, "reward": 6.0},
            "hardcore": {"entry": 500, "strength": 1.26, "reward": 14.0},
            "nightmare": {"entry": 1200, "strength": 1.42, "reward": 32.0},
        },
    },
    # Profile customization (/customize) and team banners (/team banner).
    "profiles": {
        "bio_max": 150,
        "color_price": 300,  # each dye color, bought once
        "hex_price": 1500,  # unlocks any #hex color, once
        "banner_cost": 200,  # each change of a team banner (paid by the leader)
        # Frames sold for emeralds (the others are earned, see game/profiles.py).
        "frame_prices": {"stone": 200, "gold": 500, "redstone": 800, "lapis": 1000, "diamond": 2000, "emerald": 3000},
        # What it takes to earn the other frames and the titles (game/profiles.py says what is counted).
        "frame_goals": {"netherite": 1, "ender": 1, "nether": 25, "champion": 1},
        "title_goals": {
            "miner": 1000, "quarry_master": 50000, "bedrock_hunter": 100, "blacksmith": 50, "duelist": 25,
            "gladiator": 100, "boss_slayer": 10, "season_champion": 1, "arena_champion": 1, "team_champion": 1,
            "dungeon_crawler": 1, "nightmare_survivor": 1, "tycoon": 100000, "banker": 10000, "merchant": 50,
            "heavy_hitter": 150, "veteran": 50, "legend": 100,
        },
    },
    # The guide: a private channel for every new player (in channels.guide_category) with
    # a checklist of first steps. The reward is paid once per player, ever.
    "guide": {
        "reward": 200,
        "delete_after_days": 3,  # after the checklist is done (0 = kept)
        "expire_days": 30,  # if it is never done (0 = kept)
    },
    # Training dummy (/dummy): a damage tester (series of hits, with a leaderboard) and training duels.
    "dummy": {
        "hits": 10,
        "cooldown_seconds": 60,  # between two series of the damage tester
    },
    # Species (/species): a small bonus each. The first choice is free, then changing costs
    # change_cost emeralds, once every change_days days.
    "species": {
        "change_cost": 1000,
        "change_days": 7,
        "villager_trade": 0.05,  # /sell +5%, market and villager goods -5%, villager pays +5% for blocks
        "dwarf_damage": 0.05,  # damage in every fight (duels, tournaments, bosses, dungeon, dummy)
        "witch_potions": 0.10,  # potion effects in duels and the dungeon
        "mage_enchants": 0.10,  # enchantment effects
        "miner_speed": 0.05,  # mining cooldown
        "gambler_max_bet": 0.5,  # the maximum bet at the games of chance (Lucky Block, the wheel)
    },
    # Loans between players (/loan). The lender picks the interest and the duration within these limits.
    "loans": {
        "min_amount": 50,
        "max_amount": 5000,
        "max_interest": 0.20,  # highest interest a lender can ask
        "min_days": 1,
        "max_days": 7,
        "max_loans_out": 5,  # unpaid loans a lender can have at once
        "offer_minutes": 15,  # time to accept an offer
        # Late: this % of what's left is added, the bot takes what it can from the borrower's
        # emeralds, then this share of every emerald they receive until it's paid.
        "late_penalty": 0.10,
        "garnish": 0.50,
    },
    # Mini-games. They work in the channels of config.json channels.games (anywhere when there are none).
    "games": {
        # Games of chance (Lucky Block, the wheel): bets, waiting time, and what a player may win in a day
        # (winnings minus losses at these games; then they can't play before tomorrow, 0 = no cap).
        "min_bet": 1,
        "max_bet": 200,
        "cooldown_seconds": 5,  # between two games of a player
        "daily_win_cap": 1500,
        # Lucky Block (/luckyblock): how often each thing falls out (weights) and what it pays (times the bet,
        # the bet included). Each step is rarer than the one before, from the creeper to netherite (1 in 500,
        # x10 at most). The defaults give back about 84% of the bets on average.
        "lucky_block": {
            "creeper": {"weight": 270, "payout": 0.0},
            "cobblestone": {"weight": 250, "payout": 0.5},
            "iron": {"weight": 230, "payout": 1.0},
            "gold": {"weight": 180, "payout": 1.5},
            "diamond": {"weight": 50, "payout": 2.5},
            "emerald": {"weight": 18, "payout": 4.0},
            "netherite": {"weight": 2, "payout": 10.0},
        },
        "roulette_enabled": True,  # the wheel (/wheel), a Minecraft roulette
        # What players may bet on at the wheel: Redstone (red), Obsidian (black) and a number for now.
        "roulette_bets": {
            "red": True, "black": True, "green": False, "even": False, "odd": False, "low": False, "high": False,
            "dozens": False, "number": True,
        },
        # Diamond blocks (green slots) of the wheel: 1 (0 only, a European roulette) = the bank keeps 2.7% of the
        # bets on average, 2 (0 and 00, an American roulette) = 5.3%.
        "roulette_zeros": 1,
        # Blockdle: emeralds for finding the block of the day in 1, 2, 3… guesses (the last value for more guesses).
        "blockdle_rewards": [300, 250, 200, 160, 130, 100, 80, 60, 50, 40],
        "blockdle_xp": 50,
        "blockdle_no_repeat_days": 60,  # a block isn't the block of the day again before this many days
        "quiz_every_minutes": 60,  # a question in a games channel every X minutes (0 = only /event quiz)
        "quiz_every_jitter": 0.25,  # ...give or take 25%, so it isn't predictable
        "quiz_no_repeat": 40,  # the last 40 questions aren't asked again
        "quiz_seconds": 30,  # time to answer
        "quiz_reward": 50,
        "quiz_xp": 20,
    },
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

    r = merged["rob"]
    for mode in ("risky", "discreet"):
        if r[f"{mode}_min"] > r[f"{mode}_max"]:
            out.append((f"`balance.rob.{mode}_min` must not be above `{mode}_max`.", [("rob", f"{mode}_min"), ("rob", f"{mode}_max")]))
    if r["minutes_to_stop"] < 1:
        out.append(("`balance.rob.minutes_to_stop` must be at least 1.", [("rob", "minutes_to_stop")]))
    lo = merged["loans"]
    if lo["min_amount"] < 1 or lo["min_amount"] > lo["max_amount"]:
        out.append(("Loans: the minimum amount must be at least 1 and not above the maximum.",
                    [("loans", "min_amount"), ("loans", "max_amount")]))
    if lo["min_days"] < 1 or lo["min_days"] > lo["max_days"]:
        out.append(("Loans: the shortest duration must be at least 1 day and not above the longest.",
                    [("loans", "min_days"), ("loans", "max_days")]))
    g = merged["games"]
    if g["roulette_zeros"] not in (1, 2):
        out.append(("`balance.games.roulette_zeros` is 1 (0 only) or 2 (0 and 00).", [("games", "roulette_zeros")]))
    if g["min_bet"] < 1 or g["min_bet"] > g["max_bet"]:
        out.append(("Games: the minimum bet must be at least 1 and not above the maximum bet.",
                    [("games", "min_bet"), ("games", "max_bet")]))
    if g["quiz_seconds"] < 10 or g["quiz_seconds"] > 600:
        out.append(("`balance.games.quiz_seconds` goes from 10 to 600.", [("games", "quiz_seconds")]))
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

    # Weights picked at random: all at 0 would make the draw fail (a challenge reward, a boss, a block…).
    ench = merged["enchants"]
    for key in ("book_weights", "boss_book_weights"):
        if sum(float(w) for w in ench[key]) <= 0:
            out.append((f"`balance.enchants.{key}`: at least one level needs a weight above 0.", [("enchants", key)]))
    if float(merged["repair"]["durability_per_ingot"]) <= 0:
        out.append(("`balance.repair.durability_per_ingot` must be above 0.", [("repair", "durability_per_ingot")]))
    if sum(float(w) for w in merged["potions"]["random_weights"].values()) <= 0:
        out.append(("`balance.potions.random_weights`: at least one potion needs a weight above 0.",
                    [("potions", "random_weights", k) for k in merged["potions"]["random_weights"]]))
    for kind, monster in merged["pve"]["monsters"].items():
        if float(monster["min_damage"]) > float(monster["max_damage"]):
            out.append((f"`balance.pve.monsters.{kind}`: the smallest hit can't be above the biggest.",
                        [("pve", "monsters", kind, "min_damage"), ("pve", "monsters", kind, "max_damage")]))
    if sum(float(w) for w in merged["villager"]["book_weights"]) <= 0:
        out.append(("`balance.villager.book_weights`: at least one level needs a weight above 0.",
                    [("villager", "book_weights")]))
    if sum(float(o["weight"]) for o in g["lucky_block"].values()) <= 0:
        out.append(("`balance.games.lucky_block`: at least one outcome needs a weight above 0.",
                    [("games", "lucky_block", k, "weight") for k in g["lucky_block"]]))
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
