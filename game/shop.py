"""NPC market and crafting."""
from __future__ import annotations

import math

from game import anvil, enchants, gear, live_events, players, potions, settings, species
from game.catalog import ARMOR, MATERIALS, RECIPES, SHIELD, materials_for
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
        if material == "netherite":
            continue  # only found in the Nether
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
    sale = live_events.market_discount(ctx)  # a Market Sale
    villager = species.bonus(ctx, user_id, "villager")
    total_price = max(1, round(full_price * (1 - sale) * (1 - villager)))
    players.spend_emeralds(ctx, user_id, total_price)
    amount = units * offer["unit_size"]
    players.add_item(ctx, user_id, offer["item"], offer["material"], amount)
    return {
        "offer": offer,
        "amount": amount,
        "price": total_price,
        "saved": full_price - total_price,
        "sale": sale,
        "villager": villager > 0,
        "balance": players.get_emeralds(ctx, user_id),
    }


def sale_price(price: int, discount: float) -> int:
    """A market price during a Market Sale."""
    return max(1, round(price * (1 - discount))) if discount else price


def ingot_value(material: str) -> int:
    return int(settings.get()["market"]["ingots"][material])


def stick_value() -> float:
    pack = settings.get()["market"]["stick_pack"]
    return pack["price"] / pack["amount"]


def craft_cost(item: str, material: str) -> float:
    """Value in emeralds of the resources used to craft a piece of gear (netherite: the diamond piece it was
    and one netherite ingot)."""
    if material == "netherite":
        return craft_cost(item, "diamond") + ingot_value("netherite")
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
    if item == "scrap":  # a netherite ingot is its scraps and its gold
        d = settings.get()["dimensions"]
        gold = int(d["gold_per_ingot"]) * ingot_value("gold")
        return max(0.0, (ingot_value("netherite") - gold) / max(1, int(d["scraps_per_ingot"])))
    if item == "potion":
        return potions.value(material)
    name, level = enchants.parse_book(material)
    if enchants.ENCHANTS[name].rare:
        return float(e["mending_value"])
    return float(e["book_values"][level - 1])


def max_durability(material: str, item: str | None = None) -> int:
    g = settings.get()["gear"]
    if item == SHIELD:
        return int(g["shield_durability"])
    base = int(g["durability"][material])
    if item in ARMOR:  # each armor piece its share, like in Minecraft
        return max(1, round(base * float(g["armor_durability_share"][item])))
    return base


def rescaled(durability: int, old_max: int, new_max: int) -> int:
    """The durability a piece keeps when its maximum changes: the same share (a piece that wasn't broken stays
    usable)."""
    if old_max <= 0:
        return new_max
    kept = min(new_max, round(durability * new_max / old_max))
    return max(1, kept) if durability > 0 else 0


def sync_max_durability(ctx: Ctx) -> int:
    """Gear (and gear listed at the auction) made before a durability setting or rule changed gets the new
    maximum, keeping the same share of durability. Returns how many changed."""
    changed = 0
    for r in ctx.all("SELECT gear_id, item, material, durability, max_durability FROM gear;"):
        new = max_durability(r["material"], r["item"])
        if new != r["max_durability"]:
            ctx.execute("UPDATE gear SET durability=?, max_durability=? WHERE gear_id=?;",
                        (rescaled(r["durability"], r["max_durability"], new), new, r["gear_id"]))
            changed += 1
    for r in ctx.all("SELECT auction_id, asset, durability, max_durability FROM auctions "
                     "WHERE asset LIKE 'gear:%' AND max_durability IS NOT NULL;"):
        _, material, item = r["asset"].split(":")[:3]
        new = max_durability(material, item)
        if new != r["max_durability"]:
            ctx.execute("UPDATE auctions SET durability=?, max_durability=? WHERE auction_id=?;",
                        (rescaled(r["durability"], r["max_durability"], new), new, r["auction_id"]))
            changed += 1
    return changed


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
    if item == "netherite_ingot":
        return {**craft_netherite_ingot(ctx, user_id), "netherite_ingot": True}
    if item not in RECIPES:
        raise GameError(f"Unknown item. Allowed: {', '.join(RECIPES)}, anvil, netherite_ingot.")
    if material is None:
        if len(materials_for(item)) != 1:
            raise GameError(f"Choose the `material` of your {item}: {', '.join(materials_for(item))}.")
        material = materials_for(item)[0]
    if material not in MATERIALS:
        raise GameError(f"Unknown material. Allowed: {', '.join(MATERIALS)}.")
    if material not in materials_for(item):
        raise GameError(f"A {item} can only be made of {', '.join(materials_for(item))}.")
    if material == "netherite":
        return upgrade_to_netherite(ctx, user_id, item)
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


