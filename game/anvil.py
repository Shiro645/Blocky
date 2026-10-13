"""The anvil: crafted with iron ingots, needed to repair gear and to combine books.

Like in Minecraft it wears out: each use has a chance (repair.anvil_damage_chance) to damage it,
new → chipped → damaged → broken. A player has one anvil at a time (users.anvil: 0 = none,
3 = new, 2 = chipped, 1 = damaged).
"""
from __future__ import annotations

from game import players, settings
from game.db import Ctx
from game.errors import GameError

NEW = 3
STATES = {3: "Anvil", 2: "Chipped anvil", 1: "Damaged anvil"}


def _cfg() -> dict:
    return settings.get()["repair"]


def state(ctx: Ctx, user_id: int) -> int:
    row = ctx.one("SELECT anvil FROM users WHERE user_id=?;", (user_id,))
    return int(row["anvil"]) if row else 0


def label(level: int) -> str:
    return STATES.get(level, "No anvil")


def craft(ctx: Ctx, user_id: int) -> dict:
    """Craft an anvil with iron ingots (one at a time)."""
    have = state(ctx, user_id)
    if have:
        raise GameError(f"You already have an anvil (**{label(have).lower()}**). Craft a new one when it breaks.")
    cost = int(_cfg()["anvil_iron"])
    owned = players.item_amount(ctx, user_id, "ingot", "iron")
    if owned < cost:
        raise GameError(f"An anvil takes **{cost}** iron ingots: you have **{owned}** (`/market` sells them).")
    players.take_item(ctx, user_id, "ingot", "iron", cost)
    players.ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET anvil=? WHERE user_id=?;", (NEW, user_id))
    players.bump_stat(ctx, user_id, "anvils_crafted")
    return {"ingots": cost}


def require(ctx: Ctx, user_id: int, what: str) -> int:
    level = state(ctx, user_id)
    if not level:
        raise GameError(f"You need an anvil to {what}: craft one with `/craft item:anvil` "
                        f"(**{int(_cfg()['anvil_iron'])}** iron ingots).")
    return level


def use(ctx: Ctx, user_id: int) -> dict:
    """The anvil was used: it may get damaged, or break. Returns {"before", "after", "broke"}."""
    before = state(ctx, user_id)
    after = before
    if before and ctx.rng.random() < float(_cfg()["anvil_damage_chance"]):
        after = before - 1
        ctx.execute("UPDATE users SET anvil=? WHERE user_id=?;", (after, user_id))
    return {"before": before, "after": after, "broke": bool(before) and after == 0}


def wear_text(res: dict) -> str:
    """'' when nothing happened, else what happened to the anvil."""
    if res["after"] == res["before"]:
        return ""
    if res["broke"]:
        return "💥 Your anvil broke! Craft a new one with `/craft item:anvil`."
    return f"🔨 Your anvil is now **{label(res['after']).split()[0].lower()}**."
