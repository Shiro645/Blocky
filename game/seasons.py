"""Weekly seasons: the score is the emeralds earned during the week (Monday to Sunday).

The score is fed by players.earn_emeralds. Spending doesn't lower it, and
emeralds received from other players don't count. When a week is over, the
top 3 get emeralds and the winner becomes champion until the next season ends.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from game import players, settings
from game.db import Ctx


def standings(ctx: Ctx, season_id: str) -> list[tuple[int, int]]:
    rows = ctx.all(
        "SELECT user_id, score FROM season_scores WHERE season_id=? AND score > 0 ORDER BY score DESC, user_id;",
        (season_id,),
    )
    return [(r["user_id"], r["score"]) for r in rows]


def season_end(ctx: Ctx) -> int:
    """Timestamp of the end of the current season (next Monday 00:00, local time)."""
    now = ctx.local_now
    monday = now.date() - timedelta(days=now.weekday()) + timedelta(days=7)
    return int(datetime.combine(monday, datetime.min.time(), tzinfo=now.tzinfo).timestamp())


def close_finished(ctx: Ctx) -> list[dict]:
    """Close every past season not closed yet: pay the podium and record the results."""
    rewards = [int(r) for r in settings.get()["seasons"]["rewards"]]
    rows = ctx.all(
        """
        SELECT DISTINCT season_id FROM season_scores
        WHERE season_id < ? AND season_id NOT IN (SELECT season_id FROM seasons_closed)
        ORDER BY season_id;
        """,
        (ctx.week_id,),
    )
    closed = []
    for r in rows:
        season_id = r["season_id"]
        podium = []
        for rank, (user_id, score) in enumerate(standings(ctx, season_id)[: len(rewards)], start=1):
            reward = rewards[rank - 1]
            # Not "earned": the reward must not count for the new season.
            players.give_emeralds(ctx, user_id, reward)
            ctx.execute(
                "INSERT INTO season_results(season_id, rank, user_id, score, reward) VALUES(?, ?, ?, ?, ?);",
                (season_id, rank, user_id, score, reward),
            )
            if rank == 1:
                players.bump_stat(ctx, user_id, "seasons_won")
            players.bump_stat(ctx, user_id, "season_podiums")
            podium.append({"rank": rank, "user_id": user_id, "score": score, "reward": reward})
        ctx.execute("INSERT INTO seasons_closed(season_id, closed_at) VALUES(?, ?);", (season_id, int(ctx.now)))
        closed.append({"season_id": season_id, "podium": podium})
    return closed


def current_champion(ctx: Ctx) -> int | None:
    row = ctx.one(
        """
        SELECT user_id FROM season_results WHERE rank=1
        ORDER BY season_id DESC LIMIT 1;
        """
    )
    return row["user_id"] if row else None


def overview(ctx: Ctx, user_id: int, limit: int = 10) -> dict:
    # Imported here: teams depends on this module.
    from game import teams

    rows = standings(ctx, ctx.week_id)
    rank = next((i for i, (uid, _) in enumerate(rows, start=1) if uid == user_id), None)
    return {
        "season_id": ctx.week_id,
        "ends_at": season_end(ctx),
        "top": rows[:limit],
        "tags": teams.tags_of(ctx, [uid for uid, _ in rows[:limit]]),
        "rank": rank,
        "score": rows[rank - 1][1] if rank else 0,
        "champion": current_champion(ctx),
        "rewards": [int(r) for r in settings.get()["seasons"]["rewards"]],
    }
