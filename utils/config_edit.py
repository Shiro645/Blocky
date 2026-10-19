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
from game.catalog import ARMOR, BLOCK_TYPES, DIMENSION_BLOCKS, DIMENSION_NAMES, DIMENSIONS, MATERIALS, block_name
from utils.config import balance_overrides

PROTECTED = (
    ("minecraft", "rcon_password"),
    ("staff", "role_id"),
    ("database_path",),
)

# /config: a section, then one of its categories.
SECTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "server": ("🖥️ Server", ("channels", "roles", "level_roles", "minecraft", "server", "moderation")),
    "economy": ("💰 Economy", ("mining", "mining_odds", "dimensions", "market", "trading", "loans", "villager")),
    "progress": ("⭐ Progress", ("xp", "seasons", "challenges", "achievements", "species", "profiles", "titles", "guide",
                                 "teams", "beacon")),
    "combat": ("⚔️ Combat", ("duels", "potions", "tools", "combat_gear", "enchant_books", "enchant_effects", "pve",
                             "pve_monsters", "bosses", "tournament")),
    "games": ("🎉 Games & events", ("live_events", "chance", "minigames", "rob", "war", "drops")),
}

CATEGORIES = {
    "channels": "📢 Channels",
    "roles": "🎭 Roles",
    "level_roles": "🎖️ Level roles",
    "minecraft": "🌍 Minecraft texts",
    "server": "🕒 Time zone & backups",
    "moderation": "🔨 Moderation",
    "mining": "⛏️ Mining & block values",
    "mining_odds": "📊 Mining odds",
    "dimensions": "🌋 Dimensions & netherite",
    "beacon": "🔆 Beacon",
    "war": "🏴 Gang wars",
    "market": "🛒 Market & daily",
    "trading": "🤝 Trading & auction",
    "loans": "💳 Loans",
    "villager": "🧑‍🌾 Villager",
    "xp": "📈 XP, levels & talents",
    "seasons": "🏆 Seasons",
    "challenges": "🎯 Daily & weekly challenges",
    "achievements": "🏅 Achievements",
    "species": "🧬 Species",
    "profiles": "🎨 Profiles",
    "titles": "🏷️ Titles & earned frames",
    "guide": "📘 Guide",
    "teams": "🛡️ Teams",
    "duels": "🤺 Duels & dummy",
    "potions": "🧪 Potions",
    "tools": "🛠️ Tools, durability & repair",
    "combat_gear": "🗡️ Swords, armor & shield",
    "enchant_books": "📕 Enchanting: books & lapis",
    "enchant_effects": "✨ Enchanting: effects",
    "pve": "🏰 Dungeon",
    "pve_monsters": "🧟 Dungeon monsters",
    "bosses": "🐉 Gate bosses",
    "tournament": "🏟️ Tournament",
    "live_events": "⏱️ Timed events",
    "chance": "🎰 Games of chance",
    "minigames": "🧩 Blockdle & quiz",
    "rob": "🦹 Robberies",
    "drops": "🎁 Drops",
}
SECTION_OF = {category: section for section, (_, categories) in SECTIONS.items() for category in categories}

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")
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
    item: str = ""  # list: "int" or "text"; table: "drops" or "goods"; channel: "category" (a category)
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


def _per_level(dotted: str, category: str, label: str, help: str = "", kind: str = "int", levels: int = 3,
               **extra: Any) -> list[Field]:
    """One field per value of a list with a value for each level (I, II, III… up to `levels`)."""
    return [_b(f"{dotted}.{i}", category, f"{label} ({ROMAN[i]})", help, kind, **extra) for i in range(levels)]


def _pct(dotted: str, category: str, label: str, help: str = "", max: float = 1.0) -> Field:
    return _b(dotted, category, label, help, "percent", 0, max)


def _profile_frames():
    from game import profiles  # here: profiles imports a lot of the game
    return profiles.FRAMES.items()


def _profile_titles():
    from game import profiles
    return profiles.TITLES.items()


