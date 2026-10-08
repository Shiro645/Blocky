"""Passive mining: every message (outside the cooldown) mines a few blocks."""
from __future__ import annotations

import random

from game import players, settings
from game.db import Ctx


def cooldown_seconds(efficiency_points: int) -> int:
    m = settings.get()["mining"]
    t = settings.get()["talents"]
    base = int(m["cooldown_seconds"])
    if base <= 0:
        return 0
    points = min(max(0, efficiency_points), t["caps"]["efficiency"])
    return max(int(m["min_cooldown_seconds"]), base - t["efficiency_seconds_per_point"] * points)


def roll_blocks(rng: random.Random, miner_points: int, lucky_points: int) -> tuple[str, int]:
    caps = settings.get()["talents"]["caps"]
    miner = min(max(0, miner_points), caps["miner"])
    lucky = min(max(0, lucky_points), caps["lucky"])
    amount = rng.randint(1, 6)

    if amount == 6:
        block = "cobblestone"
    elif amount in (4, 5):
        block = rng.choices(["cobblestone", "gravel"], weights=[70, 30 + min(40, miner * 5)])[0]
    elif amount in (2, 3):
        block = rng.choices(
            ["cobblestone", "gravel", "deepslate"],
            weights=[70, 20 + min(30, miner * 3), 10 + min(30, miner * 2)],
        )[0]
    else:
        block = rng.choices(
            ["cobblestone", "gravel", "deepslate", "bedrock"],
            weights=[70, 20, 9, 1 + lucky],
        )[0]

    # Miner talent: small chance of one bonus block on big rolls.
    if amount >= 4 and rng.random() < min(0.25, 0.05 * miner):
        amount += 1
    return block, amount


def mine(ctx: Ctx, user_id: int) -> dict:
    """Mine once. Returns what was found and the cooldown before the next mining."""
    user = players.get_user(ctx, user_id)
    block, amount = roll_blocks(ctx.rng, user["miner_points"], user["lucky_points"])

    players.add_blocks(ctx, user_id, block, amount)
    players.bump_stat(ctx, user_id, "blocks_mined", amount)
    if block == "bedrock":
        players.bump_stat(ctx, user_id, "bedrock_found", amount)

    lo, hi = settings.get()["mining"]["xp_per_message"]
    xp = ctx.rng.randint(int(lo), int(hi))
    players.add_xp(ctx, user_id, xp)

    return {
        "block": block,
        "amount": amount,
        "xp": xp,
        "cooldown": cooldown_seconds(user["efficiency_points"]),
    }
