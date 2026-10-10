"""Settings staff can change from Discord with /config, and how config.json is rewritten.

Every game setting (game/settings.py) has a Field here: a readable label, an
explanation, how it is typed and its limits. Lists with one value per level are
split into one field per value. Secrets and dangerous keys (PROTECTED) can never
be read or written from Discord.
"""
from __future__ import annotations

import copy
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from game import settings
from game.catalog import ARMOR, BLOCK_TYPES, MATERIALS
from utils.config import balance_overrides

PROTECTED = (
    ("minecraft", "rcon_password"),
    ("staff", "role_id"),
    ("database_path",),
)

CATEGORIES = {
    "channels": "📢 Channels",
    "roles": "🎭 Roles",
    "level_roles": "🎖️ Level roles",
    "minecraft": "🌍 Minecraft texts",
    "server": "🕒 Time zone, backups & moderation",
    "mining": "⛏️ Mining & block values",
    "mining_odds": "🎲 Mining odds",
    "xp": "📈 XP & talents",
    "economy": "🛒 Market, daily & trading",
    "tools": "🛠️ Tools & durability",
    "combat_gear": "🗡️ Swords & armor",
    "duels": "⚔️ Duels",
    "potions": "🧪 Potions",
    "enchant_books": "📕 Enchanting: books & lapis",
    "enchant_effects": "✨ Enchanting: effects",
    "drops": "🎁 Drops",
    "bosses": "🐉 Bosses",
    "seasons": "🏆 Seasons & challenges",
    "achievements": "🏅 Achievements",
    "teams": "🛡️ Teams",
    "tournament": "🏟️ Tournament",
    "villager": "🧑‍🌾 Villager",
}

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ROMAN = ("I", "II", "III")
# Kinds typed in a text box. The others use pickers, buttons or editors.
TYPED = ("int", "float", "percent", "text", "timezone")


@dataclass(frozen=True)
class Field:
    key: str
    category: str
    label: str  # 45 characters at most (Discord modal titles)
    path: tuple  # path in config.json; an int is an index in a list
    kind: str  # channel | channels | role | text | int | float | percent | bool | choice | timezone | list | map | table
    min: float | None = None  # for percent: as a fraction (0.5 = 50%)
    max: float | None = None
    help: str = ""
    choices: tuple[tuple[str, Any], ...] = ()  # choice: (label, value)
    item: str = ""  # list: "int" or "text"; table: "drops" or "goods"
    max_items: int = 25  # list, map and table editors

    @property
    def is_balance(self) -> bool:
        return self.path[0] == "balance"

    @property
    def typed(self) -> bool:
        return self.kind in TYPED


def _path(dotted: str) -> tuple:
    return ("balance",) + tuple(int(p) if p.isdigit() else p for p in dotted.split("."))


def _b(dotted: str, category: str, label: str, help: str = "", kind: str = "int", min: float | None = 0,
       max: float | None = None, **extra: Any) -> Field:
    """A balance setting, keyed by its path in settings (e.g. "mining.cooldown_seconds")."""
    return Field(dotted, category, label, _path(dotted), kind, min, max, help, **extra)


def _per_level(dotted: str, category: str, label: str, help: str = "", kind: str = "int", **extra: Any) -> list[Field]:
    """One field per value of a list with a value for level I, II and III."""
    return [_b(f"{dotted}.{i}", category, f"{label} ({ROMAN[i]})", help, kind, **extra) for i in range(3)]


def _pct(dotted: str, category: str, label: str, help: str = "", max: float = 1.0) -> Field:
    return _b(dotted, category, label, help, "percent", 0, max)


WEIGHT_HELP = "Chances = this weight ÷ the total of the weights of the pile. 0 = never."
DAY_CHOICES = tuple((day, i) for i, day in enumerate(DAYS))
PILES = (("odds_6_blocks", "6 blocks"), ("odds_4_5_blocks", "4-5 blocks"), ("odds_2_3_blocks", "2-3 blocks"),
         ("odds_1_block", "1 block"))

