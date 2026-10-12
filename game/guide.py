"""The guide: a private channel for every new player, with a checklist of first steps.

The steps are read from what the player did (stats, species), so a step done before
the guide was opened is already checked. When every step is done the player gets
`reward` emeralds, once ever (a guide opened again by the staff never pays twice).
The channel is deleted `delete_after_days` after the checklist is done, after
`expire_days` if it never is (0 = kept), or when the player leaves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from game import players, settings
from game.db import Ctx
from game.notices import GuideProgress

DAY = 86_400


@dataclass(frozen=True)
class Step:
    key: str
    text: str
    check: Callable[[dict], bool]


def _stat(*names: str) -> Callable[[dict], bool]:
    return lambda facts: any(facts["stats"].get(name, 0) > 0 for name in names)


STEPS: tuple[Step, ...] = (
    Step("mine", "Chat in the server to mine your first blocks", _stat("blocks_mined")),
    Step("daily", "Claim your daily reward: `/daily`", _stat("daily_claims")),
    Step("sell", "Sell your blocks for emeralds: `/sell`", _stat("emeralds_from_sales")),
    Step("species", "Pick a species: `/species list`, then `/species choose`", lambda facts: bool(facts["species"])),
    Step("profile", "Look at your profile card: `/profile`", _stat("profiles_viewed")),
    Step("dummy", "Hit the training dummy (`/dummy hit`) or play a training duel (`/dummy duel`)",
         lambda facts: facts["dummy"] or _stat("dummy_series", "training_duels")(facts)),
)
STEPS_BY_KEY = {s.key: s for s in STEPS}


def _cfg() -> dict:
    return settings.get()["guide"]


def _facts(ctx: Ctx, user_id: int) -> dict:
    user = players.get_user(ctx, user_id)
    return {
        "stats": players.get_stats(ctx, user_id),
        "species": user["species"],
        "dummy": bool(ctx.one("SELECT 1 FROM dummy_scores WHERE user_id=? AND series > 0;", (user_id,))),
    }


def steps_of(ctx: Ctx, user_id: int) -> list[tuple[Step, bool]]:
    facts = _facts(ctx, user_id)
    return [(step, step.check(facts)) for step in STEPS]


def get(ctx: Ctx, user_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM guides WHERE user_id=?;", (user_id,))
    return dict(row) if row else None


def overview(ctx: Ctx, user_id: int) -> dict:
    """What the checklist shows: the steps, done or not, and the reward."""
    players.ensure_user(ctx, user_id)
    row = get(ctx, user_id)
    return {
        "steps": steps_of(ctx, user_id),
        "reward": int(_cfg()["reward"]),
        "completed": bool(row and row["completed_at"]),
        "rewarded": bool(row and row["rewarded_at"]),
        "channel_id": row["channel_id"] if row else None,
        "delete_at": row["delete_at"] if row else None,
    }


def _deadline(ctx: Ctx, completed: bool) -> int | None:
    days = float(_cfg()["delete_after_days"] if completed else _cfg()["expire_days"])
    return int(ctx.now + days * DAY) if days > 0 else None


def opened(ctx: Ctx, user_id: int, channel_id: int | None, message_id: int | None) -> dict:
    """A guide channel was just made for this player (a new one replaces the old one).

    Without a channel (no guide category set), the checklist is followed all the same (/guide).
    The checklist starts from what the player already did; if that's everything, it's done now."""
    players.ensure_user(ctx, user_id)
    row = get(ctx, user_id)
    done = {step.key for step, ok in steps_of(ctx, user_id) if ok}
    completed = bool(row and row["completed_at"])
    ctx.execute(
        """
        INSERT INTO guides(user_id, channel_id, message_id, created_at, done, delete_at) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id,
            created_at=excluded.created_at, done=excluded.done, delete_at=excluded.delete_at;
        """,
        (user_id, channel_id, message_id, int(ctx.now), ",".join(sorted(done)),
         _deadline(ctx, completed) if channel_id else None),
    )
    if not completed and len(done) == len(STEPS):
        _complete(ctx, user_id, ())
    return overview(ctx, user_id)


def check(ctx: Ctx, user_id: int) -> None:
    """After something a step may count: check the newly done steps (and the end of the checklist)."""
    row = ctx.one("SELECT done, completed_at FROM guides WHERE user_id=?;", (user_id,))
    if row is None or row["completed_at"]:
        return
    done = {step.key for step, ok in steps_of(ctx, user_id) if ok}
    new = done - set(filter(None, row["done"].split(",")))
    if not new:
        return
    ctx.execute("UPDATE guides SET done=? WHERE user_id=?;", (",".join(sorted(done)), user_id))
    new_steps = tuple(s.key for s in STEPS if s.key in new)
    if len(done) == len(STEPS):
        _complete(ctx, user_id, new_steps)
    else:
        row = get(ctx, user_id)
        ctx.notices.append(GuideProgress(user_id, row["channel_id"], row["message_id"], new_steps, len(done),
                                         len(STEPS), False, 0))


def _complete(ctx: Ctx, user_id: int, new_steps: tuple[str, ...]) -> None:
    row = get(ctx, user_id)
    reward = 0 if row["rewarded_at"] else int(_cfg()["reward"])
    now = int(ctx.now)
    # Marked done before paying: paying must not check the guide again.
    ctx.execute(
        "UPDATE guides SET completed_at=?, rewarded_at=COALESCE(rewarded_at, ?), delete_at=? WHERE user_id=?;",
        (now, now, _deadline(ctx, True) if row["channel_id"] else None, user_id),
    )
    if reward:
        # Like achievements: a reward for milestones, not counted for the seasons.
        players.give_emeralds(ctx, user_id, reward)
    ctx.notices.append(GuideProgress(user_id, row["channel_id"], row["message_id"], new_steps, len(STEPS),
                                     len(STEPS), True, reward))


def closed(ctx: Ctx, user_id: int) -> int | None:
    """The player's guide channel is gone (or going): forget it. Returns its id."""
    row = get(ctx, user_id)
    if row is None or not row["channel_id"]:
        return None
    ctx.execute("UPDATE guides SET channel_id=NULL, message_id=NULL, delete_at=NULL WHERE user_id=?;", (user_id,))
    return row["channel_id"]


def channel_deleted(ctx: Ctx, channel_id: int) -> int | None:
    """A guide channel was deleted from Discord. Returns its player."""
    row = ctx.one("SELECT user_id FROM guides WHERE channel_id=?;", (channel_id,))
    if row is None:
        return None
    closed(ctx, row["user_id"])
    return row["user_id"]


def due(ctx: Ctx) -> list[dict]:
    """Guide channels to delete now."""
    rows = ctx.all("SELECT user_id, channel_id FROM guides WHERE channel_id IS NOT NULL AND delete_at IS NOT NULL "
                   "AND delete_at <= ?;", (int(ctx.now),))
    return [dict(r) for r in rows]


def channels(ctx: Ctx) -> dict[int, int]:
    """channel id -> player, for every open guide channel."""
    return {r["channel_id"]: r["user_id"] for r in ctx.all("SELECT user_id, channel_id FROM guides "
                                                            "WHERE channel_id IS NOT NULL;")}
