"""Achievements (permanent milestones) and weekly challenges.

Both are driven by player stats: every time a stat changes, players.py calls
`on_stat`, which advances the challenges and checks the achievements.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from game import gear, players, settings
from game.catalog import ARMOR
from game.db import Ctx
from game.notices import AchievementUnlocked, ChallengeCompleted


# ---------------- achievements ----------------
@dataclass(frozen=True)
class Achievement:
    code: str
    icon: str
    name: str
    description: str
    reward: int
    check: Callable[[dict], bool]


def _stat(name: str, at_least: int) -> Callable[[dict], bool]:
    return lambda f: f["stats"].get(name, 0) >= at_least


def _armor_set(min_tier: int) -> Callable[[dict], bool]:
    def check(f: dict) -> bool:
        eq = f["equipped"]
        return all(s in eq and gear.tier(eq[s]["material"]) >= min_tier for s in ARMOR)

    return check


def _level(at_least: int) -> Callable[[dict], bool]:
    return lambda f: f["level"] >= at_least


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_bedrock", "🟪", "Bedrock Breaker", "Find your first bedrock", 25, _stat("bedrock_found", 1)),
    Achievement("bedrock_100", "💎", "Bedrock Collector", "Find 100 bedrock", 200, _stat("bedrock_found", 100)),
    Achievement("first_obsidian", "🟣", "Into the Void", "Find your first obsidian", 50, _stat("obsidian_found", 1)),
    Achievement("miner_1k", "⛏️", "Miner", "Mine 1,000 blocks", 100, _stat("blocks_mined", 1_000)),
    Achievement("miner_10k", "🚧", "Excavator", "Mine 10,000 blocks", 500, _stat("blocks_mined", 10_000)),
    Achievement("miner_50k", "🌋", "Quarry Master", "Mine 50,000 blocks", 1500, _stat("blocks_mined", 50_000)),
    Achievement("first_craft", "🛠️", "First Craft", "Craft your first piece of gear", 10, _stat("items_crafted", 1)),
    Achievement("blacksmith", "⚒️", "Blacksmith", "Craft 25 pieces of gear", 200, _stat("items_crafted", 25)),
    Achievement("iron_set", "🛡️", "Suit Up", "Wear a full armor set (iron or better)", 100, _armor_set(2)),
    Achievement("diamond_set", "💠", "Diamonds!", "Wear a full armor set (diamond or better)", 300, _armor_set(3)),
    Achievement("netherite_set", "🔥", "Netherite Legend", "Wear a full netherite armor set", 1000, _armor_set(4)),
    Achievement("level_10", "⭐", "Getting Started", "Reach level 10", 50, _level(10)),
    Achievement("level_25", "🌟", "Experienced", "Reach level 25", 150, _level(25)),
    Achievement("level_50", "✨", "Veteran", "Reach level 50", 400, _level(50)),
    Achievement("level_100", "🌠", "Legend", "Reach level 100", 1000, _level(100)),
    Achievement("first_blood", "🗡️", "First Blood", "Win your first duel", 20, _stat("duels_won", 1)),
    Achievement("gladiator", "⚔️", "Gladiator", "Win 25 duels", 300, _stat("duels_won", 25)),
    Achievement("streak_7", "📅", "Dedicated", "Reach a 7-day daily streak", 100, _stat("best_streak", 7)),
    Achievement("streak_30", "🔥", "Unstoppable", "Reach a 30-day daily streak", 500, _stat("best_streak", 30)),
    Achievement("merchant", "🤝", "Merchant", "Complete 10 trades", 100, _stat("trades_completed", 10)),
    Achievement("auctioneer", "🏷️", "Auctioneer", "Sell 10 listings at the auction house", 100, _stat("auction_sales", 10)),
    Achievement("treasure_hunter", "🎁", "Treasure Hunter", "Claim 10 drops", 150, _stat("drops_claimed", 10)),
    Achievement("boss_slayer", "🐉", "Boss Slayer", "Help defeat a boss", 100, _stat("bosses_defeated", 1)),
    Achievement("champion", "👑", "Champion", "Win a weekly season", 250, _stat("seasons_won", 1)),
    Achievement("tycoon", "💰", "Emerald Tycoon", "Earn 10,000 emeralds", 500, _stat("emeralds_earned", 10_000)),
    Achievement("wear_and_tear", "🔨", "Wear and Tear", "Break a piece of gear", 10, _stat("gear_broken", 1)),
]
ACHIEVEMENTS_BY_CODE = {a.code: a for a in ACHIEVEMENTS}


def unlocked_codes(ctx: Ctx, user_id: int) -> dict[str, int]:
    """code -> unlocked_at"""
    rows = ctx.all("SELECT code, unlocked_at FROM achievements WHERE user_id=?;", (user_id,))
    return {r["code"]: r["unlocked_at"] for r in rows}


def check_achievements(ctx: Ctx, user_id: int) -> list[Achievement]:
    done = unlocked_codes(ctx, user_id)
    todo = [a for a in ACHIEVEMENTS if a.code not in done]
    if not todo:
        return []
    facts = {
        "stats": players.get_stats(ctx, user_id),
        "level": players.get_user(ctx, user_id)["level"],
        "equipped": gear.get_equipped(ctx, user_id),
    }
    new = []
    for a in todo:
        if not a.check(facts):
            continue
        ctx.execute(
            "INSERT INTO achievements(user_id, code, unlocked_at) VALUES(?, ?, ?);",
            (user_id, a.code, int(ctx.now)),
        )
        # Not "earned": rewards for milestones must not snowball into other milestones.
        players.give_emeralds(ctx, user_id, a.reward)
        ctx.notices.append(AchievementUnlocked(user_id, a.code, f"{a.icon} {a.name}", a.reward))
        new.append(a)
    return new


# ---------------- weekly challenges ----------------
@dataclass(frozen=True)
class Challenge:
    code: str
    stat: str
    target: int
    reward: int
    text: str


CHALLENGE_POOL: list[Challenge] = [
    Challenge("mine_blocks", "blocks_mined", 500, 150, "Mine 500 blocks"),
    Challenge("find_bedrock", "bedrock_found", 15, 150, "Find 15 bedrock"),
    Challenge("sell_blocks", "emeralds_from_sales", 1000, 150, "Earn 1,000 emeralds by selling blocks"),
    Challenge("craft_gear", "items_crafted", 3, 100, "Craft 3 pieces of gear"),
    Challenge("win_duels", "duels_won", 3, 150, "Win 3 duels"),
    Challenge("claim_drops", "drops_claimed", 2, 100, "Claim 2 drops"),
    Challenge("boss_damage", "boss_damage", 100, 150, "Deal 100 damage to bosses"),
    Challenge("daily_rewards", "daily_claims", 5, 150, "Claim your daily reward 5 times"),
    Challenge("trades", "trades_completed", 2, 75, "Complete 2 trades"),
]
CHALLENGES_BY_CODE = {c.code: c for c in CHALLENGE_POOL}


def challenges_of_week(week_id: str) -> list[Challenge]:
    """The same challenges for everyone, picked from the week id (no storage needed)."""
    count = min(int(settings.get()["challenges"]["per_week"]), len(CHALLENGE_POOL))
    return random.Random(f"blocky-challenges-{week_id}").sample(CHALLENGE_POOL, count)


def advance_challenges(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    if amount <= 0:
        return
    week = ctx.week_id
    for c in challenges_of_week(week):
        if c.stat != stat:
            continue
        ctx.execute(
            """
            INSERT INTO challenge_progress(week_id, user_id, code, progress) VALUES(?, ?, ?, ?)
            ON CONFLICT(week_id, user_id, code) DO UPDATE SET progress = progress + excluded.progress;
            """,
            (week, user_id, c.code, amount),
        )
        row = ctx.one(
            "SELECT progress, completed_at FROM challenge_progress WHERE week_id=? AND user_id=? AND code=?;",
            (week, user_id, c.code),
        )
        if row["completed_at"] is None and row["progress"] >= c.target:
            ctx.execute(
                "UPDATE challenge_progress SET completed_at=? WHERE week_id=? AND user_id=? AND code=?;",
                (int(ctx.now), week, user_id, c.code),
            )
            players.earn_emeralds(ctx, user_id, c.reward)
            players.bump_stat(ctx, user_id, "challenges_completed")
            ctx.notices.append(ChallengeCompleted(user_id, c.text, c.reward))


def weekly_challenges(ctx: Ctx, user_id: int) -> list[dict]:
    week = ctx.week_id
    out = []
    for c in challenges_of_week(week):
        row = ctx.one(
            "SELECT progress, completed_at FROM challenge_progress WHERE week_id=? AND user_id=? AND code=?;",
            (week, user_id, c.code),
        )
        out.append({
            "text": c.text,
            "target": c.target,
            "reward": c.reward,
            "progress": min(row["progress"], c.target) if row else 0,
            "completed": bool(row and row["completed_at"]),
        })
    return out


# ---------------- hook ----------------
def on_stat(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    advance_challenges(ctx, user_id, stat, amount)
    check_achievements(ctx, user_id)


def achievements_overview(ctx: Ctx, user_id: int) -> dict:
    done = unlocked_codes(ctx, user_id)
    return {
        "unlocked": [(a, done[a.code]) for a in ACHIEVEMENTS if a.code in done],
        "locked": [a for a in ACHIEVEMENTS if a.code not in done],
    }
