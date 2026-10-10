"""Roulette: a solo spin against the bank.

The wheel has the numbers 1 to 36 (half red, half black) and one or two green
slots (0, and 00 with settings games.roulette_zeros = 2). Payouts are the
classic ones (the stake included): x2 for red/black, even/odd and 1-18/19-36,
x3 for a dozen, x36 for a number. The green slots make every bet lose a little
on average: 5.3% with 0 and 00, 2.7% with 0 only. Winnings never count for the
seasons (it's chance, not value created).
"""
from __future__ import annotations

from game import players, settings
from game.db import Ctx
from game.errors import GameError

RED = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})

# key -> (label, payout with the stake)
BETS: dict[str, tuple[str, int]] = {
    "red": ("Red", 2),
    "black": ("Black", 2),
    "even": ("Even", 2),
    "odd": ("Odd", 2),
    "low": ("1-18", 2),
    "high": ("19-36", 2),
    "dozen1": ("1st dozen (1-12)", 3),
    "dozen2": ("2nd dozen (13-24)", 3),
    "dozen3": ("3rd dozen (25-36)", 3),
    "number": ("A number", 36),
}


def _cfg() -> dict:
    return settings.get()["games"]


def slots() -> list[str]:
    """Every slot of the wheel: "0" (and "00"), then "1" to "36"."""
    zeros = ["0", "00"][: int(_cfg()["roulette_zeros"])]
    return zeros + [str(n) for n in range(1, 37)]


def color(slot: str) -> str:
    if slot in ("0", "00"):
        return "green"
    return "red" if int(slot) in RED else "black"


def wins(bet: str, number: str | None, slot: str) -> bool:
    if slot in ("0", "00"):
        return bet == "number" and number == slot
    n = int(slot)
    return {
        "red": n in RED,
        "black": n not in RED,
        "even": n % 2 == 0,
        "odd": n % 2 == 1,
        "low": n <= 18,
        "high": n >= 19,
        "dozen1": n <= 12,
        "dozen2": 13 <= n <= 24,
        "dozen3": n >= 25,
        "number": number == slot,
    }[bet]


def check_bet(amount: int) -> None:
    lo, hi = int(_cfg()["min_bet"]), int(_cfg()["max_bet"])
    if not lo <= amount <= hi:
        raise GameError(f"Bets go from **{lo:,}** to **{hi:,}** emeralds.")


def return_rate() -> float:
    """What a bet gives back on average (0.947 with 0 and 00)."""
    return 36 / len(slots())


def spin(ctx: Ctx, user_id: int, bet: str, amount: int, number: str | None = None) -> dict:
    if bet not in BETS:
        raise GameError("Unknown bet.")
    if bet == "number":
        number = (number or "").strip()
        if number not in slots():
            zeros = " or 00" if "00" in slots() else ""
            raise GameError(f"Pick the number you bet on: 0{zeros}, or 1 to 36.")
    else:
        number = None
    check_bet(amount)
    players.spend_emeralds(ctx, user_id, amount)
    slot = ctx.rng.choice(slots())
    won = wins(bet, number, slot)
    payout = amount * BETS[bet][1] if won else 0
    if payout:
        players.give_emeralds(ctx, user_id, payout)  # chance: not counted for the seasons
    players.bump_stat(ctx, user_id, "roulette_spins")
    players.bump_stat(ctx, user_id, "roulette_bet", amount)
    players.bump_stat(ctx, user_id, "roulette_paid", payout)
    return {
        "slot": slot, "color": color(slot), "won": won, "bet": bet, "number": number, "amount": amount,
        "payout": payout, "balance": players.get_emeralds(ctx, user_id),
    }
