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
        # These are the overworld's; the other dimensions have theirs in "dimensions".
        "odds_6_blocks": {"dirt": 50, "cobblestone": 50, "gravel": 0, "deepslate": 0, "obsidian": 0, "bedrock": 0},
        "odds_4_5_blocks": {"dirt": 20, "cobblestone": 50, "gravel": 30, "deepslate": 0, "obsidian": 0, "bedrock": 0},
        "odds_2_3_blocks": {"dirt": 0, "cobblestone": 70, "gravel": 20, "deepslate": 10, "obsidian": 0, "bedrock": 0},
        "odds_1_block": {"dirt": 0, "cobblestone": 70, "gravel": 20, "deepslate": 9, "obsidian": 3, "bedrock": 1},
    },
    # Each dimension's blocks pay more: about 5.2 emeralds a message in the overworld (no gear), x1.25 in the
    # Nether, x1.5 in the End, x1.75 in the Deep Dark and x2 in the Shimmer.
    "block_values": {
        "dirt": 1, "cobblestone": 1, "gravel": 3, "deepslate": 5, "obsidian": 7, "bedrock": 10,
        "netherrack": 1, "blackstone": 4, "nether_bricks": 11, "gilded_blackstone": 18,
        "end_stone": 1, "end_bricks": 4, "purpur": 24,
        "sculk": 2, "sculk_shrieker": 5,
        "shimmer_stone": 3,
    },
    # Dimensions (game/dimensions.py): each has its mining channels and blocks. The odds work like the
    # overworld's (mining.odds_*); the Shimmer has a single block.
    "dimensions": {
        # Netherite scrap: the chance a mining reward in the Nether or beyond finds Ancient debris (one scrap).
        # A full netherite set takes 9 ingots = 36 scraps: 1.2% ≈ a month at ~100 mining rewards a day.
        "scrap_chance": 0.012,
        "scraps_per_ingot": 4,
        "gold_per_ingot": 4,
        # Tool bonuses (pickaxe, shovel) are worth their overworld value times this, given in the dimension's
        # blocks. Calibrated so that with tools too (gold to netherite) each dimension pays x1.25 / x1.5 / x1.75 /
        # x2 the overworld: the pickaxe's block upgrade is worth more in some dimensions than in others.
        "multipliers": {"nether": 1.06, "end": 1.18, "deep_dark": 1.41, "shimmer": 2.57},
        "nether": {
            "odds_6_blocks": {"netherrack": 100, "blackstone": 0, "nether_bricks": 0, "gilded_blackstone": 0},
            "odds_4_5_blocks": {"netherrack": 70, "blackstone": 30, "nether_bricks": 0, "gilded_blackstone": 0},
            "odds_2_3_blocks": {"netherrack": 70, "blackstone": 20, "nether_bricks": 10, "gilded_blackstone": 0},
            "odds_1_block": {"netherrack": 70, "blackstone": 20, "nether_bricks": 9, "gilded_blackstone": 4},
        },
        "end": {
            "odds_6_blocks": {"end_stone": 100, "end_bricks": 0, "purpur": 0},
            "odds_4_5_blocks": {"end_stone": 70, "end_bricks": 30, "purpur": 0},
            "odds_2_3_blocks": {"end_stone": 70, "end_bricks": 20, "purpur": 10},
            "odds_1_block": {"end_stone": 70, "end_bricks": 20, "purpur": 13},
        },
        "deep_dark": {
            "odds_6_blocks": {"sculk": 100, "sculk_shrieker": 0},
            "odds_4_5_blocks": {"sculk": 70, "sculk_shrieker": 30},
            "odds_2_3_blocks": {"sculk": 70, "sculk_shrieker": 30},
            "odds_1_block": {"sculk": 70, "sculk_shrieker": 33},
        },
    },
    "market": {
        "stick_pack": {"amount": 4, "price": 1},
        # Netherite isn't sold (it's mined in the Nether): its price is only its value (rewind refunds, fair prices).
        "ingots": {"gold": 5, "iron": 10, "diamond": 60, "netherite": 300},
        "gear_sell_rate": 0.8,  # /sell gear: this share of its value (craft + books), times its durability left
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
        # /talent_reset: every spent point back for reset_cost_per_point emeralds a point (never under reset_cost_min).
        "reset_cost_per_point": 50, "reset_cost_min": 100,
    },
    # XP to go from a level to the next: xp_first_level at level 1, then xp_growth_per_level times more each level
    # (1.05 = +5% a level: level 10 needs 155, level 50 needs 1,092, level 100 needs 12,524).
    "levels": {"xp_first_level": 100, "xp_growth_per_level": 1.05},
    "gear": {
        "tier": {"gold": 1, "iron": 2, "diamond": 3, "netherite": 4},
        "durability": {"gold": 60, "iron": 250, "diamond": 800, "netherite": 1500},
        # Armor pieces get this share of their material's durability, in Minecraft's proportions (11, 16, 15 and
        # 13 sixteenths): the chestplate lasts the longest, the helmet the least. Tools: all of it.
        "armor_durability_share": {"helmet": 0.6875, "chestplate": 1.0, "leggings": 0.9375, "boots": 0.8125},
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
        # Maximum damage of a hit (duels, gate bosses, tournament): a better sword raises the maximum.
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
        "level2_multiplier": 2,  # reinforced potions (II, sold by the villager): effect x2...
        "strong_per_fight": 1,  # ...and only this many per duel or dungeon run
        # Random potions (drops, the villager's goods): how often each kind comes (0 = never).
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
            {"weight": 12, "title": "A lapis vein", "reward": {"lapis": 4}},
            {"weight": 10, "title": "An enchanted book", "reward": {"book": True}},
            {"weight": 12, "title": "A witch's stash", "reward": {"potions": 2}},
        ],
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
        # Levels I to VII. Random books are I to III; IV to VII are only made by combining two books, and only
        # in a dimension that allows them (max level = 3 + the dimension: Nether IV … Shimmer VII). Beyond III each
        # level adds half of what the level before added.
        "apply_cost": [2, 4, 8, 16, 32, 64, 128],  # lapis to apply a book of level I … VII
        "book_weights": [60, 30, 10],  # chances of level I / II / III (drops, challenges)
        "boss_book_weights": [0, 70, 30],  # the book of each survivor of a gate boss
        "challenges_book": True,  # a random book for completing every weekly challenge
        # Effects for level I / II / III.
        "efficiency_seconds": [2.0, 4.0, 6.0, 7.0, 7.5, 7.75, 7.875],  # pickaxe: shorter mining cooldown
        "fortune_bonus": [1.0, 2.0, 3.0, 3.5, 3.75, 3.875, 3.9375],  # pickaxe blocks, shovel gravel, axe sticks
        "fortune_hoe_xp": [0.05, 0.10, 0.15, 0.175, 0.1875, 0.19375, 0.196875],
        "unbreaking_chance": [0.25, 0.40, 0.50, 0.55, 0.575, 0.5875, 0.59375],  # chance a use costs no durability
        "sharpness_damage": [1.0, 2.0, 3.0, 3.5, 3.75, 3.875, 3.9375],
        "looting_boss_bonus": [0.10, 0.20, 0.30, 0.35, 0.375, 0.3875, 0.39375],  # gate bosses' bounty
        # Armor points per piece. From IV on, Protection raises the cap of the damage reduction instead
        # (gear.max_damage_reduction) by protection_cap_bonus per piece: the points are already capped there.
        "protection_points": [1.0, 2.0, 3.0, 3.0, 3.0, 3.0, 3.0],
        "protection_cap_bonus": [0.0, 0.0, 0.0, 0.01, 0.02, 0.03, 0.04],
        # Mending (one level, any gear): the XP a player gains repairs their equipped Mending pieces first,
        # this much durability per XP; only the XP left goes to the player.
        "mending_durability_per_xp": 2,
        "mending_value": 600,  # the most valuable book (fortune, fair prices, the villager's price)
        "boss_mending_chance": 0.05,  # a gate boss survivor's book is Mending this often
        # Reference values in emeralds (fortune, fair auction prices).
        "lapis_value": 10,
        "book_values": [50, 150, 400, 800, 1600, 3200, 6400],
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
        # No robbery can start from night_start_hour to night_end_hour (local time): nobody robs sleeping
        # players. The same hour twice = robberies all day.
        "night_start_hour": 22,
        "night_end_hour": 6,
    },
    # Timed events (/event start, and one random event a day): a bonus for everyone for a while.
    "live_events": {
        "daily_random": True,  # one event comes by itself every day
        "earliest_hour": 10,  # it starts at a random time from this hour (local time)…
        "latest_hour": 22,  # …to this one
        "duration_minutes": 60,
        # The events that can come by themselves (the staff can start any of them).
        "random_kinds": {"gambling_frenzy": True, "mining_rush": True, "golden_hour": True, "lucky_hour": True,
                         "market_sale": True},
        "frenzy_multiplier": 2.0,  # Gambling Frenzy: the maximum bet and the daily cap of games of chance
        "rush_xp_multiplier": 2.0,  # Mining Rush: mining XP
        "golden_sell_bonus": 0.5,  # Golden Hour: /sell pays this much more for blocks
        "lucky_rare_multiplier": 2.0,  # Lucky Hour: weight of obsidian and bedrock when mining
        "market_sale_discount": 0.25,  # Market Sale: /market costs this much less
    },
    # PVE dungeon (/pve): 5 waves, alone or in a group. Health isn't restored between waves; the loot of
    # every wave cleared adds up but is lost on death. Monsters' health and damage: x strength of the
    # difficulty, +wave_growth every wave. Wave rewards (emeralds, waves 1 to 5) are multiplied by the
    # difficulty's reward; clearing wave 5 adds clear_bonus.
    "pve": {
        "hp": 20,
        "max_players": 5,
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
        # Hard ~80% netherite; Hardcore ~80% enchanted netherite. Nightmare is a raid: its monsters are much
        # stronger but each extra player adds fewer of them (its own group_monsters), so a group of 5 in
        # diamond with Protection III and Sharpness III clears it ~35% of the time (4 players or fewer ~0-2%,
        # 5 in the same netherite gear ~68%).
        "difficulties": {
            "easy": {"entry": 30, "strength": 0.85, "reward": 1.0},
            "normal": {"entry": 75, "strength": 1.0, "reward": 2.5},
            "hard": {"entry": 200, "strength": 1.13, "reward": 6.0},
            "hardcore": {"entry": 500, "strength": 1.26, "reward": 14.0},
            "nightmare": {"entry": 1200, "strength": 2.64, "reward": 32.0, "group_monsters": 0.5},
        },
    },
    # Gate bosses (/boss, game/gate.py): the Wither opens the End, the Ender Dragon the Deep Dark, the Warden the
    # Shimmer. A group of 1 to max_players, turn by turn. A boss has the same health whatever the group (it's
    # made for 4), and its hits are reduced by armor like in duels. Calibrated: 4 players in the best gear of the
    # boss's dimension (netherite, Sharpness and Protection IV for the Wither, V for the Dragon, VI for the
    # Warden), a shield and 2 healing potions each (drunk under 8 health), win ~35% of the time. Unprepared
    # (no shield or no potion), they rarely win.
    "gate_bosses": {
        "hp": 20,  # each player's health
        "max_players": 4,
        "lobby_minutes": 5,  # a group not started by then is cancelled (entries refunded)
        "turn_seconds": 30,  # time to play a turn, then the bot attacks for the player
        "afk_turns": 2,  # turns missed in a row before the player's turns play by themselves
        "cooldown_hours": 12,  # between two fights of a player
        "max_rounds": 60,  # the boss's turns: then it wins
        "min_hit_after_armor": 0.5,
        "crit_chance": 0.0,  # the bosses' critical hits (0 = none)
        "crit_multiplier": 2.0,
        "max_potions": 2,  # per player and per fight (reinforced II ones: potions.strong_per_fight)
        "repeat_reward": 0.25,  # share of the bounty for a boss the player had already beaten
        # small_group_hp: a smaller group of 1, 2 or 3 faces this share of the boss's health (a prepared group
        # then wins ~4%, ~8% and ~15% of the time).
        "wither": {"entry": 1500, "boss_hp": 400.0, "min_damage": 3.1, "max_damage": 7.1,
                   "wither_damage": 1.0, "wither_turns": 2, "bounty": 3000, "xp": 300,
                   "small_group_hp": [0.34, 0.59, 0.82]},
        "ender_dragon": {"entry": 3000, "boss_hp": 440.0, "min_damage": 9.85, "max_damage": 22.2, "strikes": 2,
                         "breath_every": 3, "breath_min": 3.7, "breath_max": 7.4, "bounty": 6000, "xp": 500,
                         "small_group_hp": [0.15, 0.36, 0.66]},
        "warden": {"entry": 6000, "boss_hp": 480.0, "min_damage": 18.1, "max_damage": 36.2,
                   "boom_every": 4, "boom_min": 15.0, "boom_max": 24.1, "bounty": 12000, "xp": 800,
                   "small_group_hp": [0.14, 0.38, 0.69]},
    },
    # The server's Beacon (/beacon, game/beacon.py): lit by the first Wither victory, then built by everyone. A
    # pyramid of 4 levels (level_ingots each), first all in gold, then each level in iron, diamond and netherite.
    # Each level gives its effects to everyone, times the multiplier of its material.
    "beacon": {
        "level_ingots": [81, 225, 441, 729],  # 9, 25, 49 and 81 blocks of 9 ingots
        "multipliers": {"gold": 1.0, "iron": 1.5, "diamond": 2.0, "netherite": 3.0},
        # Effects of each level in gold. Level 1: haste (mining cooldown) and mining XP; 2: /sell of blocks;
        # 3: strength (damage) and 4: resistance (damage taken) in the dungeon and against the gate bosses. Combat
        # is calibrated: a beacon fully in netherite takes a prepared group from ~35% to ~45-60% against a boss.
        "haste": 0.05, "xp": 0.05, "sell": 0.05, "strength": 0.015, "resistance": 0.015,
        # Every week the Beacon needs this share of its last step (in that material, rounded up to whole blocks):
        # not given by Monday, that step is undone.
        "upkeep": 0.05,
        # A player who gave at least contributor_value emeralds' worth this week: mining XP and /sell bonus too.
        "contributor_value": 200, "contributor_xp": 0.05, "contributor_sell": 0.05,
    },
    # Gang wars (game/war.py): every week all teams of at least min_members fight each other for points. Each
    # Monday `levy` of every team chest goes into the week's pot; the top teams share it (prizes) after `tax`.
    "war": {
        "min_members": 2,
        "levy": 0.05,
        "tax": 0.10,
        "prizes": [0.5, 0.3, 0.2],
        "points": {"duel": 1, "rob": 2, "rob_stopped": 1, "raid": 5, "raid_defended": 3},
        "duel_pair_cap": 3,  # duel wins a day of one player over the same enemy that score
        # Raids on a team's chest: min_attackers to max_attackers members gather (gather_minutes), then the
        # target's members have defend_minutes to come and defend; then the fight. Won (or nobody defended):
        # the attackers take raid_steal of the chest (raid_steal_max at most) into their own chest.
        "raid_min_attackers": 2,
        "raid_max_attackers": 4,
        "raid_max_defenders": 4,
        "raid_gather_minutes": 5,
        "raid_defend_minutes": 30,
        "raid_steal": 0.15,
        "raid_steal_max": 5000,
        "raids_per_day": 1,  # raids a team can launch a day
        "raid_protection_hours": 24,  # a raided chest is safe for this long
        "raid_max_rounds": 40,
    },
    # Bounties (/bounty): fixed tiers that add up on the same head, claimed by beating the target in a duel,
    # a /rob or a raid. Unclaimed after `days`, the payer gets it back minus refund_tax.
    "bounty": {
        "tiers": [250, 500, 1000, 2500],
        "min_level": 10,  # for the payer and the target
        "days": 7,
        "refund_tax": 0.10,
        "protection_hours": 24,  # no new bounty on a player this long after one was claimed
    },
    # Profile customization (/customize) and team banners (/team banner).
    "profiles": {
        "bio_max": 150,
        "color_price": 150,  # each dye color, bought once
        "hex_price": 750,  # unlocks any #hex color, once
        "banner_cost": 100,  # each change of a team banner (paid by the leader)
        # Frames sold for emeralds (the others are earned, see game/profiles.py).
        "frame_prices": {"stone": 100, "gold": 250, "redstone": 400, "lapis": 500, "diamond": 1000, "emerald": 1500},
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
        "dwarf_damage": 0.05,  # damage in every fight (duels, tournaments, gate bosses, dungeon, dummy)
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
        # Blackjack (/blackjack) and mines (/mines) share the bets and the daily cap. A game with no move for
        # move_minutes ends by itself (blackjack: you stand; mines: you cash out, or get the bet back if you
        # dug nothing).
        "move_minutes": 3,
        "blackjack_enabled": True,
        "blackjack_natural_payout": 1.5,  # a blackjack (21 with the first two cards) pays 3:2
        "blackjack_dealer_stands": 17,  # the dealer draws until this total
        "mines_enabled": True,
        "mines_return": 0.95,  # what a cash out pays compared to a fair game (0.95 = the bank keeps 5%)
        "mines_tnt_max": 10,  # TNT a player may hide in the 20 blocks (at least 1)
        "mines_max_multiplier": 25.0,  # the game cashes out by itself at this many times the bet
        # Lucky Block (/luckyblock): how often each thing falls out (weights) and what it pays (times the bet,
        # the bet included). Each step is rarer than the one before, from the creeper to netherite (1 in 500,
        # x10 at most). The defaults give back about 95% of the bets on average.
        "lucky_block": {
            # Gives back 95% of the bets on average; 28.5% of the blocks pay more than the bet.
            "creeper": {"weight": 315, "payout": 0.0},
            "cobblestone": {"weight": 220, "payout": 0.5},
            "iron": {"weight": 180, "payout": 1.0},
            "gold": {"weight": 150, "payout": 1.5},
            "diamond": {"weight": 90, "payout": 2.5},
            "emerald": {"weight": 40, "payout": 4.0},
            "netherite": {"weight": 5, "payout": 10.0},
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
        "per_day": 3,
        # The pool the weekly challenges are picked from: what to reach, and the emeralds it pays. A week never
        # has the same challenges as the week before (when there are enough others).
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
            "lucky_blocks": {"target": 25, "reward": 150},
            "wheel_spins": {"target": 25, "reward": 150},
            "blockdle": {"target": 4, "reward": 150},
            "quiz": {"target": 3, "reward": 150},
            "pve_waves": {"target": 15, "reward": 150},
            "dummy": {"target": 10, "reward": 100},
            "robs": {"target": 3, "reward": 150},
        },
        # The pool of the daily challenges (small ones), never the same as the day before.
        "daily_goals": {
            "mine_blocks": {"target": 150, "reward": 30},
            "find_bedrock": {"target": 1, "reward": 40},
            "sell_blocks": {"target": 200, "reward": 30},
            "win_duels": {"target": 1, "reward": 40},
            "lucky_blocks": {"target": 5, "reward": 30},
            "wheel_spins": {"target": 5, "reward": 30},
            "blockdle": {"target": 1, "reward": 40},
            "quiz": {"target": 1, "reward": 40},
            "pve_waves": {"target": 3, "reward": 40},
            "dummy": {"target": 3, "reward": 25},
            "robs": {"target": 1, "reward": 50},
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
        "lucky_100": {"goal": 100, "reward": 200},
        "wheel_100": {"goal": 100, "reward": 200},
        "bullseye": {"reward": 100},
        "blockdle_10": {"goal": 10, "reward": 150},
        "quiz_10": {"goal": 10, "reward": 150},
        "thief_10": {"goal": 10, "reward": 200},
        "watch_5": {"goal": 5, "reward": 150},
        "dungeon_hard": {"reward": 300},
        "dungeon_hardcore": {"reward": 500},
        "dungeon_nightmare": {"reward": 1000},
        "challenger_10": {"goal": 10, "reward": 150},
        "challenger_50": {"goal": 50, "reward": 500},
        "high_roller": {"reward": 50},
        "enchanter_10": {"goal": 10, "reward": 150},
        "handyman_10": {"goal": 10, "reward": 100},
        "regular_20": {"goal": 20, "reward": 200},
        "moneylender": {"goal": 10000, "reward": 200},
        "wither_slayer": {"reward": 1000},
        "dragon_slayer": {"reward": 2000},
        "warden_slayer": {"reward": 4000},
        "beacon_builder": {"goal": 5000, "reward": 500},
        "warlord": {"reward": 1000},
        "raider_5": {"goal": 5, "reward": 300},
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
# Lists that grew in an update (enchantments: levels I-III, then I-VII): an older, shorter override keeps its
# values and gets the defaults for the rest.
_GROWN = {("enchants", k) for k in ("apply_cost", "efficiency_seconds", "fortune_bonus", "fortune_hoe_xp",
                                     "unbreaking_chance", "sharpness_damage", "looting_boss_bonus",
                                     "protection_points", "book_values")}
# Lists that can have any length (the others have one value per level and keep their length).
_FREE_LENGTH = {
    ("seasons", "rewards"), ("teams", "season_rewards"),
    ("drops", "table"), ("villager", "goods"),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(default: Any, value: Any, path: tuple[str, ...], problems: list[str]) -> Any:
    """Validate `value` against the shape of `default`. Returns the cleaned value (or _INVALID)."""
    name = "balance" + "".join(f".{p}" for p in path)
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
        if path in _GROWN and 0 < len(value) < len(default):
            value = list(value) + list(default[len(value):])
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

    if merged["daily"]["weekly_bonus_item"] not in ("gold", "iron", "diamond"):
        out.append(("`balance.daily.weekly_bonus_item` must be gold, iron or diamond (netherite is only found in the "
                    "Nether).", [("daily", "weekly_bonus_item")]))

    r = merged["rob"]
    for mode in ("risky", "discreet"):
        if r[f"{mode}_min"] > r[f"{mode}_max"]:
            out.append((f"`balance.rob.{mode}_min` must not be above `{mode}_max`.", [("rob", f"{mode}_min"), ("rob", f"{mode}_max")]))
    if r["night_start_hour"] > 23 or r["night_end_hour"] > 23:
        out.append(("`balance.rob.night_start_hour` and `night_end_hour` are hours: 0 to 23.",
                    [("rob", "night_start_hour"), ("rob", "night_end_hour")]))
    for slot, share in merged["gear"]["armor_durability_share"].items():
        if not 0 < float(share) <= 1:
            out.append((f"`balance.gear.armor_durability_share.{slot}` goes from 1% to 100%.",
                        [("gear", "armor_durability_share", slot)]))
    le = merged["live_events"]
    if not 0 <= le["earliest_hour"] < le["latest_hour"] <= 23:
        out.append(("Timed events: the random event starts between `earliest_hour` and `latest_hour`: hours from 0 "
                    "to 23, the first one before the second.",
                    [("live_events", "earliest_hour"), ("live_events", "latest_hour")]))
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
        for dim, odds in merged["dimensions"].items():
            if isinstance(odds, dict) and pile in odds and sum(float(w) for w in odds[pile].values()) <= 0:
                out.append((f"`balance.dimensions.{dim}.{pile}`: at least one block needs a weight above 0.",
                            [("dimensions", dim, pile)]))
    w = merged["war"]
    if sum(float(x) for x in w["prizes"]) > 1:
        out.append(("`balance.war.prizes`: the podium can't share more than the whole pot.", [("war", "prizes")]))
    if int(w["raid_min_attackers"]) > int(w["raid_max_attackers"]):
        out.append(("`balance.war`: a raid's minimum attackers can't be above its maximum.",
                    [("war", "raid_min_attackers"), ("war", "raid_max_attackers")]))
    if any(int(t) <= 0 for t in merged["bounty"]["tiers"]):
        out.append(("`balance.bounty.tiers`: each tier is at least 1 emerald.", [("bounty", "tiers")]))
    if any(int(n) <= 0 or int(n) % 9 for n in merged["beacon"]["level_ingots"]):
        out.append(("`balance.beacon.level_ingots`: each level is whole blocks, a multiple of 9 ingots.",
                    [("beacon", "level_ingots")]))
    d = merged["dimensions"]
    if int(d["scraps_per_ingot"]) < 1:
        out.append(("`balance.dimensions.scraps_per_ingot` must be 1 or more.", [("dimensions", "scraps_per_ingot")]))
    if not 1 <= float(merged["levels"]["xp_growth_per_level"]) <= 2:
        out.append(("`balance.levels.xp_growth_per_level` goes from 1 (the same every level) to 2.",
                    [("levels", "xp_growth_per_level")]))
    if merged["levels"]["xp_first_level"] < 1:
        out.append(("`balance.levels.xp_first_level` must be at least 1.", [("levels", "xp_first_level")]))
    for pool in ("goals", "daily_goals"):
        for code, goal in merged["challenges"][pool].items():
            if goal["target"] < 1:
                out.append((f"`balance.challenges.{pool}.{code}.target` must be at least 1.",
                            [("challenges", pool, code, "target")]))
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
        if reward.get("ingot") == "netherite":
            out.append(("`balance.drops.table`: netherite is only found in the Nether, not in drops.", [("drops", "table")]))
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
        return (isinstance(asset, str) and assets.parse(asset)[0] not in ("emeralds", "gear")
                and assets.tradeable(asset))
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
