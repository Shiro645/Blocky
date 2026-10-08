"""Anything a player can give, trade or sell, identified by a short key.

    "emeralds"          emeralds
    "block:<type>"      blocks (cobblestone, gravel...)
    "stick"             sticks
    "ingot:<material>"  ingots
    "gear:<material>:<item>"   one piece of gear (the most worn spare piece is used)
"""
from __future__ import annotations

from game import players, shop
from game.catalog import BLOCK_TYPES, GEAR_ITEMS, MATERIALS
from game.db import Ctx
from game.errors import GameError


def parse(key: str) -> tuple[str, ...]:
    parts = tuple(key.split(":"))
    kind = parts[0]
    ok = (
        (kind == "emeralds" and len(parts) == 1)
        or (kind == "stick" and len(parts) == 1)
        or (kind == "block" and len(parts) == 2 and parts[1] in BLOCK_TYPES)
        or (kind == "ingot" and len(parts) == 2 and parts[1] in MATERIALS)
        or (kind == "gear" and len(parts) == 3 and parts[1] in MATERIALS and parts[2] in GEAR_ITEMS)
    )
    if not ok:
        raise GameError("Unknown item. Pick one from the suggestions.")
    return parts


def describe(key: str, amount: int | None = None) -> str:
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        name = "emeralds"
    elif kind == "stick":
        name = "sticks"
    elif kind == "block":
        name = parts[1]
    elif kind == "ingot":
        name = f"{parts[1]} ingot"
    else:
        name = f"{parts[1]} {parts[2]}"
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
    if kind == "block":
        return players.block_value(parts[1])
    if kind == "ingot":
        return shop.ingot_value(parts[1])
    return shop.craft_cost(parts[2], parts[1])


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
        out.append(("stick" if item == "stick" else f"ingot:{material}", amount))
    gear_counts: dict[str, int] = {}
    for g in shop.get_gear(ctx, user_id):
        key = f"gear:{g['material']}:{g['item']}"
        gear_counts[key] = gear_counts.get(key, 0) + 1
    out.extend(sorted(gear_counts.items()))
    return out


def _pick_gear(ctx: Ctx, user_id: int, material: str, item: str) -> dict:
    """Spare pieces first, then the most worn one."""
    row = ctx.one(
        """
        SELECT * FROM gear WHERE user_id=? AND material=? AND item=?
        ORDER BY equipped, durability LIMIT 1;
        """,
        (user_id, material, item),
    )
    if row is None:
        raise GameError(f"You don't have a **{material} {item}**.")
    return dict(row)


def take(ctx: Ctx, user_id: int, key: str, amount: int) -> dict | None:
    """Remove an asset from a player. For gear, returns the removed piece."""
    if amount <= 0:
        raise GameError("Amount must be greater than 0.")
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        players.spend_emeralds(ctx, user_id, amount)
    elif kind == "stick":
        players.take_item(ctx, user_id, "stick", "none", amount)
    elif kind == "ingot":
        players.take_item(ctx, user_id, "ingot", parts[1], amount)
    elif kind == "block":
        players.take_blocks(ctx, user_id, parts[1], amount)
    else:
        if amount != 1:
            raise GameError("Gear can only be moved one piece at a time.")
        piece = _pick_gear(ctx, user_id, parts[1], parts[2])
        ctx.execute("DELETE FROM gear WHERE gear_id=?;", (piece["gear_id"],))
        return piece
    return None


def give(ctx: Ctx, user_id: int, key: str, amount: int, durability: int | None = None) -> None:
    """Add an asset to a player (gear keeps the given durability)."""
    parts = parse(key)
    kind = parts[0]
    if kind == "emeralds":
        players.give_emeralds(ctx, user_id, amount)
    elif kind == "stick":
        players.add_item(ctx, user_id, "stick", "none", amount)
    elif kind == "ingot":
        players.add_item(ctx, user_id, "ingot", parts[1], amount)
    elif kind == "block":
        players.add_blocks(ctx, user_id, parts[1], amount)
    else:
        for _ in range(amount):
            gear_id = shop.create_gear(ctx, user_id, parts[2], parts[1])
            if durability is not None:
                ctx.execute("UPDATE gear SET durability=? WHERE gear_id=?;", (durability, gear_id))


def transfer(ctx: Ctx, from_id: int, to_id: int, key: str, amount: int) -> None:
    piece = take(ctx, from_id, key, amount)
    give(ctx, to_id, key, amount, durability=piece["durability"] if piece else None)
