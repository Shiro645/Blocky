"""Enchantments: books (levels I to VII) applied to gear with lapis lazuli.

Books and lapis are stackable items (items table): ("book", "<enchant>:<level>")
and ("lapis", "none"). Applying a book costs lapis and replaces a lower level
of the same enchantment. Two identical books combine into the next level, on an anvil.
Mending has a single level and is rare: never a random book (drops, challenges), only
the villager's exclusive offer and, sometimes, the book of each survivor of a gate boss victory.
Enchantments belong to the piece of gear: they follow it in trades and
auctions, and disappear when it breaks.
Random books are levels I to III. Levels IV to VII only come from combining, and a
player can only make or apply a level up to 3 + their dimension (Nether IV … Shimmer VII).
Curses (Binding, Vanishing) never come as books: only the enchanting table puts them on a piece
(game/enchanting_table.py), and they can't be removed.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from game import anvil, players, settings, species
from game.catalog import ARMOR, GEAR_ITEMS
from game.db import Ctx
from game.errors import GameError

MAX_LEVEL = 7
BASE_LEVEL = 3  # the highest level of random books, and of the overworld
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII"}
CURSABLE = tuple(i for i in GEAR_ITEMS if i != "shield")  # what the enchanting table enchants


@dataclass(frozen=True)
class Enchant:
    key: str
    name: str
    items: tuple[str, ...]
    setting: str  # the effect in settings "enchants": a list for level I / II / III, or one value (one level)
    max_level: int = MAX_LEVEL
    rare: bool = False  # never a random book, nor from the enchanting table
    curse: bool = False  # never a book: only the enchanting table puts it, and it can't be removed


ENCHANTS: dict[str, Enchant] = {
    e.key: e
    for e in (
        Enchant("efficiency", "Efficiency", ("pickaxe",), "efficiency_seconds"),
        Enchant("fortune", "Fortune", ("pickaxe", "shovel", "axe", "hoe"), "fortune_bonus"),
        Enchant("unbreaking", "Unbreaking", tuple(i for i in GEAR_ITEMS if i != "shield"), "unbreaking_chance"),
        Enchant("sharpness", "Sharpness", ("sword",), "sharpness_damage"),
        Enchant("looting", "Looting", ("sword",), "looting_boss_bonus"),
        Enchant("protection", "Protection", ARMOR, "protection_points"),
        Enchant("mending", "Mending", GEAR_ITEMS, "mending_durability_per_xp", max_level=1, rare=True),
        Enchant("fire_aspect", "Fire Aspect", ("sword",), "fire_aspect_damage"),
        Enchant("sweeping_edge", "Sweeping Edge", ("sword",), "sweeping_edge_share"),
        Enchant("thorns", "Thorns", ARMOR, "thorns_reflect"),
        Enchant("binding", "Curse of Binding", CURSABLE, "", max_level=1, rare=True, curse=True),
        Enchant("vanishing", "Curse of Vanishing", CURSABLE, "", max_level=1, rare=True, curse=True),
    )
}
RANDOM_BOOKS = tuple(sorted(k for k, e in ENCHANTS.items() if not e.rare))  # what a random book can be
CURSES = tuple(k for k, e in ENCHANTS.items() if e.curse)

_PART = re.compile(r"^([a-z_]+)([1-9])$")


def _cfg() -> dict:
    return settings.get()["enchants"]


def _per_level(values: list | float, level: int) -> float:
    if level <= 0:
        return 0.0
    if not isinstance(values, list):
        return float(values)  # a single-level enchantment
    return float(values[min(level, len(values)) - 1])


def bonus(name: str, level: int) -> float:
    """Effect of an enchantment at a level (0 when not enchanted; curses have no number)."""
    if ENCHANTS[name].curse:
        return float(level > 0)
    return _per_level(_cfg()[ENCHANTS[name].setting], level)


def boost_of(ctx: Ctx, user_id: int) -> float:
    """Multiplier of the enchantment effects of a player's gear (Mages: stronger)."""
    return 1.0 + species.bonus(ctx, user_id, "mage")


def effect(piece: dict | None, name: str) -> float:
    """Effect of an enchantment on a gear row, with its owner's species bonus (rows from attach)."""
    if not piece:
        return 0.0
    return bonus(name, level_of(piece, name)) * float(piece.get("enchant_boost", 1.0))


def hoe_xp_bonus(level: int) -> float:
    return _per_level(_cfg()["fortune_hoe_xp"], level)


def apply_cost(level: int) -> int:
    return int(_per_level(_cfg()["apply_cost"], level))


