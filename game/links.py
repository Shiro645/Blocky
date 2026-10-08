"""Links between Discord members and Minecraft accounts, validated by staff."""
from __future__ import annotations

import re

from game.db import Ctx
from game.errors import GameError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def get_link(ctx: Ctx, user_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM links WHERE user_id=?;", (user_id,))
    return dict(row) if row else None


def request_link(ctx: Ctx, user_id: int, username: str) -> dict:
    """Create (or replace) a pending request. Returns the request."""
    if not USERNAME_RE.match(username):
        raise GameError("Invalid Minecraft username (3-16 letters, digits or _).")
    current = get_link(ctx, user_id)
    if current and current["status"] == "approved":
        raise GameError(
            f"You are already linked to **{current['mc_username']}**. Ask the staff if you need to change it."
        )
    taken = ctx.one(
        "SELECT user_id FROM links WHERE mc_username = ? COLLATE NOCASE AND user_id != ?;",
        (username, user_id),
    )
    if taken:
        raise GameError(f"**{username}** is already linked (or requested) by another member.")
    ctx.execute(
        """
        INSERT INTO links(user_id, mc_username, status, requested_at) VALUES(?, ?, 'pending', ?)
        ON CONFLICT(user_id) DO UPDATE SET mc_username=excluded.mc_username, requested_at=excluded.requested_at;
        """,
        (user_id, username, int(ctx.now)),
    )
    return get_link(ctx, user_id)


def _pending(ctx: Ctx, user_id: int) -> dict:
    link = get_link(ctx, user_id)
    if link is None or link["status"] != "pending":
        raise GameError("This request was already handled or cancelled.")
    return link


def approve(ctx: Ctx, user_id: int, staff_id: int) -> dict:
    link = _pending(ctx, user_id)
    ctx.execute(
        "UPDATE links SET status='approved', decided_by=?, decided_at=? WHERE user_id=?;",
        (staff_id, int(ctx.now), user_id),
    )
    return {**link, "status": "approved"}


def reject(ctx: Ctx, user_id: int, staff_id: int) -> dict:
    link = _pending(ctx, user_id)
    ctx.execute("DELETE FROM links WHERE user_id=?;", (user_id,))
    return link


def unlink(ctx: Ctx, user_id: int) -> dict:
    link = get_link(ctx, user_id)
    if link is None:
        raise GameError("This member has no linked Minecraft account.")
    ctx.execute("DELETE FROM links WHERE user_id=?;", (user_id,))
    return link


def check_pending(ctx: Ctx, user_id: int, username: str) -> None:
    """Raise if approving now would be wrong (request changed or cancelled meanwhile)."""
    link = _pending(ctx, user_id)
    if link["mc_username"].lower() != username.lower():
        raise GameError("The member changed their request; use the newest message.")