# Achievements: (code, name). Those with a goal count something (blocks, levels…).
_ACHIEVEMENT_NAMES = {
    "first_bedrock": "Bedrock Breaker", "bedrock_100": "Bedrock Collector", "first_obsidian": "Into the Void",
    "miner_1k": "Miner", "miner_10k": "Excavator", "miner_50k": "Quarry Master", "first_craft": "First Craft",
    "blacksmith": "Blacksmith", "iron_set": "Suit Up", "diamond_set": "Diamonds!", "netherite_set": "Netherite Legend",
    "level_10": "Getting Started", "level_25": "Experienced", "level_50": "Veteran", "level_100": "Legend",
    "first_blood": "First Blood", "gladiator": "Gladiator", "streak_7": "Dedicated", "streak_30": "Unstoppable",
    "merchant": "Merchant", "auctioneer": "Auctioneer", "treasure_hunter": "Treasure Hunter",
    "boss_slayer": "Boss Slayer", "champion": "Champion", "arena_champion": "Arena Champion",
    "team_champion": "Squad Goals", "tycoon": "Emerald Tycoon", "wear_and_tear": "Wear and Tear",
}
_CHALLENGE_NAMES = {
    "mine_blocks": "Mine blocks", "find_bedrock": "Find bedrock", "sell_blocks": "Earn emeralds by selling",
    "craft_gear": "Craft gear", "win_duels": "Win duels", "claim_drops": "Claim drops",
    "boss_damage": "Damage bosses", "daily_rewards": "Claim the daily reward", "trades": "Complete trades",
}


def _achievement_fields() -> list[Field]:
    out = []
    for code, name in _ACHIEVEMENT_NAMES.items():
        if "goal" in settings.DEFAULTS["achievements"][code]:
            out.append(_b(f"achievements.{code}.goal", "achievements", f"{name}: goal", "What to reach (blocks, levels, wins…).", min=1))
        out.append(_b(f"achievements.{code}.reward", "achievements", f"{name}: reward", "Emeralds paid once, when it's unlocked."))
    return out


def _challenge_fields() -> list[Field]:
    out = []
    for code, name in _CHALLENGE_NAMES.items():
        out.append(_b(f"challenges.goals.{code}.target", "seasons", f"{name}: target", "What to reach during the week.", min=1))
        out.append(_b(f"challenges.goals.{code}.reward", "seasons", f"{name}: reward", "Emeralds paid when it's done."))
    return out