def _with_n(text) -> str:
    """'Mine N blocks': what an earned title or frame asks, with N for the setting."""
    return text(0).replace(" 0 ", " N ").replace(" 0", " N")


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
    "lucky_100": "Feeling Lucky", "wheel_100": "Spin Doctor", "bullseye": "Bullseye", "blockdle_10": "Block Detective", "quiz_10": "Know-It-All", "thief_10": "Master Thief", "watch_5": "Neighborhood Watch", "dungeon_hard": "Into the Depths", "dungeon_hardcore": "Hardcore Hero", "dungeon_nightmare": "Nightmare Slayer", "challenger_10": "Challenger", "challenger_50": "Challenge Master", "high_roller": "High Roller", "enchanter_10": "Enchanter", "handyman_10": "Handyman", "regular_20": "Regular Customer", "moneylender": "Moneylender",
    "wither_slayer": "Wither Slayer", "dragon_slayer": "Dragon Slayer", "warden_slayer": "Warden Slayer",
    "beacon_builder": "Beacon Builder", "warlord": "Warlord", "raider_5": "Raider",
}
_CHALLENGE_NAMES = {
    "mine_blocks": "Mine blocks", "find_bedrock": "Find bedrock", "sell_blocks": "Earn emeralds by selling",
    "craft_gear": "Craft gear", "win_duels": "Win duels", "claim_drops": "Claim drops",
    "boss_damage": "Damage bosses", "daily_rewards": "Claim the daily reward", "trades": "Complete trades",
    "lucky_blocks": "Break Lucky Blocks", "wheel_spins": "Spin the wheel", "blockdle": "Find the Blockdle block",
    "quiz": "Win quiz questions", "pve_waves": "Clear dungeon waves", "dummy": "Hit the training dummy",
    "robs": "Rob players",
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
    for pool, when, label in (("goals", "week", "Weekly"), ("daily_goals", "day", "Daily")):
        for code, name in _CHALLENGE_NAMES.items():
            if code not in settings.DEFAULTS["challenges"][pool]:
                continue
            out.append(_b(f"challenges.{pool}.{code}.target", "challenges", f"{label} · {name}: target",
                          f"What to reach during the {when}.", min=1))
            out.append(_b(f"challenges.{pool}.{code}.reward", "challenges", f"{label} · {name}: reward",
                          "Emeralds paid when it's done (they count for the season)."))
    return out


FIELDS: list[Field] = [
    # ---- channels, roles, texts ----
    Field("ch_announcements", "channels", "Announcements channel", ("channels", "announcements"), "channel",
          help="Level-ups, achievements, challenges, season and tournament results."),
    Field("ch_events", "channels", "Events channel", ("channels", "events"), "channel",
          help="Drops and bosses appear here (not set = where people chat)."),
    Field("ch_staff_log", "channels", "Staff channel", ("channels", "staff_log"), "channel",
          help="/link requests and the log of every staff action."),
    Field("ch_mining", "channels", "Mining channels", ("channels", "mining"), "channels",
          help="Chatting there mines overworld blocks and gives XP and drops (their threads too). Not set = every "
               "channel mines the overworld (except the other dimensions' channels). Set = the other channels give "
               "nothing (spam channels keep their tiny reward)."),
    *[Field(f"ch_mining_{d}", "channels", f"{DIMENSION_NAMES[d]} mining channels", ("channels", f"mining_{d}"), "channels",
            help=f"Chatting there mines {DIMENSION_NAMES[d]} blocks (their threads too), for the players who unlocked "
                 f"the {DIMENSION_NAMES[d]}; the others get nothing there. Hide them with the {DIMENSION_NAMES[d]} "
                 "role (see Roles).")
      for d in DIMENSIONS[1:]],
    Field("ch_spam", "channels", "Spam channels", ("channels", "spam"), "channels",
          help="Messages there give no blocks, XP or drops, only a tiny reward (see Mining)."),
    Field("ch_games", "channels", "Game channels", ("channels", "games"), "channels",
          help="/luckyblock, /wheel, /blockdle, /rob, /pve start and /dummy hit only work there (and in the guide "
               "channels), and the quiz is posted there (not set = they work anywhere, but no automatic quiz)."),
    Field("ch_robberies", "channels", "Robberies channel", ("channels", "robberies"), "channel",
          help="Robberies (/rob) are posted there, with the Stop the thief! button (the victim is pinged there for a "
               "risky one). Best as a channel where members can't write. Not set = where /rob is used."),
    Field("ch_market", "channels", "Market channel", ("channels", "market"), "channel",
          help="The bot keeps two messages there, always up to date: the market (fixed prices), then every "
               "auction listing, each with a menu to buy. Best as a channel where members can't write."),
    Field("ch_updates", "channels", "Updates channel", ("channels", "updates"), "channel",
          help="The bot announces each new Blocky feature there, once, after the bot is updated. Not set = the "
               "announcements wait until a channel is set."),
    Field("ch_wiki", "channels", "Wiki channel", ("channels", "wiki"), "channel",
          help="The bot keeps the wiki there: every feature explained in detail for players, with the current "
               "numbers, updated when the settings change. Best as a channel where members can't write."),
    Field("ch_guide_category", "channels", "Guide category", ("channels", "guide_category"), "channel",
          help="Every Blocky player (the Blocky player role, see Roles) gets a private guide channel in this "
               "category (only them and the staff see it), with a checklist of first steps. When it's full "
               "(50 channels) the bot adds \"<name> 2\", \"<name> 3\"… Not set = no guide channels (/guide still "
               "shows the guide).", item="category"),
    Field("role_event_ping", "roles", "Role pinged for events", ("roles", "event_ping"), "role",
          help="Mentioned when a boss appears, when the wandering villager arrives and when a tournament opens. "
               "Nobody else is pinged."),
    Field("role_champion", "roles", "Season champion role", ("roles", "season_champion"), "role",
          help="Given to the winner of the last weekly season.", item="assign"),
    Field("role_tournament", "roles", "Tournament champion role", ("roles", "tournament_champion"), "role",
          help="Given to the winner of the last weekend tournament.", item="assign"),
    Field("role_updates_ping", "roles", "Role pinged for updates", ("roles", "updates_ping"), "role",
          help="Mentioned when a new Blocky feature is announced in the updates channel (not set = no ping)."),
    Field("role_blocky_player", "roles", "Blocky player role", ("roles", "blocky_player"), "role",
          help="Only members with this role get a guide channel: it opens as soon as they get the role (e.g. from a "
               "question in Channels & Roles) and is deleted if they lose it. Not set = no guide channels."),
    Field("role_team_leader", "roles", "Team leader role", ("roles", "team_leader"), "role",
          help="Given to every team leader, and taken back when they no longer lead a team.", item="assign"),
    Field("role_untouchable", "roles", "Untouchables role", ("roles", "untouchable"), "role",
          help="Members with this role are out of the robberies: nobody can /rob them and they can't /rob anyone. "
               "The staff gives and takes it by hand. Not set = nobody is untouchable."),
    *[Field(f"role_dimension_{d}", "roles", f"{DIMENSION_NAMES[d]} role (dimension)", ("roles", f"dimension_{d}"), "role",
            help=f"Given to every player who unlocked the {DIMENSION_NAMES[d]}, taken back if they lose it. Use it to "
                 f"show the {DIMENSION_NAMES[d]} mining channels only to them.", item="assign")
      for d in DIMENSIONS[1:]],
    *[Field(f"role_species_{key}", "roles", f"{name} role (species)", ("roles", f"species_{key}"), "role",
            help=f"Given to every {name} (/species), and taken back when they change species.", item="assign")
      for key, name in (("villager", "Villager"), ("dwarf", "Dwarf"), ("witch", "Witch"), ("mage", "Mage"),
                        ("miner", "Miner"), ("gambler", "Gambler"))],
    Field("mc_ip_text", "minecraft", "/ip text", ("minecraft", "public_ip_text"), "text",
          help="What /ip shows to join the server."),
    Field("mc_modpack_text", "minecraft", "/modpacks text", ("minecraft", "modpack_text"), "text",
          help="What /modpacks shows. Links like [Name](https://…) work."),
    # ---- server ----
    _b("timezone", "server", "Time zone", "Daily reset, seasons, villager, tournament and backups follow it. "
       "E.g. Europe/Paris.", "timezone", None),
    _b("backups.hour", "server", "Nightly backup: hour", "Hour (0-23) of the daily copy of the database.", max=23),
    _b("backups.keep", "server", "Nightly backups kept", "How many nightly copies are kept.", min=1, max=365),
    _b("moderation.warn_expire_days", "moderation", "Warnings count for (days)",
       "After this many days a warning stops counting for automatic mutes (0 = forever).", max=3650),
    _b("moderation.warn_mutes", "moderation", "Automatic mutes", "How many active warnings mute a member, and for how long.",
       "map", None, max_items=10),
    # ---- mining ----
    _b("mining.cooldown_seconds", "mining", "Mining cooldown (seconds)", "Time between two mining rewards (0 = none).", max=3600),
    _b("mining.min_cooldown_seconds", "mining", "Shortest mining cooldown (seconds)",
       "The Efficiency talent and enchantment never go below this.", max=3600),
    _b("mining.xp_per_message.0", "mining", "XP per mining reward: minimum", max=10_000),
    _b("mining.xp_per_message.1", "mining", "XP per mining reward: maximum", max=10_000),
    _b("mining.spam_reward", "mining", "Spam channels: emeralds per reward",
       "Saved until it makes a whole emerald. 0.01 = 1 emerald every 100 rewards.", "float", max=100),
    *[_b(f"block_values.{b}", "mining", f"{block_name(b).capitalize()} value",
         "Emeralds per block with /sell. Also what the block is worth in the season score.") for b in BLOCK_TYPES],
    # ---- mining odds ----
    *[_b(f"mining.{pile}.{b}", "mining_odds", f"Pile of {size}: {block_name(b)}", WEIGHT_HELP, max=100_000)
      for pile, size in PILES for b in DIMENSION_BLOCKS["overworld"]],
    # ---- dimensions ----
    _pct("dimensions.scrap_chance", "dimensions", "Ancient debris: chance per mining reward",
         "In the Nether and beyond, a mining reward finds a netherite scrap this often. 36 scraps make a full "
         "netherite set: 1.2% ≈ a month at ~100 mining rewards a day."),
    _b("dimensions.scraps_per_ingot", "dimensions", "Netherite ingot: scraps", "Scraps for one netherite ingot.",
       min=1, max=100),
    _b("dimensions.gold_per_ingot", "dimensions", "Netherite ingot: gold ingots", "Gold ingots for one netherite ingot.",
       max=100),
    *[_b(f"dimensions.multipliers.{d}", "dimensions", f"{DIMENSION_NAMES[d]}: tool bonus ×",
         "The pickaxe's and the shovel's extra blocks are worth their overworld value times this (in this "
         "dimension's blocks). Set so that with tools too the dimension pays as much more as without.", "float", max=100)
      for d in DIMENSIONS[1:]],
    *[_b(f"dimensions.{d}.{pile}.{b}", "dimensions", f"{DIMENSION_NAMES[d]}, pile of {size}: {block_name(b)}",
         WEIGHT_HELP, max=100_000)
      for d in DIMENSIONS[1:] if len(DIMENSION_BLOCKS[d]) > 1 for pile, size in PILES for b in DIMENSION_BLOCKS[d]],
    # ---- XP & talents ----
    _b("levels.xp_first_level", "xp", "XP from level 1 to 2", "XP needed to reach level 2.", min=1, max=1_000_000),
    _b("levels.xp_growth_per_level", "xp", "XP growth per level (×)",
       "Each level needs this many times the XP of the previous one: 1.05 = +5% a level (level 50: 1,092 XP, "
       "level 100: 12,524). 1 = the same every level.", kind="float", min=1, max=2),
    _b("talents.points_every_levels", "xp", "Levels per talent point", "A talent point every this many levels.", min=1, max=100),
    *[_b(f"talents.caps.{t}", "xp", f"{t.capitalize()} talent: max points", "Points beyond this can't be bought.", max=100)
      for t in ("miner", "trader", "lucky", "efficiency")],
    _pct("talents.trader_bonus_per_point", "xp", "Trader: /sell bonus per point"),
    _b("talents.reset_cost_per_point", "xp", "Talent reset: price per point", "/talent_reset costs this many "
       "emeralds for each spent point it gives back.", max=1_000_000),
    _b("talents.reset_cost_min", "xp", "Talent reset: minimum price", "/talent_reset never costs less than this.",
       max=1_000_000),
    _b("talents.efficiency_seconds_per_point", "xp", "Efficiency: seconds less per point", "Shorter mining cooldown.", max=3600),
    _b("talents.miner_gravel_4_5", "xp", "Miner: gravel weight/point (4-5)", "Added to gravel on piles of 4-5 blocks."),
    _b("talents.miner_gravel_4_5_max", "xp", "Miner: max gravel bonus (4-5)"),
    _b("talents.miner_gravel_2_3", "xp", "Miner: gravel weight/point (2-3)", "Added to gravel on piles of 2-3 blocks."),
    _b("talents.miner_gravel_2_3_max", "xp", "Miner: max gravel bonus (2-3)"),
    _b("talents.miner_deepslate_2_3", "xp", "Miner: deepslate weight/point (2-3)", "Added to deepslate on piles of 2-3 blocks."),
    _b("talents.miner_deepslate_2_3_max", "xp", "Miner: max deepslate bonus (2-3)"),
    _pct("talents.miner_bonus_block_chance", "xp", "Miner: bonus block chance/point", "One more block on big piles."),
    _pct("talents.miner_bonus_block_max", "xp", "Miner: max bonus block chance"),
    _b("talents.miner_bonus_min_pile", "xp", "Miner: bonus block from piles of", "The bonus block only comes on "
       "piles of at least this many blocks.", min=1, max=6),
    _b("talents.lucky_rare_weight", "xp", "Lucky: rare block weight/point",
       "Added to obsidian and to bedrock on 1-block piles."),
    # ---- economy ----
    _b("market.stick_pack.price", "market", "Sticks: price of a pack", min=1),
    _b("market.stick_pack.amount", "market", "Sticks: sticks per pack", min=1),
    *[_b(f"market.ingots.{m}", "market", f"{m.capitalize()} ingot price", "Price at /market. Also their value "
         "for crafting values, fortunes and fair prices.", min=1) for m in MATERIALS],
    _pct("market.gear_sell_rate", "market", "/sell gear: share of its value",
         "A piece sells for this share of its value (craft + books), times its durability left: at 80%, a piece "
         "worth 100 with half its durability sells for 40."),
    _b("pay.min_amount", "trading", "/pay: minimum amount", min=1),
    _b("auction.tax_percent", "trading", "Auction tax (%)", "Taken from the seller's price.", max=100),
    _b("auction.max_listings", "trading", "Auction: listings per player", min=1, max=100),
    _b("auction.duration_days", "trading", "Auction: days before a listing ends", min=1, max=60),
    _b("daily.base_reward", "market", "Daily: reward on day 1"),
    _b("daily.streak_bonus_per_day", "market", "Daily: bonus per day in a row"),
    _b("daily.streak_cap_days", "market", "Daily: days the streak grows", "The reward stops growing after this.", min=1, max=365),
    _b("daily.weekly_bonus_item", "market", "Daily: bonus ingot", "Given every few days in a row (see below).",
       kind="choice", min=None, choices=tuple((m, m) for m in MATERIALS)),
    _b("daily.bonus_every_days", "market", "Daily: bonus ingot every … days",
       "7 = on day 7, 14, 21… of a streak.", min=1, max=365),
    _b("trade.offer_minutes", "trading", "/trade: minutes to answer", "A proposal ends after this.", kind="float",
       min=1, max=14),
    _b("daily.xp", "market", "Daily: XP"),
    # ---- tools ----
    _pct("repair.durability_per_ingot", "tools", "/repair: durability per ingot",
         "What one ingot of its material gives back to a piece, at its first repair (25% = 4 ingots).", max=1),
    _pct("repair.penalty_per_repair", "tools", "/repair: costlier after each repair",
         "25% = each repair the piece already had adds 25% to the ingots needed (4, 5, 6, 7 ingots…).", max=10),
    _b("repair.anvil_iron", "tools", "Anvil: iron ingots to craft it", "The anvil is needed to repair and to "
       "combine books.", min=1, max=1000),
    _pct("repair.anvil_damage_chance", "tools", "Anvil: chance to wear at each use",
         "New → chipped → damaged → broken (12% = about 25 uses)."),
    *[_b(f"gear.tier.{m}", "tools", f"{m.capitalize()} tier", "Tool bonuses are multiplied by the tier.", min=1, max=20)
      for m in MATERIALS],
    *[_b(f"gear.durability.{m}", "tools", f"{m.capitalize()} durability", "Uses before a piece breaks (armor: its share of this, see Swords, "
         "armor & shield). Changing it adapts the pieces already made.", min=1, max=1_000_000)
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
    _b("gear.shield_blocks_per_fight", "combat_gear", "Shield: blocks per duel",
       "Times a player can \"Attack + block\" in a duel (it blocks the opponent's next attack).", min=0, max=20),
    *[_pct(f"gear.armor_durability_share.{slot}", "combat_gear", f"{slot.capitalize()}: share of the durability",
           "Of its material's durability (Minecraft: helmet 69%, chestplate 100%, leggings 94%, boots 81%). "
           "Changing it adapts the pieces already made.") for slot in ARMOR],
    _b("gear.shield_durability", "combat_gear", "Shield: durability", "Of a new or repaired shield.", min=1, max=100_000),
    _b("gear.shield_wear_per_block", "combat_gear", "Shield: durability used per block",
       "At 0 it stays, unusable until /repair.", min=1, max=100_000),
    # ---- duels ----
    _b("duel.min_stake", "duels", "Minimum stake", min=1),
    _b("duel.hp", "duels", "HP of each player", min=1, max=10_000),
    _b("duel.min_damage", "duels", "Minimum damage of a hit", "Strength potions raise it for a turn.", "float", 0, 1000),
    _b("duel.min_hit_after_armor", "duels", "Smallest hit after armor", "Armor never lowers a hit below this "
       "(duels, tournament, dummy).", kind="float", max=100),
    _pct("duel.crit_chance", "duels", "Critical hit chance"),
    _b("duel.crit_multiplier", "duels", "Critical hit multiplier", kind="float", min=1, max=10),
    _b("duel.second_player_bonus_hp", "duels", "Extra HP for the second player", "Makes up for not striking first.", max=1000),
    _b("duel.max_rounds", "duels", "Max rounds", "Then the player with the most HP wins.", min=1, max=1000),
    _b("dummy.hits", "duels", "Dummy: hits per series", "The damage tester (/dummy hit).", min=1, max=50),
    _b("dummy.cooldown_seconds", "duels", "Dummy: seconds between two series", max=86_400),
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
    _b("potions.strong_per_fight", "potions", "Reinforced (II) potions per fight", "Per duel and per dungeon run.",
       max=20),
    *[_b(f"potions.random_weights.{k}", "potions", f"Random potions: {name} weight",
         "How often it comes in drops, bosses and the villager's goods (0 = never).", kind="float", max=1000)
      for k, name in (("strength", "Strength"), ("speed", "Speed"), ("healing", "Healing"), ("harming", "Harming"))],
    _b("potions.value", "potions", "Potion value (emeralds)", "Used for fortunes and fair prices."),
    _b("potions.value_ii", "potions", "Reinforced potion value (emeralds)", "Used for fortunes and fair prices."),
    # ---- enchanting ----
    _pct("enchants.lapis_chance", "enchant_books", "Lapis chance per mining reward"),
    _b("enchants.lapis_amount.0", "enchant_books", "Lapis found: minimum", min=1, max=1000),
    _b("enchants.lapis_amount.1", "enchant_books", "Lapis found: maximum", min=1, max=1000),
    *_per_level("enchants.apply_cost", "enchant_books", "Lapis to apply a book", "Lapis spent with /enchant apply.",
                max=100_000, levels=7),
    *_per_level("enchants.book_weights", "enchant_books", "Book level weight", "Chances of each level for books "
                "from drops and challenges (weight ÷ total).", max=10_000),
    *_per_level("enchants.boss_book_weights", "enchant_books", "Boss book level weight", "Chances of each level for "
                "the book of each survivor of a gate boss.", max=10_000),
    _b("enchants.challenges_book", "enchant_books", "Book for all weekly challenges", kind="bool", min=None,
       help="A random book for completing every challenge of the week."),
    _b("enchants.lapis_value", "enchant_books", "Lapis value (emeralds)", "Used for fortunes and fair prices."),
    *_per_level("enchants.book_values", "enchant_books", "Book value (emeralds)", "Used for fortunes and fair prices.",
                max=10_000_000, levels=7),
    *_per_level("enchants.efficiency_seconds", "enchant_effects", "Efficiency: seconds less", "Shorter mining cooldown.",
                kind="float", max=3600, levels=7),
    *_per_level("enchants.fortune_bonus", "enchant_effects", "Fortune: extra blocks",
                "Pickaxe cobblestone, shovel gravel, axe sticks (a fraction is a chance of one more).", kind="float",
                max=100, levels=7),
    *[_pct(f"enchants.fortune_hoe_xp.{i}", "enchant_effects", f"Fortune on a hoe: XP bonus ({ROMAN[i]})", max=10) for i in range(7)],
    *[_pct(f"enchants.unbreaking_chance.{i}", "enchant_effects", f"Unbreaking: chance to keep ({ROMAN[i]})",
           "Chance that a use costs no durability.") for i in range(7)],
    *_per_level("enchants.sharpness_damage", "enchant_effects", "Sharpness: max damage +", kind="float", max=1000, levels=7),
    *[_pct(f"enchants.looting_boss_bonus.{i}", "enchant_effects", f"Looting: gate boss bounty bonus ({ROMAN[i]})", max=10)
      for i in range(7)],
    *_per_level("enchants.protection_points", "enchant_effects", "Protection: armor points", "Per enchanted piece.",
                kind="float", max=100, levels=7),
    *[_pct(f"enchants.protection_cap_bonus.{i}", "enchant_effects", f"Protection: reduction cap + ({ROMAN[i]})",
           "Per enchanted piece: raises the most the armor can reduce the damage (Combat → max damage reduction). "
           "Useful from IV on, where the armor points are already capped.", max=1) for i in range(7)],
    _b("enchants.mending_durability_per_xp", "enchant_effects", "Mending: durability per XP",
       "The XP a player gains repairs their equipped Mending pieces first, this much per XP.", kind="float", max=100),
    _b("enchants.mending_value", "enchant_books", "Mending book value (emeralds)",
       "The rarest book. Used for fortunes and fair prices.", min=1),
    _pct("enchants.boss_mending_chance", "enchant_books", "Gate bosses: chance a book is Mending",
         "Each survivor's book is a Mending book this often."),
    # ---- drops ----
    _pct("drops.chance", "drops", "Drop chance per mining reward"),
    _b("drops.min_interval_seconds", "drops", "Seconds between two drops (min)", max=7 * 86_400),
    _b("drops.claim_seconds", "drops", "Seconds to claim a drop", min=5, max=840),
    _b("drops.table", "drops", "Drop table", "What a drop can be, and how often (weight ÷ total).", "table", None,
       item="drops"),
    # ---- gang wars ----
    _b("war.min_members", "war", "Members to be at war", "A team with fewer members isn't in the weekly war.",
       min=1, max=50),
    _pct("war.levy", "war", "Weekly levy on each chest", "Taken every Monday into the week's pot."),
    _pct("war.tax", "war", "Tax on the pot", "Taken before the podium is paid."),
    *[_pct(f"war.prizes.{i}", "war", f"Pot share of #{i + 1}", "After the tax, paid into the team's chest.")
      for i in range(3)],
    *[_b(f"war.points.{k}", "war", f"Points: {label}", max=1000) for k, label in (
        ("duel", "duel won against an enemy"), ("rob", "robbery on an enemy"),
        ("rob_stopped", "enemy robbery stopped"), ("raid", "raid won"), ("raid_defended", "raid pushed back"))],
    _b("war.duel_pair_cap", "war", "Duel wins a day per pair", "Wins of one player over the same enemy that score "
       "in a day.", max=100),
    _b("war.raid_min_attackers", "war", "Raid: attackers (min)", min=1, max=10),
    _b("war.raid_max_attackers", "war", "Raid: attackers (max)", min=1, max=10),
    _b("war.raid_max_defenders", "war", "Raid: defenders (max)", min=1, max=10),
    _b("war.raid_gather_minutes", "war", "Raid: minutes to gather", min=1, max=120),
    _b("war.raid_defend_minutes", "war", "Raid: minutes to defend", "Between the call and the assault.",
       min=1, max=600),
    _pct("war.raid_steal", "war", "Raid: share of the chest taken"),
    _b("war.raid_steal_max", "war", "Raid: most emeralds taken", max=10_000_000),
    _b("war.raids_per_day", "war", "Raids a team launches a day", min=1, max=20),
    _b("war.raid_protection_hours", "war", "Hours a raided chest is safe", kind="float", max=720),
    _b("war.raid_max_rounds", "war", "Raid: fight rounds (max)", min=1, max=500),
    # ---- beacon ----
    *[_b(f"beacon.level_ingots.{i}", "beacon", f"Level {i + 1}: ingots", "Ingots for this level in one material "
         "(a multiple of 9: whole blocks).", min=9, max=1_000_000) for i in range(4)],
    *[_b(f"beacon.multipliers.{m}", "beacon", f"{m.capitalize()}: effect ×", "A level built in this material gives "
         "its effects times this.", kind="float", max=100) for m in ("gold", "iron", "diamond", "netherite")],
    _pct("beacon.haste", "beacon", "Level 1: mining cooldown -", "In gold (times the material's multiplier)."),
    _pct("beacon.xp", "beacon", "Level 1: mining XP +", "In gold (times the material's multiplier)."),
    _pct("beacon.sell", "beacon", "Level 2: /sell +", "Blocks sold. In gold (times the material's multiplier)."),
    _pct("beacon.strength", "beacon", "Level 3: damage +", "In the dungeon and against the gate bosses. In gold "
         "(times the material's multiplier)."),
    _pct("beacon.resistance", "beacon", "Level 4: damage taken -", "In the dungeon and against the gate bosses. In "
         "gold (times the material's multiplier)."),
    _pct("beacon.upkeep", "beacon", "Weekly upkeep", "Share of the last step needed every week (rounded up to whole "
         "blocks); not given by Monday, that step is undone. 0 = none."),
    _b("beacon.contributor_value", "beacon", "Contributor: emeralds' worth a week", "Giving this much this week also "
       "gives the contributor bonus. 0 = none.", max=1_000_000),
    _pct("beacon.contributor_xp", "beacon", "Contributor: mining XP +"),
    _pct("beacon.contributor_sell", "beacon", "Contributor: /sell +"),
    # ---- gate bosses ----
    _b("gate_bosses.max_players", "bosses", "Players per group (max)", "A boss is made for this many.", min=1, max=10),
    _b("gate_bosses.hp", "bosses", "Each player's health", min=1, max=1000),
    _b("gate_bosses.lobby_minutes", "bosses", "Minutes to start a group", "Not started by then: cancelled, entries back.",
       min=1, max=1440),
    _b("gate_bosses.turn_seconds", "bosses", "Seconds to play a turn", "Then the bot attacks for the player.",
       min=10, max=600),
    _b("gate_bosses.afk_turns", "bosses", "Missed turns before auto", "In a row: then the player's turns play by "
       "themselves.", min=1, max=20),
    _b("gate_bosses.cooldown_hours", "bosses", "Hours between two fights", "Per player, from the start of a fight.",
       kind="float", max=720),
    _b("gate_bosses.max_rounds", "bosses", "Boss turns before it wins", min=1, max=500),
    _b("gate_bosses.min_hit_after_armor", "bosses", "Smallest boss hit after armor", kind="float", max=100),
    _pct("gate_bosses.crit_chance", "bosses", "Boss critical hit chance", "0 = none."),
    _b("gate_bosses.crit_multiplier", "bosses", "Boss critical hit multiplier", kind="float", min=1, max=10),
    _b("gate_bosses.max_potions", "bosses", "Potions per player per fight", max=20),
    _pct("gate_bosses.repeat_reward", "bosses", "Bounty share for a boss already beaten"),
    *[f for key, name in (("wither", "Wither"), ("ender_dragon", "Dragon"), ("warden", "Warden")) for f in (
        _b(f"gate_bosses.{key}.entry", "bosses", f"{name}: entry (emeralds)", "Paid by each player; back if the group "
           "never starts."),
        _b(f"gate_bosses.{key}.boss_hp", "bosses", f"{name}: health", "For a full group (see below for smaller ones).",
           kind="float", min=1, max=1_000_000),
        *[_pct(f"gate_bosses.{key}.small_group_hp.{i}", "bosses", f"{name}: health share for {i + 1} player(s)",
               "A smaller group faces this share of the boss's health.") for i in range(3)],
        _b(f"gate_bosses.{key}.min_damage", "bosses", f"{name}: smallest hit", "Before armor.", kind="float", max=1000),
        _b(f"gate_bosses.{key}.max_damage", "bosses", f"{name}: biggest hit", "Before armor.", kind="float", max=1000),
        _b(f"gate_bosses.{key}.bounty", "bosses", f"{name}: bounty (emeralds)", "For each survivor of a victory "
           "(Looting adds to it)."),
        _b(f"gate_bosses.{key}.xp", "bosses", f"{name}: XP for each survivor", max=1_000_000),
    )],
    _b("gate_bosses.wither.wither_damage", "bosses", "Wither: withering per turn", "Health lost on its next turns, "
       "no armor.", kind="float", max=1000),
    _b("gate_bosses.wither.wither_turns", "bosses", "Wither: withering turns", max=20),
    _b("gate_bosses.ender_dragon.strikes", "bosses", "Dragon: strikes per turn", "On players at random.", min=1, max=10),
    _b("gate_bosses.ender_dragon.breath_every", "bosses", "Dragon: breath every X turns", "On everyone; no shield "
       "stops it.", min=1, max=100),
    _b("gate_bosses.ender_dragon.breath_min", "bosses", "Dragon: smallest breath", kind="float", max=1000),
    _b("gate_bosses.ender_dragon.breath_max", "bosses", "Dragon: biggest breath", kind="float", max=1000),
    _b("gate_bosses.warden.boom_every", "bosses", "Warden: Sonic Boom every X turns", "Ignores armor and shields.",
       min=1, max=100),
    _b("gate_bosses.warden.boom_min", "bosses", "Warden: smallest Sonic Boom", kind="float", max=1000),
    _b("gate_bosses.warden.boom_max", "bosses", "Warden: biggest Sonic Boom", kind="float", max=1000),
    # ---- seasons & challenges ----
    _b("seasons.rewards", "seasons", "Season podium rewards", "Emeralds for #1, #2, #3… of the weekly season.",
       "list", None, item="int", max_items=10),
    _b("challenges.per_week", "challenges", "Challenges per week", "Never the same as the week before when the "
       "pool has enough others.", max=len(settings.DEFAULTS["challenges"]["goals"])),
    _b("challenges.per_day", "challenges", "Challenges per day", "0 = no daily challenges. Never the same as the "
       "day before when the pool has enough others.", max=len(settings.DEFAULTS["challenges"]["daily_goals"])),
    *_challenge_fields(),
    # ---- achievements ----
    *_achievement_fields(),
    # ---- teams ----
    _b("teams.max_members", "teams", "Max members per team", min=2, max=25),
    _b("teams.create_cost", "teams", "Team creation cost", "0 = free."),
    _b("teams.min_members_ranked", "teams", "Members who scored, to be ranked", min=1, max=25),
    _b("teams.invite_hours", "teams", "Invitations last (hours)", min=1, max=720),
    _b("teams.space_cost", "teams", "Team category price", "Paid once by the leader (/team category) for the team's "
       "private category, where the leader creates channels. 0 = free."),
    _b("teams.max_channels", "teams", "Channels per team category", "Text and voice channels together.", min=1,
       max=20),
    _pct("teams.xp_bonus_per_active_member", "teams", "XP bonus per active teammate",
         "For each other member who mined today."),
    _pct("teams.max_xp_bonus", "teams", "Max team XP bonus", max=10),
    _b("teams.season_rewards", "teams", "Team season rewards", "Emeralds for the #1, #2, #3… teams, shared by "
       "what each member brought.", "list", None, item="int", max_items=10),
    _b("teams.log_score", "teams", "Logarithmic team score", "On: the best earner counts in full, the others less "
       "and less, so 5 members earning the same score ×2.6 instead of ×5 (big teams don't win just by being big). "
       "Off: the sum of what the members earned.", kind="bool", min=None),
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
    _pct("villager.exclusive_mending_chance", "villager", "Exclusive offer: chance of Mending",
         "The exclusive offer is a Mending book this often (checked first)."),
    _b("villager.mending_price", "villager", "Price of a Mending book", min=1),
    _pct("villager.exclusive_book_chance", "villager", "Exclusive offer: chance of a book",
         "Else, the exclusive offer is a level III book this often, or a reinforced potion."),
    *[_b(f"villager.book_weights.{i}", "villager", f"Book in his goods: weight of level {ROMAN[i]}",
         "Chances = this weight ÷ the total of both weights. 0 = never.", kind="float") for i in range(2)],
    *[_b(f"villager.buys.{b}", "villager", f"He buys {block_name(b)} by (0 = never)", "How many blocks he buys at once.", max=100_000)
      for b in BLOCK_TYPES],
    _b("villager.goods", "villager", "His goods", "What he can sell (one is picked for each visit).", "table", None,
       item="goods"),
    # ---- mini-games ----
    # shared by every game of chance first: they're the ones changed most
    _b("games.min_bet", "chance", "Games of chance: minimum bet", "Lucky Block, wheel, blackjack and mines.", min=1),
    _b("games.max_bet", "chance", "Games of chance: maximum bet", "Lucky Block, wheel, blackjack and mines.", min=1),
    _b("games.cooldown_seconds", "chance", "Games of chance: seconds between 2 games",
       "Each game counts its own wait (Lucky Block, wheel, blackjack, mines).", max=3600),
    _b("games.daily_win_cap", "chance", "Daily limit at games of chance", "Once a player won this much today at the "
       "games of chance (winnings minus losses), they play again tomorrow. 0 = no limit.", max=1_000_000),
    _b("games.move_minutes", "chance", "Blackjack & mines: minutes to play a move",
       "Then the game ends by itself (blackjack: stand; mines: cash out, or the bet back if nothing was dug).",
       min=1, max=60),
    _b("games.blackjack_enabled", "chance", "Blackjack open", "Off: /blackjack says it's closed.", kind="bool"),
    _b("games.blackjack_natural_payout", "chance", "Blackjack: a blackjack pays (×bet)",
       "On top of the bet back: 1.5 = 3:2.", kind="float", min=1, max=10),
    _b("games.blackjack_dealer_stands", "chance", "Blackjack: the dealer draws up to", min=12, max=21),
    _b("games.mines_enabled", "chance", "Mines open", "Off: /mines says it's closed.", kind="bool"),
    _pct("games.mines_return", "chance", "Mines: share of a fair game paid",
         "95% = the bank keeps 5% of every cash out on average.", max=1),
    _b("games.mines_tnt_max", "chance", "Mines: most TNT a player can hide", "In the 20 blocks.", min=1, max=19),
    _b("games.mines_max_multiplier", "chance", "Mines: cash out by itself at (×bet)",
       "Keeps a lucky streak from winning millions.", kind="float", min=1, max=10_000),
    _b("games.roulette_enabled", "chance", "Wheel open", "Off: /wheel says it's closed.", kind="bool"),
    _b("games.roulette_zeros", "chance", "Wheel: Diamond blocks (green slots)", "The Diamond blocks make the bank "
       "win a little on average.", kind="choice", min=None,
       choices=(("1: 0 only (the bank keeps 2.7%)", 1), ("2: 0 and 00 (the bank keeps 5.3%)", 2))),
    *[_b(f"games.roulette_bets.{key}", "chance", f"Wheel: bets on {name}", "On: players can bet on it.", kind="bool",
         min=None)
      for key, name in (("red", "Redstone"), ("black", "Obsidian"), ("green", "Diamond block"), ("even", "even"),
                        ("odd", "odd"), ("low", "1-18"), ("high", "19-36"), ("dozens", "dozens"),
                        ("number", "a number"))],
    *[f for key, name in (('creeper', 'Creeper'), ('cobblestone', 'Cobblestone'), ('iron', 'Iron'), ('gold', 'Gold'), ('diamond', 'Diamonds'), ('emerald', 'Emeralds'), ('netherite', 'Netherite')) for f in (
        _b(f"games.lucky_block.{key}.weight", "chance", f"Lucky Block: {name} weight",
           "How often it falls out, compared with the others (0 = never).", max=100_000),
        _b(f"games.lucky_block.{key}.payout", "chance", f"Lucky Block: {name} pays (×bet)",
           "Times the bet, the bet included: 0 = lost, 1 = the bet back.", kind="float", max=1000),
    )],
    *[_b(f"games.blockdle_rewards.{i}", "minigames", f"Blockdle reward: {i + 1}{'+' if i == 9 else ''} guess{'es' if i else ''}",
         "Emeralds for finding the block of the day in this many guesses.") for i in range(10)],
    _b("games.blockdle_xp", "minigames", "Blockdle: XP for finding the block"),
    _b("games.blockdle_no_repeat_days", "minigames", "Blockdle: days before a block comes back",
       "A block of the day isn't picked again for this many days (when there are enough blocks).", max=180),
    _b("games.quiz_every_minutes", "minigames", "Quiz: a question every X minutes",
       "Posted in a game channel. 0 = only with /event quiz.", max=10_080),
    _pct("games.quiz_every_jitter", "minigames", "Quiz: give or take (%)",
         "25% = a question every 45 to 75 minutes when it's every 60.", max=0.9),
    _b("games.quiz_no_repeat", "minigames", "Quiz: questions not asked again soon",
       "The last N questions asked aren't picked again (when there are enough).", max=100),
    _b("games.quiz_seconds", "minigames", "Quiz: seconds to answer", min=10, max=600),
    _b("games.quiz_reward", "minigames", "Quiz: emeralds for the right answer"),
    _b("games.quiz_xp", "minigames", "Quiz: XP for the right answer"),
    # ---- robberies ----
    _b("live_events.daily_random", "live_events", "A random event every day",
       "On: one event comes by itself every day, at a random time. The staff can always start one with /event start.",
       kind="bool", min=None),
    _b("live_events.earliest_hour", "live_events", "Random event: from (hour, 0-23)", "Server time.", max=23),
    _b("live_events.latest_hour", "live_events", "Random event: until (hour, 0-23)",
       "It starts before this hour.", max=23),
    _b("live_events.duration_minutes", "live_events", "How long an event lasts (minutes)",
       "Also the default of /event start.", min=1, max=1440),
    *[_b(f"live_events.random_kinds.{key}", "live_events", f"Random: {name}",
         "On: it can come by itself. The staff can start it anyway.", kind="bool", min=None)
      for key, name in (("gambling_frenzy", "🎰 Gambling Frenzy"), ("mining_rush", "⛏️ Mining Rush"),
                        ("golden_hour", "💰 Golden Hour"), ("lucky_hour", "🍀 Lucky Hour"),
                        ("market_sale", "🏷️ Market Sale"))],
    _b("live_events.frenzy_multiplier", "live_events", "Gambling Frenzy: bets ×",
       "The maximum bet and the daily limit of the Lucky Block and the wheel are multiplied by this.",
       kind="float", min=1, max=10),
    _b("live_events.rush_xp_multiplier", "live_events", "Mining Rush: mining XP ×", kind="float", min=1, max=10),
    _pct("live_events.golden_sell_bonus", "live_events", "Golden Hour: /sell bonus for blocks",
         "Added to the price of blocks (it counts for the season, like the Trader bonus).", max=5),
    _b("live_events.lucky_rare_multiplier", "live_events", "Lucky Hour: obsidian & bedrock ×",
       "Their weight when mining is multiplied by this.", kind="float", min=1, max=10),
    _pct("live_events.market_sale_discount", "live_events", "Market Sale: /market discount"),
    _b("rob.risky_min", "rob", "Risky robbery: minimum loot", "The victim is pinged. Never more than they have."),
    _b("rob.risky_max", "rob", "Risky robbery: maximum loot"),
    _b("rob.discreet_min", "rob", "Discreet robbery: minimum loot", "Nobody is pinged. Never more than they have."),
    _b("rob.discreet_max", "rob", "Discreet robbery: maximum loot"),
    _b("rob.minutes_to_stop", "rob", "Minutes the victim has to stop it", min=1, max=1440),
    _b("rob.fine_percent", "rob", "Fine when stopped (% of the loot)",
       "Paid by the thief to the victim (never more than the thief has).", max=1000),
    _b("rob.cooldown_hours", "rob", "Hours between two robberies (thief)", kind="float", max=720),
    _b("rob.victim_protection_hours", "rob", "Hours a robbed player is protected", kind="float", max=720),
    _b("rob.min_victim_level", "rob", "Players below this level are safe", max=10_000),
    _b("rob.night_start_hour", "rob", "Night: no robbery from (hour, 0-23)",
       "Server time. A robbery started before keeps going. Same hour as the end = robberies all day.", max=23),
    _b("rob.night_end_hour", "rob", "Night: robberies again at (hour, 0-23)", max=23),
    # ---- profiles ----
    _b("profiles.bio_max", "profiles", "Bio: maximum characters", min=10, max=300),
    _b("profiles.color_price", "profiles", "Price of a profile color", "Each of the 16 dye colors, bought once."),
    _b("profiles.hex_price", "profiles", "Price of custom #hex colors", "Paid once: then any #hex color."),
    _b("profiles.banner_cost", "profiles", "Price of a team banner change", "Paid by the leader."),
    *[_b(f"profiles.frame_prices.{key}", "profiles", f"Frame price: {name}", "The rarer frames are earned, not sold.")
      for key, name in (("stone", "Stone"), ("gold", "Gold"), ("redstone", "Redstone"), ("lapis", "Lapis"),
                        ("diamond", "Diamond"), ("emerald", "Emerald"))],
    *[_b(f"profiles.frame_goals.{key}", "titles", f"Frame to earn: {frame.name}"[:45],
         f"Earned when: {_with_n(frame.text)}.", min=1, max=10_000_000)
      for key, frame in _profile_frames() if frame.what],
    *[_b(f"profiles.title_goals.{key}", "titles", f"Title: {title.name}"[:45],
         f"Earned when: {_with_n(title.text)}.", min=1, max=10_000_000)
      for key, title in _profile_titles()],
    # ---- guide ----
    _b("guide.reward", "guide", "Checklist reward", "Emeralds for doing every step of the guide, paid once per player."),
    _b("guide.delete_after_days", "guide", "Days before a finished guide is deleted",
       "After the checklist is done (0 = kept). The player can delete it sooner with a button.", kind="float",
       max=365),
    _b("guide.expire_days", "guide", "Days before an unfinished guide is deleted",
       "If the checklist is never done (0 = kept). Progress is kept: /guide opens a new one.", kind="float", max=365),
    # ---- PVE dungeon ----
    _b("pve.hp", "pve", "Health of a player", "Not restored between waves.", min=1, max=1000),
    _b("pve.max_players", "pve", "Players per group", min=1, max=10),
    _b("pve.cooldown_minutes", "pve", "Minutes between two runs", "From the start of a run.", max=10_080),
    _b("pve.lobby_minutes", "pve", "Minutes to start a group", "Then it's cancelled and refunded.", min=1, max=60),
    _b("pve.decision_minutes", "pve", "Minutes to decide between waves",
       "Then everyone still in leaves with their loot.", min=1, max=60),
    _b("pve.max_potions", "pve", "Potions per player and run", "Reinforced (II) ones: see Potions.", max=20),
    _pct("pve.group_monsters", "pve", "Monsters added per extra player",
         "100% = each player in the group adds a whole wave of monsters.", max=5),
    _b("pve.min_hit_after_armor", "pve", "Smallest monster hit after armor", "Armor never lowers a hit below "
       "this.", kind="float", max=10),
    *[f for key, name in (("zombie", "Zombie"), ("skeleton", "Skeleton"), ("spider", "Spider"),
                          ("creeper", "Creeper"), ("ravager", "Ravager")) for f in (
        _b(f"pve.monsters.{key}.hp", "pve_monsters", f"{name}: health", "At Normal difficulty, wave 1.", kind="float",
           min=0.1, max=1000),
        _b(f"pve.monsters.{key}.min_damage", "pve_monsters", f"{name}: smallest hit", "At Normal difficulty, wave 1, "
           "before armor.", kind="float", max=100),
        _b(f"pve.monsters.{key}.max_damage", "pve_monsters", f"{name}: biggest hit", "At Normal difficulty, wave 1, "
           "before armor.", kind="float", max=100),
    )],
    _pct("pve.wave_growth", "pve", "Monsters stronger each wave", "Health and damage.", max=2),
    _pct("pve.clear_bonus", "pve", "Bonus for clearing wave 5", "Added to the loot.", max=10),
    _b("pve.xp_per_wave", "pve", "XP per wave cleared", max=10_000),
    *[_b(f"pve.wave_rewards.{i}", "pve", f"Wave {i + 1} reward (× difficulty)",
         "Emeralds for clearing this wave, multiplied by the difficulty's reward. Lost on death.")
      for i in range(5)],
    *[f for key, name in (("easy", "Easy"), ("normal", "Normal"), ("hard", "Hard"), ("hardcore", "Hardcore"),
                          ("nightmare", "Nightmare"))
      for f in (
          _b(f"pve.difficulties.{key}.entry", "pve", f"{name}: entry fee"),
          _b(f"pve.difficulties.{key}.strength", "pve", f"{name}: monster strength",
             "Multiplies the monsters' health and damage (Normal = 1).", kind="float", min=0.1, max=100),
          _b(f"pve.difficulties.{key}.reward", "pve", f"{name}: reward multiplier",
             "Multiplies the wave rewards.", kind="float", min=0, max=1000),
      )],
    _pct("pve.difficulties.nightmare.group_monsters", "pve", "Nightmare: monsters added per extra player",
         "Its own share (the others use \"Monsters added per extra player\"): lower = a raid for a full group.",
         max=5),
    # ---- species ----
    _b("species.change_cost", "species", "Cost to change species", "The first choice is free."),
    _b("species.change_days", "species", "Days between two changes", kind="float", max=365),
    _pct("species.villager_trade", "species", "Villager: better prices",
         "/sell gives more, the market and the wandering villager's goods cost less, he pays more for blocks."),
    _pct("species.dwarf_damage", "species", "Dwarf: more damage", "Every fight: duels, tournaments, bosses, the dungeon, the dummy."),
    _pct("species.witch_potions", "species", "Witch: stronger potions", "Potion effects in duels and the dungeon."),
    _pct("species.mage_enchants", "species", "Mage: stronger enchantments", "Every enchantment effect."),
    _pct("species.miner_speed", "species", "Miner: shorter mining cooldown"),
    _pct("species.gambler_max_bet", "species", "Gambler: higher maximum bet",
         "At the Lucky Block and the wheel: 50% = 300 when the others can bet 200.", max=10),
    # ---- loans ----
    _b("loans.min_amount", "loans", "Smallest loan", min=1),
    _b("loans.max_amount", "loans", "Biggest loan", min=1),
    _pct("loans.max_interest", "loans", "Highest interest", "The lender picks the interest, from 0 up to this."),
    _b("loans.min_days", "loans", "Shortest loan (days)", min=1, max=365),
    _b("loans.max_days", "loans", "Longest loan (days)", min=1, max=365),
    _b("loans.max_loans_out", "loans", "Unpaid loans a lender can have", min=1, max=100),
    _b("loans.offer_minutes", "loans", "Minutes to accept an offer", min=1, max=1440),
    _pct("loans.late_penalty", "loans", "Late penalty", "Added to what's left at the deadline."),
    _pct("loans.garnish", "loans", "Taken from a late borrower's income",
         "Share of every emerald a late borrower receives that goes to the lender until it's paid."),
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
LEGACY_COOLDOWN = ("economy", "cooldown_seconds")  # old place of balance.mining.cooldown_seconds


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
    if field.path == ("balance", "mining", "cooldown_seconds") and _get(cfg, LEGACY_COOLDOWN) is not None:
        # The old economy.cooldown_seconds would come back as soon as the new key is the default again.
        cfg = set_value(cfg, LEGACY_COOLDOWN, None)
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


# ---------------- roles the bot gives out ----------------
# A role with one of these is never given out by the bot (staff and admin powers).
POWERS = ("administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks", "manage_messages",
          "manage_nicknames", "manage_threads", "manage_events", "ban_members", "kick_members", "moderate_members",
          "mention_everyone", "view_audit_log", "move_members", "mute_members", "deafen_members")


def safe_to_give(permissions: Any) -> bool:
    """A role the bot may give out automatically: no staff or admin power (`permissions`: discord.Permissions)."""
    return not any(getattr(permissions, p, False) for p in POWERS)


def roles_in_use(cfg: dict, keep: tuple = ()) -> set[int]:
    """Roles already set in another role setting (`keep`: the path of the setting being changed)."""
    roles = cfg.get("roles", {}) or {}
    used: set[int] = set()
    for key, value in roles.items():
        if ("roles", key) == tuple(keep):
            continue
        if key == "level_roles" and isinstance(value, dict):
            if tuple(keep[:2]) != ("roles", "level_roles"):
                used |= {int(v) for v in value.values() if int(v or 0)}
        elif isinstance(value, int) and value:
            used.add(value)
    return used
