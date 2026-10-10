"""Moderation records: warnings, mutes, kicks and bans.

Discord does the actual muting (timeouts) and banning; this module keeps the
history and knows what must happen next:
- a Discord timeout lasts 28 days at most, so long and permanent mutes are
  renewed by the bot before they end (and re-applied if the member rejoins);
- temporary bans are lifted by the bot when they expire;
- warnings stop counting after some days, and reaching some numbers of
  warnings mutes the member automatically.
"""
from __future__ import annotations

import json
import re

from game import settings
from game.db import Ctx
from game.errors import GameError

MINUTE, HOUR, DAY = 60, 3600, 86400
UNITS = {"s": 1, "m": MINUTE, "h": HOUR, "d": DAY, "w": 7 * DAY}
PERMANENT = {"perm", "perma", "permanent", "forever", "def", "definitif", "définitif"}
# Discord refuses timeouts longer than 28 days: renew a bit before that.
MAX_TIMEOUT = 27 * DAY
RENEW_BEFORE = DAY

_PART = re.compile(r"(\d+)\s*([smhdw])")


def _cfg() -> dict:
    return settings.get()["moderation"]


# ---------------- durations ----------------
def parse_duration(text: str | None) -> int | None:
    """'10m', '2h', '1d12h', '1w' -> seconds; 'perm' (or nothing) -> None (permanent)."""
    text = (text or "").strip().lower()
    if not text or text in PERMANENT:
        return None
    compact = text.replace(" ", "")
    parts = _PART.findall(compact)
    if not parts or "".join(n + u for n, u in parts) != compact:
        raise GameError("Invalid duration. Use for example `30m`, `2h`, `3d`, `1w`, `1d12h`, or `perm`.")
    seconds = sum(int(n) * UNITS[u] for n, u in parts)
    if seconds < MINUTE:
        raise GameError("The minimum duration is 1 minute.")
    if seconds > 365 * DAY:
        raise GameError("The maximum duration is 1 year (use `perm` for permanent).")
    return seconds


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "permanent"
    out = []
    for unit, size in (("w", 7 * DAY), ("d", DAY), ("h", HOUR), ("m", MINUTE)):
        if seconds >= size:
            out.append(f"{seconds // size}{unit}")
            seconds %= size
    return " ".join(out) or "less than 1m"