FIELDS: list[Field] = [
    # ---- channels, roles, texts ----
    Field("ch_announcements", "channels", "Announcements channel", ("channels", "announcements"), "channel",
          help="Level-ups, achievements, challenges, season and tournament results."),
    Field("ch_events", "channels", "Events channel", ("channels", "events"), "channel",
          help="Drops and bosses appear here (not set = where people chat)."),
    Field("ch_staff_log", "channels", "Staff channel", ("channels", "staff_log"), "channel",
          help="/link requests and the log of every staff action."),
    Field("ch_spam", "channels", "Spam channels", ("channels", "spam"), "channels",
          help="Messages there give no blocks, XP or drops, only a tiny reward (see Mining)."),
    Field("role_event_ping", "roles", "Role pinged for bosses", ("roles", "event_ping"), "role",
          help="Mentioned when a boss appears. Nobody else is pinged."),
    Field("role_champion", "roles", "Season champion role", ("roles", "season_champion"), "role",
          help="Given to the winner of the last weekly season."),
    Field("role_tournament", "roles", "Tournament champion role", ("roles", "tournament_champion"), "role",
          help="Given to the winner of the last weekend tournament."),
    Field("mc_ip_text", "minecraft", "/ip text", ("minecraft", "public_ip_text"), "text",
          help="What /ip shows to join the server."),
    Field("mc_modpack_text", "minecraft", "/modpacks text", ("minecraft", "modpack_text"), "text",
          help="What /modpacks shows. Links like [Name](https://…) work."),
    # ---- server ----
    _b("timezone", "server", "Time zone", "Daily reset, seasons, villager, tournament and backups follow it. "
       "E.g. Europe/Paris.", "timezone", None),
    _b("backups.hour", "server", "Nightly backup: hour", "Hour (0-23) of the daily copy of the database.", max=23),
    _b("backups.keep", "server", "Nightly backups kept", "How many nightly copies are kept.", min=1, max=365),
    _b("moderation.warn_expire_days", "server", "Warnings count for (days)",
       "After this many days a warning stops counting for automatic mutes (0 = forever).", max=3650),
    _b("moderation.warn_mutes", "server", "Automatic mutes", "How many active warnings mute a member, and for how long.",
       "map", None, max_items=10),
    # ---- mining ----
    _b("mining.cooldown_seconds", "mining", "Mining cooldown (seconds)", "Time between two mining rewards (0 = none).", max=3600),
    _b("mining.min_cooldown_seconds", "mining", "Shortest mining cooldown (seconds)",
       "The Efficiency talent and enchantment never go below this.", max=3600),
    _b("mining.xp_per_message.0", "mining", "XP per mining reward: minimum", max=10_000),
    _b("mining.xp_per_message.1", "mining", "XP per mining reward: maximum", max=10_000),
    _b("mining.spam_reward", "mining", "Spam channels: emeralds per reward",
       "Saved until it makes a whole emerald. 0.01 = 1 emerald every 100 rewards.", "float", max=100),
    *[_b(f"block_values.{b}", "mining", f"{b.capitalize()} value",
         "Emeralds per block with /sell. Also what the block is worth in the season score.") for b in BLOCK_TYPES],
    # ---- mining odds ----
    *[_b(f"mining.{pile}.{b}", "mining_odds", f"Pile of {size}: {b}", WEIGHT_HELP, max=100_000)
      for pile, size in PILES for b in BLOCK_TYPES],
    # ---- XP & talents ----
    _b("levels.xp_first_level", "xp", "XP from level 1 to 2", "XP needed to reach level 2.", min=1, max=1_000_000),
    _b("levels.xp_increase_per_level", "xp", "Extra XP needed per level",
       "Each level needs this much more XP than the previous one.", max=1_000_000),
    _b("talents.points_every_levels", "xp", "Levels per talent point", "A talent point every this many levels.", min=1, max=100),
    *[_b(f"talents.caps.{t}", "xp", f"{t.capitalize()} talent: max points", "Points beyond this can't be bought.", max=100)
      for t in ("miner", "trader", "lucky", "efficiency")],
    _pct("talents.trader_bonus_per_point", "xp", "Trader: /sell bonus per point"),
    _b("talents.efficiency_seconds_per_point", "xp", "Efficiency: seconds less per point", "Shorter mining cooldown.", max=3600),
    _b("talents.miner_gravel_4_5", "xp", "Miner: gravel weight/point (4-5)", "Added to gravel on piles of 4-5 blocks."),
    _b("talents.miner_gravel_4_5_max", "xp", "Miner: max gravel bonus (4-5)"),
    _b("talents.miner_gravel_2_3", "xp", "Miner: gravel weight/point (2-3)", "Added to gravel on piles of 2-3 blocks."),
    _b("talents.miner_gravel_2_3_max", "xp", "Miner: max gravel bonus (2-3)"),
    _b("talents.miner_deepslate_2_3", "xp", "Miner: deepslate weight/point (2-3)", "Added to deepslate on piles of 2-3 blocks."),
    _b("talents.miner_deepslate_2_3_max", "xp", "Miner: max deepslate bonus (2-3)"),
    _pct("talents.miner_bonus_block_chance", "xp", "Miner: bonus block chance/point", "One more block on piles of 4+."),
    _pct("talents.miner_bonus_block_max", "xp", "Miner: max bonus block chance"),
    _b("talents.lucky_rare_weight", "xp", "Lucky: rare block weight/point",
       "Added to obsidian and to bedrock on 1-block piles."),
    # ---- economy ----
    _b("market.stick_pack.price", "economy", "Sticks: price of a pack", min=1),
    _b("market.stick_pack.amount", "economy", "Sticks: sticks per pack", min=1),
    *[_b(f"market.ingots.{m}", "economy", f"{m.capitalize()} ingot price", "Price at /market. Also their value "
         "for /repair costs, fortunes and fair prices.", min=1) for m in MATERIALS],
    _b("repair.cost_percent", "economy", "/repair: cost (% of crafting value)",
       "For a piece with no durability left; less when it's only partly worn.", max=1000),
    _b("pay.min_amount", "economy", "/pay: minimum amount", min=1),
    _b("auction.tax_percent", "economy", "Auction tax (%)", "Taken from the seller's price.", max=100),
    _b("auction.max_listings", "economy", "Auction: listings per player", min=1, max=100),
    _b("auction.duration_days", "economy", "Auction: days before a listing ends", min=1, max=60),
    _b("daily.base_reward", "economy", "Daily: reward on day 1"),
    _b("daily.streak_bonus_per_day", "economy", "Daily: bonus per day in a row"),
    _b("daily.streak_cap_days", "economy", "Daily: days the streak grows", "The reward stops growing after this.", min=1, max=365),
    _b("daily.weekly_bonus_item", "economy", "Daily: ingot every 7th day", kind="choice", min=None,
       choices=tuple((m, m) for m in MATERIALS)),
    _b("daily.xp", "economy", "Daily: XP"),
    # ---- tools ----
    *[_b(f"gear.tier.{m}", "tools", f"{m.capitalize()} tier", "Tool bonuses are multiplied by the tier.", min=1, max=20)
      for m in MATERIALS],
    *[_b(f"gear.durability.{m}", "tools", f"{m.capitalize()} durability", "Uses before a piece breaks.", min=1, max=1_000_000)
      for m in MATERIALS],
    _b("gear.pickaxe_extra_blocks_per_tier", "tools", "Pickaxe: extra cobblestone per tier", max=100),
    _pct("gear.pickaxe_upgrade_chance_per_tier", "tools", "Pickaxe: upgrade chance per tier",
         "Chance that the mined block becomes the next rarer one."),
    _b("gear.shovel_extra_gravel_per_tier", "tools", "Shovel: extra gravel per tier", max=100),
    _pct("gear.axe_stick_chance", "tools", "Axe: chance to find sticks", "Sticks found = the axe's tier."),
    _pct("gear.hoe_xp_bonus_per_tier", "tools", "Hoe: XP bonus per tier", max=10),
    # ---- swords & armor ----
    *[_b(f"gear.sword_max_damage.{m}", "combat_gear", f"Max damage: {'no sword' if m == 'none' else m + ' sword'}",
         "A hit deals between the duel minimum damage and this.", "float", 1, 1000)
      for m in ("none", *MATERIALS)],
    *[_b(f"gear.armor_points.{m}.{slot}", "combat_gear", f"{m.capitalize()} {slot}: armor points", max=100)
      for m in MATERIALS for slot in ARMOR],
    _pct("gear.damage_reduction_per_armor_point", "combat_gear", "Damage reduction per armor point"),
    _pct("gear.max_damage_reduction", "combat_gear", "Max damage reduction"),
    # ---- duels ----
    _b("duel.min_stake", "duels", "Minimum stake", min=1),
    _b("duel.hp", "duels", "HP of each player", min=1, max=10_000),
    _b("duel.min_damage", "duels", "Minimum damage of a hit", "Strength potions raise it for a turn.", "float", 0, 1000),
    _pct("duel.dodge_chance", "duels", "Dodge chance"),
    _pct("duel.crit_chance", "duels", "Critical hit chance"),
    _b("duel.crit_multiplier", "duels", "Critical hit multiplier", kind="float", min=1, max=10),
    _b("duel.second_player_bonus_hp", "duels", "Extra HP for the second player", "Makes up for not striking first.", max=1000),
    _b("duel.max_rounds", "duels", "Max rounds", "Then the player with the most HP wins.", min=1, max=1000),
    _b("duel.cooldown_seconds", "duels", "Seconds between two duels", max=86_400),
    _b("duel.request_timeout_seconds", "duels", "Seconds to accept a challenge", min=10, max=840),
    _b("duel.xp_win", "duels", "XP for a win"),
    _b("duel.xp_loss", "duels", "XP for a loss"),
    _b("duel.turn_seconds", "duels", "Seconds to play a turn", "Then the bot attacks for the player.", min=10, max=300),
    _b("duel.afk_turns", "duels", "Missed turns before auto play", min=1, max=10),
    # ---- potions ----
    _b("potions.max_per_duel", "potions", "Potions per duel (per player)", max=20),
    _b("potions.strength_min_bonus", "potions", "Strength: minimum damage bonus", kind="float", max=100),
    _pct("potions.speed_chance", "potions", "Speed: chance to strike twice"),
    _b("potions.speed_turns", "potions", "Speed: turns it lasts", min=1, max=10),
    _b("potions.healing_hp", "potions", "Healing: HP healed", kind="float", max=100),
    _b("potions.harming_damage", "potions", "Harming: direct damage", "Reduced by armor.", "float", max=100),
    _b("potions.level2_multiplier", "potions", "Reinforced potions: effect ×", kind="float", min=1, max=10),
    _b("potions.boss_top", "potions", "Bosses: top N fighters get a potion", max=50),
    _b("potions.value", "potions", "Potion value (emeralds)", "Used for fortunes and fair prices."),
    _b("potions.value_ii", "potions", "Reinforced potion value (emeralds)", "Used for fortunes and fair prices."),
    # ---- enchanting ----
    _pct("enchants.lapis_chance", "enchant_books", "Lapis chance per mining reward"),
    _b("enchants.lapis_amount.0", "enchant_books", "Lapis found: minimum", min=1, max=1000),
    _b("enchants.lapis_amount.1", "enchant_books", "Lapis found: maximum", min=1, max=1000),
    *_per_level("enchants.apply_cost", "enchant_books", "Lapis to apply a book", "Lapis spent with /enchant apply.", max=1000),
    *_per_level("enchants.book_weights", "enchant_books", "Book level weight", "Chances of each level for books "
                "from drops and challenges (weight ÷ total).", max=10_000),
    *_per_level("enchants.boss_book_weights", "enchant_books", "Boss book level weight", "Chances of each level for "
                "the book of a boss's top damage dealer.", max=10_000),
    _b("enchants.challenges_book", "enchant_books", "Book for all weekly challenges", kind="bool", min=None,
       help="A random book for completing every challenge of the week."),
    _b("enchants.lapis_value", "enchant_books", "Lapis value (emeralds)", "Used for fortunes and fair prices."),
    *_per_level("enchants.book_values", "enchant_books", "Book value (emeralds)", "Used for fortunes and fair prices."),
    *_per_level("enchants.efficiency_seconds", "enchant_effects", "Efficiency: seconds less", "Shorter mining cooldown.", max=3600),
    *_per_level("enchants.fortune_bonus", "enchant_effects", "Fortune: extra blocks",
                "Pickaxe cobblestone, shovel gravel, axe sticks.", max=100),
    *[_pct(f"enchants.fortune_hoe_xp.{i}", "enchant_effects", f"Fortune on a hoe: XP bonus ({ROMAN[i]})", max=10) for i in range(3)],
    *[_pct(f"enchants.unbreaking_chance.{i}", "enchant_effects", f"Unbreaking: chance to keep ({ROMAN[i]})",
           "Chance that a use costs no durability.") for i in range(3)],
    *_per_level("enchants.sharpness_damage", "enchant_effects", "Sharpness: max damage +", kind="float", max=1000),
    *[_pct(f"enchants.looting_boss_bonus.{i}", "enchant_effects", f"Looting: boss reward bonus ({ROMAN[i]})", max=10)
      for i in range(3)],
    *_per_level("enchants.protection_points", "enchant_effects", "Protection: armor points", "Per enchanted piece.",
                kind="float", max=100),
    # ---- drops ----
    _pct("drops.chance", "drops", "Drop chance per mining reward"),
    _b("drops.min_interval_seconds", "drops", "Seconds between two drops (min)", max=7 * 86_400),
    _b("drops.claim_seconds", "drops", "Seconds to claim a drop", min=5, max=840),
    _b("drops.table", "drops", "Drop table", "What a drop can be, and how often (weight ÷ total).", "table", None,
       item="drops"),
    # ---- bosses ----
    _b("boss.auto_spawn_hours", "bosses", "Automatic boss every X hours",
       "Hours after the previous boss ended. 0 = only /event boss.", "float", max=720),
    _b("boss.duration_hours", "bosses", "Hours before a boss escapes", kind="float", min=0.1, max=720),
    _b("boss.hp", "bosses", "Boss HP", min=1, max=10_000_000),
    _b("boss.attack_cooldown_seconds", "bosses", "Seconds between two attacks", max=86_400),
    _pct("boss.crit_chance", "bosses", "Critical hit chance"),
    _b("boss.crit_multiplier", "bosses", "Critical hit multiplier", kind="float", min=1, max=10),
    _b("boss.reward_pool", "bosses", "Reward pool (emeralds)", "Shared by damage dealt."),
    _b("boss.top_damage_bonus", "bosses", "Top damage dealer bonus"),
    _b("boss.xp_reward", "bosses", "XP for every fighter"),
    _b("boss.names", "bosses", "Boss names", "A random one is picked for each boss.", "list", None, item="text"),
    # ---- seasons & challenges ----
    _b("seasons.rewards", "seasons", "Season podium rewards", "Emeralds for #1, #2, #3… of the weekly season.",
       "list", None, item="int", max_items=10),
    _b("challenges.per_week", "seasons", "Challenges per week", max=len(_CHALLENGE_NAMES)),
    *_challenge_fields(),
    # ---- achievements ----
    *_achievement_fields(),
    # ---- teams ----
    _b("teams.max_members", "teams", "Max members per team", min=2, max=25),
    _b("teams.create_cost", "teams", "Team creation cost", "0 = free."),
    _b("teams.min_members_ranked", "teams", "Members who scored, to be ranked", min=1, max=25),
    _b("teams.invite_hours", "teams", "Invitations last (hours)", min=1, max=720),
    _pct("teams.xp_bonus_per_active_member", "teams", "XP bonus per active teammate",
         "For each other member who mined today."),
    _pct("teams.max_xp_bonus", "teams", "Max team XP bonus", max=10),
    _b("teams.season_rewards", "teams", "Team season rewards", "Emeralds for the #1, #2, #3… teams, shared by "
       "what each member brought.", "list", None, item="int", max_items=10),
    # ---- tournament ----
    _b("tournament.entry_fee", "tournament", "Entry fee"),
    _b("tournament.house_bonus", "tournament", "Server bonus added to the pot"),
    _b("tournament.min_players", "tournament", "Minimum players (else cancelled)", min=2, max=128),
    _b("tournament.max_players", "tournament", "Maximum players", min=2, max=128),
    _b("tournament.opens_day", "tournament", "Registrations open: day", kind="choice", min=None, choices=DAY_CHOICES),
    _b("tournament.opens_hour", "tournament", "Registrations open: hour (0-23)", max=23),
    _b("tournament.closes_day", "tournament", "Registrations close: day", kind="choice", min=None, choices=DAY_CHOICES),
    _b("tournament.closes_hour", "tournament", "Registrations close: hour (0-23)", max=23),
    _b("tournament.start_day", "tournament", "First round: day", kind="choice", min=None, choices=DAY_CHOICES),
    _b("tournament.start_hour", "tournament", "First round: hour (0-23)", max=23),
    _b("tournament.round_minutes", "tournament", "Minutes between rounds", min=1, max=1440),
    _b("tournament.prize_split.0", "tournament", "Pot share: winner (%)", max=100),
    _b("tournament.prize_split.1", "tournament", "Pot share: runner-up (%)", max=100),
    _b("tournament.prize_split.2", "tournament", "Pot share: semi-finalists (%)", "Shared between them.", max=100),
    _b("tournament.xp_per_win", "tournament", "XP per fight won"),
    # ---- villager ----
    _b("villager.arrive_hour", "villager", "Arrives at (hour, 0-23)", max=23),
    _b("villager.leave_hour", "villager", "Leaves at (hour, 0-23)", max=23),
    _pct("villager.sell_discount", "villager", "Discount on his goods", "30% = sold 30% below their value.", max=0.95),
    _pct("villager.buy_bonus", "villager", "Bonus when he buys blocks", "50% = he pays 50% more than /sell.", max=5),
    _b("villager.book_iii_price", "villager", "Price of a level III book", min=1),
    _b("villager.potion_ii_price", "villager", "Price of a reinforced potion", min=1),
    *[_b(f"villager.buys.{b}", "villager", f"He buys {b} by (0 = never)", "How many blocks he buys at once.", max=100_000)
      for b in BLOCK_TYPES],
    _b("villager.goods", "villager", "His goods", "What he can sell (one is picked for each visit).", "table", None,
       item="goods"),
]
FIELDS_BY_KEY = {f.key: f for f in FIELDS}

