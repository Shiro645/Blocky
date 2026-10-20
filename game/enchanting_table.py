"""The enchanting table: crafted once (obsidian, diamond ingots and a book), it never wears out.

/enchant table puts 1 to 3 random enchantments on a piece of gear that has none, for lapis only (settings
"enchanting_table"). Each level is drawn up to the player's maximum (III, +1 per dimension), the maximum itself very
rarely. Mending never comes from the table. Sometimes a curse comes on top (Binding or Vanishing): it can't be
removed. Books can then add more enchantments, as on any piece.
"""
from __future__ import annotations

import random

from game import enchants, players, settings, shop
from game.db import Ctx
from game.enchants import CURSABLE, ENCHANTS
from game.errors import GameError


def _cfg() -> dict:
    return settings.get()["enchanting_table"]


def has(ctx: Ctx, user_id: int) -> bool:
    row = ctx.one("SELECT enchanting_table FROM users WHERE user_id=?;", (user_id,))
    return bool(row and row["enchanting_table"])


def require(ctx: Ctx, user_id: int) -> None:
    if not has(ctx, user_id):
        raise GameError("You need an **enchanting table**: `/craft item:enchanting_table` "
                        f"({recipe_text()}).")


def recipe_text() -> str:
    c = _cfg()
    return f"{c['obsidian']} obsidian + {c['diamond_ingots']} diamond ingots + {c['books']} enchanted book"


def _cheapest_books(ctx: Ctx, user_id: int, amount: int) -> list[str]:
    """The least valuable books a player has (book materials, one per book)."""
    owned = sorted(enchants.books(ctx, user_id), key=lambda b: (shop.item_value("book", enchants.book_material(b[0], b[1])), b))
    out: list[str] = []
    for name, level, have in owned:
        out += [enchants.book_material(name, level)] * min(have, amount - len(out))
        if len(out) >= amount:
            break
    return out


def craft(ctx: Ctx, user_id: int) -> dict:
    """Craft the table (one per player, for good)."""
    if has(ctx, user_id):
        raise GameError("You already have an enchanting table: it never wears out.")
    c = _cfg()
    obsidian, diamonds, nbooks = int(c["obsidian"]), int(c["diamond_ingots"]), int(c["books"])
    missing = []
    have_obsidian = players.get_blocks(ctx, user_id)["obsidian"]
    if have_obsidian < obsidian:
        missing.append(f"- **{obsidian - have_obsidian} obsidian** (mined)")
    have_diamonds = players.item_amount(ctx, user_id, "ingot", "diamond")
    if have_diamonds < diamonds:
        missing.append(f"- **{diamonds - have_diamonds} diamond ingot(s)** (`/market`)")
    books = _cheapest_books(ctx, user_id, nbooks)
    if len(books) < nbooks:
        missing.append(f"- **{nbooks - len(books)} enchanted book(s)** (any: drops, challenges, the villager…)")
    if missing:
        raise GameError(f"An enchanting table takes {recipe_text()}. You're missing:\n" + "\n".join(missing))
    players.take_blocks(ctx, user_id, "obsidian", obsidian)
    players.take_item(ctx, user_id, "ingot", "diamond", diamonds)
    for book in books:
        players.take_item(ctx, user_id, "book", book, 1)
    ctx.execute("UPDATE users SET enchanting_table=1 WHERE user_id=?;", (user_id,))
    return {"obsidian": obsidian, "diamonds": diamonds, "books": [enchants.parse_book(b) for b in books]}


def candidates(item: str) -> list[str]:
    """The enchantments the table can put on an item (never Mending nor a curse: those are apart)."""
    return [k for k, e in ENCHANTS.items() if not e.rare and item in e.items]


def level_weights(top: int) -> list[float]:
    """Weights of level I … top: the configured ones, the top one always top_level_weight (very rare)."""
    c = _cfg()
    weights = [float(w) for w in c["level_weights"][:top]]
    weights[-1] = float(c["top_level_weight"])
    return weights


def draw(rng: random.Random, item: str, top: int) -> dict[str, int]:
    """The enchantments of one use of the table (curse included, when one comes)."""
    c = _cfg()
    pool = candidates(item)
    counts = [float(w) for w in c["count_weights"]][: len(pool)]
    count = rng.choices(range(1, len(counts) + 1), weights=counts)[0] if sum(counts) > 0 else 1
    weights = level_weights(top)
    out = {name: rng.choices(range(1, top + 1), weights=weights)[0] for name in rng.sample(pool, count)}
    if rng.random() < float(c["curse_chance"]):
        curses = {k: float(w) for k, w in c["curse_weights"].items() if k in ENCHANTS and item in ENCHANTS[k].items}
        if sum(curses.values()) > 0:
            out[rng.choices(list(curses), weights=list(curses.values()))[0]] = 1
    return out


def enchant(ctx: Ctx, user_id: int, gear_id: int) -> dict:
    """One use of the table on a piece without any enchantment."""
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    piece = enchants.attach(ctx, [dict(row)])[0]
    if piece["item"] not in CURSABLE:
        raise GameError(f"The enchanting table can't enchant a {piece['item']}.")
    if piece["enchants"]:
        raise GameError(f"The enchanting table only enchants a piece **without any enchantment**: this one has "
                        f"{enchants.labels(piece['enchants'])}. Use books on it (`/enchant apply`).")
    require(ctx, user_id)
    cost = int(_cfg()["lapis"])
    have = enchants.lapis(ctx, user_id)
    if have < cost:
        raise GameError(f"The enchanting table takes **{cost} lapis lazuli** (you have {have}).")
    result = draw(ctx.rng, piece["item"], enchants.max_level_for(ctx, user_id))
    players.take_item(ctx, user_id, "lapis", "none", cost)
    enchants.set_enchants(ctx, gear_id, result)
    players.bump_stat(ctx, user_id, "items_enchanted")
    piece["enchants"] = dict(result)
    return {"piece": piece, "enchants": result, "cost": cost, "curse": next((k for k in result if ENCHANTS[k].curse), None)}
