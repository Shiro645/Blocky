"""Staff: reset a player's waiting times (/player cooldowns).

Some waiting times are counted from an event that must stay in the history (a robbery, a
dungeon run): for those a reset is noted in cooldown_resets, and the check ignores the events
before it. The others are simply cleared. The short waits kept in memory (duel, mining, games of
chance) are cleared by the cog.
"""
from __future__ import annotations

from datetime import timedelta

from game import players
from game.db import Ctx

# key -> label, in the order shown to the staff
TIMERS: dict[str, str] = {
    "rob": "Robbing again",
    "rob_protection": "Protection after being robbed",
    "dungeon": "Dungeon",
    "dummy": "Training dummy",
    "boss": "Gate boss fight",
    "duel": "Duels",
    "games": "Games of chance (Lucky Block, wheel, blackjack, mines)",
    "mining": "Mining",
    "species": "Changing species",
    "daily": "Daily reward",
}
IN_MEMORY = ("duel", "games", "mining")  # kept by the cogs, cleared there


def _note(ctx: Ctx, user_id: int, timer: str) -> None:
    ctx.execute(
        """
        INSERT INTO cooldown_resets(user_id, timer, at) VALUES(?, ?, ?)
        ON CONFLICT(user_id, timer) DO UPDATE SET at = excluded.at;
        """,
        (user_id, timer, int(ctx.now)),
    )


def cleared(ctx: Ctx, user_id: int, timer: str, since: float | None) -> bool:
    """True when the staff reset this waiting time after `since` (the event it is counted from)."""
    if since is None:
        return False
    row = ctx.one("SELECT at FROM cooldown_resets WHERE user_id=? AND timer=?;", (user_id, timer))
    return row is not None and row["at"] >= since


def reset(ctx: Ctx, user_id: int, timers: list[str]) -> list[str]:
    """Reset these waiting times. Returns the ones that needed it (in-memory ones always count)."""
    players.ensure_user(ctx, user_id)
    done = []
    for timer in timers:
        if timer in ("rob", "rob_protection", "dungeon", "boss"):
            _note(ctx, user_id, timer)
            done.append(timer)
        elif timer == "dummy":
            if ctx.execute("UPDATE dummy_scores SET last_at=0 WHERE user_id=? AND last_at>0;", (user_id,)).rowcount:
                done.append(timer)
        elif timer == "species":
            if ctx.execute("UPDATE users SET species_changed_at=NULL WHERE user_id=? AND species_changed_at IS NOT NULL;",
                           (user_id,)).rowcount:
                done.append(timer)
        elif timer == "daily":
            # Undo today's claim, keeping the streak: claiming again gives today's reward once more.
            user = players.get_user(ctx, user_id)
            if user["last_daily"] == ctx.today.isoformat():
                ctx.execute(
                    "UPDATE users SET last_daily=?, daily_streak=? WHERE user_id=?;",
                    ((ctx.today - timedelta(days=1)).isoformat(), max(0, user["daily_streak"] - 1), user_id),
                )
                done.append(timer)
        elif timer in IN_MEMORY:
            done.append(timer)
    return done