# Drop table rewards: (key, label). The key gives the reward: see drop_reward.
DROP_REWARDS = (
    ("emeralds", "Emeralds"),
    *[(f"ingot:{m}", f"{m.capitalize()} ingots") for m in MATERIALS],
    *[(f"block:{b}", f"{b.capitalize()} blocks") for b in BLOCK_TYPES],
    ("lapis", "Lapis lazuli"),
    ("book", "A random enchanted book"),
    ("potions", "Random potions"),
)
# What the villager can sell: (asset, label). "book" and "potion" are random ones.
GOODS = (
    *[(f"ingot:{m}", f"{m.capitalize()} ingots") for m in MATERIALS],
    ("lapis", "Lapis lazuli"),
    ("stick", "Sticks"),
    ("book", "A random level I/II book"),
    ("potion", "Random potions"),
)


def fields_in(category: str) -> list[Field]:
    return [f for f in FIELDS if f.category == category]


# ---------------- reading ----------------
def _check_path(path: tuple) -> None:
    if any(path[: len(p)] == p for p in PROTECTED):
        raise PermissionError("This setting can't be changed from Discord.")


def _get(data: Any, path: tuple) -> Any:
    for part in path:
        if isinstance(part, int):
            if not isinstance(data, list) or part >= len(data):
                return None
        elif not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _in_free_dict(path: tuple) -> bool:
    return len(path) >= 2 and settings.is_free_dict(path[1:-1])