def craft_netherite_ingot(ctx: Ctx, user_id: int) -> dict:
    """Netherite scraps (found in the Nether) and gold ingots make a netherite ingot."""
    d = settings.get()["dimensions"]
    scraps, gold = int(d["scraps_per_ingot"]), int(d["gold_per_ingot"])
    have_scraps = players.item_amount(ctx, user_id, "scrap", "none")
    have_gold = players.item_amount(ctx, user_id, "ingot", "gold")
    missing = []
    if have_scraps < scraps:
        missing.append(f"- **{scraps - have_scraps} netherite scrap(s)** (Ancient debris, mined in the Nether)")
    if have_gold < gold:
        missing.append(f"- **{gold - have_gold} gold ingot(s)**")
    if missing:
        raise GameError("Not enough resources. Missing:\n" + "\n".join(missing))
    players.take_item(ctx, user_id, "scrap", "none", scraps)
    players.take_item(ctx, user_id, "ingot", "gold", gold)
    players.add_item(ctx, user_id, "ingot", "netherite", 1)
    players.bump_stat(ctx, user_id, "netherite_ingots_made")
    return {"scraps": scraps, "gold": gold, "have": players.item_amount(ctx, user_id, "ingot", "netherite")}


def upgrade_to_netherite(ctx: Ctx, user_id: int, item: str) -> dict:
    """A diamond piece and a netherite ingot make the same piece in netherite: it keeps its enchantments and is
    as good as new. The worn piece goes first, else the most enchanted spare one."""
    if "netherite" not in materials_for(item):
        raise GameError(f"A {item} can't be made of netherite.")
    rows = enchants.attach(ctx, [dict(r) for r in ctx.all(
        "SELECT * FROM gear WHERE user_id=? AND item=? AND material='diamond';", (user_id, item))])
    if not rows:
        raise GameError(f"Netherite gear is a **diamond {item}** upgraded with a netherite ingot: you have no "
                        f"diamond {item}.")
    piece = max(rows, key=lambda g: (g["equipped"], sum(g["enchants"].values()), g["durability"], -g["gear_id"]))
    if players.item_amount(ctx, user_id, "ingot", "netherite") < 1:
        raise GameError("Not enough resources. Missing:\n- **1 netherite ingot** (4 netherite scraps + 4 gold ingots: "
                        "`/craft item:netherite_ingot`)")
    players.take_item(ctx, user_id, "ingot", "netherite", 1)
    dura = max_durability("netherite", item)
    ctx.execute("UPDATE gear SET material='netherite', durability=?, max_durability=?, repairs=0 WHERE gear_id=?;",
                (dura, dura, piece["gear_id"]))
    players.bump_stat(ctx, user_id, "items_crafted")
    if piece["equipped"]:
        from game import progress  # progress depends on this module

        progress.check_achievements(ctx, user_id)  # a worn upgraded piece can complete the netherite set
    return {"gear_id": piece["gear_id"], "material": "netherite", "ingots": 1, "sticks": 0,
            "equipped": bool(piece["equipped"]), "upgraded": piece}


def get_gear(ctx: Ctx, user_id: int) -> list[dict]:
    rows = ctx.all(
        "SELECT * FROM gear WHERE user_id=? ORDER BY equipped DESC, item, material, gear_id;",
        (user_id,),
    )
    return enchants.attach(ctx, [dict(r) for r in rows])


def owned_piece(ctx: Ctx, user_id: int, gear_id: int) -> dict:
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    return enchants.attach(ctx, [dict(row)])[0]


def gear_value(piece: dict) -> float:
    """What a piece is worth new: the resources of its craft and the books applied to it."""
    books = sum(item_value("book", enchants.book_material(name, level)) for name, level in piece["enchants"].items())
    return craft_cost(piece["item"], piece["material"]) + books


def gear_offer(ctx: Ctx, user_id: int, piece: dict) -> dict:
    """What /sell pays for a piece: market.gear_sell_rate of its value, times the durability it has left
    (Villagers get their bonus on top)."""
    value = gear_value(piece)
    # During a Market Sale its craft is worth what the ingots cost now: buying cheap to sell gear isn't a profit.
    value -= craft_cost(piece["item"], piece["material"]) * live_events.market_discount(ctx)
    left = piece["durability"] / piece["max_durability"] if piece["max_durability"] else 0.0
    base = max(1, int(round(value * float(settings.get()["market"]["gear_sell_rate"]) * left)))
    bonus = int(round(base * species.bonus(ctx, user_id, "villager")))
    return {"value": int(round(value)), "left": left, "base": base, "bonus": bonus, "price": base + bonus}


def gear_offers(ctx: Ctx, user_id: int) -> list[tuple[dict, dict]]:
    """Every piece the player can sell, with what /sell pays for it (netherite can't be sold)."""
    return [(piece, gear_offer(ctx, user_id, piece)) for piece in get_gear(ctx, user_id)
            if piece["material"] != "netherite"]


def sell_gear(ctx: Ctx, user_id: int, gear_id: int, price: int | None = None) -> dict:
    """Sell a piece of gear back (taken off first when it is worn). `price`: what the player agreed to pay
    for it, refused when the piece changed since."""
    piece = owned_piece(ctx, user_id, gear_id)
    if piece["material"] == "netherite":
        raise GameError("🔥 Netherite gear can't be sold: it's yours for good.")
    offer = gear_offer(ctx, user_id, piece)
    if price is not None and offer["price"] != price:
        raise GameError(f"The price changed: it now sells for **{offer['price']:,}** emeralds. Use `/sell` again.")
    ctx.execute("DELETE FROM gear WHERE gear_id=?;", (gear_id,))
    # Not earned: the piece was paid with emeralds or resources that already counted.
    players.give_emeralds(ctx, user_id, offer["price"])
    return {**offer, "piece": piece, "balance": players.get_emeralds(ctx, user_id)}


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
    piece = owned_piece(ctx, user_id, gear_id)
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
