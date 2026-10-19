"""Prestige (/prestige): start over for good bonuses, up to prestige.max times.

- Prestige n+1 needs level prestige.base_level + prestige.level_step × n (50, 60, 70…), every achievement,
  every dimension (up to the Shimmer) and the server's Beacon lit.
- The level stays. The parts switched on in prestige.reset start over: wealth (emeralds, blocks, items, auction
  listings, loans, bounties put), gear (and its enchantments, the anvil), talents (every spent point is given back
  to spend again: they come from the level, so none is lost), achievements (with the stats and the challenges
  they come from) and dimensions (back to the overworld). With both wealth and achievements reset, achievement rewards are paid again (like /reset).
- Each prestige: +prestige.bonus mining XP and /sell for good, a ⭐ next to the name, the Prestige role, and
  earned cosmetics (game/profiles.py: the titles Reborn and Mythic, the Prestige frame).
"""
from __future__ import annotations

from game import beacon, notices, players, profiles, progress, reset, settings
from game.catalog import DIMENSIONS
from game.db import Ctx
from game.errors import GameError

ROMAN = ("", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
PARTS = {
    "wealth": "emeralds, blocks and items (auction listings, loans and the bounties you put are cancelled)",
    "gear": "gear, its enchantments and the anvil",
    "talents": "talents (every spent point is given back to spend again)",
    "achievements": "achievements, stats and challenges",
    "dimensions": "dimensions (back to the overworld)",
}


def _cfg() -> dict:
    return settings.get()["prestige"]


def roman(n: int) -> str:
    return ROMAN[n] if 0 <= n < len(ROMAN) else str(n)


stars = players.prestige_stars
marks = players.prestige_marks


def level_needed(n: int) -> int:
    """The level Prestige n needs (n ≥ 1)."""
    c = _cfg()
    return int(c["base_level"]) + int(c["level_step"]) * (n - 1)


def bonus(user: dict) -> float:
    """The permanent mining XP and /sell bonus of a player (their users row)."""
    return players.prestige_bonus(user)


def resets() -> list[str]:
    on = _cfg()["reset"]
    return [p for p in PARTS if on.get(p, True)]


def status(ctx: Ctx, user_id: int) -> dict:
    """The player's prestige and what the next one needs."""
    user = players.get_user(ctx, user_id)
    n = int(user["prestige"])
    out = {"prestige": n, "max": int(_cfg()["max"]), "bonus": bonus(user), "resets": resets()}
    if n >= out["max"]:
        return {**out, "next": None, "ready": False}
    every = progress.achievements()
    done = progress.unlocked_codes(ctx, user_id)
    missing = [a for a in every if a.code not in done]
    checks = {
        "level": (int(user["level"]), level_needed(n + 1)),
        "achievements": (len(every) - len(missing), len(every)),
        "dimensions": (int(user["dimension_level"]), len(DIMENSIONS) - 1),
        "beacon": (int(beacon.is_lit(ctx)), 1),
    }
    ready = all(have >= need for have, need in checks.values())
    return {**out, "next": n + 1, "checks": checks, "missing": missing, "ready": ready}


def ascend(ctx: Ctx, user_id: int) -> dict:
    """Become Prestige n+1: the parts of prestige.reset start over."""
    st = status(ctx, user_id)
    if st["next"] is None:
        raise GameError(f"You reached the highest prestige (**{roman(st['max'])}**).")
    if not st["ready"]:
        raise GameError("You don't meet every condition yet: see `/prestige`.")
    parts = st["resets"]
    if "wealth" in parts or "gear" in parts:
        reset.apply(ctx, {p for p in ("wealth", "gear") if p in parts}, user_id)
    if "achievements" in parts:
        for table in ("stats", "achievements", "challenge_progress"):
            ctx.execute(f"DELETE FROM {table} WHERE user_id=?;", (user_id,))
        if "wealth" in parts:  # their rewards are earned again (like /reset)
            ctx.execute("DELETE FROM rewards_paid WHERE user_id=?;", (user_id,))
    if "talents" in parts:
        players.reset_talents(ctx, user_id)
    if "dimensions" in parts:
        ctx.execute("UPDATE users SET dimension_level=0 WHERE user_id=?;", (user_id,))
    n = st["next"]
    ctx.execute("UPDATE users SET prestige=? WHERE user_id=?;", (n, user_id))
    profiles.check_worn(ctx, user_id)  # earned titles and frames whose stats were reset
    ctx.notices.append(notices.PrestigeReached(user_id, n))
    return {"prestige": n, "reset": parts, "bonus": bonus(players.get_user(ctx, user_id))}


def set_prestige(ctx: Ctx, user_id: int, n: int) -> int:
    """Staff: set a player's prestige (nothing is reset)."""
    n = max(0, min(int(n), int(_cfg()["max"])))
    players.ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET prestige=? WHERE user_id=?;", (n, user_id))
    profiles.check_worn(ctx, user_id)
    return n


def holders(ctx: Ctx) -> list[int]:
    """Every player with a prestige (the Prestige role)."""
    return [r["user_id"] for r in ctx.all("SELECT user_id FROM users WHERE prestige > 0;")]
