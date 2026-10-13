"""NPC market and crafting."""
from __future__ import annotations

import math

from game import anvil, enchants, gear, players, potions, settings, species
from game.catalog import MATERIALS, RECIPES, SHIELD, materials_for
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
    full_price = units * offer["price"]
    total_price = max(1, round(full_price * (1 - species.bonus(ctx, user_id, "villager"))))
    players.spend_emeralds(ctx, user_id, total_price)
    amount = units * offer["unit_size"]
    players.add_item(ctx, user_id, offer["item"], offer["material"], amount)
    return {
        "offer": offer,
        "amount": amount,
        "price": total_price,
        "saved": full_price - total_price,
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
    name, level = enchants.parse_book(material)
    if enchants.ENCHANTS[name].rare:
        return float(e["mending_value"])
    return float(e["book_values"][level - 1])


def max_durability(material: str, item: str | None = None) -> int:
    if item == SHIELD:
        return int(settings.get()["gear"]["shield_durability"])
    return int(settings.get()["gear"]["durability"][material])


def create_gear(ctx: Ctx, user_id: int, item: str, material: str) -> int:
    players.ensure_user(ctx, user_id)
    dura = max_durability(material, item)
    cur = ctx.execute(
        """
        INSERT INTO gear(user_id, item, material, durability, max_durability, created_at)
        VALUES(?, ?, ?, ?, ?, ?);
        """,
        (user_id, item, material, dura, dura, int(ctx.now)),
    )
    return int(cur.lastrowid)


def craft(ctx: Ctx, user_id: int, item: str, material: str | None = None) -> dict:
    """Craft a piece of gear (or the anvil). Without a material, the item's only material is used."""
    if item == "anvil":
        return {**anvil.craft(ctx, user_id), "anvil": True}
    if item not in RECIPES:
        raise GameError(f"Unknown item. Allowed: {', '.join(RECIPES)}, anvil.")
    if material is None:
        if len(materials_for(item)) != 1:
            raise GameError(f"Choose the `material` of your {item}: {', '.join(materials_for(item))}.")
        material = materials_for(item)[0]
    if material not in MATERIALS:
        raise GameError(f"Unknown material. Allowed: {', '.join(MATERIALS)}.")
    if material not in materials_for(item):
        raise GameError(f"A {item} can only be made of {', '.join(materials_for(item))}.")
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
    return {"gear_id": gear_id, "material": material, "ingots": ingots, "sticks": sticks, "equipped": auto_equipped}


def get_gear(ctx: Ctx, user_id: int) -> list[dict]:
    rows = ctx.all(
        "SELECT * FROM gear WHERE user_id=? ORDER BY equipped DESC, item, material, gear_id;",
        (user_id,),
    )
    return enchants.attach(ctx, [dict(r) for r in rows])


def per_ingot(piece: dict) -> float:
    """Durability one ingot gives back to this piece (less after each repair it already had)."""
    r = settings.get()["repair"]
    base = piece["max_durability"] * float(r["durability_per_ingot"])
    return max(1.0, base / (1 + float(r["penalty_per_repair"]) * int(piece.get("repairs", 0))))


def ingots_needed(piece: dict) -> int:
    """Ingots of its material to bring a piece back to full durability (0 = nothing to repair)."""
    missing = piece["max_durability"] - piece["durability"]
    return math.ceil(missing / per_ingot(piece)) if missing > 0 else 0


def repair(ctx: Ctx, user_id: int, gear_id: int, ingots: int | None = None) -> dict:
    """Repair a piece of gear on the anvil with ingots of its material (`ingots` = how many to put in,
    None = as many as needed, or all the player has). It keeps its enchantments, and each repair makes the
    next one cost more."""
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    piece = enchants.attach(ctx, [dict(row)])[0]
    name = f"{piece['material']} {piece['item']}"
    needed = ingots_needed(piece)
    if needed == 0:
        raise GameError(f"Your {name} is already at full durability.")
    anvil.require(ctx, user_id, "repair gear")
    material = piece["material"]
    have = players.item_amount(ctx, user_id, "ingot", material)
    if ingots is not None and ingots <= 0:
        raise GameError("Put at least 1 ingot.")
    use = min(needed, ingots if ingots is not None else have)
    if use <= 0:
        raise GameError(f"Repairing your {name} takes **{material} ingots** ({needed} for a full repair): you "
                        "have none (`/market` sells them).")
    if have < use:
        raise GameError(f"You only have **{have}** {material} ingot(s).")
    missing = piece["max_durability"] - piece["durability"]
    repaired = missing if use >= needed else min(missing, max(1, int(use * per_ingot(piece))))
    players.take_item(ctx, user_id, "ingot", material, use)
    ctx.execute("UPDATE gear SET durability = durability + ?, repairs = repairs + 1 WHERE gear_id=?;",
                (repaired, gear_id))
    players.bump_stat(ctx, user_id, "items_repaired")
    wear = anvil.use(ctx, user_id)
    piece["durability"] += repaired
    piece["repairs"] = int(piece.get("repairs", 0)) + 1
    return {"piece": piece, "ingots": use, "material": material, "repaired": repaired,
            "left": ingots_needed(piece), "next_full": math.ceil(piece["max_durability"] / per_ingot(piece)),
            "anvil": wear}
