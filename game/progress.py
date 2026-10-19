"""Achievements (permanent milestones) and daily and weekly challenges.

Both are driven by player stats: every time a stat changes, players.py calls
`on_stat`, which advances the challenges and checks the achievements.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from game import biomes, enchants, gear, guide, players, settings
from game.catalog import ARMOR
from game.db import Ctx, week_id_of
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
    ("boss_slayer", "⚔️", "Boss Slayer", "stat:bosses_defeated", lambda n: "Survive a victory against a gate boss"),
    ("champion", "👑", "Champion", "stat:seasons_won", lambda n: "Win a weekly season"),
    ("arena_champion", "🏟️", "Arena Champion", "stat:tournaments_won", lambda n: "Win a weekend tournament"),
    ("team_champion", "🚩", "Squad Goals", "stat:team_seasons_won", lambda n: "Win a team season with your team"),
    ("tycoon", "💰", "Emerald Tycoon", "stat:emeralds_earned", lambda n: f"Earn {_plural(n, 'emerald')}"),
    ("wear_and_tear", "🔨", "Wear and Tear", "stat:gear_broken", lambda n: "Break a piece of gear"),
    ("lucky_100", "🍀", "Feeling Lucky", "stat:lucky_blocks", lambda n: f"Break {_plural(n, 'Lucky Block')}"),
    ("wheel_100", "🎡", "Spin Doctor", "stat:roulette_spins", lambda n: f"Spin the wheel {n:,} times"),
    ("bullseye", "🎯", "Bullseye", "stat:roulette_numbers_won", lambda n: "Win a bet on a number at the wheel"),
    ("blockdle_10", "🧩", "Block Detective", "stat:blockdle_wins", lambda n: f"Find the Blockdle block of the day {n:,} times"),
    ("quiz_10", "🧠", "Know-It-All", "stat:quiz_wins", lambda n: f"Win {_plural(n, 'quiz question')}"),
    ("thief_10", "🦹", "Master Thief", "stat:robs_succeeded", lambda n: f"Rob {_plural(n, 'player')} successfully"),
    ("watch_5", "🚨", "Neighborhood Watch", "stat:robs_stopped", lambda n: "Stop a thief" if n == 1 else f"Stop {n:,} thieves"),
    ("dungeon_hard", "🏰", "Into the Depths", "stat:pve_clears_hard", lambda n: "Clear the dungeon in Hard"),
    ("dungeon_hardcore", "⚔️", "Hardcore Hero", "stat:pve_clears_hardcore", lambda n: "Clear the dungeon in Hardcore"),
    ("dungeon_nightmare", "💀", "Nightmare Slayer", "stat:pve_clears_nightmare", lambda n: "Clear the dungeon in Nightmare"),
    ("challenger_10", "🎯", "Challenger", "stat:challenges_completed", lambda n: f"Complete {_plural(n, 'challenge')}"),
    ("challenger_50", "🏅", "Challenge Master", "stat:challenges_completed", lambda n: f"Complete {_plural(n, 'challenge')}"),
    ("high_roller", "🎰", "High Roller", "stat:frenzy_games", lambda n: "Play the Lucky Block or the wheel during a Gambling Frenzy"),
    ("enchanter_10", "📚", "Enchanter", "stat:items_enchanted", lambda n: f"Apply {_plural(n, 'enchanted book')}"),
    ("handyman_10", "🔧", "Handyman", "stat:items_repaired", lambda n: f"Repair gear {n:,} times"),
    ("regular_20", "🧑‍🌾", "Regular Customer", "stat:villager_trades", lambda n: f"Make {_plural(n, 'deal')} with the wandering villager"),
    ("moneylender", "🏦", "Moneylender", "stat:emeralds_lent", lambda n: f"Lend {_plural(n, 'emerald')}"),
    ("wither_slayer", "🖤", "Wither Slayer", "stat:wither_defeated", lambda n: "Survive a victory against the Wither"),
    ("dragon_slayer", "🐉", "Dragon Slayer", "stat:ender_dragon_defeated",
     lambda n: "Survive a victory against the Ender Dragon"),
    ("warden_slayer", "👁️", "Warden Slayer", "stat:warden_defeated", lambda n: "Survive a victory against the Warden"),
    ("warlord", "🏴", "Warlord", "stat:wars_won", lambda n: "Win a weekly gang war with your team"),
    ("raider_5", "🪓", "Raider", "stat:raids_won", lambda n: f"Win {_plural(n, 'raid')} on another team's chest"),
    ("beacon_builder", "🔆", "Beacon Builder", "stat:beacon_value",
     lambda n: f"Give {_plural(n, 'emerald')}' worth of ingots to the Beacon"),
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
        # Paid once ever: unlocked again after a /reset of the progress, it pays nothing.
        first = ctx.execute("INSERT OR IGNORE INTO rewards_paid(user_id, kind, key) VALUES(?, 'achievement', ?);",
                            (user_id, a.code)).rowcount
        reward = a.reward if first else 0
        # Not "earned": rewards for milestones must not snowball into other milestones.
        players.give_emeralds(ctx, user_id, reward)
        ctx.notices.append(AchievementUnlocked(user_id, a.code, f"{a.icon} {a.name}", reward))
        new.append(a)
    return new


# ---------------- daily and weekly challenges ----------------
@dataclass(frozen=True)
class Challenge:
    code: str
    stat: str
    target: int
    reward: int
    text: str


def _times(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=f"{n:,}")


# code, stat it counts, text for a target. Targets and rewards come from settings "challenges.goals" (weekly)
# and "challenges.daily_goals" (daily): a challenge without a goal there isn't in that pool.
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
    ("lucky_blocks", "lucky_blocks", lambda n: f"Break {_plural(n, 'Lucky Block')}"),
    ("wheel_spins", "roulette_spins", lambda n: _times(n, "Spin the wheel", "Spin the wheel {n} times")),
    ("blockdle", "blockdle_wins", lambda n: _times(n, "Find the Blockdle block of the day",
                                                   "Find the Blockdle block of the day {n} times")),
    ("quiz", "quiz_wins", lambda n: _times(n, "Win a quiz question", "Win {n} quiz questions")),
    ("pve_waves", "pve_waves", lambda n: f"Clear {_plural(n, 'dungeon wave')}"),
    ("dummy", "dummy_series", lambda n: _times(n, "Hit the training dummy", "Hit the training dummy {n} times")),
    ("robs", "robs_succeeded", lambda n: _times(n, "Rob a player successfully", "Rob {n} players successfully")),
]
CHALLENGE_CODES = [c[0] for c in _CHALLENGES]
# The weekly pool before the daily challenges: the first weekly set picked with the new rules is this one, so
# the week running when the bot is updated keeps its challenges.
LEGACY_WEEK_CODES = ("mine_blocks", "find_bedrock", "sell_blocks", "craft_gear", "win_duels", "claim_drops",
                     "boss_damage", "daily_rewards", "trades")
KINDS = ("day", "week")


def _goals(kind: str) -> dict:
    c = settings.get()["challenges"]
    return c["daily_goals"] if kind == "day" else c["goals"]


def per_period(kind: str) -> int:
    return int(settings.get()["challenges"]["per_day" if kind == "day" else "per_week"])


def challenge_pool(kind: str = "week") -> list[Challenge]:
    """Every possible daily or weekly challenge, with the target and reward of the current settings."""
    goals = _goals(kind)
    out = []
    for code, stat, text in _CHALLENGES:
        if code in goals:
            target = int(goals[code]["target"])
            out.append(Challenge(code, stat, target, int(goals[code]["reward"]), text(target)))
    return out


def available(c: Challenge) -> bool:
    """A challenge that can be done now (the game it needs is on)."""
    s = settings.get()
    if c.stat == "boss_damage":  # gate bosses need a group and a dimension: not a challenge for everyone
        return False
    if c.stat == "quiz_wins":
        return float(s["games"]["quiz_every_minutes"]) > 0
    if c.stat == "roulette_spins":
        return bool(s["games"]["roulette_enabled"])
    return True


def pick(kind: str, period: str, avoid: frozenset[str] | set[str] = frozenset(),
         pool: list[Challenge] | None = None) -> list[Challenge]:
    """The challenges of a day or a week, picked from its id (the same for everyone), leaving out `avoid` (the
    previous ones) while there are enough others."""
    every = challenge_pool(kind) if pool is None else pool
    ok = [c for c in every if available(c)]
    count = min(per_period(kind), len(ok))
    rng = random.Random(f"blocky-challenges-{period}" if kind == "week" else f"blocky-daily-challenges-{period}")
    picked = [c for c in rng.sample(every, min(count, len(every))) if available(c) and c.code not in avoid]
    spare = [c for c in rng.sample(every, len(every)) if available(c) and c not in picked and c.code not in avoid]
    again = [c for c in ok if c.code in avoid]  # not enough new ones
    return (picked + spare + again)[:count]


def _periods(ctx: Ctx, kind: str) -> tuple[str, str]:
    """The id of the current day or week, and of the one before."""
    if kind == "day":
        return ctx.today.isoformat(), (ctx.today - timedelta(days=1)).isoformat()
    return ctx.week_id, week_id_of(ctx.local_now - timedelta(days=7))


def progress_key(kind: str, period: str) -> str:
    """challenge_progress.week_id of a period (weeks keep their plain id)."""
    return period if kind == "week" else f"day:{period}"


def current_challenges(ctx: Ctx, kind: str) -> list[Challenge]:
    """Today's or this week's challenges. Picked the first time they're needed and kept (challenge_sets), never
    the same as the previous day's or week's when there are enough others."""
    period, previous = _periods(ctx, kind)
    pool = {c.code: c for c in challenge_pool(kind)}
    row = ctx.one("SELECT codes FROM challenge_sets WHERE period=?;", (f"{kind}:{period}",))
    if row is not None:
        return [pool[code] for code in row["codes"].split(",") if code in pool]
    before = ctx.one("SELECT codes FROM challenge_sets WHERE period=?;", (f"{kind}:{previous}",))
    avoid = set(before["codes"].split(",")) if before else set()
    first_week = kind == "week" and ctx.one("SELECT 1 FROM challenge_sets WHERE period LIKE 'week:%';") is None
    legacy = [c for c in pool.values() if c.code in LEGACY_WEEK_CODES] if first_week else None
    picked = pick(kind, period, avoid, legacy)
    ctx.execute("INSERT OR IGNORE INTO challenge_sets(period, codes) VALUES(?, ?);",
                (f"{kind}:{period}", ",".join(c.code for c in picked)))
    return picked


def advance_challenges(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    if amount <= 0:
        return
    for kind in KINDS:
        key = progress_key(kind, _periods(ctx, kind)[0])
        for c in current_challenges(ctx, kind):
            if c.stat != stat:
                continue
            ctx.execute(
                """
                INSERT INTO challenge_progress(week_id, user_id, code, progress) VALUES(?, ?, ?, ?)
                ON CONFLICT(week_id, user_id, code) DO UPDATE SET progress = progress + excluded.progress;
                """,
                (key, user_id, c.code, amount),
            )
            row = ctx.one(
                "SELECT progress, completed_at FROM challenge_progress WHERE week_id=? AND user_id=? AND code=?;",
                (key, user_id, c.code),
            )
            if row["completed_at"] is None and row["progress"] >= c.target:
                ctx.execute(
                    "UPDATE challenge_progress SET completed_at=? WHERE week_id=? AND user_id=? AND code=?;",
                    (int(ctx.now), key, user_id, c.code),
                )
                players.earn_emeralds(ctx, user_id, c.reward)
                players.bump_stat(ctx, user_id, "challenges_completed")
                ctx.notices.append(ChallengeCompleted(user_id, c.text, c.reward, daily=kind == "day"))
                if kind == "week":
                    _check_all_done(ctx, user_id, key)
    _advance_biome(ctx, user_id, stat, amount)


# ---------------- the biome's challenge ----------------
def biome_challenge(ctx: Ctx) -> Challenge | None:
    """This week's biome challenge (paid apart: it doesn't count for the weekly book)."""
    biome = biomes.current(ctx)
    if biome is None:
        return None
    c = settings.get()["biomes"]
    stat, text = next((s, t) for code, s, t in _CHALLENGES if code == biome.challenge)
    target = int(c["challenges"][biome.key])
    return Challenge(f"biome_{biome.key}", stat, target, int(c["challenge_reward"]), text(target))


def _biome_row(ctx: Ctx, user_id: int, c: Challenge):
    return ctx.one("SELECT progress, completed_at FROM challenge_progress WHERE week_id=? AND user_id=? AND code=?;",
                   (f"biome:{ctx.week_id}", user_id, c.code))


def _advance_biome(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    c = biome_challenge(ctx)
    if c is None or c.stat != stat or c.target <= 0:
        return
    key = f"biome:{ctx.week_id}"
    ctx.execute(
        """
        INSERT INTO challenge_progress(week_id, user_id, code, progress) VALUES(?, ?, ?, ?)
        ON CONFLICT(week_id, user_id, code) DO UPDATE SET progress = progress + excluded.progress;
        """,
        (key, user_id, c.code, amount),
    )
    row = _biome_row(ctx, user_id, c)
    if row["completed_at"] is None and row["progress"] >= c.target:
        ctx.execute("UPDATE challenge_progress SET completed_at=? WHERE week_id=? AND user_id=? AND code=?;",
                    (int(ctx.now), key, user_id, c.code))
        players.earn_emeralds(ctx, user_id, c.reward)
        players.bump_stat(ctx, user_id, "biome_challenges")
        biome = biomes.current(ctx)
        ctx.notices.append(ChallengeCompleted(user_id, f"{biome.label}: {c.text}", c.reward))


def biome_progress(ctx: Ctx, user_id: int) -> dict | None:
    c = biome_challenge(ctx)
    if c is None:
        return None
    row = _biome_row(ctx, user_id, c)
    return {"text": c.text, "target": c.target, "reward": c.reward,
            "progress": min(row["progress"], c.target) if row else 0, "completed": bool(row and row["completed_at"])}


def _check_all_done(ctx: Ctx, user_id: int, week: str) -> None:
    """Every challenge of the week done: a random enchanted book."""
    codes = [c.code for c in current_challenges(ctx, "week")]
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


def challenges(ctx: Ctx, user_id: int, kind: str = "week") -> list[dict]:
    """Today's or this week's challenges with the player's progress."""
    key = progress_key(kind, _periods(ctx, kind)[0])
    out = []
    for c in current_challenges(ctx, kind):
        row = ctx.one(
            "SELECT progress, completed_at FROM challenge_progress WHERE week_id=? AND user_id=? AND code=?;",
            (key, user_id, c.code),
        )
        out.append({
            "code": c.code,
            "text": c.text,
            "target": c.target,
            "reward": c.reward,
            "progress": min(row["progress"], c.target) if row else 0,
            "completed": bool(row and row["completed_at"]),
        })
    return out


def weekly_challenges(ctx: Ctx, user_id: int) -> list[dict]:
    return challenges(ctx, user_id, "week")


def daily_challenges(ctx: Ctx, user_id: int) -> list[dict]:
    return challenges(ctx, user_id, "day")


# ---------------- hook ----------------
def on_stat(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    advance_challenges(ctx, user_id, stat, amount)
    check_achievements(ctx, user_id)
    guide.check(ctx, user_id)


def achievements_overview(ctx: Ctx, user_id: int) -> dict:
    done = unlocked_codes(ctx, user_id)
    every = achievements()
    return {
        "unlocked": [(a, done[a.code]) for a in every if a.code in done],
        "locked": [a for a in every if a.code not in done],
    }
