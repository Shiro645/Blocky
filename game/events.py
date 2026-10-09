"""Server events: random drops and bosses."""
from __future__ import annotations

import random

from game import enchants, gear, players, settings
from game.db import Ctx
from game.errors import GameError

HOUR = 3600


# ---------------- drops ----------------
def roll_drop(rng: random.Random) -> dict:
    table = settings.get()["drops"]["table"]
    return rng.choices(table, weights=[int(e["weight"]) for e in table])[0]


def describe_reward(reward: dict) -> str:
    if "emeralds" in reward:
        return f"{reward['emeralds']} emeralds"
    if "ingot" in reward:
        return f"{reward['amount']} {reward['ingot']} ingot(s)"
    if "lapis" in reward:
        return f"{reward['lapis']} lapis lazuli"
    if "book" in reward:
        return "an enchanted book"
    return f"{reward['amount']} {reward['block']}"


def claim_drop(ctx: Ctx, user_id: int, drop: dict) -> str:
    """Give the drop's reward. Returns what was won."""
    reward = drop["reward"]
    text = describe_reward(reward)
    if "emeralds" in reward:
        players.earn_emeralds(ctx, user_id, int(reward["emeralds"]))
    elif "ingot" in reward:
        players.add_item(ctx, user_id, "ingot", reward["ingot"], int(reward["amount"]))
    elif "lapis" in reward:
        enchants.give_lapis(ctx, user_id, int(reward["lapis"]))
    elif "book" in reward:
        name, level = enchants.give_random_book(ctx, user_id)
        text = f"a {enchants.label(name, level)} book"
    else:
        players.add_blocks(ctx, user_id, reward["block"], int(reward["amount"]))
    players.bump_stat(ctx, user_id, "drops_claimed")
    return text


# ---------------- bosses ----------------
def active_boss(ctx: Ctx) -> dict | None:
    row = ctx.one("SELECT * FROM bosses WHERE status='active' ORDER BY boss_id DESC LIMIT 1;")
    return dict(row) if row else None


