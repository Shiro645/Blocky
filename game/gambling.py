"""What every game of chance shares (Lucky Block, the wheel, blackjack, mines): the bet limits and the daily cap,
and the games played over several clicks (blackjack, mines: table chance_games).

The daily cap counts what a player won minus what they lost at these games today
(`games.daily_win_cap`, 0 = no cap): once it's reached they can't play again before
tomorrow. Losing never blocks anyone. Winnings never count for the seasons.
"""
from __future__ import annotations

import json

from game import biomes, live_events, players, settings
from game.db import Ctx
from game.errors import GameError


def _cfg() -> dict:
    return settings.get()["games"]


def max_bet(ctx: Ctx | None = None, user_id: int | None = None) -> int:
    """The highest bet, for this player (Gamblers bet higher: species.gambler_max_bet; everyone during a
    Gambling Frenzy, and in the Desert's week)."""
    top = float(_cfg()["max_bet"])
    if ctx is not None:
        top *= live_events.bet_multiplier(ctx) * biomes.multiplier(ctx, "gamble_bet")  # the Desert
        if user_id is not None:
            from game import species  # here: species imports a lot of the game

            top *= 1 + species.bonus(ctx, user_id, "gambler")
    return int(round(top))


def daily_cap(ctx: Ctx) -> int:
    """What a player can win a day (0 = no cap): more during a Gambling Frenzy."""
    return int(round(int(_cfg()["daily_win_cap"]) * live_events.bet_multiplier(ctx)))


def check_bet(amount: int, ctx: Ctx | None = None, user_id: int | None = None) -> None:
    lo, hi = int(_cfg()["min_bet"]), max_bet(ctx, user_id)
    if not lo <= amount <= hi:
        raise GameError(f"Bets go from **{lo:,}** to **{hi:,}** emeralds.")


# ---------------- games played over several clicks (blackjack, mines) ----------------
def open_game(ctx: Ctx, user_id: int, kind: str, bet: int, state: dict) -> dict:
    """Take the bet (after the usual checks) and start a game. One game of each kind at a time."""
    if ctx.one("SELECT 1 FROM chance_games WHERE user_id=? AND kind=? AND status='active';", (user_id, kind)):
        raise GameError(f"You already have a game of {kind} going: finish it first.")
    check_bet(bet, ctx, user_id)
    check_day(ctx, user_id)
    players.spend_emeralds(ctx, user_id, bet)
    deadline = int(ctx.now + float(_cfg()["move_minutes"]) * 60)
    cur = ctx.execute(
        "INSERT INTO chance_games(user_id, kind, bet, state, created_at, deadline) VALUES(?, ?, ?, ?, ?, ?);",
        (user_id, kind, bet, json.dumps(state), int(ctx.now), deadline),
    )
    return get_game(ctx, cur.lastrowid)


def get_game(ctx: Ctx, game_id: int) -> dict:
    row = ctx.one("SELECT * FROM chance_games WHERE game_id=?;", (game_id,))
    if row is None:
        raise GameError("This game doesn't exist anymore.")
    game = dict(row)
    game["state"] = json.loads(game["state"])
    game["balance"] = players.get_emeralds(ctx, game["user_id"])  # shown once the game is over
    return game


def my_game(ctx: Ctx, game_id: int, user_id: int, kind: str) -> dict:
    """A game the player can still play."""
    game = get_game(ctx, game_id)
    if game["user_id"] != user_id or game["kind"] != kind:
        raise GameError("This isn't your game: start your own!")
    if game["status"] != "active":
        raise GameError("This game is over.")
    return game


def save_game(ctx: Ctx, game: dict, extra_bet: int = 0) -> dict:
    """Store the game after a move (and push its deadline back)."""
    deadline = int(ctx.now + float(_cfg()["move_minutes"]) * 60)
    ctx.execute("UPDATE chance_games SET state=?, bet=bet+?, deadline=? WHERE game_id=?;",
                (json.dumps(game["state"]), extra_bet, deadline, game["game_id"]))
    return get_game(ctx, game["game_id"])


def close_game(ctx: Ctx, game: dict, result: str, paid: int, record_it: bool = True) -> dict:
    """The game is over: pay, add it to today's total (unless it's a refund) and keep how it ended."""
    if paid:
        players.give_emeralds(ctx, game["user_id"], paid)  # chance: not counted for the seasons
    ctx.execute("UPDATE chance_games SET state=?, status='done', result=?, paid=? WHERE game_id=?;",
                (json.dumps(game["state"]), result, paid, game["game_id"]))
    if record_it:
        record(ctx, game["user_id"], paid - game["bet"])
    return get_game(ctx, game["game_id"])


def set_message(ctx: Ctx, game_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE chance_games SET channel_id=?, message_id=? WHERE game_id=?;", (channel_id, message_id, game_id))


def due_games(ctx: Ctx, kind: str) -> list[dict]:
    rows = ctx.all("SELECT game_id FROM chance_games WHERE kind=? AND status='active' AND deadline <= ?;",
                   (kind, int(ctx.now)))
    return [get_game(ctx, r["game_id"]) for r in rows]


def net_today(ctx: Ctx, user_id: int) -> int:
    row = ctx.one("SELECT net FROM gamble_days WHERE user_id=? AND day=?;", (user_id, ctx.today.isoformat()))
    return row["net"] if row else 0


def check_day(ctx: Ctx, user_id: int) -> None:
    cap = daily_cap(ctx)
    if cap and net_today(ctx, user_id) >= cap:
        raise GameError(f"You won **{cap:,}** emeralds or more at games of chance today: that's the limit. "
                        "Come back tomorrow!")


def record(ctx: Ctx, user_id: int, net: int) -> None:
    """A game was played: add what it won (or lost) to today's total."""
    if live_events.active(ctx, "gambling_frenzy"):
        players.bump_stat(ctx, user_id, "frenzy_games")
    ctx.execute(
        """
        INSERT INTO gamble_days(user_id, day, net) VALUES(?, ?, ?)
        ON CONFLICT(user_id, day) DO UPDATE SET net = net + excluded.net;
        """,
        (user_id, ctx.today.isoformat(), net),
    )