def default_value(field: Field) -> Any:
    if not field.is_balance:
        return None
    if _in_free_dict(field.path):
        return (_get(settings.DEFAULTS, field.path[1:-1]) or {}).get(field.path[-1], 0)
    return _get(settings.DEFAULTS, field.path[1:])


def used_settings(cfg: dict) -> dict:
    """The game settings the bot uses with this config.json."""
    return settings.merged(balance_overrides(cfg))


def current_value(cfg: dict, field: Field, used: dict | None = None) -> Any:
    """Value in config.json, or for balance settings what the bot uses (the default when not overridden).

    `used` (used_settings(cfg)) saves recomputing it when showing many fields.
    """
    if not field.is_balance:
        return _get(cfg, field.path)
    used = used if used is not None else used_settings(cfg)
    if _in_free_dict(field.path):
        return (_get(used, field.path[1:-1]) or {}).get(field.path[-1], 0)
    return _get(used, field.path[1:])


def is_modified(cfg: dict, field: Field, used: dict | None = None) -> bool:
    return field.is_balance and current_value(cfg, field, used) != default_value(field)


# ---------------- typing ----------------
def _number(text: str, whole: bool) -> float:
    try:
        value: float = int(text) if whole else float(text.replace(",", "."))
        if not math.isfinite(value):
            raise ValueError
    except ValueError:
        raise ValueError(f"“{text}” is not a {'whole number' if whole else 'number'}.")
    return value