def protection_cap_bonus(level: int) -> float:
    """How much a piece's Protection raises the cap of the damage reduction (from IV on)."""
    return _per_level(_cfg()["protection_cap_bonus"], level)


def max_level_for(ctx: Ctx, user_id: int) -> int:
    """The highest level a player can make or apply: III in the overworld, +1 per dimension."""
    from game import dimensions  # dimensions depends on players, like this module

    return min(MAX_LEVEL, BASE_LEVEL + dimensions.level(ctx, user_id))


def _check_level(ctx: Ctx, user_id: int, level: int, what: str) -> None:
    top = max_level_for(ctx, user_id)
    if level > top:
        from game import dimensions
        from game.catalog import DIMENSIONS

        need = DIMENSIONS[min(level - BASE_LEVEL, len(DIMENSIONS) - 1)]
        raise GameError(f"You can't {what} a level {ROMAN[level]} book yet: your maximum is **{ROMAN[top]}**. "
                        f"Level {ROMAN[level]} needs the {dimensions.label(need)}.")


def label(name: str, level: int) -> str:
    if ENCHANTS[name].max_level == 1:
        return ENCHANTS[name].name
    return f"{ENCHANTS[name].name} {ROMAN.get(level, level)}"


def labels(enchants: dict[str, int]) -> str:
    return ", ".join(label(n, lvl) for n, lvl in sorted(enchants.items()))


def effect_text(name: str, level: int) -> str:
    v = bonus(name, level)
    if name == "efficiency":
        return f"mining cooldown -{v:g}s"
    if name == "fortune":
        return f"+{v:g} blocks / gravel / sticks, +{hoe_xp_bonus(level):.0%} XP (hoe)"
    if name == "unbreaking":
        return f"{v:.0%} chance to keep durability"
    if name == "sharpness":
        return f"+{v:g} maximum damage"
    if name == "looting":
        return f"+{v:.0%} boss reward"
    if name == "mending":
        return f"the XP you gain repairs it first ({v:g} durability per XP)"
    if name == "fire_aspect":
        return f"burns {int(_cfg()['fire_aspect_turns'])} turns, -{v:g}/turn"
    if name == "sweeping_edge":
        return f"{v * 100:g}% on a 2nd monster"
    if name == "thorns":
        return f"{v * 100:g}% sent back"
    if name == "binding":
        return "once worn, it can't be taken off, replaced, sold or traded until it breaks"
    if name == "vanishing":
        return "it vanishes if you fall in the dungeon, against a gate boss or at night"
    cap = protection_cap_bonus(level)
    return f"+{v:g} armor points" + (f", damage reduction cap +{cap:.0%}" if cap else "")


def level_of(piece: dict | None, name: str) -> int:
    """Level of an enchantment on a gear row (rows from gear.get_equipped / shop.get_gear)."""
    if not piece:
        return 0
    return int((piece.get("enchants") or {}).get(name, 0))


# ---------------- keys ----------------
def book_material(name: str, level: int) -> str:
    return f"{name}:{level}"


def parse_book(material: str) -> tuple[str, int]:
    """'sharpness:2' -> ('sharpness', 2)"""
    name, _, level = material.partition(":")
    if name not in ENCHANTS or ENCHANTS[name].curse or not level.isdigit() or not 1 <= int(level) <= ENCHANTS[name].max_level:
        raise GameError("Unknown book. Pick one from the suggestions.")
    return name, int(level)


def signature(enchants: dict[str, int]) -> str:
    """{'sharpness': 2, 'unbreaking': 1} -> 'sharpness2,unbreaking1' ('' when none)."""
    return ",".join(f"{n}{lvl}" for n, lvl in sorted(enchants.items()))


