"""Anything a player can give, trade or sell, identified by a short key.

    "emeralds"          emeralds
    "block:<type>"      blocks (cobblestone, gravel...)
    "stick"             sticks
    "ingot:<material>"  ingots
    "lapis"             lapis lazuli
    "book:<enchant>:<level>"   an enchanted book
    "potion:<kind>"     a potion ("potion:<kind>:2" for a reinforced one)
    "gear:<material>:<item>"   one piece of gear without enchantments (the most worn spare piece is used)
    "gear:<material>:<item>:<enchantments>"   one piece with exactly these enchantments,
                        e.g. "gear:diamond:sword:sharpness2,unbreaking1" (they follow the piece)
"""
from __future__ import annotations

from game import enchants, players, potions, shop
from game.catalog import BLOCK_TYPES, GEAR_ITEMS, MATERIALS
from game.db import Ctx
from game.errors import GameError


def parse(key: str) -> tuple[str, ...]:
    parts = tuple(key.split(":"))
    kind = parts[0]
    ok = (
        (kind in ("emeralds", "stick", "lapis") and len(parts) == 1)
        or (kind == "block" and len(parts) == 2 and parts[1] in BLOCK_TYPES)
        or (kind == "ingot" and len(parts) == 2 and parts[1] in MATERIALS)
        or (kind == "book" and len(parts) == 3)
        or (kind == "potion" and len(parts) in (2, 3))
        or (kind == "gear" and len(parts) in (3, 4) and parts[1] in MATERIALS and parts[2] in GEAR_ITEMS)
    )
    if ok and kind == "book":
        enchants.parse_book(f"{parts[1]}:{parts[2]}")
    if ok and kind == "potion":
        potions.parse(":".join(parts[1:]))
    if ok and kind == "gear" and len(parts) == 4:
        try:
            enchants.parse_signature(parts[3])
        except ValueError:
            ok = False
    if not ok:
        raise GameError("Unknown item. Pick one from the suggestions.")
    return parts


def gear_key(piece: dict) -> str:
    """Asset key of a gear row (rows with "enchants", see enchants.attach)."""
    key = f"gear:{piece['material']}:{piece['item']}"
    sig = enchants.signature(piece.get("enchants") or {})
    return f"{key}:{sig}" if sig else key


def gear_enchants(key: str) -> dict[str, int]:
    parts = parse(key)
    return enchants.parse_signature(parts[3]) if len(parts) == 4 else {}


def describe(key: str, amount: int | None = None) -> str:
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        name = "emeralds"
    elif kind == "stick":
        name = "sticks"
    elif kind == "lapis":
        name = "lapis lazuli"
    elif kind == "block":
        name = parts[1]
    elif kind == "ingot":
        name = f"{parts[1]} ingot"
    elif kind == "book":
        name = f"{enchants.label(parts[1], int(parts[2]))} book"
    elif kind == "potion":
        name = potions.label(":".join(parts[1:]))
    else:
        name = f"{parts[1]} {parts[2]}"
        if len(parts) == 4:
            name += f" ({enchants.labels(enchants.parse_signature(parts[3]))})"
    return f"{amount} × {name}" if amount is not None else name


def is_gear(key: str) -> bool:
    return key.startswith("gear:")


def unit_value(key: str) -> float:
    """Reference value in emeralds (NPC prices), used to show fair prices."""
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        return 1
    if kind == "stick":
        return shop.stick_value()
    if kind == "lapis":
        return shop.item_value("lapis", "none")
    if kind == "block":
        return players.block_value(parts[1])
    if kind == "ingot":
        return shop.ingot_value(parts[1])
    if kind == "book":
        return shop.item_value("book", f"{parts[1]}:{parts[2]}")
    if kind == "potion":
        return shop.item_value("potion", ":".join(parts[1:]))
    books = sum(shop.item_value("book", enchants.book_material(n, lvl)) for n, lvl in gear_enchants(key).items())
    return shop.craft_cost(parts[2], parts[1]) + books


