"""Dimensions: the overworld, then the Nether, the End, the Deep Dark and the Shimmer.

- Each player has the dimensions they unlocked (users.dimension_level: 0 = only the overworld, 1 = up to the
  Nether…). Unlocking one unlocks those before it. Clearing the Nightmare dungeon opens the Nether, then the
  gate bosses (game/gate.py) open the others; the staff can set them too (/player dimension).
- There is one mining channel (channels.mining): each player mines in the dimension they are in (users.
  current_dimension, NULL = their highest). /portal takes them to any dimension they unlocked, and unlocking a
  new one takes them there. Each dimension has its blocks, worth more than the dimension before (game/mining.py),
  and its role (roles.dimension_<key>): a player has the role of the dimension they are in.
- Ores add up from one dimension to the next: gold from the Nether, iron from the End, diamond from the Deep
  Dark, emerald from the Shimmer (an ingot, or emeralds for the emerald; ORE_FROM).
- Netherite only comes from the Nether: mining there can find Ancient debris (a netherite scrap), and
  4 scraps + 4 gold ingots make a netherite ingot (/craft). Netherite gear is a diamond piece upgraded with
  one netherite ingot.
"""
from __future__ import annotations

from game import players, settings
from game.catalog import DIMENSION_ICONS, DIMENSION_NAMES, DIMENSIONS
from game.db import Ctx
from game.errors import GameError

NETHER = DIMENSIONS.index("nether")
# The ores, and the first dimension where each is found (it stays in the ones after).
ORE_FROM = {"gold": "nether", "iron": "end", "diamond": "deep_dark", "emerald": "shimmer"}


def label(dimension: str) -> str:
    return f"{DIMENSION_ICONS[dimension]} {DIMENSION_NAMES[dimension]}"


def level_of(dimension: str) -> int:
    if dimension not in DIMENSIONS:
        raise GameError(f"Unknown dimension. Allowed: {', '.join(DIMENSIONS)}.")
    return DIMENSIONS.index(dimension)


def level(ctx: Ctx, user_id: int) -> int:
    """How far the player went: 0 = the overworld only, 1 = up to the Nether…"""
    return int(players.get_user(ctx, user_id)["dimension_level"])


def highest(ctx: Ctx, user_id: int) -> str:
    return DIMENSIONS[min(level(ctx, user_id), len(DIMENSIONS) - 1)]


def unlocked(ctx: Ctx, user_id: int) -> list[str]:
    return list(DIMENSIONS[: level(ctx, user_id) + 1])


def current(ctx: Ctx, user_id: int) -> str:
    """The dimension the player mines in: the one they went to with /portal, else their highest."""
    user = players.get_user(ctx, user_id)
    here = user["current_dimension"]
    top = min(int(user["dimension_level"]), len(DIMENSIONS) - 1)
    if here in DIMENSIONS and DIMENSIONS.index(here) <= top:
        return here
    return DIMENSIONS[top]


def travel(ctx: Ctx, user_id: int, dimension: str) -> dict:
    """/portal: go to a dimension the player unlocked."""
    target = level_of(dimension)
    if not has(ctx, user_id, dimension):
        raise GameError(f"You haven't unlocked the {label(dimension)} yet: your furthest is the "
                        f"{label(highest(ctx, user_id))}.")
    before = current(ctx, user_id)
    if before == dimension:
        raise GameError(f"You're already in the {label(dimension)}.")
    ctx.execute("UPDATE users SET current_dimension=? WHERE user_id=?;", (DIMENSIONS[target], user_id))
    players.bump_stat(ctx, user_id, "portals_taken")
    return {"before": before, "after": dimension}


def has(ctx: Ctx, user_id: int, dimension: str) -> bool:
    return level(ctx, user_id) >= level_of(dimension)


def has_nether(ctx: Ctx, user_id: int) -> bool:
    return level(ctx, user_id) >= NETHER


def check_nether(ctx: Ctx, user_id: int, what: str) -> None:
    if not has_nether(ctx, user_id):
        raise GameError(f"🔥 {what} needs the **Nether**: netherite is only found there.")


def set_highest(ctx: Ctx, user_id: int, dimension: str) -> dict:
    """Staff: the player now has every dimension up to this one (and none after it)."""
    new = level_of(dimension)
    before = level(ctx, user_id)
    ctx.execute("UPDATE users SET dimension_level=?, current_dimension=NULL WHERE user_id=?;", (new, user_id))
    if new > before:
        players.bump_stat(ctx, user_id, "dimensions_unlocked", new - before)
    return {"before": DIMENSIONS[before], "after": dimension, "unlocked": unlocked(ctx, user_id)}


def multiplier(dimension: str) -> float:
    """How much more a dimension pays than the overworld (tool bonuses follow it)."""
    return 1.0 if dimension == "overworld" else float(settings.get()["dimensions"]["multipliers"][dimension])


def unlock(ctx: Ctx, user_id: int, dimension: str) -> bool:
    """A player reaches a dimension (beating its gate): it and every one before it open. Returns True if it's new."""
    new = level_of(dimension)
    before = level(ctx, user_id)
    if new <= before:
        return False
    # The new dimension opens and the player goes through to it.
    ctx.execute("UPDATE users SET dimension_level=?, current_dimension=NULL WHERE user_id=?;", (new, user_id))
    players.bump_stat(ctx, user_id, "dimensions_unlocked", new - before)
    return True


def odds(dimension: str, pile: str) -> dict[str, float]:
    """Weight of each block of the dimension for a pile ("odds_1_block"…)."""
    if dimension == "overworld":
        return dict(settings.get()["mining"][pile])
    table = settings.get()["dimensions"].get(dimension)
    if not isinstance(table, dict):  # a single block (the Shimmer)
        from game.catalog import DIMENSION_BLOCKS

        return {DIMENSION_BLOCKS[dimension][0]: 1.0}
    return dict(table[pile])


def role_key(dimension: str) -> str:
    return f"dimension_{dimension}"


def ores(dimension: str) -> list[str]:
    """The ores found in a dimension: the ones of every dimension up to it."""
    here = level_of(dimension)
    return [ore for ore, start in ORE_FROM.items() if level_of(start) <= here]


def all_current(ctx: Ctx) -> dict[int, int]:
    """user_id -> the level of the dimension they are in, for the players past the overworld."""
    out = {}
    for r in ctx.all("SELECT user_id, dimension_level, current_dimension FROM users WHERE dimension_level > 0;"):
        top = min(int(r["dimension_level"]), len(DIMENSIONS) - 1)
        here = r["current_dimension"]
        out[r["user_id"]] = DIMENSIONS.index(here) if here in DIMENSIONS and DIMENSIONS.index(here) <= top else top
    return out


def overview(ctx: Ctx, user_id: int) -> dict:
    """What /dimensions shows: how far the player went and their netherite progress."""
    return {
        "level": level(ctx, user_id),
        "current": current(ctx, user_id),
        "scraps": players.item_amount(ctx, user_id, "scrap", "none"),
        "ingots": players.item_amount(ctx, user_id, "ingot", "netherite"),
        "netherite_pieces": ctx.one("SELECT COUNT(*) AS n FROM gear WHERE user_id=? AND material='netherite';",
                                    (user_id,))["n"],
    }
