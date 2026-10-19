"""Passive mining: every message (outside the cooldown) mines a few blocks."""
from __future__ import annotations

import random

from game import dimensions, enchants, gear, live_events, players, settings, species, teams
from game.catalog import DIMENSION_BLOCKS, rank_block
from game.db import Ctx
from game.errors import GameError


def cooldown_seconds(efficiency_points: int, enchant_seconds: float = 0) -> int:
    """Talent points and the pickaxe's Efficiency enchantment shorten the cooldown, down to the minimum."""
    m = settings.get()["mining"]
    t = settings.get()["talents"]
    base = int(m["cooldown_seconds"])
    if base <= 0:
        return 0
    points = min(max(0, efficiency_points), t["caps"]["efficiency"])
    return max(int(m["min_cooldown_seconds"]), int(base - t["efficiency_seconds_per_point"] * points - enchant_seconds))


def pile_weights(amount: int, miner: int, lucky: int, rare: float = 1.0, dimension: str = "overworld") -> dict[str, float]:
    """Weight of each block of the dimension for a pile of `amount` blocks, with the talent bonuses (`rare`: the
    rare blocks weigh that much more, during a Lucky Hour). In every dimension the bonuses go to the blocks of
    the same rank as in the overworld: Miner to gravel's and deepslate's, Lucky to obsidian's and bedrock's."""
    t = settings.get()["talents"]
    second, third = rank_block(dimension, 1), rank_block(dimension, 2)
    rares = {rank_block(dimension, 3), rank_block(dimension, 4)}
    if amount >= 6:
        weights = dimensions.odds(dimension, "odds_6_blocks")
    elif amount >= 4:
        weights = dimensions.odds(dimension, "odds_4_5_blocks")
        weights[second] += min(t["miner_gravel_4_5_max"], t["miner_gravel_4_5"] * miner)
    elif amount >= 2:
        weights = dimensions.odds(dimension, "odds_2_3_blocks")
        weights[second] += min(t["miner_gravel_2_3_max"], t["miner_gravel_2_3"] * miner)
        weights[third] += min(t["miner_deepslate_2_3_max"], t["miner_deepslate_2_3"] * miner)
    else:
        weights = dimensions.odds(dimension, "odds_1_block")
        for block in (rank_block(dimension, 3), rank_block(dimension, 4)):
            weights[block] += t["lucky_rare_weight"] * lucky
    for block in rares:
        weights[block] *= rare
    return {b: float(weights.get(b, 0)) for b in DIMENSION_BLOCKS[dimension]}


def roll_blocks(rng: random.Random, miner_points: int, lucky_points: int, rare: float = 1.0,
                dimension: str = "overworld") -> tuple[str, int]:
    t = settings.get()["talents"]
    miner = min(max(0, miner_points), t["caps"]["miner"])
    lucky = min(max(0, lucky_points), t["caps"]["lucky"])
    amount = rng.randint(1, 6)

    weights = pile_weights(amount, miner, lucky, rare, dimension)
    possible = [b for b, w in weights.items() if w > 0]
    if len(possible) == 1:  # nothing to roll
        block = possible[0]
    else:
        block = rng.choices(list(weights), weights=list(weights.values()))[0]

    # Miner talent: small chance of one bonus block on big piles.
    if amount >= int(t["miner_bonus_min_pile"]) and rng.random() < min(float(t["miner_bonus_block_max"]), float(t["miner_bonus_block_chance"]) * miner):
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


def upgrade_block(block: str, dimension: str = "overworld") -> str:
    """The next block of the same dimension (the rarest one stays)."""
    blocks = DIMENSION_BLOCKS[dimension]
    i = blocks.index(block)
    return blocks[min(i + 1, len(blocks) - 1)]