# ---------------- records ----------------
def get(ctx: Ctx, sanction_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM sanctions WHERE sanction_id=?;", (sanction_id,))
    return dict(row) if row else None


def add(ctx: Ctx, user_id: int, kind: str, reason: str | None, moderator_id: int, duration: int | None = None) -> dict:
    """Record a sanction. A new mute or ban replaces the one in force."""
    if kind in ("mute", "ban"):
        _end(ctx, user_id, kind, moderator_id)
    expires = int(ctx.now + duration) if duration is not None and kind in ("mute", "ban") else None
    active = 1 if kind in ("warn", "mute", "ban") else 0
    cur = ctx.execute(
        """
        INSERT INTO sanctions(user_id, kind, reason, moderator_id, created_at, expires_at, active)
        VALUES(?, ?, ?, ?, ?, ?, ?);
        """,
        (user_id, kind, reason, moderator_id, int(ctx.now), expires, active),
    )
    return get(ctx, int(cur.lastrowid))  # type: ignore[return-value]


def _end(ctx: Ctx, user_id: int, kind: str, by: int | None) -> list[dict]:
    rows = [
        dict(r) for r in ctx.all(
            "SELECT * FROM sanctions WHERE user_id=? AND kind=? AND active=1;", (user_id, kind)
        )
    ]
    ctx.execute(
        "UPDATE sanctions SET active=0, ended_at=?, ended_by=? WHERE user_id=? AND kind=? AND active=1;",
        (int(ctx.now), by, user_id, kind),
    )
    return rows


def lift(ctx: Ctx, user_id: int, kind: str, moderator_id: int) -> list[dict]:
    """End the mute or ban in force (unmute / unban). Returns what was ended."""
    return _end(ctx, user_id, kind, moderator_id)


def active(ctx: Ctx, user_id: int, kind: str) -> dict | None:
    row = ctx.one(
        "SELECT * FROM sanctions WHERE user_id=? AND kind=? AND active=1 ORDER BY sanction_id DESC LIMIT 1;",
        (user_id, kind),
    )
    return dict(row) if row else None


def set_applied(ctx: Ctx, sanction_id: int, until: int) -> None:
    ctx.execute("UPDATE sanctions SET applied_until=? WHERE sanction_id=?;", (until, sanction_id))


def timeout_until(ctx: Ctx, sanction: dict) -> int:
    """End of the Discord timeout to set now for a mute (28 days at most)."""
    limit = int(ctx.now + MAX_TIMEOUT)
    return limit if sanction["expires_at"] is None else min(sanction["expires_at"], limit)


# ---------------- warnings ----------------
def warns(ctx: Ctx, user_id: int) -> list[dict]:
    """Warnings that still count."""
    days = int(_cfg()["warn_expire_days"])
    since = int(ctx.now - days * DAY) if days > 0 else 0
    rows = ctx.all(
        """
        SELECT * FROM sanctions WHERE user_id=? AND kind='warn' AND active=1 AND created_at >= ?
        ORDER BY sanction_id;
        """,
        (user_id, since),
    )
    return [dict(r) for r in rows]


def warn(ctx: Ctx, user_id: int, reason: str, moderator_id: int) -> dict:
    """Record a warning.

    "auto_mute" is True when this warning triggers an automatic mute, of
    "duration" seconds (None = permanent). No automatic mute when the member
    already has a mute that lasts longer: a warning never shortens a mute.
    """
    sanction = add(ctx, user_id, "warn", reason, moderator_id)
    count = len(warns(ctx, user_id))
    rule = (_cfg()["warn_mutes"] or {}).get(str(count))
    duration = parse_duration(str(rule)) if rule else None
    auto = rule is not None
    current = active(ctx, user_id, "mute")
    if auto and current is not None:
        current_end = current["expires_at"]
        new_end = None if duration is None else ctx.now + duration
        if current_end is None or (new_end is not None and current_end >= new_end):
            auto = False
    return {"sanction": sanction, "count": count, "auto_mute": auto, "duration": duration, "rule": rule}


def remove_warn(ctx: Ctx, sanction_id: int, moderator_id: int) -> dict:
    row = get(ctx, sanction_id)
    if row is None or row["kind"] != "warn":
        raise GameError(f"Warning `#{sanction_id}` doesn't exist.")
    if not row["active"]:
        raise GameError(f"Warning `#{sanction_id}` was already removed.")
    ctx.execute(
        "UPDATE sanctions SET active=0, ended_at=?, ended_by=? WHERE sanction_id=?;",
        (int(ctx.now), moderator_id, sanction_id),
    )
    return row


def clear_warns(ctx: Ctx, user_id: int, moderator_id: int) -> int:
    return len(_end(ctx, user_id, "warn", moderator_id))


# ---------------- channel locks ----------------
def lock(ctx: Ctx, channel_id: int, saved: dict, moderator_id: int) -> None:
    """Remember the permissions /lock changes, so /unlock puts them back."""
    if ctx.one("SELECT 1 FROM channel_locks WHERE channel_id=?;", (channel_id,)):
        raise GameError("This channel is already locked. Use `/unlock` first.")
    ctx.execute(
        "INSERT INTO channel_locks(channel_id, saved, locked_by, locked_at) VALUES(?, ?, ?, ?);",
        (channel_id, json.dumps(saved), moderator_id, int(ctx.now)),
    )


def unlock(ctx: Ctx, channel_id: int) -> dict:
    """The saved permissions of a locked channel (and forget the lock)."""
    row = ctx.one("SELECT saved FROM channel_locks WHERE channel_id=?;", (channel_id,))
    if row is None:
        raise GameError("This channel wasn't locked with `/lock`.")
    ctx.execute("DELETE FROM channel_locks WHERE channel_id=?;", (channel_id,))
    return json.loads(row["saved"])


# ---------------- history and clock ----------------
def history(ctx: Ctx, user_id: int, limit: int = 20) -> dict:
    rows = ctx.all(
        "SELECT * FROM sanctions WHERE user_id=? ORDER BY sanction_id DESC LIMIT ?;", (user_id, limit)
    )
    total = ctx.one("SELECT COUNT(*) AS n FROM sanctions WHERE user_id=?;", (user_id,))["n"]
    return {
        "rows": [dict(r) for r in rows],
        "total": total,
        "warns": len(warns(ctx, user_id)),
        "mute": active(ctx, user_id, "mute"),
        "ban": active(ctx, user_id, "ban"),
    }


def due(ctx: Ctx) -> dict:
    """What the bot must do now: lift expired bans, end expired mutes, renew long mutes."""
    now = int(ctx.now)
    expired = [
        dict(r) for r in ctx.all(
            "SELECT * FROM sanctions WHERE kind IN ('mute', 'ban') AND active=1 AND expires_at IS NOT NULL AND expires_at <= ?;",
            (now,),
        )
    ]
    for r in expired:
        ctx.execute("UPDATE sanctions SET active=0, ended_at=? WHERE sanction_id=?;", (now, r["sanction_id"]))
    renew = [
        dict(r) for r in ctx.all(
            """
            SELECT * FROM sanctions WHERE kind='mute' AND active=1
              AND (expires_at IS NULL OR expires_at > ?)
              AND (applied_until IS NULL OR applied_until < ?)
              AND (expires_at IS NULL OR applied_until IS NULL OR applied_until < expires_at);
            """,
            (now, now + RENEW_BEFORE),
        )
    ]
    return {
        "unban": [r for r in expired if r["kind"] == "ban"],
        "unmuted": [r for r in expired if r["kind"] == "mute"],
        "renew": renew,
    }
