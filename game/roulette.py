"""The wheel (/wheel): a Minecraft roulette, a solo spin against the bank.

The wheel has the numbers 1 to 36, as on a real roulette: the red ones are Redstone, the black
ones Obsidian, and the green slot (0, plus 00 with settings games.roulette_zeros = 2) is a
Diamond block. Payouts are the classic ones (the stake included): x2 for Redstone/Obsidian,
even/odd and 1-18/19-36, x3 for a dozen, x36 for a number, and a Diamond block pays as a bet on
those green slots (x36 with one, x18 with two). The green slots make every bet lose a little on
average: 2.7% with 0 only (the default), 5.3% with 0 and 00. Which bets players may make is a
setting (games.roulette_bets): Redstone, Obsidian and a number by default. Winnings never count for the
seasons (it's chance, not value created).
"""
from __future__ import annotations

from game import gambling, players, settings
from game.db import Ctx
from game.errors import GameError

RED = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})

# key -> (label, payout with the stake); the Diamond block's payout depends on the green slots (payout())
BETS: dict[str, tuple[str, int]] = {
    "red": ("🟥 Redstone", 2),
    "black": ("⬛ Obsidian", 2),
    "green": ("💎 Diamond block", 18),
    "even": ("Even", 2),
    "odd": ("Odd", 2),
    "low": ("1-18", 2),
    "high": ("19-36", 2),
    "dozen1": ("1st dozen (1-12)", 3),
    "dozen2": ("2nd dozen (13-24)", 3),
    "dozen3": ("3rd dozen (25-36)", 3),
    "number": ("🎯 A number", 36),
}


def _cfg() -> dict:
    return settings.get()["games"]


def slots() -> list[str]:
    """Every slot of the wheel: "0" (and "00"), then "1" to "36"."""
    zeros = ["0", "00"][: int(_cfg()["roulette_zeros"])]
    return zeros + [str(n) for n in range(1, 37)]


# What each colour of slot is on the wheel.
BLOCKS = {"red": ("🟥", "Redstone"), "black": ("⬛", "Obsidian"), "green": ("💎", "Diamond block")}
# The setting that opens each bet (games.roulette_bets); the three dozens share one.
BET_GROUP = {"dozen1": "dozens", "dozen2": "dozens", "dozen3": "dozens"}


def bet_open(bet: str) -> bool:
    return bool(_cfg()["roulette_bets"].get(BET_GROUP.get(bet, bet), False))


def open_bets() -> list[str]:
    return [b for b in BETS if bet_open(b)]


def payout(bet: str) -> int:
    """Times the stake a winning bet pays (the stake included)."""
    if bet == "green":
        return 36 // len([s for s in slots() if s in ("0", "00")])
    return BETS[bet][1]


def slot_label(slot: str) -> str:
    """'🟥 Redstone 17', '💎 Diamond block 00'"""
    emoji, name = BLOCKS[color(slot)]
    return f"{emoji} {name} {slot}"


def color(slot: str) -> str:
    if slot in ("0", "00"):
        return "green"
    return "red" if int(slot) in RED else "black"


def wins(bet: str, number: str | None, slot: str) -> bool:
    if slot in ("0", "00"):
        return bet == "green" or (bet == "number" and number == slot)
    if bet == "green":
        return False
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


check_bet = gambling.check_bet


def is_open() -> bool:
    """The wheel can be closed by the staff (games.roulette_enabled)."""
    return bool(_cfg()["roulette_enabled"])


def return_rate() -> float:
    """What a bet gives back on average (0.973 with 0 only, 0.947 with 0 and 00)."""
    return 36 / len(slots())


def spin(ctx: Ctx, user_id: int, bet: str, amount: int, number: str | None = None) -> dict:
    if bet not in BETS:
        raise GameError("Unknown bet. Pick one from the suggestions.")
    if not bet_open(bet):
        names = ", ".join(BETS[b][0] for b in open_bets()) or "nothing"
        raise GameError(f"You can't bet on that right now. Open bets: {names}.")
    if bet == "number":
        number = (number or "").strip()
        if number not in slots():
            zeros = " or 00" if "00" in slots() else ""
            raise GameError(f"Pick the number you bet on: 0{zeros}, or 1 to 36.")
    else:
        number = None
    if not is_open():
        raise GameError("🎡 The wheel is closed for now: try `/luckyblock`!")
    check_bet(amount, ctx, user_id)
    gambling.check_day(ctx, user_id)
    players.spend_emeralds(ctx, user_id, amount)
    slot = ctx.rng.choice(slots())
    won = wins(bet, number, slot)
    payout_ = amount * payout(bet) if won else 0
    if payout_:
        players.give_emeralds(ctx, user_id, payout_)  # chance: not counted for the seasons
    gambling.record(ctx, user_id, payout_ - amount)
    players.bump_stat(ctx, user_id, "roulette_spins")
    players.bump_stat(ctx, user_id, "roulette_bet", amount)
    players.bump_stat(ctx, user_id, "roulette_paid", payout_)
    if won and bet == "number":
        players.bump_stat(ctx, user_id, "roulette_numbers_won")
    return {
        "slot": slot, "color": color(slot), "won": won, "bet": bet, "number": number, "amount": amount,
        "payout": payout_, "balance": players.get_emeralds(ctx, user_id),
    }
