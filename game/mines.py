"""Mines (/mines): dig blocks for emeralds, without hitting the TNT.

- 20 blocks, some hiding TNT (the player picks how many, 1 to games.mines_tnt_max).
- Each safe block dug raises the multiplier; cash out any time after the first one. Digging the TNT loses
  the bet. The multiplier is what a fair game would pay times games.mines_return (0.95), and the game cashes
  out by itself at games.mines_max_multiplier, or when every safe block is dug.
- Bets and the daily cap are shared with the other games of chance (game/gambling.py). No move for
  games.move_minutes: you cash out (or get the bet back if you dug nothing).
"""
from __future__ import annotations

import math

from game import gambling, players, settings
from game.db import Ctx
from game.errors import GameError

KIND = "mines"
CELLS = 20  # 4 rows of 5 buttons, the 5th row holds the cash out button


def _cfg() -> dict:
    return settings.get()["games"]


def multiplier(dug: int, tnt: int) -> float:
    """What a cash out pays (times the bet) after `dug` safe blocks with `tnt` TNT."""
    fair = 1.0
    for i in range(dug):
        fair *= (CELLS - i) / (CELLS - tnt - i)
    return min(float(_cfg()["mines_max_multiplier"]), fair * float(_cfg()["mines_return"])) if dug else 0.0


def start(ctx: Ctx, user_id: int, amount: int, tnt: int) -> dict:
    if not _cfg()["mines_enabled"]:
        raise GameError("💣 The mines are closed for now.")
    top = int(_cfg()["mines_tnt_max"])
    if not 1 <= tnt <= min(top, CELLS - 1):
        raise GameError(f"Hide 1 to {min(top, CELLS - 1)} TNT.")
    state = {"tnt": sorted(ctx.rng.sample(range(CELLS), tnt)), "dug": []}
    game = gambling.open_game(ctx, user_id, KIND, amount, state)
    players.bump_stat(ctx, user_id, "mines_games")
    players.bump_stat(ctx, user_id, "mines_bet", amount)
    return game


def payout(game: dict) -> int:
    return math.floor(game["bet"] * multiplier(len(game["state"]["dug"]), len(game["state"]["tnt"])) + 0.5)


def dig(ctx: Ctx, game_id: int, user_id: int, cell: int) -> dict:
    game = gambling.my_game(ctx, game_id, user_id, KIND)
    state = game["state"]
    if not 0 <= cell < CELLS or cell in state["dug"]:
        raise GameError("Pick a block you haven't dug yet.")
    state["dug"].append(cell)
    if cell in state["tnt"]:
        state["boom"] = cell
        return gambling.close_game(ctx, game, "boom", 0)
    tnt, dug = len(state["tnt"]), len(state["dug"])
    if dug == CELLS - tnt or multiplier(dug, tnt) >= float(_cfg()["mines_max_multiplier"]):
        return _cash(ctx, game)  # nothing better to win
    return gambling.save_game(ctx, game)


def cash_out(ctx: Ctx, game_id: int, user_id: int) -> dict:
    game = gambling.my_game(ctx, game_id, user_id, KIND)
    if not game["state"]["dug"]:
        raise GameError("Dig at least one block before you cash out.")
    return _cash(ctx, game)


def _cash(ctx: Ctx, game: dict) -> dict:
    paid = payout(game)
    if paid > game["bet"]:
        players.bump_stat(ctx, game["user_id"], "mines_wins")
    players.bump_stat(ctx, game["user_id"], "mines_paid", paid)
    return gambling.close_game(ctx, game, "cashed", paid)


def expire(ctx: Ctx) -> list[dict]:
    """Games left without a move: cash out, or the bet back when nothing was dug."""
    out = []
    for game in gambling.due_games(ctx, KIND):
        if game["state"]["dug"]:
            out.append(_cash(ctx, game))
        else:
            out.append(gambling.close_game(ctx, game, "refunded", game["bet"], record_it=False))
    return out
