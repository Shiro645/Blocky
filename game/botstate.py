"""Small values the bot keeps between restarts (e.g. which message is the market board)."""
from __future__ import annotations

from game.db import Ctx


def get(ctx: Ctx, key: str) -> str | None:
    row = ctx.one("SELECT value FROM bot_state WHERE key=?;", (key,))
    return row["value"] if row else None


def put(ctx: Ctx, key: str, value: str | None) -> None:
    if value is None:
        ctx.execute("DELETE FROM bot_state WHERE key=?;", (key,))
    else:
        ctx.execute(
            "INSERT INTO bot_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
            (key, value),
        )
