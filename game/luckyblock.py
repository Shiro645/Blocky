"""Lucky Block: bet emeralds, break the block, see what falls out.

What can fall out, how often (weight) and what it pays (times the bet, the bet
included) are settings (games.lucky_block). With the defaults each outcome is rarer than
the one before, from the creeper (loses everything) to netherite (1 in 500, x10), and a
block gives back about 84% of the bets on average. Bets, the daily cap and the waiting time are
shared with the wheel (game/gambling.py, games.*).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from game import gambling, players, settings
from game.db import Ctx


@dataclass(frozen=True)
class Outcome:
    key: str
    name: str
    emoji: str
    text: str


OUTCOMES: dict[str, Outcome] = {o.key: o for o in (
    # Only what falls out: what it pays comes from the settings (the result line says it).
    Outcome("creeper", "Creeper", "💥", "A creeper jumps out and explodes!"),
    Outcome("cobblestone", "Cobblestone", "🪨", "Just some cobblestone."),
    Outcome("iron", "Iron", "⚙️", "Iron ingots."),
    Outcome("gold", "Gold", "🟨", "Gold ingots!"),
    Outcome("diamond", "Diamonds", "💎", "Diamonds!"),
    Outcome("emerald", "Emeralds", "🟩", "A pile of emeralds!"),
    Outcome("netherite", "Netherite", "⬛", "NETHERITE! The jackpot!"),
)}


def table() -> list[tuple[Outcome, int, float]]:
    """(outcome, weight, payout) from the settings."""
    cfg = settings.get()["games"]["lucky_block"]
    return [(o, int(cfg[o.key]["weight"]), float(cfg[o.key]["payout"])) for o in OUTCOMES.values()]


def chances() -> list[tuple[Outcome, float, float]]:
    """(outcome, chance, payout) of every outcome that can happen."""
    rows = [(o, w, p) for o, w, p in table() if w > 0]
    total = sum(w for _, w, _ in rows)
    return [(o, w / total, p) for o, w, p in rows]


def return_rate() -> float:
    """What a bet gives back on average (about 0.84 with the defaults)."""
    return sum(chance * payout for _, chance, payout in chances())


def open_block(ctx: Ctx, user_id: int, amount: int) -> dict:
    gambling.check_bet(amount, ctx, user_id)
    gambling.check_day(ctx, user_id)
    players.spend_emeralds(ctx, user_id, amount)
    rows = [(o, w, p) for o, w, p in table() if w > 0]
    outcome, _, payout = ctx.rng.choices(rows, weights=[w for _, w, _ in rows])[0]
    won = math.floor(amount * payout + 0.5)  # halves round up (round() would round 2.5 to 2 but 3.5 to 4)
    if won:
        players.give_emeralds(ctx, user_id, won)  # chance: not counted for the seasons
    gambling.record(ctx, user_id, won - amount)
    players.bump_stat(ctx, user_id, "lucky_blocks")
    players.bump_stat(ctx, user_id, "lucky_bet", amount)
    players.bump_stat(ctx, user_id, "lucky_paid", won)
    return {"outcome": outcome, "payout": payout, "amount": amount, "won": won,
            "balance": players.get_emeralds(ctx, user_id), "net_today": gambling.net_today(ctx, user_id)}
