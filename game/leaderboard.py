"""Rankings and player profiles."""
from __future__ import annotations

from game import players, shop
from game.db import Ctx

# key -> (label, unit shown after the value)
BOARDS: dict[str, tuple[str, str]] = {
    "emeralds": ("Emeralds", "emerald"),
    "level": ("Level", "level"),
    "fortune": ("Total fortune", "emerald"),
    "blocks_mined": ("Blocks mined", ""),
    "bedrock_found": ("Bedrock found", ""),
    "items_crafted": ("Items crafted", ""),
}


def fortunes(ctx: Ctx) -> dict[int, int]:
    """user_id -> emeralds + value of blocks, sticks, ingots and gear (worn gear is worth less)."""
    total: dict[int, float] = {r["user_id"]: r["emeralds"] for r in ctx.all("SELECT user_id, emeralds FROM users;")}
    for r in ctx.all("SELECT user_id, block_type, amount FROM blocks;"):
        total[r["user_id"]] += r["amount"] * players.block_value(r["block_type"])
    for r in ctx.all("SELECT user_id, item, material, amount FROM items;"):
        unit = shop.stick_value() if r["item"] == "stick" else shop.ingot_value(r["material"])
        total[r["user_id"]] += r["amount"] * unit
    for r in ctx.all("SELECT user_id, item, material, durability, max_durability FROM gear;"):
        wear = r["durability"] / r["max_durability"] if r["max_durability"] else 0
        total[r["user_id"]] += shop.craft_cost(r["item"], r["material"]) * wear
    return {uid: int(v) for uid, v in total.items()}


def ranking(ctx: Ctx, board: str) -> list[tuple[int, int]]:
    """Every player with a non-zero score, best first: [(user_id, value)]."""
    if board == "emeralds":
        rows = ctx.all("SELECT user_id, emeralds AS v FROM users WHERE emeralds > 0 ORDER BY emeralds DESC, user_id;")
        return [(r["user_id"], r["v"]) for r in rows]
    if board == "level":
        rows = ctx.all("SELECT user_id, level FROM users ORDER BY level DESC, xp DESC, user_id;")
        return [(r["user_id"], r["level"]) for r in rows]
    if board == "fortune":
        values = fortunes(ctx)
        return sorted(((u, v) for u, v in values.items() if v > 0), key=lambda x: (-x[1], x[0]))
    if board in BOARDS:
        rows = ctx.all(
            "SELECT user_id, value FROM stats WHERE stat=? AND value > 0 ORDER BY value DESC, user_id;",
            (board,),
        )
        return [(r["user_id"], r["value"]) for r in rows]
    raise ValueError(f"Unknown leaderboard: {board}")


def leaderboard(ctx: Ctx, board: str, user_id: int, limit: int = 10) -> dict:
    """Top `limit` plus the rank of `user_id` (None if unranked)."""
    rows = ranking(ctx, board)
    rank = next((i for i, (uid, _) in enumerate(rows, start=1) if uid == user_id), None)
    return {
        "top": rows[:limit],
        "rank": rank,
        "value": rows[rank - 1][1] if rank else 0,
        "players": len(rows),
    }


def profile(ctx: Ctx, user_id: int) -> dict:
    user = players.get_user(ctx, user_id)
    fortune_rows = ranking(ctx, "fortune")
    fortune_rank = next((i for i, (uid, _) in enumerate(fortune_rows, start=1) if uid == user_id), None)
    level_rank = next((i for i, (uid, _) in enumerate(ranking(ctx, "level"), start=1) if uid == user_id), None)
    return {
        "user": user,
        "stats": players.get_stats(ctx, user_id),
        "fortune": fortunes(ctx).get(user_id, 0),
        "fortune_rank": fortune_rank,
        "level_rank": level_rank,
        "equipped": [g for g in shop.get_gear(ctx, user_id) if g["equipped"]],
    }