def parse(field: Field, text: str) -> Any:
    """Turn what staff typed into a value. Empty text resets a balance setting (returns None)."""
    text = text.strip()
    if not text:
        if field.is_balance:
            return None
        raise ValueError("The text can't be empty.")
    if field.kind == "text":
        return text
    if field.kind == "timezone":
        try:
            ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"“{text}” is not a time zone (e.g. Europe/Paris, America/New_York).")
        return text
    if field.kind == "percent":
        value = _number(text.rstrip("%").strip(), whole=False) / 100
        value = round(value, 6)
        low, high = field.min, field.max
        if low is not None and value < low:
            raise ValueError(f"The minimum is {percent(low)}.")
        if high is not None and value > high:
            raise ValueError(f"The maximum is {percent(high)}.")
        return value
    value = _number(text, whole=field.kind == "int")
    if field.min is not None and value < field.min:
        raise ValueError(f"The minimum is {field.min:g}.")
    if field.max is not None and value > field.max:
        raise ValueError(f"The maximum is {field.max:g}.")
    return value


def as_text(field: Field, value: Any) -> str:
    """A value as staff would type it (to fill the text box)."""
    if value is None:
        return ""
    if field.kind == "percent":
        return f"{round(float(value) * 100, 4):g}"
    return f"{value:g}" if isinstance(value, float) else str(value)


