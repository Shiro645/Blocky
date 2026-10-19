"""Server events: random drops (the gate bosses are in game/gate.py)."""
from __future__ import annotations

import random

from game import enchants, players, potions, settings
from game.db import Ctx


# ---------------- drops ----------------
def roll_drop(rng: random.Random) -> dict:
    table = settings.get()["drops"]["table"]
    return rng.choices(table, weights=[float(e["weight"]) for e in table])[0]


def describe_reward(reward: dict) -> str:
    if "emeralds" in reward:
        return f"{reward['emeralds']} emeralds"
    if "ingot" in reward:
        return f"{reward['amount']} {reward['ingot']} ingot(s)"
    if "lapis" in reward:
        return f"{reward['lapis']} lapis lazuli"
    if "book" in reward:
        return "an enchanted book"
    if "potions" in reward:
        return f"{reward['potions']} potion(s)"
    return f"{reward['amount']} {reward['block']}"


def claim_drop(ctx: Ctx, user_id: int, drop: dict) -> str:
    """Give the drop's reward. Returns what was won."""
    reward = drop["reward"]
    text = describe_reward(reward)
    if "emeralds" in reward:
        players.earn_emeralds(ctx, user_id, int(reward["emeralds"]))
    elif "ingot" in reward:
        players.add_item(ctx, user_id, "ingot", reward["ingot"], int(reward["amount"]))
    elif "lapis" in reward:
        enchants.give_lapis(ctx, user_id, int(reward["lapis"]))
    elif "book" in reward:
        name, level = enchants.give_random_book(ctx, user_id)
        text = f"a {enchants.label(name, level)} book"
    elif "potions" in reward:
        found = potions.give_random(ctx, user_id, int(reward["potions"]))
        text = ", ".join(potions.label(k) for k in found)
    else:
        players.add_blocks(ctx, user_id, reward["block"], int(reward["amount"]))
        players.add_score(ctx, user_id, players.block_value(reward["block"]) * int(reward["amount"]))
    players.bump_stat(ctx, user_id, "drops_claimed")
    return text