def get_boss(ctx: Ctx, boss_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM bosses WHERE boss_id=?;", (boss_id,))
    return dict(row) if row else None


def last_boss_end(ctx: Ctx) -> int:
    row = ctx.one("SELECT MAX(ends_at) AS t FROM bosses;")
    return int(row["t"] or 0)


def spawn_boss(ctx: Ctx, name: str | None = None, hp: int | None = None) -> dict:
    b = settings.get()["boss"]
    if active_boss(ctx):
        raise GameError("A boss is already active.")
    name = name or ctx.rng.choice(b["names"])
    hp = int(hp or b["hp"])
    cur = ctx.execute(
        "INSERT INTO bosses(name, max_hp, hp, started_at, ends_at) VALUES(?, ?, ?, ?, ?);",
        (name, hp, hp, int(ctx.now), int(ctx.now + float(b["duration_hours"]) * HOUR)),
    )
    return get_boss(ctx, int(cur.lastrowid))


def set_boss_message(ctx: Ctx, boss_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE bosses SET channel_id=?, message_id=? WHERE boss_id=?;", (channel_id, message_id, boss_id))


def boss_ranking(ctx: Ctx, boss_id: int) -> list[dict]:
    rows = ctx.all(
        "SELECT user_id, damage, hits FROM boss_damage WHERE boss_id=? ORDER BY damage DESC, user_id;",
        (boss_id,),
    )
    return [dict(r) for r in rows]


def attack_boss(ctx: Ctx, user_id: int, boss_id: int | None = None) -> dict:
    b = settings.get()["boss"]
    boss = active_boss(ctx)
    if boss is None or (boss_id is not None and boss["boss_id"] != boss_id):
        raise GameError("There is no active boss right now.")
    if boss["ends_at"] <= ctx.now:
        raise GameError("The boss is escaping… too late!")

    players.ensure_user(ctx, user_id)
    row = ctx.one("SELECT last_attack_at FROM boss_damage WHERE boss_id=? AND user_id=?;", (boss["boss_id"], user_id))
    ready_at = (row["last_attack_at"] if row else 0) + int(b["attack_cooldown_seconds"])
    if ready_at > ctx.now:
        raise GameError(f"You are catching your breath. Attack again <t:{int(ready_at)}:R>.")

    equipped = gear.get_equipped(ctx, user_id)
    damage = gear.attack_damage(equipped) * ctx.rng.uniform(1 - b["damage_variance"], 1 + b["damage_variance"])
    crit = ctx.rng.random() < b["crit_chance"]
    if crit:
        damage *= b["crit_multiplier"]
    damage = max(1, min(int(round(damage)), boss["hp"]))

    ctx.execute(
        """
        INSERT INTO boss_damage(boss_id, user_id, damage, hits, last_attack_at) VALUES(?, ?, ?, 1, ?)
        ON CONFLICT(boss_id, user_id) DO UPDATE SET
            damage = damage + excluded.damage, hits = hits + 1, last_attack_at = excluded.last_attack_at;
        """,
        (boss["boss_id"], user_id, damage, int(ctx.now)),
    )
    hp = boss["hp"] - damage
    ctx.execute("UPDATE bosses SET hp=? WHERE boss_id=?;", (hp, boss["boss_id"]))
    players.bump_stat(ctx, user_id, "boss_damage", damage)

    sword = equipped.get("sword")
    broken = bool(sword and gear.wear(ctx, sword))

    result = {"boss_id": boss["boss_id"], "name": boss["name"], "damage": damage, "crit": crit,
              "hp": hp, "max_hp": boss["max_hp"], "sword_broke": broken, "defeat": None}
    if hp <= 0:
        result["defeat"] = _defeat(ctx, boss)
    return result


def _defeat(ctx: Ctx, boss: dict) -> dict:
    """Share the reward pool by damage dealt; the top damage dealer gets a bonus and a book.

    A sword with Looting adds a bonus on top of the player's share.
    """
    b = settings.get()["boss"]
    # ends_at becomes the real end, so the next automatic boss waits from now.
    ctx.execute(
        "UPDATE bosses SET status='defeated', hp=0, ends_at=? WHERE boss_id=?;",
        (int(ctx.now), boss["boss_id"]),
    )
    ranking = boss_ranking(ctx, boss["boss_id"])
    total = sum(r["damage"] for r in ranking) or 1
    pool = int(b["reward_pool"])
    rewards = []
    for i, r in enumerate(ranking):
        share = pool * r["damage"] // total
        if i == 0:
            share += int(b["top_damage_bonus"])
        sword = gear.get_equipped(ctx, r["user_id"]).get("sword")
        looting = int(share * enchants.bonus("looting", enchants.level_of(sword, "looting")))
        players.earn_emeralds(ctx, r["user_id"], share + looting)
        players.add_xp(ctx, r["user_id"], int(b["xp_reward"]))
        players.bump_stat(ctx, r["user_id"], "bosses_defeated")
        reward = {**r, "reward": share + looting, "looting": looting, "book": None}
        if i == 0:
            book = enchants.give_random_book(ctx, r["user_id"], settings.get()["enchants"]["boss_book_weights"])
            reward["book"] = enchants.label(*book)
        rewards.append(reward)
    return {"rewards": rewards, "xp": int(b["xp_reward"])}


def escape_expired(ctx: Ctx) -> list[dict]:
    rows = ctx.all("SELECT * FROM bosses WHERE status='active' AND ends_at <= ?;", (int(ctx.now),))
    for r in rows:
        ctx.execute("UPDATE bosses SET status='escaped' WHERE boss_id=?;", (r["boss_id"],))
    return [dict(r) for r in rows]


def boss_view(ctx: Ctx, boss_id: int) -> dict | None:
    boss = get_boss(ctx, boss_id)
    if boss is None:
        return None
    return {**boss, "ranking": boss_ranking(ctx, boss_id)}
