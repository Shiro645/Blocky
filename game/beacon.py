"""The server's Beacon (/beacon): built by everyone, it gives everyone its effects.

- It is lit by the first victory against the Wither (its Nether Star). Before that, nothing can be given.
- A pyramid of 4 levels (beacon.level_ingots: 1, 3, 5 and 9 blocks = 9, 27, 45 and 81 ingots). It is built in 16 steps, in
  this order: the 4 levels in gold, then level 1 to 4 again in iron, then in diamond, then in netherite. A
  level rebuilt in a better material keeps working the whole time.
- /beacon give: anyone gives ingots, by whole blocks (multiples of 9), of the material the Beacon needs now.
- Each level gives its effects to everyone (1: faster mining and more mining XP, 2: /sell pays more, 3: more
  damage, 4: less damage taken, in the dungeon and against the gate bosses), times its material's multiplier.
- Upkeep: every week it needs a share of its last step (beacon.upkeep, in that material). What is given goes to
  the upkeep first; building a step covers the week's upkeep. Not given by Monday: that step is undone.
- Whoever gave enough this week (contributor_value) also gets more mining XP and /sell for the rest of the week.
"""
from __future__ import annotations

import math

from game import players, settings, shop
from game.db import Ctx
from game.errors import GameError

ORDER = ("gold", "iron", "diamond", "netherite")
LEVELS = 4
STEPS = len(ORDER) * LEVELS
EFFECTS = {1: ("haste", "xp"), 2: ("sell",), 3: ("strength",), 4: ("resistance",)}


def _cfg() -> dict:
    return settings.get()["beacon"]


