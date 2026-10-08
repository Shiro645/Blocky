"""Equipment: equip slots, durability and the bonuses each piece gives."""
from __future__ import annotations

from game import players, settings
from game.catalog import ARMOR, GEAR_ITEMS
from game.db import Ctx
from game.errors import GameError
from game.notices import GearBroken


def tier(material: str) -> int:
    return int(settings.get()["gear"]["tier"].get(material, 0))


def get_equipped(ctx: Ctx, user_id: int) -> dict[str, dict]:
    """slot (item type) -> gear row"""
    rows = ctx.all("SELECT * FROM gear WHERE user_id=? AND equipped=1;", (user_id,))
    return {r["item"]: dict(r) for r in rows}


def equip(ctx: Ctx, user_id: int, gear_id: int) -> dict:
    row = ctx.one("SELECT * FROM gear WHERE gear_id=? AND user_id=?;", (gear_id, user_id))
    if row is None:
        raise GameError("You don't own this piece of gear.")
    ctx.execute("UPDATE gear SET equipped=0 WHERE user_id=? AND item=? AND equipped=1;", (user_id, row["item"]))
    ctx.execute("UPDATE gear SET equipped=1 WHERE gear_id=?;", (gear_id,))
    from game import progress  # progress depends on this module

    progress.check_achievements(ctx, user_id)
    return dict(ctx.one("SELECT * FROM gear WHERE gear_id=?;", (gear_id,)))


def unequip(ctx: Ctx, user_id: int, slot: str) -> dict:
    if slot not in GEAR_ITEMS:
        raise GameError("Unknown slot.")
    row = ctx.one("SELECT * FROM gear WHERE user_id=? AND item=? AND equipped=1;", (user_id, slot))
    if row is None:
        raise GameError(f"You have nothing equipped in the **{slot}** slot.")
    ctx.execute("UPDATE gear SET equipped=0 WHERE gear_id=?;", (row["gear_id"],))
    return dict(row)


def equip_best(ctx: Ctx, user_id: int) -> list[dict]:
    """Equip, for every empty slot, the best piece owned (highest tier, then durability)."""
    equipped = get_equipped(ctx, user_id)
    done = []
    for slot in GEAR_ITEMS:
        if slot in equipped:
            continue
        rows = ctx.all("SELECT * FROM gear WHERE user_id=? AND item=?;", (user_id, slot))
        if not rows:
            continue
        best = max(rows, key=lambda r: (tier(r["material"]), r["durability"]))
        done.append(equip(ctx, user_id, best["gear_id"]))
    return done


def wear(ctx: Ctx, piece: dict, amount: int = 1) -> bool:
    """Use a piece of gear. Returns True if it broke (it is then destroyed)."""
    left = piece["durability"] - amount
    if left > 0:
        ctx.execute("UPDATE gear SET durability=? WHERE gear_id=?;", (left, piece["gear_id"]))
        piece["durability"] = left
        return False
    ctx.execute("DELETE FROM gear WHERE gear_id=?;", (piece["gear_id"],))
    piece["durability"] = 0
    players.bump_stat(ctx, piece["user_id"], "gear_broken")
    ctx.notices.append(GearBroken(piece["user_id"], piece["item"], piece["material"]))
    return True


# ---------------- combat stats ----------------
def attack_damage(equipped: dict[str, dict]) -> int:
    dmg = settings.get()["gear"]["sword_damage"]
    sword = equipped.get("sword")
    return int(dmg[sword["material"]] if sword else dmg["none"])


def armor_points(equipped: dict[str, dict]) -> int:
    table = settings.get()["gear"]["armor_points"]
    return sum(int(table[equipped[s]["material"]][s]) for s in ARMOR if s in equipped)


def damage_reduction(equipped: dict[str, dict]) -> float:
    g = settings.get()["gear"]
    return min(g["max_damage_reduction"], armor_points(equipped) * g["damage_reduction_per_armor_point"])
