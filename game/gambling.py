"""What every game of chance shares (Lucky Block, the wheel): the bet limits and the daily cap.

The daily cap counts what a player won minus what they lost at these games today
(`games.daily_win_cap`, 0 = no cap): once it's reached they can't play again before
tomorrow. Losing never blocks anyone. Winnings never count for the seasons.
"""
from __future__ import annotations

from game import settings
from game.db import Ctx
from game.errors import GameError


def _cfg() -> dict:
    return settings.get()["games"]


def max_bet(ctx: Ctx | None = None, user_id: int | None = None) -> int:
    """The highest bet, for this player (Gamblers bet higher: species.gambler_max_bet)."""
    top = int(_cfg()["max_bet"])
    if ctx is not None and user_id is not None:
        from game import species  # here: species imports a lot of the game

        top = int(round(top * (1 + species.bonus(ctx, user_id, "gambler"))))
    return top


def check_bet(amount: int, ctx: Ctx | None = None, user_id: int | None = None) -> None:
    lo, hi = int(_cfg()["min_bet"]), max_bet(ctx, user_id)
    if not lo <= amount <= hi:
        raise GameError(f"Bets go from **{lo:,}** to **{hi:,}** emeralds.")


def net_today(ctx: Ctx, user_id: int) -> int:
    row = ctx.one("SELECT net FROM gamble_days WHERE user_id=? AND day=?;", (user_id, ctx.today.isoformat()))
    return row["net"] if row else 0


def check_day(ctx: Ctx, user_id: int) -> None:
    cap = int(_cfg()["daily_win_cap"])
    if cap and net_today(ctx, user_id) >= cap:
        raise GameError(f"You won **{cap:,}** emeralds or more at games of chance today: that's the limit. "
                        "Come back tomorrow!")


def record(ctx: Ctx, user_id: int, net: int) -> None:
    ctx.execute(
        """
        INSERT INTO gamble_days(user_id, day, net) VALUES(?, ?, ?)
        ON CONFLICT(user_id, day) DO UPDATE SET net = net + excluded.net;
        """,
        (user_id, ctx.today.isoformat(), net),
    )