def step_of(index: int) -> tuple[str, int]:
    """The material and level of a step (0 = gold level 1, 4 = iron level 1…)."""
    return ORDER[index // LEVELS], index % LEVELS + 1


def cost(level: int) -> int:
    return int(_cfg()["level_ingots"][level - 1])


def get(ctx: Ctx) -> dict:
    return dict(ctx.one("SELECT * FROM beacon WHERE id=1;"))


def is_lit(ctx: Ctx) -> bool:
    return get(ctx)["lit_at"] is not None


def level_materials(step: int) -> dict[int, str | None]:
    """level -> its material once `step` steps are built (None: not built yet)."""
    out: dict[int, str | None] = {}
    for level in range(1, LEVELS + 1):
        tiers = sum(1 for s in range(step) if s % LEVELS == level - 1)
        out[level] = ORDER[tiers - 1] if tiers else None
    return out


def effects(ctx: Ctx) -> dict[str, float]:
    """The Beacon's effects now, for everyone ({} when it isn't lit)."""
    b = get(ctx)
    out = {k: 0.0 for lvl in EFFECTS.values() for k in lvl}
    if b["lit_at"] is None:
        return out
    c = _cfg()
    for level, material in level_materials(b["step"]).items():
        if material is not None:
            for name in EFFECTS[level]:
                out[name] = float(c[name]) * float(c["multipliers"][material])
    return out


def effect(ctx: Ctx, name: str) -> float:
    return effects(ctx)[name]


def week_value(ctx: Ctx, user_id: int, week: str | None = None) -> int:
    row = ctx.one("SELECT COALESCE(SUM(value), 0) AS v FROM beacon_gifts WHERE user_id=? AND week_id=?;",
                  (user_id, week or ctx.week_id))
    return int(row["v"])


def contributor(ctx: Ctx, user_id: int) -> bool:
    """Gave enough this week for the contributor bonus."""
    need = int(_cfg()["contributor_value"])
    return need > 0 and week_value(ctx, user_id) >= need


def mining_xp_bonus(ctx: Ctx, user_id: int) -> float:
    return effect(ctx, "xp") + (float(_cfg()["contributor_xp"]) if contributor(ctx, user_id) else 0.0)


def sell_bonus(ctx: Ctx, user_id: int) -> float:
    return effect(ctx, "sell") + (float(_cfg()["contributor_sell"]) if contributor(ctx, user_id) else 0.0)


def combat(ctx: Ctx) -> tuple[float, float]:
    """(strength, resistance) for the dungeon and the gate bosses."""
    e = effects(ctx)
    return e["strength"], e["resistance"]


def upkeep_due(ctx: Ctx, b: dict | None = None) -> tuple[str | None, int]:
    """(material, ingots) the Beacon needs this week: a share of its last step, in whole blocks."""
    b = b or get(ctx)
    if b["lit_at"] is None or b["step"] <= 0:
        return None, 0
    material, level = step_of(b["step"] - 1)
    ingots = math.ceil(cost(level) * float(_cfg()["upkeep"]) / 9) * 9 if float(_cfg()["upkeep"]) > 0 else 0
    return material, ingots


def _this_week(ctx: Ctx, b: dict) -> dict:
    """Start counting this week's upkeep (the past weeks were settled by weekly())."""
    if b["upkeep_week"] != ctx.week_id:
        ctx.execute("UPDATE beacon SET upkeep_week=?, upkeep_paid=0 WHERE id=1;", (ctx.week_id,))
        b = get(ctx)
    return b


def next_step(b: dict) -> tuple[str, int] | None:
    return step_of(b["step"]) if b["step"] < STEPS else None


def status(ctx: Ctx) -> dict:
    b = get(ctx)
    material, due = upkeep_due(ctx, b)
    paid = b["upkeep_paid"] if b["upkeep_week"] == ctx.week_id else 0
    nxt = next_step(b)
    return {
        **b,
        "lit": b["lit_at"] is not None,
        "levels": level_materials(b["step"]),
        "effects": effects(ctx),
        "next": nxt,
        "next_cost": cost(nxt[1]) if nxt else 0,
        "upkeep_material": material,
        "upkeep_due": due,
        "upkeep_paid": min(paid, due),
        "top_week": [dict(r) for r in ctx.all(
            "SELECT user_id, SUM(value) AS value, SUM(ingots) AS ingots FROM beacon_gifts WHERE week_id=? "
            "GROUP BY user_id ORDER BY value DESC, user_id LIMIT 5;", (ctx.week_id,))],
    }


def give(ctx: Ctx, user_id: int, material: str, ingots: int) -> dict:
    """Give ingots to the Beacon: the week's upkeep first, then the next steps. Whole blocks only."""
    b = get(ctx)
    if b["lit_at"] is None:
        raise GameError("The Beacon isn't lit yet: it needs a Nether Star, from the first victory against the Wither.")
    if ingots <= 0 or ingots % 9:
        raise GameError("Give whole blocks: a multiple of 9 ingots (9, 18, 27…).")
    # A new week the loop hasn't settled yet: settle the last one first (its missed upkeep isn't forgiven).
    settled = weekly(ctx)
    b = _this_week(ctx, get(ctx))
    up_material, due = upkeep_due(ctx, b)
    to_upkeep = min(ingots, max(0, due - b["upkeep_paid"])) if material == up_material else 0
    left = ingots - to_upkeep
    step, progress, built = b["step"], b["progress"], []
    while left > 0 and step < STEPS and step_of(step)[0] == material:
        need = cost(step_of(step)[1]) - progress
        put = min(left, need)
        progress += put
        left -= put
        if progress >= cost(step_of(step)[1]):
            built.append(step_of(step))
            step, progress = step + 1, 0
    if left > 0:
        wanted = []
        if up_material and due > b["upkeep_paid"]:
            wanted.append(f"{due - b['upkeep_paid']} {up_material} ingots for this week's upkeep")
        if b["step"] < STEPS:
            m, lvl = step_of(b["step"])
            wanted.append(f"{cost(lvl) - b['progress']} {m} ingots for level {lvl} in {m}")
        need = " or ".join(wanted) if wanted else "nothing more"
        raise GameError(f"The Beacon doesn't need that many **{material}** ingots now: it needs {need}.")
    players.take_item(ctx, user_id, "ingot", material, ingots)
    value = int(ingots * shop.ingot_value(material))
    ctx.execute("INSERT INTO beacon_gifts(user_id, week_id, material, ingots, value, given_at) VALUES(?, ?, ?, ?, ?, ?);",
                (user_id, ctx.week_id, material, ingots, value, int(ctx.now)))
    ctx.execute("UPDATE beacon SET step=?, progress=?, upkeep_paid=upkeep_paid+? WHERE id=1;",
                (step, progress, to_upkeep))
    if built:  # a step built this week covers this week's upkeep (in whatever material it now needs)
        ctx.execute("UPDATE beacon SET upkeep_paid=? WHERE id=1;", (upkeep_due(ctx)[1],))
    players.bump_stat(ctx, user_id, "beacon_ingots", ingots)
    players.bump_stat(ctx, user_id, "beacon_value", value)
    return {"ingots": ingots, "material": material, "upkeep": to_upkeep, "built": built, "value": value,
            "status": status(ctx), "settled": settled}


def light(ctx: Ctx, user_id: int | None) -> bool:
    """The Nether Star lights the Beacon (once). Returns True if it was lit now."""
    if is_lit(ctx):
        return False
    # This week's upkeep is counted as paid: nothing is built yet anyway.
    ctx.execute("UPDATE beacon SET lit_at=?, lit_by=?, upkeep_week=?, upkeep_paid=0 WHERE id=1;",
                (int(ctx.now), user_id, ctx.week_id))
    return True


def weekly(ctx: Ctx) -> dict | None:
    """Once a new week starts: the last week's upkeep wasn't given in full = its last step is undone."""
    b = get(ctx)
    if b["upkeep_week"] is None or b["upkeep_week"] == ctx.week_id:
        return None
    material, due = upkeep_due(ctx, b)
    undone = None
    if b["lit_at"] is not None and due and b["upkeep_paid"] < due:
        undone = step_of(b["step"] - 1)
        new_step = b["step"] - 1
        # The ingots already given to the following step stay if they are of the material needed again (never
        # enough to rebuild the undone step at once: that's the price of a missed upkeep).
        old = next_step(b)
        keep = b["progress"] if old and old[0] == undone[0] else 0
        ctx.execute("UPDATE beacon SET step=?, progress=? WHERE id=1;",
                    (new_step, min(keep, cost(undone[1]) - 9)))
    ctx.execute("UPDATE beacon SET upkeep_week=?, upkeep_paid=0 WHERE id=1;", (ctx.week_id,))
    return {"undone": undone, "missing": max(0, due - b["upkeep_paid"]), "material": material}


def staff_set(ctx: Ctx, lit: bool, step: int | None = None) -> dict:
    """Staff: light or put out the Beacon, and set how many steps are built."""
    if lit and not is_lit(ctx):
        light(ctx, None)
    elif not lit:
        ctx.execute("UPDATE beacon SET lit_at=NULL, lit_by=NULL WHERE id=1;")
    if step is not None:
        if not 0 <= step <= STEPS:
            raise GameError(f"Steps go from 0 to {STEPS}.")
        ctx.execute("UPDATE beacon SET step=?, progress=0, upkeep_week=?, upkeep_paid=0 WHERE id=1;",
                    (step, ctx.week_id))
        ctx.execute("UPDATE beacon SET upkeep_paid=? WHERE id=1;", (upkeep_due(ctx)[1],))  # this week is covered
    return status(ctx)
