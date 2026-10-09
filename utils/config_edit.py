"""Settings staff can change from Discord with /config, and how config.json is rewritten.

Only the settings listed in FIELDS can be changed. Secrets and dangerous keys
(PROTECTED) can never be read or written from Discord.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game import settings

PROTECTED = (
    ("minecraft", "rcon_password"),
    ("staff", "role_id"),
    ("database_path",),
)

CATEGORIES = {
    "channels": "📢 Channels",
    "roles": "🎭 Roles",
    "level_roles": "⭐ Level roles",
    "market": "🛒 Market prices",
    "blocks": "🪨 Block sell values",
    "gameplay": "🎮 Gameplay",
    "teams": "🛡️ Teams",
    "tournament": "🏟️ Tournament",
    "enchants": "✨ Enchanting",
    "potions": "🧪 Duels & potions",
    "minecraft": "🌍 Minecraft texts",
}


@dataclass(frozen=True)
class Field:
    key: str
    category: str
    label: str
    path: tuple[str, ...]
    kind: str  # channel | role | int | float | text
    min: float | None = None
    max: float | None = None

    @property
    def is_balance(self) -> bool:
        return self.path[0] == "balance"


def _balance(key, category, label, *path, kind="int", min=0, max=None):
    return Field(key, category, label, ("balance",) + path, kind, min, max)


FIELDS: list[Field] = [
    Field("ch_announcements", "channels", "Announcements channel", ("channels", "announcements"), "channel"),
    Field("ch_events", "channels", "Events channel (drops, bosses)", ("channels", "events"), "channel"),
    Field("ch_staff_log", "channels", "Staff channel (/link, logs)", ("channels", "staff_log"), "channel"),
    Field("role_event_ping", "roles", "Role pinged for bosses", ("roles", "event_ping"), "role"),
    Field("role_champion", "roles", "Season champion role", ("roles", "season_champion"), "role"),
    Field("role_tournament", "roles", "Tournament champion role", ("roles", "tournament_champion"), "role"),
    _balance("stick_price", "market", "Sticks: price of a pack", "market", "stick_pack", "price", min=1),
    _balance("stick_amount", "market", "Sticks: sticks per pack", "market", "stick_pack", "amount", min=1),
    _balance("gold_price", "market", "Gold ingot price", "market", "ingots", "gold", min=1),
    _balance("iron_price", "market", "Iron ingot price", "market", "ingots", "iron", min=1),
    _balance("diamond_price", "market", "Diamond price", "market", "ingots", "diamond", min=1),
    _balance("netherite_price", "market", "Netherite ingot price", "market", "ingots", "netherite", min=1),
    _balance("cobblestone_value", "blocks", "Cobblestone", "block_values", "cobblestone"),
    _balance("gravel_value", "blocks", "Gravel", "block_values", "gravel"),
    _balance("deepslate_value", "blocks", "Deepslate", "block_values", "deepslate"),
    _balance("obsidian_value", "blocks", "Obsidian", "block_values", "obsidian"),
    _balance("bedrock_value", "blocks", "Bedrock", "block_values", "bedrock"),
    _balance("mining_cooldown", "gameplay", "Mining cooldown (seconds)", "mining", "cooldown_seconds", max=3600),
    _balance("daily_base", "gameplay", "Daily: base reward", "daily", "base_reward"),
    _balance("daily_streak", "gameplay", "Daily: bonus per streak day", "daily", "streak_bonus_per_day"),
    _balance("duel_min_stake", "gameplay", "Duel: minimum stake", "duel", "min_stake", min=1),
    _balance("auction_tax", "gameplay", "Auction tax (%)", "auction", "tax_percent", max=100),
    _balance("drop_chance", "gameplay", "Drop chance per message (0-1)", "drops", "chance", kind="float", max=1),
    _balance("drop_interval", "gameplay", "Min. seconds between drops", "drops", "min_interval_seconds"),
    _balance("boss_hp", "gameplay", "Boss HP", "boss", "hp", min=1),
    _balance("boss_auto", "gameplay", "Automatic boss every X hours (0 = off)", "boss", "auto_spawn_hours", kind="float"),
    _balance("boss_pool", "gameplay", "Boss reward pool", "boss", "reward_pool"),
    _balance("backup_keep", "gameplay", "Backups kept", "backups", "keep", min=1, max=365),
    _balance("team_max", "teams", "Max members per team", "teams", "max_members", min=2, max=25),
    _balance("team_cost", "teams", "Team creation cost", "teams", "create_cost"),
    _balance("team_invite", "teams", "Invitations last (hours)", "teams", "invite_hours", min=1, max=720),
    _balance("team_bonus", "teams", "XP bonus per active teammate (0-1)", "teams", "xp_bonus_per_active_member", kind="float", max=1),
    _balance("team_bonus_max", "teams", "Max team XP bonus (0-1)", "teams", "max_xp_bonus", kind="float", max=1),
    _balance("tn_fee", "tournament", "Entry fee", "tournament", "entry_fee"),
    _balance("tn_bonus", "tournament", "Server bonus added to the pot", "tournament", "house_bonus"),
    _balance("tn_min", "tournament", "Minimum players (else cancelled)", "tournament", "min_players", min=2, max=128),
    _balance("tn_max", "tournament", "Maximum players", "tournament", "max_players", min=2, max=128),
    _balance("tn_opens_day", "tournament", "Registrations open: day (0=Mon, 6=Sun)", "tournament", "opens_day", max=6),
    _balance("tn_opens_hour", "tournament", "Registrations open: hour (0-23)", "tournament", "opens_hour", max=23),
    _balance("tn_closes_day", "tournament", "Registrations close: day (0=Mon, 6=Sun)", "tournament", "closes_day", max=6),
    _balance("tn_closes_hour", "tournament", "Registrations close: hour (0-23)", "tournament", "closes_hour", max=23),
    _balance("tn_start_day", "tournament", "First round: day (0=Mon, 6=Sun)", "tournament", "start_day", max=6),
    _balance("tn_start_hour", "tournament", "First round: hour (0-23)", "tournament", "start_hour", max=23),
    _balance("tn_round", "tournament", "Minutes between rounds", "tournament", "round_minutes", min=1, max=1440),
    _balance("tn_xp", "tournament", "XP per match won", "tournament", "xp_per_win"),
    _balance("ench_lapis", "enchants", "Lapis chance per mining reward (0-1)", "enchants", "lapis_chance", kind="float", max=1),
    _balance("ench_lapis_value", "enchants", "Lapis value (fortune, fair prices)", "enchants", "lapis_value"),
    _balance("duel_turn", "potions", "Duel: seconds per turn", "duel", "turn_seconds", min=10, max=300),
    _balance("duel_afk", "potions", "Duel: missed turns before auto play", "duel", "afk_turns", min=1, max=10),
    _balance("pot_max", "potions", "Potions per duel (per player)", "potions", "max_per_duel", max=20),
    _balance("pot_strength", "potions", "Strength: attack bonus (0.5 = +50%)", "potions", "strength_bonus", kind="float", max=5),
    _balance("pot_speed", "potions", "Speed: double hit chance (0-1)", "potions", "speed_chance", kind="float", max=1),
    _balance("pot_speed_turns", "potions", "Speed: turns", "potions", "speed_turns", min=1, max=10),
    _balance("pot_healing", "potions", "Healing: HP", "potions", "healing_hp", kind="float", max=100),
    _balance("pot_harming", "potions", "Harming: direct damage", "potions", "harming_damage", kind="float", max=100),
    _balance("pot_boss", "potions", "Boss: top N fighters get a potion", "potions", "boss_top", max=50),
    Field("mc_ip_text", "minecraft", "/ip text", ("minecraft", "public_ip_text"), "text"),
    Field("mc_modpack_text", "minecraft", "/modpacks text", ("minecraft", "modpack_text"), "text"),
]
FIELDS_BY_KEY = {f.key: f for f in FIELDS}


def fields_in(category: str) -> list[Field]:
    return [f for f in FIELDS if f.category == category]


def _check_path(path: tuple[str, ...]) -> None:
    if any(path[: len(p)] == p for p in PROTECTED):
        raise PermissionError("This setting can't be changed from Discord.")


def _get(data: dict, path: tuple[str, ...]) -> Any:
    for part in path:
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def current_value(cfg: dict, field: Field) -> Any:
    """Value in config.json, or for balance settings the default when not overridden."""
    value = _get(cfg, field.path)
    if value is None and field.is_balance:
        value = _get(settings.DEFAULTS, field.path[1:])
    return value


def parse(field: Field, text: str) -> Any:
    """Turn what staff typed into a value. Empty text resets a balance setting (returns None)."""
    text = text.strip()
    if not text:
        if field.is_balance:
            return None
        if field.kind == "text":
            raise ValueError("The text can't be empty.")
    if field.kind == "text":
        return text
    try:
        value: float = float(text.replace(",", ".")) if field.kind == "float" else int(text)
    except ValueError:
        raise ValueError(f"“{text}” is not a {'number' if field.kind == 'float' else 'whole number'}.")
    if field.min is not None and value < field.min:
        raise ValueError(f"The minimum is {field.min:g}.")
    if field.max is not None and value > field.max:
        raise ValueError(f"The maximum is {field.max:g}.")
    return value


def set_value(cfg: dict, path: tuple[str, ...], value: Any) -> dict:
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
    else:
        node[path[-1]] = value
    return new


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
