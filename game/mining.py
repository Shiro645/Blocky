"""Passive mining: every message (outside the cooldown) mines a few blocks."""
from __future__ import annotations

import random

from game import enchants, gear, players, settings, teams
from game.catalog import BLOCK_TYPES
from game.db import Ctx


def cooldown_seconds(efficiency_points: int, enchant_seconds: float = 0) -> int:
    """Talent points and the pickaxe's Efficiency enchantment shorten the cooldown, down to the minimum."""
    m = settings.get()["mining"]
    t = settings.get()["talents"]
    base = int(m["cooldown_seconds"])
    if base <= 0:
        return 0
    points = min(max(0, efficiency_points), t["caps"]["efficiency"])
    return max(int(m["min_cooldown_seconds"]), int(base - t["efficiency_seconds_per_point"] * points - enchant_seconds))


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
            ["cobblestone", "gravel", "deepslate", "obsidian", "bedrock"],
            weights=[70, 20, 9, 3 + lucky, 1 + lucky],
        )[0]

    # Miner talent: small chance of one bonus block on big rolls.
    if amount >= 4 and rng.random() < min(0.25, 0.05 * miner):
        amount += 1
    return block, amount


def upgrade_block(block: str) -> str:
    i = BLOCK_TYPES.index(block)
    return BLOCK_TYPES[min(i + 1, len(BLOCK_TYPES) - 1)]


def mine(ctx: Ctx, user_id: int) -> dict:
    """Mine once with the equipped tools. Returns what was found and the next cooldown."""
    g = settings.get()["gear"]
    user = players.get_user(ctx, user_id)
    tools = gear.get_equipped(ctx, user_id)
    block, amount = roll_blocks(ctx.rng, user["miner_points"], user["lucky_points"])
    used: list[dict] = []
    sticks = 0

    def fortune(piece: dict) -> int:
        return int(enchants.bonus("fortune", enchants.level_of(piece, "fortune")))

    pickaxe = tools.get("pickaxe")
    if pickaxe:
        t = gear.tier(pickaxe["material"])
        amount += g["pickaxe_extra_blocks_per_tier"] * t + fortune(pickaxe)
        if ctx.rng.random() < g["pickaxe_upgrade_chance_per_tier"] * t:
            block = upgrade_block(block)
        used.append(pickaxe)

    shovel = tools.get("shovel")
    if shovel and block == "gravel":
        amount += g["shovel_extra_gravel_per_tier"] * gear.tier(shovel["material"]) + fortune(shovel)
        used.append(shovel)

    axe = tools.get("axe")
    if axe and ctx.rng.random() < g["axe_stick_chance"]:
        sticks = gear.tier(axe["material"]) + fortune(axe)
        players.add_item(ctx, user_id, "stick", "none", sticks)
        used.append(axe)

    lo, hi = settings.get()["mining"]["xp_per_message"]
    xp = ctx.rng.randint(int(lo), int(hi))
    hoe = tools.get("hoe")
    if hoe:
        hoe_bonus = g["hoe_xp_bonus_per_tier"] * gear.tier(hoe["material"])
        hoe_bonus += enchants.hoe_xp_bonus(enchants.level_of(hoe, "fortune"))
        xp = int(round(xp * (1 + hoe_bonus)))
        used.append(hoe)
    team_bonus = teams.activity_bonus(ctx, user_id)
    if team_bonus:
        xp = int(round(xp * (1 + team_bonus)))

    players.add_blocks(ctx, user_id, block, amount)
    players.bump_stat(ctx, user_id, "blocks_mined", amount)
    if block in ("bedrock", "obsidian"):
        players.bump_stat(ctx, user_id, f"{block}_found", amount)
    players.add_xp(ctx, user_id, xp)

    broken = [f"{piece['material']} {piece['item']}" for piece in used if gear.wear(ctx, piece)]

    e = settings.get()["enchants"]
    lapis = 0
    if ctx.rng.random() < float(e["lapis_chance"]):
        lo, hi = (int(n) for n in e["lapis_amount"])
        lapis = ctx.rng.randint(lo, hi)
        enchants.give_lapis(ctx, user_id, lapis)
        players.bump_stat(ctx, user_id, "lapis_found", lapis)

    return {
        "block": block,
        "amount": amount,
        "sticks": sticks,
        "xp": xp,
        "team_bonus": team_bonus,
        "lapis": lapis,
        "broken": broken,
        "cooldown": cooldown_seconds(
            user["efficiency_points"], enchants.bonus("efficiency", enchants.level_of(pickaxe, "efficiency"))
        ),
    }
