"""Robberies: /rob takes emeralds from another player, unless they stop it in time.

- Risky: the victim is pinged, the loot is big. Discreet: no ping, small loot.
  The loot is rolled at the start (settings "rob"), and is never more than the
  victim has when the time is up.
- The victim has `minutes_to_stop` minutes to stop it. Then the thief pays them
  a fine (a % of the loot he aimed at, never more than he has).
- A thief robs once every `cooldown_hours`; a robbed player is protected for
  `victim_protection_hours`; players below `min_victim_level` can't be robbed.
- Stolen emeralds and fines move between players: they don't count for the
  seasons (like trades).
"""
from __future__ import annotations

import math

from game import players, settings
from game.db import Ctx
from game.errors import GameError

MODES = ("risky", "discreet")
HOUR = 3600


def _cfg() -> dict:
    return settings.get()["rob"]


def _wait(seconds: float) -> str:
    seconds = max(60, int(seconds))
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes} min"


def get(ctx: Ctx, rob_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM robberies WHERE rob_id=?;", (rob_id,))
    return dict(row) if row else None


def start(ctx: Ctx, thief_id: int, victim_id: int, mode: str) -> dict:
    c = _cfg()
    if mode not in MODES:
        raise GameError("Pick a risky or a discreet robbery.")
    if thief_id == victim_id:
        raise GameError("You can't rob yourself.")
    victim = players.get_user(ctx, victim_id)
    if victim["level"] < int(c["min_victim_level"]):
        raise GameError(f"<@{victim_id}> is protected: players below level **{c['min_victim_level']}** can't be robbed.")
    now = int(ctx.now)
    last = ctx.one("SELECT MAX(started_at) AS t FROM robberies WHERE thief_id=?;", (thief_id,))["t"]
    ready = (last or 0) + float(c["cooldown_hours"]) * HOUR
    if last is not None and now < ready:
        raise GameError(f"Lie low for a while: you can rob again in **{_wait(ready - now)}**.")
    if ctx.one("SELECT 1 FROM robberies WHERE victim_id=? AND status='active';", (victim_id,)):
        raise GameError(f"Someone is already robbing <@{victim_id}>.")
    robbed = ctx.one("SELECT MAX(ends_at) AS t FROM robberies WHERE victim_id=? AND status='done';", (victim_id,))["t"]
    safe_until = (robbed or 0) + float(c["victim_protection_hours"]) * HOUR
    if robbed is not None and now < safe_until:
        raise GameError(f"<@{victim_id}> was robbed recently and is protected for **{_wait(safe_until - now)}**.")
    if players.get_emeralds(ctx, victim_id) <= 0:
        raise GameError(f"<@{victim_id}> has no emeralds to steal.")
    amount = ctx.rng.randint(int(c[f"{mode}_min"]), int(c[f"{mode}_max"]))
    ends_at = now + int(float(c["minutes_to_stop"]) * 60)
    cur = ctx.execute(
        "INSERT INTO robberies(thief_id, victim_id, mode, amount, started_at, ends_at) VALUES(?, ?, ?, ?, ?, ?);",
        (thief_id, victim_id, mode, amount, now, ends_at),
    )
    players.bump_stat(ctx, thief_id, "robs_started")
    return get(ctx, cur.lastrowid)


def set_message(ctx: Ctx, rob_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE robberies SET channel_id=?, message_id=? WHERE rob_id=?;", (channel_id, message_id, rob_id))


def _transfer(ctx: Ctx, from_id: int, to_id: int, amount: int) -> int:
    """Move up to `amount` emeralds (never more than `from_id` has). Not counted for the seasons."""
    amount = min(amount, players.get_emeralds(ctx, from_id))
    if amount > 0:
        players.spend_emeralds(ctx, from_id, amount)
        players.give_emeralds(ctx, to_id, amount)
    return max(0, amount)


def fine_for(amount: int) -> int:
    return math.ceil(amount * float(_cfg()["fine_percent"]) / 100)


def stop(ctx: Ctx, rob_id: int, user_id: int) -> dict:
    """The victim stops the thief: the thief pays them a fine."""
    rob = get(ctx, rob_id)
    if rob is None or rob["status"] != "active":
        raise GameError("This robbery is already over.")
    if user_id != rob["victim_id"]:
        raise GameError(f"Only <@{rob['victim_id']}> can stop this robbery.")
    if ctx.now >= rob["ends_at"]:
        raise GameError("Too late: the thief got away.")
    fine = _transfer(ctx, rob["thief_id"], rob["victim_id"], fine_for(rob["amount"]))
    ctx.execute("UPDATE robberies SET status='stopped', fine=? WHERE rob_id=?;", (fine, rob_id))
    players.bump_stat(ctx, rob["victim_id"], "robs_stopped")
    players.bump_stat(ctx, rob["thief_id"], "robs_failed")
    return {**rob, "status": "stopped", "fine": fine}


def finish_due(ctx: Ctx) -> list[dict]:
    """Robberies nobody stopped in time: the thief takes the loot."""
    done = []
    for row in ctx.all("SELECT * FROM robberies WHERE status='active' AND ends_at <= ?;", (int(ctx.now),)):
        rob = dict(row)
        stolen = _transfer(ctx, rob["victim_id"], rob["thief_id"], rob["amount"])
        ctx.execute("UPDATE robberies SET status='done', stolen=? WHERE rob_id=?;", (stolen, rob["rob_id"]))
        players.bump_stat(ctx, rob["thief_id"], "robs_succeeded")
        players.bump_stat(ctx, rob["thief_id"], "emeralds_stolen", stolen)
        done.append({**rob, "status": "done", "stolen": stolen})
    return done