def owned(ctx: Ctx, user_id: int) -> list[tuple[str, int]]:
    """Every asset the player has, with the available amount."""
    out: list[tuple[str, int]] = []
    emeralds = players.get_emeralds(ctx, user_id)
    if emeralds:
        out.append(("emeralds", emeralds))
    for block, amount in players.get_blocks(ctx, user_id).items():
        if amount:
            out.append((f"block:{block}", amount))
    for (item, material), amount in sorted(players.get_items(ctx, user_id).items()):
        out.append((item_key(item, material), amount))
    gear_counts: dict[str, int] = {}
    for g in shop.get_gear(ctx, user_id):
        key = gear_key(g)
        gear_counts[key] = gear_counts.get(key, 0) + 1
    out.extend(sorted(gear_counts.items()))
    return out


def item_key(item: str, material: str) -> str:
    """Asset key of a row of the items table."""
    if item in ("stick", "lapis"):
        return item
    return f"{item}:{material}"


def _pick_gear(ctx: Ctx, user_id: int, key: str) -> dict:
    """A piece with exactly the enchantments of the key: spare pieces first, then the most worn one."""
    parts = parse(key)
    rows = ctx.all(
        """
        SELECT * FROM gear WHERE user_id=? AND material=? AND item=?
        ORDER BY equipped, durability, gear_id;
        """,
        (user_id, parts[1], parts[2]),
    )
    wanted = gear_enchants(key)
    for piece in enchants.attach(ctx, [dict(r) for r in rows]):
        if piece["enchants"] == wanted:
            return piece
    raise GameError(f"You don't have a **{describe(key)}**.")


def take(ctx: Ctx, user_id: int, key: str, amount: int) -> dict | None:
    """Remove an asset from a player. For gear, returns the removed piece."""
    if amount <= 0:
        raise GameError("Amount must be greater than 0.")
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        players.spend_emeralds(ctx, user_id, amount)
    elif kind in ("stick", "lapis"):
        players.take_item(ctx, user_id, kind, "none", amount)
    elif kind == "ingot":
        players.take_item(ctx, user_id, "ingot", parts[1], amount)
    elif kind == "book":
        material = enchants.book_material(parts[1], int(parts[2]))
        have = players.item_amount(ctx, user_id, "book", material)
        if have < amount:
            raise GameError(f"Not enough **{describe(key)}**: you have **{have}**, you need **{amount}**.")
        players.take_item(ctx, user_id, "book", material, amount)
    elif kind == "potion":
        material = ":".join(parts[1:])
        have = players.item_amount(ctx, user_id, "potion", material)
        if have < amount:
            raise GameError(f"Not enough **{describe(key)}**: you have **{have}**, you need **{amount}**.")
        players.take_item(ctx, user_id, "potion", material, amount)
    elif kind == "block":
        players.take_blocks(ctx, user_id, parts[1], amount)
    else:
        if amount != 1:
            raise GameError("Gear can only be moved one piece at a time.")
        piece = _pick_gear(ctx, user_id, key)
        ctx.execute("DELETE FROM gear WHERE gear_id=?;", (piece["gear_id"],))
        return piece
    return None


def give(ctx: Ctx, user_id: int, key: str, amount: int, durability: int | None = None) -> None:
    """Add an asset to a player (gear keeps the given durability and the key's enchantments)."""
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        players.give_emeralds(ctx, user_id, amount)
    elif kind in ("stick", "lapis"):
        players.add_item(ctx, user_id, kind, "none", amount)
    elif kind == "ingot":
        players.add_item(ctx, user_id, "ingot", parts[1], amount)
    elif kind == "book":
        enchants.give_book(ctx, user_id, parts[1], int(parts[2]), amount)
    elif kind == "potion":
        potions.give(ctx, user_id, ":".join(parts[1:]), amount)
    elif kind == "block":
        players.add_blocks(ctx, user_id, parts[1], amount)
    else:
        for _ in range(amount):
            gear_id = shop.create_gear(ctx, user_id, parts[2], parts[1])
            if durability is not None:
                ctx.execute("UPDATE gear SET durability=? WHERE gear_id=?;", (durability, gear_id))
            enchants.set_enchants(ctx, gear_id, gear_enchants(key))


def transfer(ctx: Ctx, from_id: int, to_id: int, key: str, amount: int) -> None:
    piece = take(ctx, from_id, key, amount)
    give(ctx, to_id, key, amount, durability=piece["durability"] if piece else None)
