"""Dimensions: the overworld, then the Nether, the End, the Deep Dark and the Shimmer.

- Each player has the dimensions they unlocked (users.dimension_level: 0 = only the overworld, 1 = up to the
  Nether…). Unlocking one unlocks those before it. For now only the staff unlocks them (/player dimension);
  the gate bosses will.
- Each dimension has its mining channels (channels.mining for the overworld, channels.mining_<dimension> for
  the others) and its blocks, worth more than the dimension before (game/mining.py). A message in the channels
  of a dimension the player hasn't unlocked gives nothing.
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
    ctx.execute("UPDATE users SET dimension_level=? WHERE user_id=?;", (new, user_id))
    if new > before:
        players.bump_stat(ctx, user_id, "dimensions_unlocked", new - before)
    return {"before": DIMENSIONS[before], "after": dimension, "unlocked": unlocked(ctx, user_id)}


def multiplier(dimension: str) -> float:
    """How much more a dimension pays than the overworld (tool bonuses follow it)."""
    return 1.0 if dimension == "overworld" else float(settings.get()["dimensions"]["multipliers"][dimension])


def odds(dimension: str, pile: str) -> dict[str, float]:
    """Weight of each block of the dimension for a pile ("odds_1_block"…)."""
    if dimension == "overworld":
        return dict(settings.get()["mining"][pile])
    table = settings.get()["dimensions"].get(dimension)
    if not isinstance(table, dict):  # a single block (the Shimmer)
        from game.catalog import DIMENSION_BLOCKS

        return {DIMENSION_BLOCKS[dimension][0]: 1.0}
    return dict(table[pile])


def channel_key(dimension: str) -> str:
    """The channels list of a dimension in config.json "channels"."""
    return "mining" if dimension == "overworld" else f"mining_{dimension}"


def role_key(dimension: str) -> str:
    return f"dimension_{dimension}"


def all_levels(ctx: Ctx) -> dict[int, int]:
    """user_id -> dimension level, for the players past the overworld."""
    return {r["user_id"]: int(r["dimension_level"])
            for r in ctx.all("SELECT user_id, dimension_level FROM users WHERE dimension_level > 0;")}


def overview(ctx: Ctx, user_id: int) -> dict:
    """What /dimensions shows: how far the player went and their netherite progress."""
    return {
        "level": level(ctx, user_id),
        "scraps": players.item_amount(ctx, user_id, "scrap", "none"),
        "ingots": players.item_amount(ctx, user_id, "ingot", "netherite"),
        "netherite_pieces": ctx.one("SELECT COUNT(*) AS n FROM gear WHERE user_id=? AND material='netherite';",
                                    (user_id,))["n"],
    }