def mine(ctx: Ctx, user_id: int, dimension: str = "overworld") -> dict:
    """Mine once in a dimension with the equipped tools. Returns what was found and the next cooldown."""
    if not dimensions.has(ctx, user_id, dimension):
        raise GameError(f"You haven't unlocked the {dimensions.label(dimension)} yet.")
    g = settings.get()["gear"]
    user = players.get_user(ctx, user_id)
    tools = gear.get_equipped(ctx, user_id)
    common = rank_block(dimension, 0)
    block, amount = roll_blocks(ctx.rng, user["miner_points"], user["lucky_points"], live_events.rare_multiplier(ctx),
                                dimension)
    used: list[dict] = []
    sticks = 0

    def fortune(piece: dict) -> int:
        # A boosted Fortune (Mages) gives the fraction as a chance of one more.
        value = enchants.effect(piece, "fortune")
        whole = int(value)
        if value - whole > 1e-9 and ctx.rng.random() < value - whole:
            whole += 1
        return whole

    def scaled(count: int, ow_block: str, block: str) -> int:
        """Tool bonuses are worth what they'd be in the overworld times the dimension's multiplier, given in the
        dimension's blocks (the fraction is a chance of one more)."""
        value = count * players.block_value(ow_block) * dimensions.multiplier(dimension) / max(1, players.block_value(block))
        whole = int(value)
        if value - whole > 1e-9 and ctx.rng.random() < value - whole:
            whole += 1
        return whole

    pickaxe = tools.get("pickaxe")
    bonus = 0  # extra common blocks (cobblestone, netherrack…) from the pickaxe and its Fortune
    if pickaxe:
        t = gear.tier(pickaxe["material"])
        # Extra common blocks, not copies of the block: a rare bedrock stays a single bedrock.
        bonus = scaled(g["pickaxe_extra_blocks_per_tier"] * t + fortune(pickaxe), "cobblestone", common)
        if ctx.rng.random() < g["pickaxe_upgrade_chance_per_tier"] * t:
            block = upgrade_block(block, dimension)
        used.append(pickaxe)

    shovel = tools.get("shovel")
    second = rank_block(dimension, 1)  # gravel, or the block of its rank
    if second == common:  # a single block (the Shimmer): the shovel helps as often as on overworld gravel
        weights = pile_weights(min(amount, 6), 0, 0)
        dig = ctx.rng.random() < weights["gravel"] / sum(weights.values())
    else:
        dig = block == second
    if shovel and dig:
        extra = g["shovel_extra_gravel_per_tier"] * gear.tier(shovel["material"]) + fortune(shovel)
        amount += scaled(extra, "gravel", block)
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
        hoe_bonus += enchants.hoe_xp_bonus(enchants.level_of(hoe, "fortune")) * float(hoe.get("enchant_boost", 1.0))
        xp = int(round(xp * (1 + hoe_bonus)))
        used.append(hoe)
    team_bonus = teams.activity_bonus(ctx, user_id)
    if team_bonus:
        xp = int(round(xp * (1 + team_bonus)))
    rush = live_events.xp_multiplier(ctx)  # a Mining Rush
    if rush != 1:
        xp = int(round(xp * rush))

    players.add_blocks(ctx, user_id, block, amount)
    players.add_blocks(ctx, user_id, common, bonus)
    players.add_score(ctx, user_id, players.block_value(block) * amount + players.block_value(common) * bonus)
    players.bump_stat(ctx, user_id, "blocks_mined", amount + bonus)
    if block in ("bedrock", "obsidian"):
        players.bump_stat(ctx, user_id, f"{block}_found", amount)
    if dimension != "overworld":
        players.bump_stat(ctx, user_id, f"blocks_mined_{dimension}", amount + bonus)
    players.add_xp(ctx, user_id, xp)

    broken = [f"{piece['material']} {piece['item']}" for piece in used if gear.wear(ctx, piece)]

    e = settings.get()["enchants"]
    lapis = 0
    if ctx.rng.random() < float(e["lapis_chance"]):
        lo, hi = (int(n) for n in e["lapis_amount"])
        lapis = ctx.rng.randint(lo, hi)
        enchants.give_lapis(ctx, user_id, lapis)
        players.bump_stat(ctx, user_id, "lapis_found", lapis)

    # Ancient debris: a netherite scrap, only from the Nether on.
    scrap = 0
    if dimensions.level_of(dimension) >= dimensions.NETHER:
        if ctx.rng.random() < float(settings.get()["dimensions"]["scrap_chance"]):
            scrap = 1
            players.add_item(ctx, user_id, "scrap", "none", scrap)
            players.bump_stat(ctx, user_id, "scraps_found", scrap)

    cooldown = cooldown_seconds(user["efficiency_points"], enchants.effect(pickaxe, "efficiency"))
    speed = species.bonus(ctx, user_id, "miner")
    if speed and cooldown > 0:
        cooldown = max(1, round(cooldown * (1 - speed)))  # even below the minimum
    return {
        "dimension": dimension,
        "block": block,
        "amount": amount,
        "bonus": bonus,
        "bonus_block": common,
        "scrap": scrap,
        "sticks": sticks,
        "xp": xp,
        "team_bonus": team_bonus,
        "rush": rush,
        "lapis": lapis,
        "broken": broken,
        "cooldown": cooldown,
    }