def percent(value: float) -> str:
    return f"{round(float(value) * 100, 4):g}%"


def display(field: Field, value: Any) -> str:
    """A value for people (channels and roles are shown by the /config cog)."""
    if field.kind == "percent":
        return percent(value)
    if field.kind == "bool":
        return "on" if value else "off"
    if field.kind == "choice":
        return next((label for label, v in field.choices if v == value), str(value))
    if field.kind == "list":
        return ", ".join(f"{v:,}" if isinstance(v, int) else str(v) for v in value) if value else "none"
    if field.kind == "map":
        return " · ".join(f"{k} → {v}" for k, v in sorted(value.items(), key=lambda kv: int(kv[0]))) if value else "none"
    if field.kind == "table":
        return f"{len(value)} line{'s' if len(value) != 1 else ''}"
    if value is None:
        return "not set"
    if field.kind == "text":
        text = str(value)
        return text if len(text) <= 80 else text[:79] + "…"
    return f"{value:,g}" if isinstance(value, float) else f"{value:,}" if isinstance(value, int) else str(value)


# ---------------- writing ----------------
def _prune(cfg: dict, path: tuple) -> None:
    """Remove the dicts left empty along `path` (after a reset)."""
    for i in range(len(path) - 1, 0, -1):
        parent = _get(cfg, path[: i - 1]) if i > 1 else cfg
        node = _get(cfg, path[:i])
        if isinstance(node, dict) and not node and isinstance(parent, dict):
            parent.pop(path[i - 1], None)