def parse_signature(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in text.split(","):
        m = _PART.match(part)
        if not m or m[1] not in ENCHANTS or not 1 <= int(m[2]) <= ENCHANTS[m[1]].max_level or m[1] in out:
            raise ValueError(f"Invalid enchantments: {text}")
        out[m[1]] = int(m[2])
    return out


# ---------------- gear ----------------
def of_gear(ctx: Ctx, gear_ids: list[int]) -> dict[int, dict[str, int]]:
    ids = list(dict.fromkeys(gear_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict[int, dict[str, int]] = {}
    for r in ctx.all(f"SELECT gear_id, enchant, level FROM gear_enchants WHERE gear_id IN ({marks});", tuple(ids)):
        out.setdefault(r["gear_id"], {})[r["enchant"]] = r["level"]
    return out


def attach(ctx: Ctx, rows: list[dict]) -> list[dict]:
    """Add an "enchants" dict to gear rows."""
    found = of_gear(ctx, [r["gear_id"] for r in rows])
    boosts: dict[int, float] = {}
    for r in rows:
        r["enchants"] = found.get(r["gear_id"], {})
        if "user_id" in r:
            if r["user_id"] not in boosts:
                boosts[r["user_id"]] = boost_of(ctx, r["user_id"])
            r["enchant_boost"] = boosts[r["user_id"]]
    return rows


def set_enchants(ctx: Ctx, gear_id: int, enchants: dict[str, int]) -> None:
    for name, level in enchants.items():
        ctx.execute(
            """
            INSERT INTO gear_enchants(gear_id, enchant, level) VALUES(?, ?, ?)
            ON CONFLICT(gear_id, enchant) DO UPDATE SET level=excluded.level;
            """,
            (gear_id, name, level),
        )


# ---------------- books and lapis ----------------
def lapis(ctx: Ctx, user_id: int) -> int:
    return players.item_amount(ctx, user_id, "lapis", "none")


def give_lapis(ctx: Ctx, user_id: int, amount: int) -> None:
    players.add_item(ctx, user_id, "lapis", "none", amount)


def give_book(ctx: Ctx, user_id: int, name: str, level: int, amount: int = 1) -> None:
    players.add_item(ctx, user_id, "book", book_material(name, level), amount)


def books(ctx: Ctx, user_id: int) -> list[tuple[str, int, int]]:
    """[(enchant, level, amount)] sorted by enchant then level."""
    out = []
    for (item, material), amount in players.get_items(ctx, user_id).items():
        if item == "book":
            name, level = parse_book(material)
            out.append((name, level, amount))
    return sorted(out)


def random_book(rng: random.Random, weights: list | None = None) -> tuple[str, int]:
    weights = [float(w) for w in (weights if weights is not None else _cfg()["book_weights"])][:BASE_LEVEL]
    level = rng.choices(range(1, len(weights) + 1), weights=weights)[0]
    return rng.choice(RANDOM_BOOKS), level


def give_random_book(ctx: Ctx, user_id: int, weights: list | None = None) -> tuple[str, int]:
    name, level = random_book(ctx.rng, weights)
    give_book(ctx, user_id, name, level)
    players.bump_stat(ctx, user_id, "books_found")
    return name, level


# ---------------- actions ----------------
def apply(ctx: Ctx, user_id: int, book: str, gear_id: int) -> dict:
    name, level = parse_book(book)
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    piece = attach(ctx, [dict(row)])[0]
    enchant = ENCHANTS[name]
    if piece["item"] not in enchant.items:
        raise GameError(f"**{enchant.name}** can't go on a {piece['item']}. It goes on: {', '.join(enchant.items)}.")
    current = level_of(piece, name)
    if current >= level:
        raise GameError(f"This {piece['material']} {piece['item']} already has **{label(name, current)}**.")
    if players.item_amount(ctx, user_id, "book", book_material(name, level)) < 1:
        raise GameError(f"You don't have a **{label(name, level)}** book.")
    _check_level(ctx, user_id, level, "apply")
    cost = apply_cost(level)
    have = lapis(ctx, user_id)
    if have < cost:
        raise GameError(f"You need **{cost} lapis lazuli** to apply a level {ROMAN[level]} book (you have {have}).")
    players.take_item(ctx, user_id, "book", book_material(name, level), 1)
    players.take_item(ctx, user_id, "lapis", "none", cost)
    set_enchants(ctx, gear_id, {name: level})
    players.bump_stat(ctx, user_id, "items_enchanted")
    piece["enchants"][name] = level
    return {"piece": piece, "name": name, "level": level, "replaced": current, "cost": cost}


def combine(ctx: Ctx, user_id: int, book: str) -> dict:
    """Two identical books -> one book of the next level."""
    name, level = parse_book(book)
    top = ENCHANTS[name].max_level
    if top == 1:
        raise GameError(f"**{ENCHANTS[name].name}** has only one level: it can't be combined.")
    if level >= top:
        raise GameError(f"Level {ROMAN[top]} is the maximum.")
    _check_level(ctx, user_id, level + 1, "make")
    have = players.item_amount(ctx, user_id, "book", book_material(name, level))
    if have < 2:
        raise GameError(f"You need 2 **{label(name, level)}** books to combine them (you have {have}).")
    anvil.require(ctx, user_id, "combine books")
    players.take_item(ctx, user_id, "book", book_material(name, level), 2)
    give_book(ctx, user_id, name, level + 1)
    return {"name": name, "level": level + 1, "anvil": anvil.use(ctx, user_id)}
