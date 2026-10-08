"""Daily reward with a streak of consecutive days."""
from __future__ import annotations

from datetime import datetime, timedelta

from game import players, settings
from game.db import Ctx
from game.errors import GameError


def reward_for_streak(streak: int) -> int:
    d = settings.get()["daily"]
    days = min(max(1, streak), int(d["streak_cap_days"]))
    return int(d["base_reward"]) + int(d["streak_bonus_per_day"]) * (days - 1)


def seconds_until_tomorrow(ctx: Ctx) -> int:
    now = ctx.local_now
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
    return max(0, int((tomorrow - now).total_seconds()))


def claim(ctx: Ctx, user_id: int) -> dict:
    d = settings.get()["daily"]
    user = players.get_user(ctx, user_id)
    today = ctx.today
    if user["last_daily"] == today.isoformat():
        left = seconds_until_tomorrow(ctx)
        raise GameError(
            f"You already claimed today's reward. Come back in **{left // 3600}h {left % 3600 // 60}m**."
        )

    yesterday = (today - timedelta(days=1)).isoformat()
    streak = user["daily_streak"] + 1 if user["last_daily"] == yesterday else 1
    emeralds = reward_for_streak(streak)
    bonus_item = None
    if streak % 7 == 0 and d.get("weekly_bonus_item"):
        bonus_item = d["weekly_bonus_item"]
        players.add_item(ctx, user_id, "ingot", bonus_item, 1)

    ctx.execute(
        "UPDATE users SET daily_streak=?, last_daily=? WHERE user_id=?;",
        (streak, today.isoformat(), user_id),
    )
    players.earn_emeralds(ctx, user_id, emeralds)
    players.add_xp(ctx, user_id, int(d["xp"]))
    players.bump_stat(ctx, user_id, "daily_claims")
    players.set_stat_max(ctx, user_id, "best_streak", streak)
    return {
        "streak": streak,
        "emeralds": emeralds,
        "xp": int(d["xp"]),
        "bonus_item": bonus_item,
        "next_reward": reward_for_streak(streak + 1),
        "lost_streak": user["daily_streak"] if streak == 1 and user["daily_streak"] > 1 else 0,
    }
