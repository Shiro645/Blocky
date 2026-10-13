"""Species (/species): every player can pick one, for a small bonus.

- 🧑‍🌾 Villager: better prices. /sell gives more, the market and the wandering
  villager's goods cost less, and he pays more for blocks.
- 🪓 Dwarf: more damage in every fight (duels, tournaments, bosses, the dungeon
  and the training dummy).
- 🧪 Witch: stronger potions in duels and in the dungeon.
- 🔮 Mage: stronger enchantments.
- ⚒️ Miner: a shorter mining cooldown.

The first choice is free. Changing costs `change_cost` emeralds and is possible
once every `change_days` days. The staff can set anyone's species.
"""
from __future__ import annotations

from dataclasses import dataclass

from game import guide, players, settings
from game.db import Ctx
from game.errors import GameError

DAY = 86400


@dataclass(frozen=True)
class Species:
    key: str
    name: str
    emoji: str
    setting: str  # its bonus in settings "species"
    text: str  # what the bonus does, "{}" = the bonus in %


SPECIES: dict[str, Species] = {
    "villager": Species("villager", "Villager", "🧑‍🌾", "villager_trade",
                        "{} better prices: /sell, the market and the wandering villager"),
    "dwarf": Species("dwarf", "Dwarf", "🪓", "dwarf_damage", "+{} damage in every fight: duels, tournaments, bosses, the dungeon"),
    "witch": Species("witch", "Witch", "🧪", "witch_potions", "+{} potion effects in duels and the dungeon"),
    "mage": Species("mage", "Mage", "🔮", "mage_enchants", "+{} enchantment effects"),
    "miner": Species("miner", "Miner", "⚒️", "miner_speed", "{} shorter mining cooldown"),
}


def _cfg() -> dict:
    return settings.get()["species"]


def value(key: str) -> float:
    """The bonus of a species (0.05 = 5%)."""
    return float(_cfg()[SPECIES[key].setting])


def describe(key: str) -> str:
    return SPECIES[key].text.format(f"{value(key) * 100:g}%")


def label(key: str | None) -> str:
    return f"{SPECIES[key].emoji} {SPECIES[key].name}" if key in SPECIES else "None"


def of(ctx: Ctx, user_id: int) -> str | None:
    row = ctx.one("SELECT species FROM users WHERE user_id=?;", (user_id,))
    return row["species"] if row and row["species"] in SPECIES else None


def bonus(ctx: Ctx, user_id: int, key: str) -> float:
    """The player's bonus of species `key` (0 if they are another species)."""
    return value(key) if of(ctx, user_id) == key else 0.0


def emojis(ctx: Ctx, user_ids: list[int]) -> dict[int, str]:
    """user_id -> the emoji of their species (players without one are left out)."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = ctx.all(f"SELECT user_id, species FROM users WHERE user_id IN ({marks});", tuple(ids))
    return {r["user_id"]: SPECIES[r["species"]].emoji for r in rows if r["species"] in SPECIES}


def change_terms(ctx: Ctx, user_id: int) -> dict:
    """What choosing a species costs this player now: {"current", "cost", "ready_at", "ready"}."""
    user = players.get_user(ctx, user_id)
    current = user["species"] if user["species"] in SPECIES else None
    if current is None:
        return {"current": None, "cost": 0, "ready_at": 0, "ready": True}
    ready_at = int((user["species_changed_at"] or 0) + float(_cfg()["change_days"]) * DAY)
    return {"current": current, "cost": int(_cfg()["change_cost"]), "ready_at": ready_at, "ready": ctx.now >= ready_at}


def choose(ctx: Ctx, user_id: int, key: str) -> dict:
    if key not in SPECIES:
        raise GameError("Unknown species.")
    terms = change_terms(ctx, user_id)
    if terms["current"] == key:
        raise GameError(f"You are already a {label(key)}.")
    if terms["current"] is not None:
        if not terms["ready"]:
            raise GameError(f"You can change your species again <t:{terms['ready_at']}:R>.")
        players.spend_emeralds(ctx, user_id, terms["cost"])
    ctx.execute("UPDATE users SET species=?, species_changed_at=? WHERE user_id=?;", (key, int(ctx.now), user_id))
    guide.check(ctx, user_id)
    return {"species": key, "before": terms["current"], "cost": terms["cost"]}


def staff_set(ctx: Ctx, user_id: int, key: str | None) -> dict:
    """Staff: set a player's species (None = none), for free and without waiting."""
    if key is not None and key not in SPECIES:
        raise GameError("Unknown species.")
    before = of(ctx, user_id)
    players.ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET species=? WHERE user_id=?;", (key, user_id))
    guide.check(ctx, user_id)
    return {"species": key, "before": before}


def counts(ctx: Ctx) -> dict[str, int]:
    rows = ctx.all("SELECT species, COUNT(*) AS n FROM users WHERE species IS NOT NULL GROUP BY species;")
    found = {r["species"]: r["n"] for r in rows}
    return {key: found.get(key, 0) for key in SPECIES}


def all_species(ctx: Ctx) -> dict[int, str]:
    """user_id -> species, for the role sync."""
    return {r["user_id"]: r["species"] for r in ctx.all("SELECT user_id, species FROM users WHERE species IS NOT NULL;")
            if r["species"] in SPECIES}
