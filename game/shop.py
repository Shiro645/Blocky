"""NPC market and crafting."""
from __future__ import annotations

import math

from game import enchants, gear, players, potions, settings
from game.catalog import MATERIALS, RECIPES
from game.db import Ctx
from game.errors import GameError


def market_offers() -> dict[str, dict]:
    """key -> {"label", "item", "material", "unit_size", "price"}"""
    m = settings.get()["market"]
    offers = {
        "sticks": {
            "label": f"{m['stick_pack']['amount']} Sticks",
            "item": "stick",
            "material": "none",
            "unit_size": int(m["stick_pack"]["amount"]),
            "price": int(m["stick_pack"]["price"]),
        }
    }
    for material in MATERIALS:
        offers[f"{material}_ingot"] = {
            "label": f"{material.capitalize()} Ingot",
            "item": "ingot",
            "material": material,
            "unit_size": 1,
            "price": int(m["ingots"][material]),
        }
    return offers


def buy(ctx: Ctx, user_id: int, key: str, units: int) -> dict:
    offers = market_offers()
    if key not in offers:
        raise GameError("Unknown market item.")
    if units <= 0:
        raise GameError("Quantity must be greater than 0.")
    offer = offers[key]
    total_price = units * offer["price"]
    players.spend_emeralds(ctx, user_id, total_price)
    amount = units * offer["unit_size"]
    players.add_item(ctx, user_id, offer["item"], offer["material"], amount)
    return {
        "offer": offer,
        "amount": amount,
        "price": total_price,
        "balance": players.get_emeralds(ctx, user_id),
    }


def ingot_value(material: str) -> int:
    return int(settings.get()["market"]["ingots"][material])


def stick_value() -> float:
    pack = settings.get()["market"]["stick_pack"]
    return pack["price"] / pack["amount"]


def craft_cost(item: str, material: str) -> float:
    """Value in emeralds of the resources used to craft a piece of gear."""
    ingots, sticks = RECIPES[item]
    return ingots * ingot_value(material) + sticks * stick_value()


def item_value(item: str, material: str) -> float:
    """Reference value in emeralds of a stackable item."""
    if item == "stick":
        return stick_value()
    if item == "ingot":
        return ingot_value(material)
    e = settings.get()["enchants"]
    if item == "lapis":
        return float(e["lapis_value"])
    if item == "potion":
        return potions.value(material)
    _, level = enchants.parse_book(material)
    return float(e["book_values"][level - 1])


def max_durability(material: str) -> int:
    return int(settings.get()["gear"]["durability"][material])


def create_gear(ctx: Ctx, user_id: int, item: str, material: str) -> int:
    players.ensure_user(ctx, user_id)
    dura = max_durability(material)
    cur = ctx.execute(
        """
        INSERT INTO gear(user_id, item, material, durability, max_durability, created_at)
        VALUES(?, ?, ?, ?, ?, ?);
        """,
        (user_id, item, material, dura, dura, int(ctx.now)),
    )
    return int(cur.lastrowid)


def craft(ctx: Ctx, user_id: int, item: str, material: str) -> dict:
    if item not in RECIPES:
        raise GameError(f"Unknown item. Allowed: {', '.join(RECIPES)}.")
    if material not in MATERIALS:
        raise GameError(f"Unknown material. Allowed: {', '.join(MATERIALS)}.")
    ingots, sticks = RECIPES[item]

    missing = []
    have_ingots = players.item_amount(ctx, user_id, "ingot", material)
    have_sticks = players.item_amount(ctx, user_id, "stick", "none")
    if have_ingots < ingots:
        missing.append(("ingot", material, ingots - have_ingots))
    if have_sticks < sticks:
        missing.append(("stick", "none", sticks - have_sticks))
    if missing:
        lines = [
            f"- **{n} {'stick(s)' if it == 'stick' else mat + ' ingot(s)'}**" for it, mat, n in missing
        ]
        raise GameError("Not enough resources. Missing:\n" + "\n".join(lines))

    players.take_item(ctx, user_id, "ingot", material, ingots)
    players.take_item(ctx, user_id, "stick", "none", sticks)
    gear_id = create_gear(ctx, user_id, item, material)
    players.bump_stat(ctx, user_id, "items_crafted")
    # Equip it right away if the slot is empty.
    auto_equipped = item not in gear.get_equipped(ctx, user_id)
    if auto_equipped:
        gear.equip(ctx, user_id, gear_id)
    return {"gear_id": gear_id, "ingots": ingots, "sticks": sticks, "equipped": auto_equipped}


def get_gear(ctx: Ctx, user_id: int) -> list[dict]:
    rows = ctx.all(
        "SELECT * FROM gear WHERE user_id=? ORDER BY equipped DESC, item, material, gear_id;",
        (user_id,),
    )
    return enchants.attach(ctx, [dict(r) for r in rows])


def repair_cost(piece: dict) -> int:
    """Emeralds to bring a piece back to full durability (in proportion to what is missing)."""
    missing = piece["max_durability"] - piece["durability"]
    if missing <= 0:
        return 0
    pct = float(settings.get()["repair"]["cost_percent"]) / 100
    return max(1, math.ceil(craft_cost(piece["item"], piece["material"]) * pct * missing / piece["max_durability"]))


def repair(ctx: Ctx, user_id: int, gear_id: int) -> dict:
    """Repair a piece of gear for emeralds. It keeps its enchantments."""
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    piece = enchants.attach(ctx, [dict(row)])[0]
    cost = repair_cost(piece)
    if cost == 0:
        raise GameError(f"Your {piece['material']} {piece['item']} is already at full durability.")
    players.spend_emeralds(ctx, user_id, cost)
    ctx.execute("UPDATE gear SET durability = max_durability WHERE gear_id=?;", (gear_id,))
    players.bump_stat(ctx, user_id, "items_repaired")
    piece["durability"] = piece["max_durability"]
    return {"piece": piece, "cost": cost, "balance": players.get_emeralds(ctx, user_id)}


def remove_gear(ctx: Ctx, user_id: int, item: str, material: str, count: int) -> int:
    """Staff: delete up to `count` pieces (unequipped first). Returns how many were removed."""
    rows = ctx.all(
        """
        SELECT gear_id FROM gear WHERE user_id=? AND item=? AND material=?
        ORDER BY equipped, gear_id LIMIT ?;
        """,
        (user_id, item, material, count),
    )
    for r in rows:
        ctx.execute("DELETE FROM gear WHERE gear_id=?;", (r["gear_id"],))
    return len(rows)
