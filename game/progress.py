"""Achievements (permanent milestones) and weekly challenges.

Both are driven by player stats: every time a stat changes, players.py calls
`on_stat`, which advances the challenges and checks the achievements.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from game import enchants, gear, players, settings
from game.catalog import ARMOR
from game.db import Ctx
from game.notices import AchievementUnlocked, AllChallengesCompleted, ChallengeCompleted


# ---------------- achievements ----------------
@dataclass(frozen=True)
class Achievement:
    code: str
    icon: str
    name: str
    description: str
    reward: int
    check: Callable[[dict], bool]


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


# code, icon, name, what is checked, description. The goal and the reward come from
# settings "achievements"; achievements without a goal there count to 1 (or check an armor tier).
_ACHIEVEMENTS: list[tuple[str, str, str, str, Callable[[int], str]]] = [
    ("first_bedrock", "🟪", "Bedrock Breaker", "stat:bedrock_found", lambda n: "Find your first bedrock"),
    ("bedrock_100", "💎", "Bedrock Collector", "stat:bedrock_found", lambda n: f"Find {n:,} bedrock"),
    ("first_obsidian", "🟣", "Into the Void", "stat:obsidian_found", lambda n: "Find your first obsidian"),
    ("miner_1k", "⛏️", "Miner", "stat:blocks_mined", lambda n: f"Mine {_plural(n, 'block')}"),
    ("miner_10k", "🚧", "Excavator", "stat:blocks_mined", lambda n: f"Mine {_plural(n, 'block')}"),
    ("miner_50k", "🌋", "Quarry Master", "stat:blocks_mined", lambda n: f"Mine {_plural(n, 'block')}"),
    ("first_craft", "🛠️", "First Craft", "stat:items_crafted", lambda n: "Craft your first piece of gear"),
    ("blacksmith", "⚒️", "Blacksmith", "stat:items_crafted", lambda n: f"Craft {_plural(n, 'piece')} of gear"),
    ("iron_set", "🛡️", "Suit Up", "armor:2", lambda n: "Wear a full armor set (iron or better)"),
    ("diamond_set", "💠", "Diamonds!", "armor:3", lambda n: "Wear a full armor set (diamond or better)"),
    ("netherite_set", "🔥", "Netherite Legend", "armor:4", lambda n: "Wear a full netherite armor set"),
    ("level_10", "⭐", "Getting Started", "level", lambda n: f"Reach level {n:,}"),
    ("level_25", "🌟", "Experienced", "level", lambda n: f"Reach level {n:,}"),
    ("level_50", "✨", "Veteran", "level", lambda n: f"Reach level {n:,}"),
    ("level_100", "🌠", "Legend", "level", lambda n: f"Reach level {n:,}"),
    ("first_blood", "🗡️", "First Blood", "stat:duels_won", lambda n: "Win your first duel"),
    ("gladiator", "⚔️", "Gladiator", "stat:duels_won", lambda n: f"Win {_plural(n, 'duel')}"),
    ("streak_7", "📅", "Dedicated", "stat:best_streak", lambda n: f"Reach a {n:,}-day daily streak"),
    ("streak_30", "🔥", "Unstoppable", "stat:best_streak", lambda n: f"Reach a {n:,}-day daily streak"),
    ("merchant", "🤝", "Merchant", "stat:trades_completed", lambda n: f"Complete {_plural(n, 'trade')}"),
    ("auctioneer", "🏷️", "Auctioneer", "stat:auction_sales", lambda n: f"Sell {_plural(n, 'listing')} at the auction house"),
    ("treasure_hunter", "🎁", "Treasure Hunter", "stat:drops_claimed", lambda n: f"Claim {_plural(n, 'drop')}"),
    ("boss_slayer", "🐉", "Boss Slayer", "stat:bosses_defeated", lambda n: "Help defeat a boss"),
    ("champion", "👑", "Champion", "stat:seasons_won", lambda n: "Win a weekly season"),
    ("arena_champion", "🏟️", "Arena Champion", "stat:tournaments_won", lambda n: "Win a weekend tournament"),
    ("team_champion", "🚩", "Squad Goals", "stat:team_seasons_won", lambda n: "Win a team season with your team"),
    ("tycoon", "💰", "Emerald Tycoon", "stat:emeralds_earned", lambda n: f"Earn {_plural(n, 'emerald')}"),
    ("wear_and_tear", "🔨", "Wear and Tear", "stat:gear_broken", lambda n: "Break a piece of gear"),
]
ACHIEVEMENT_CODES = [a[0] for a in _ACHIEVEMENTS]


def _checker(what: str, goal: int) -> Callable[[dict], bool]:
    kind, _, arg = what.partition(":")
    if kind == "stat":
        return lambda f: f["stats"].get(arg, 0) >= goal
    if kind == "level":
        return lambda f: f["level"] >= goal

    def armor_set(f: dict) -> bool:
        eq = f["equipped"]
        return all(s in eq and gear.tier(eq[s]["material"]) >= int(arg) for s in ARMOR)

    return armor_set


def achievements() -> list[Achievement]:
    """Every achievement, with the goal and reward of the current settings."""
    cfg = settings.get()["achievements"]
    out = []
    for code, icon, name, what, text in _ACHIEVEMENTS:
        goal = int(cfg[code].get("goal", 1))
        out.append(Achievement(code, icon, name, text(goal), int(cfg[code]["reward"]), _checker(what, goal)))
    return out


def unlocked_codes(ctx: Ctx, user_id: int) -> dict[str, int]:
    """code -> unlocked_at"""
    rows = ctx.all("SELECT code, unlocked_at FROM achievements WHERE user_id=?;", (user_id,))
    return {r["code"]: r["unlocked_at"] for r in rows}


def check_achievements(ctx: Ctx, user_id: int) -> list[Achievement]:
    done = unlocked_codes(ctx, user_id)
    todo = [a for a in achievements() if a.code not in done]
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


# code, stat it counts, text for a target. Targets and rewards come from settings "challenges.goals".
_CHALLENGES: list[tuple[str, str, Callable[[int], str]]] = [
    ("mine_blocks", "blocks_mined", lambda n: f"Mine {_plural(n, 'block')}"),
    ("find_bedrock", "bedrock_found", lambda n: f"Find {n:,} bedrock"),
    ("sell_blocks", "emeralds_from_sales", lambda n: f"Earn {_plural(n, 'emerald')} by selling blocks"),
    ("craft_gear", "items_crafted", lambda n: f"Craft {_plural(n, 'piece')} of gear"),
    ("win_duels", "duels_won", lambda n: f"Win {_plural(n, 'duel')}"),
    ("claim_drops", "drops_claimed", lambda n: f"Claim {_plural(n, 'drop')}"),
    ("boss_damage", "boss_damage", lambda n: f"Deal {n:,} damage to bosses"),
    ("daily_rewards", "daily_claims", lambda n: f"Claim your daily reward {_plural(n, 'time')}"),
    ("trades", "trades_completed", lambda n: f"Complete {_plural(n, 'trade')}"),
]
CHALLENGE_CODES = [c[0] for c in _CHALLENGES]


def challenge_pool() -> list[Challenge]:
    """Every possible weekly challenge, with the target and reward of the current settings."""
    goals = settings.get()["challenges"]["goals"]
    out = []
    for code, stat, text in _CHALLENGES:
        target = int(goals[code]["target"])
        out.append(Challenge(code, stat, target, int(goals[code]["reward"]), text(target)))
    return out


def available(c: Challenge) -> bool:
    # No boss challenge when bosses only come from /event boss: the week may have none.
    return c.stat != "boss_damage" or float(settings.get()["boss"]["auto_spawn_hours"]) > 0


def challenges_of_week(week_id: str) -> list[Challenge]:
    """The same challenges for everyone, picked from the week id (no storage needed).

    A challenge that can't be done this week (see available) is replaced by
    the next one of the week's shuffled pool, so the other picks don't change.
    """
    every = challenge_pool()
    pool = [c for c in every if available(c)]
    count = min(int(settings.get()["challenges"]["per_week"]), len(pool))
    rng = random.Random(f"blocky-challenges-{week_id}")
    picked = [c for c in rng.sample(every, min(count, len(every))) if available(c)]
    spare = [c for c in rng.sample(every, len(every)) if available(c) and c not in picked]
    return (picked + spare)[:count]


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
            _check_all_done(ctx, user_id, week)


def _check_all_done(ctx: Ctx, user_id: int, week: str) -> None:
    """Every challenge of the week done: a random enchanted book."""
    codes = [c.code for c in challenges_of_week(week)]
    if not codes or not settings.get()["enchants"]["challenges_book"]:
        return
    marks = ",".join("?" * len(codes))
    done = ctx.one(
        f"""
        SELECT COUNT(*) AS n FROM challenge_progress
        WHERE week_id=? AND user_id=? AND completed_at IS NOT NULL AND code IN ({marks});
        """,
        (week, user_id, *codes),
    )["n"]
    if done == len(codes):
        name, level = enchants.give_random_book(ctx, user_id)
        ctx.notices.append(AllChallengesCompleted(user_id, enchants.label(name, level)))


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
    every = achievements()
    return {
        "unlocked": [(a, done[a.code]) for a in every if a.code in done],
        "locked": [a for a in every if a.code not in done],
    }