def set_value(cfg: dict, path: tuple, value: Any) -> dict:
    """New config with `path` set to `value` (None removes the key). `cfg` is not modified."""
    _check_path(path)
    new = copy.deepcopy(cfg)
    node = new
    for part in path[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    if value is None:
        node.pop(path[-1], None)
        _prune(new, path)
    else:
        node[path[-1]] = value
    return new


def set_field(cfg: dict, field: Field, value: Any) -> dict:
    """Set a field (None = clear it, or back to the default for a game setting).

    A value inside a list or a free dict (villager.buys) rewrites the whole list or dict,
    and an override equal to the default is removed from config.json.
    """
    if not field.is_balance:
        return set_value(cfg, field.path, value)
    rel = field.path[1:]
    used = settings.merged(balance_overrides(cfg))
    if isinstance(rel[-1], int):
        whole_path = rel[:-1]
        values = copy.deepcopy(_get(used, whole_path))
        default = _get(settings.DEFAULTS, whole_path)
        values[rel[-1]] = default[rel[-1]] if value is None else value
        return set_value(cfg, ("balance",) + whole_path, None if values == default else values)
    if _in_free_dict(field.path):
        whole_path = rel[:-1]
        mapping = dict(_get(used, whole_path))
        default = _get(settings.DEFAULTS, whole_path)
        if value is None:
            value = default.get(rel[-1], 0)
        if value:
            mapping[rel[-1]] = value
        else:
            mapping.pop(rel[-1], None)
        return set_value(cfg, ("balance",) + whole_path, None if mapping == default else mapping)
    default = default_value(field)
    return set_value(cfg, field.path, None if value is None or value == default else value)


def set_whole(cfg: dict, field: Field, value: Any) -> dict:
    """Replace a whole list, map or table (an editor's result)."""
    return set_value(cfg, field.path, None if value == default_value(field) else value)


# ---------------- editors: lists, automatic mutes, drop table, villager goods ----------------
def parse_item(field: Field, text: str) -> Any:
    """An element of a list editor."""
    text = text.strip()
    if field.item == "text":
        if not text or len(text) > 64:
            raise ValueError("A name has 1 to 64 characters.")
        return text
    value = _number(text, whole=True)
    if value < 0:
        raise ValueError("It can't be negative.")
    return value


def drop_reward(kind: str, amount: int) -> dict:
    """('ingot:iron', 3) -> {"ingot": "iron", "amount": 3}"""
    name, _, what = kind.partition(":")
    if name == "emeralds":
        return {"emeralds": amount}
    if name in ("ingot", "block"):
        return {name: what, "amount": amount}
    if name == "lapis":
        return {"lapis": amount}
    if name == "book":
        return {"book": True}
    if name == "potions":
        return {"potions": amount}
    raise ValueError("Unknown reward.")


def drop_kind(reward: dict) -> tuple[str, int]:
    """The reverse of drop_reward."""
    for name in ("ingot", "block"):
        if name in reward:
            return f"{name}:{reward[name]}", int(reward.get("amount", 1))
    for name in ("emeralds", "lapis", "potions"):
        if name in reward:
            return name, int(reward[name])
    return "book", 1


def reward_label(reward: dict) -> str:
    kind, amount = drop_kind(reward)
    label = dict(DROP_REWARDS).get(kind, kind)
    return label if kind == "book" else f"{amount:,} × {label.lower()}"


def good_label(good: dict) -> str:
    return f"{int(good['amount']):,} × {dict(GOODS).get(good['asset'], good['asset']).lower()}"


def mute_rule(count_text: str, duration: str) -> tuple[str, str]:
    """A line of the automatic mutes: ('3', '1h')."""
    from game import moderation  # it imports the settings
    from game.errors import GameError

    count = int(_number(count_text.strip(), whole=True))
    if count < 1 or count > 100:
        raise ValueError("The number of warnings goes from 1 to 100.")
    duration = duration.strip().lower()
    try:
        moderation.parse_duration(duration)
    except GameError as e:
        raise ValueError(str(e))
    return str(count), duration


# ---------------- level roles ----------------
def level_roles(cfg: dict) -> dict[int, int]:
    raw = _get(cfg, ("roles", "level_roles")) or {}
    return {int(level): int(rid) for level, rid in raw.items() if int(rid or 0)}


def set_level_role(cfg: dict, level: int, role_id: int | None) -> dict:
    """Add/replace (role_id) or remove (None) the role given at `level`."""
    roles = {str(k): v for k, v in level_roles(cfg).items()}
    if role_id is None:
        roles.pop(str(level), None)
    else:
        roles[str(level)] = role_id
    ordered = dict(sorted(roles.items(), key=lambda kv: int(kv[0])))
    return set_value(cfg, ("roles", "level_roles"), ordered)


# ---------------- saving ----------------
@dataclass
class Change:
    config: dict  # the config to write
    refused: list[str]  # problems this change would create: nothing is written
    cleaned: list[str]  # problems that were already in the file: removed from it


def prepare_change(old: dict, mutate: Callable[[dict], dict]) -> Change:
    """Apply `mutate` to a copy of config.json.

    Only the problems the change itself creates refuse it. The ones already in the
    file (a key from an older version of the bot, a typo…) never block a change:
    the bot ignores them anyway, so they are removed from the file.
    """
    before = set(settings.problems(balance_overrides(old)))
    new = mutate(copy.deepcopy(old))
    after = settings.problems(balance_overrides(new))
    refused = [p for p in after if p not in before]
    if refused or not after:
        return Change(new, refused, [])
    new["balance"] = settings.clean(new.get("balance") or {})[0]
    return Change(new, [], after)


def write_config(path: Path, cfg: dict, backup_folder: Path, keep: int = 20) -> Path | None:
    """Save a copy of the current file in `backup_folder`, then rewrite `path` in place.

    In place (not rename) because with Docker config.json is a single bind-mounted file.
    """
    copy_path = None
    if path.exists():
        backup_folder.mkdir(parents=True, exist_ok=True)
        copy_path = backup_folder / f"config-{time.strftime('%Y-%m-%d-%H%M%S')}.json"
        copy_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        old = sorted(backup_folder.glob("config-*.json"))
        for p in old[: max(0, len(old) - keep)]:
            p.unlink()
    path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return copy_path
