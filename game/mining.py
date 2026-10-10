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


def pile_weights(amount: int, miner: int, lucky: int) -> dict[str, float]:
    """Weight of each block for a pile of `amount` blocks, with the talent bonuses."""
    m, t = settings.get()["mining"], settings.get()["talents"]
    if amount >= 6:
        weights = dict(m["odds_6_blocks"])
    elif amount >= 4:
        weights = dict(m["odds_4_5_blocks"])
        weights["gravel"] += min(t["miner_gravel_4_5_max"], t["miner_gravel_4_5"] * miner)
    elif amount >= 2:
        weights = dict(m["odds_2_3_blocks"])
        weights["gravel"] += min(t["miner_gravel_2_3_max"], t["miner_gravel_2_3"] * miner)
        weights["deepslate"] += min(t["miner_deepslate_2_3_max"], t["miner_deepslate_2_3"] * miner)
    else:
        weights = dict(m["odds_1_block"])
        weights["obsidian"] += t["lucky_rare_weight"] * lucky
        weights["bedrock"] += t["lucky_rare_weight"] * lucky
    return {b: float(weights[b]) for b in BLOCK_TYPES}


def roll_blocks(rng: random.Random, miner_points: int, lucky_points: int) -> tuple[str, int]:
    t = settings.get()["talents"]
    miner = min(max(0, miner_points), t["caps"]["miner"])
    lucky = min(max(0, lucky_points), t["caps"]["lucky"])
    amount = rng.randint(1, 6)

    weights = pile_weights(amount, miner, lucky)
    possible = [b for b, w in weights.items() if w > 0]
    if len(possible) == 1:  # nothing to roll
        block = possible[0]
    else:
        block = rng.choices(list(weights), weights=list(weights.values()))[0]

    # Miner talent: small chance of one bonus block on big piles.
    if amount >= 4 and rng.random() < min(float(t["miner_bonus_block_max"]), float(t["miner_bonus_block_chance"]) * miner):
        amount += 1
    return block, amount


def spam_mine(ctx: Ctx, user_id: int) -> int:
    """A mining reward in a spam channel: a tiny amount of emeralds (spam_reward), no blocks.

    Fractions are saved (in thousandths) until they make a whole emerald.
    Returns the whole emeralds given now. They don't count for the seasons.
    """
    milli = round(float(settings.get()["mining"]["spam_reward"]) * 1000)
    if milli <= 0:
        return 0
    players.ensure_user(ctx, user_id)
    ctx.execute(
        """
        INSERT INTO stats(user_id, stat, value) VALUES(?, 'spam_milli', ?)
        ON CONFLICT(user_id, stat) DO UPDATE SET value = value + excluded.value;
        """,
        (user_id, milli),
    )
    total = ctx.one("SELECT value FROM stats WHERE user_id=? AND stat='spam_milli';", (user_id,))["value"]
    whole = total // 1000
    if whole:
        ctx.execute("UPDATE stats SET value = value - ? WHERE user_id=? AND stat='spam_milli';", (whole * 1000, user_id))
        players.give_emeralds(ctx, user_id, whole)
    return whole


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
    bonus = 0  # extra cobblestone from the pickaxe and its Fortune
    if pickaxe:
        t = gear.tier(pickaxe["material"])
        # Extra cobblestone, not copies of the block: a rare bedrock stays a single bedrock.
        bonus = g["pickaxe_extra_blocks_per_tier"] * t + fortune(pickaxe)
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
    players.add_blocks(ctx, user_id, "cobblestone", bonus)
    players.add_score(ctx, user_id, players.block_value(block) * amount + players.block_value("cobblestone") * bonus)
    players.bump_stat(ctx, user_id, "blocks_mined", amount + bonus)
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
        "bonus": bonus,
        "sticks": sticks,
        "xp": xp,
        "team_bonus": team_bonus,
        "lapis": lapis,
        "broken": broken,
        "cooldown": cooldown_seconds(
            user["efficiency_points"], enchants.bonus("efficiency", enchants.level_of(pickaxe, "efficiency"))
        ),
    }
