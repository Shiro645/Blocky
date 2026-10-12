"""Players blocked from Blocky by the staff (/blocky ban), for a while or until lifted.

A blocked player can't use the bot's commands, buttons or menus (except /help),
but keeps what they own and still mines by chatting.
"""
from __future__ import annotations

from game.db import Ctx
from game.errors import GameError


def _row(r) -> dict:
    return {"user_id": r["user_id"], "until": r["until"], "reason": r["reason"], "by_id": r["by_id"], "at": r["at"]}


def active(ctx: Ctx) -> dict[int, dict]:
    """user_id -> their block, for the blocks still running (finished ones are forgotten)."""
    ctx.execute("DELETE FROM blocky_bans WHERE until IS NOT NULL AND until <= ?;", (int(ctx.now),))
    return {r["user_id"]: _row(r) for r in ctx.all("SELECT * FROM blocky_bans ORDER BY at;")}


def ban(ctx: Ctx, user_id: int, seconds: int | None, reason: str | None, by_id: int) -> dict:
    """Block a player for `seconds` (None = until lifted). A new block replaces the previous one."""
    now = int(ctx.now)
    until = now + seconds if seconds is not None else None
    before = active(ctx).get(user_id)
    ctx.execute(
        """
        INSERT INTO blocky_bans(user_id, until, reason, by_id, at) VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET until=excluded.until, reason=excluded.reason, by_id=excluded.by_id, at=excluded.at;
        """,
        (user_id, until, reason, by_id, now),
    )
    return {"user_id": user_id, "until": until, "reason": reason, "by_id": by_id, "at": now, "before": before}


def unban(ctx: Ctx, user_id: int) -> dict:
    block = active(ctx).get(user_id)
    if block is None:
        raise GameError(f"<@{user_id}> isn't blocked from Blocky.")
    ctx.execute("DELETE FROM blocky_bans WHERE user_id=?;", (user_id,))
    return block
