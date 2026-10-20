"""Day and night (/time, /sleep): the night is the hours of rob.night_start_hour to rob.night_end_hour.

- Every night, night.monsters monsters come at random times (night.margin_minutes after dusk to as long before
  dawn), each one attacking a random player of at least night.min_level who didn't /sleep that night. The target
  fights it alone with their gear (like the dungeon) within night.fight_minutes: won, a reward and XP; lost or
  ignored, night.loss of their emeralds (night.loss_max at most).
- A 👻 Phantom also comes every night, for a player who didn't sleep the night.phantom_nights nights before:
  stronger, a bigger reward, a bigger loss.
- /sleep (once a night): no monster attacks you until the morning, and the next /daily pays night.sleep_daily_bonus
  more.
The nights are named after the date of their evening ("2026-10-19" = from the 19th at 22:00 to the 20th at 06:00).
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, time, timedelta

from game import botstate, gear, players, pve, settings
from game.db import Ctx
from game.errors import GameError

MINUTE = 60
KINDS = ("zombie", "skeleton", "spider", "creeper")
PHANTOM = "phantom"
PHANTOM_SLOT = 999  # its own slot: changing night.monsters during a night never makes it come twice
LATE = 10 * MINUTE  # a slot missed by more than this (the bot was off) is skipped


def _cfg() -> dict:
    return settings.get()["night"]


def _hours() -> tuple[int, int]:
    r = settings.get()["rob"]
    return int(r["night_start_hour"]) % 24, int(r["night_end_hour"]) % 24


def night_of(ctx: Ctx) -> date | None:
    """The night now (the date of its evening), None in the day."""
    start, end = _hours()
    if start == end:
        return None
    local = ctx.local_now
    if start < end:
        return local.date() if start <= local.hour < end else None
    if local.hour >= start:
        return local.date()
    if local.hour < end:
        return local.date() - timedelta(days=1)
    return None


def _bounds(ctx: Ctx, night: date) -> tuple[datetime, datetime]:
    start, end = _hours()
    tz = ctx.local_now.tzinfo
    dusk = datetime.combine(night, time(hour=start), tzinfo=tz)
    dawn = datetime.combine(night + timedelta(days=0 if start < end else 1), time(hour=end), tzinfo=tz)
    return dusk, dawn


def next_change(ctx: Ctx) -> int:
    """When it's dawn (at night) or dusk (in the day)."""
    night = night_of(ctx)
    if night is not None:
        return int(_bounds(ctx, night)[1].timestamp())
    today = ctx.local_now.date()
    for day in (today, today + timedelta(days=1)):
        dusk = _bounds(ctx, day)[0]
        if dusk.timestamp() > ctx.now:
            return int(dusk.timestamp())
    return int(ctx.now)


def slots(ctx: Ctx, night: date) -> list[tuple[int, int, str]]:
    """(slot, time, kind) of a night's monsters, the Phantom last. The same whenever it's asked."""
    c = _cfg()
    dusk, dawn = _bounds(ctx, night)
    margin = float(c["margin_minutes"]) * MINUTE
    lo, hi = dusk.timestamp() + margin, dawn.timestamp() - margin
    if hi <= lo:
        lo, hi = dusk.timestamp(), dawn.timestamp()
    rng = random.Random(f"blocky-night-{night.isoformat()}")
    phantom_at = int(rng.uniform(lo, hi))  # drawn first: the number of monsters doesn't move it
    out = [(i, int(rng.uniform(lo, hi)), rng.choice(KINDS)) for i in range(int(c["monsters"]))]
    out.append((PHANTOM_SLOT, phantom_at, PHANTOM))
    return out


# ---------------- sleep ----------------
def _since(ctx: Ctx) -> date:
    """The first night the bot counted (players who never slept are counted from it)."""
    saved = botstate.get(ctx, "night_since")
    if saved is None:
        saved = (night_of(ctx) or ctx.today).isoformat()
        botstate.put(ctx, "night_since", saved)
    return date.fromisoformat(saved)


def nights_awake(ctx: Ctx, user: dict, night: date) -> int:
    """How many nights before this one the player didn't sleep."""
    last = date.fromisoformat(user["last_sleep"]) if user.get("last_sleep") else _since(ctx) - timedelta(days=1)
    return max(0, (night - last).days - 1)


def sleep(ctx: Ctx, user_id: int) -> dict:
    night = night_of(ctx)
    if night is None:
        raise GameError(f"You can only sleep at night. The sun sets <t:{next_change(ctx)}:R>.")
    user = players.get_user(ctx, user_id)
    if user["last_sleep"] == night.isoformat():
        raise GameError("You're already asleep. Sweet dreams! 💤")
    if ctx.one("SELECT 1 FROM night_attacks WHERE target_id=? AND status='waiting';", (user_id,)):
        raise GameError("You may not rest now, there are monsters nearby! Fight it first.")
    ctx.execute("UPDATE users SET last_sleep=? WHERE user_id=?;", (night.isoformat(), user_id))
    players.bump_stat(ctx, user_id, "nights_slept")
    return {"night": night.isoformat(), "dawn": next_change(ctx), "bonus": float(_cfg()["sleep_daily_bonus"])}


def slept_before(user: dict, today: date) -> bool:
    """The player slept the night before this day (their /daily pays more)."""
    return user.get("last_sleep") == (today - timedelta(days=1)).isoformat()


# ---------------- the monsters ----------------
def get(ctx: Ctx, attack_id: int) -> dict:
    row = ctx.one("SELECT * FROM night_attacks WHERE attack_id=?;", (attack_id,))
    if row is None:
        raise GameError("This monster is gone.")
    out = dict(row)
    out["log"] = json.loads(row["log"]) if row["log"] else []
    return out


def reward(kind: str) -> int:
    return int(_cfg()["rewards"][kind])


def _monster(kind: str) -> pve.Monster:
    c = _cfg()
    if kind == PHANTOM:
        m, s = c["phantom"], 1.0
    else:
        m, s = settings.get()["pve"]["monsters"][kind], float(c["strength"][kind])
    return pve.Monster(kind, float(m["hp"]) * s, (float(m["min_damage"]) * s, float(m["max_damage"]) * s),
                       pve.MONSTERS[kind].fuse)


def _loss(ctx: Ctx, user_id: int, kind: str) -> int:
    c = _cfg()
    share, top = (c["phantom_loss"], c["phantom_loss_max"]) if kind == PHANTOM else (c["loss"], c["loss_max"])
    amount = min(int(top), int(players.get_emeralds(ctx, user_id) * float(share)))
    if amount > 0:
        players.spend_emeralds(ctx, user_id, amount)
    return amount


def seen(ctx: Ctx, user_id: int) -> None:
    """The player just played (a command, mining)."""
    ctx.execute("UPDATE users SET last_seen=? WHERE user_id=?;", (int(ctx.now), user_id))


def _targets(ctx: Ctx, candidates: list[int], night: date, phantom: bool) -> list[int]:
    c = _cfg()
    since = ctx.now - float(c["active_hours"]) * 3600
    out = []
    for uid in dict.fromkeys(candidates):
        row = ctx.one("SELECT * FROM users WHERE user_id=?;", (uid,))
        if row is None or row["level"] < int(c["min_level"]) or row["last_sleep"] == night.isoformat():
            continue
        if (row["last_seen"] or 0) < since:  # not played lately: probably not around
            continue
        if ctx.one("SELECT 1 FROM night_attacks WHERE target_id=? AND status='waiting';", (uid,)):
            continue
        if phantom and nights_awake(ctx, dict(row), night) < int(c["phantom_nights"]):
            continue
        out.append(uid)
    return out


def tick(ctx: Ctx, candidates: list[int]) -> dict:
    """Called every minute with the members who can be attacked: monsters whose time came attack, the ones
    nobody fought in time leave (their target loses emeralds)."""
    ended = []
    for row in ctx.all("SELECT attack_id FROM night_attacks WHERE status='waiting' AND deadline <= ?;", (int(ctx.now),)):
        a = get(ctx, row["attack_id"])
        lost = _loss(ctx, a["target_id"], a["kind"])
        ctx.execute("UPDATE night_attacks SET status='fled', amount=? WHERE attack_id=?;", (lost, a["attack_id"]))
        ended.append(get(ctx, a["attack_id"]))
    spawned = []
    night = night_of(ctx)
    if night is not None:
        _since(ctx)
        for slot, at, kind in slots(ctx, night):
            if at > ctx.now or ctx.one("SELECT 1 FROM night_attacks WHERE night=? AND slot=?;", (night.isoformat(), slot)):
                continue
            status, target, deadline = "missed", None, None
            if ctx.now - at <= LATE:
                pool = _targets(ctx, candidates, night, kind == PHANTOM)
                if pool:
                    status, target = "waiting", ctx.rng.choice(pool)
                    deadline = int(ctx.now + float(_cfg()["fight_minutes"]) * MINUTE)
                else:
                    status = "nobody"
            cur = ctx.execute(
                "INSERT INTO night_attacks(night, slot, kind, target_id, status, created_at, deadline) "
                "VALUES(?, ?, ?, ?, ?, ?, ?);",
                (night.isoformat(), slot, kind, target, status, int(ctx.now), deadline),
            )
            if status == "waiting":
                spawned.append(get(ctx, int(cur.lastrowid)))
    return {"spawned": spawned, "ended": ended}


def unposted(ctx: Ctx, attack_id: int) -> None:
    """The attack couldn't be shown (no channel, Discord refused): nobody can fight it, so it never happened."""
    ctx.execute("UPDATE night_attacks SET status='nobody', target_id=NULL WHERE attack_id=? AND status='waiting';",
                (attack_id,))


def set_message(ctx: Ctx, attack_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE night_attacks SET channel_id=?, message_id=? WHERE attack_id=?;",
                (channel_id, message_id, attack_id))


def fight(ctx: Ctx, attack_id: int, user_id: int) -> dict:
    """The target fights the monster alone, with their gear."""
    a = get(ctx, attack_id)
    if a["status"] != "waiting":
        raise GameError("This fight is over.")
    if a["target_id"] != user_id:
        raise GameError(f"This monster is after <@{a['target_id']}>, not you.")
    if ctx.now >= a["deadline"]:
        raise GameError("Too late: the monster left.")
    hero = pve.make_hero(ctx, user_id)
    result = pve.fight_wave(ctx.rng, [hero], 1, "normal", [_monster(a["kind"])])
    pieces = gear.get_pieces(ctx, hero.gear_ids)
    if pieces.get("sword") and hero.attacks:
        gear.wear(ctx, pieces["sword"], hero.attacks)
    gear.wear_one_piece_per_hit(ctx, pieces, hero.hits_taken)
    if result["cleared"]:
        amount = reward(a["kind"])
        players.earn_emeralds(ctx, user_id, amount)
        players.add_xp(ctx, user_id, int(_cfg()["xp"]))
        players.bump_stat(ctx, user_id, "phantoms_defeated" if a["kind"] == PHANTOM else "night_monsters_defeated")
        status = "won"
    else:
        amount = _loss(ctx, user_id, a["kind"])
        status = "lost"
    log = result["log"][-6:] + [f"❤️ <@{user_id}>: {hero.hp:.1f} HP left"]
    ctx.execute("UPDATE night_attacks SET status=?, amount=?, log=? WHERE attack_id=?;",
                (status, amount, json.dumps(log), attack_id))
    return get(ctx, attack_id)


# ---------------- announcements ----------------
def to_announce(ctx: Ctx) -> str | None:
    """'dusk' or 'dawn' once, when it changes."""
    night = night_of(ctx)
    now = f"night:{night.isoformat()}" if night else f"day:{ctx.today.isoformat()}"
    before = botstate.get(ctx, "night_state")
    if before == now:
        return None
    botstate.put(ctx, "night_state", now)
    if before is None or before.startswith("day") == (night is None):
        return None  # the first run, or a new day without a night between (the night is switched off)
    return "dusk" if night else "dawn"


def status(ctx: Ctx, user_id: int) -> dict:
    user = players.get_user(ctx, user_id)
    night = night_of(ctx)
    out = {"night": night is not None, "change": next_change(ctx), "slept": False, "awake": 0, "waiting": None}
    if night is not None:
        out["slept"] = user["last_sleep"] == night.isoformat()
        out["awake"] = nights_awake(ctx, user, night)
    else:
        out["rested"] = slept_before(user, ctx.today)
    row = ctx.one("SELECT attack_id FROM night_attacks WHERE target_id=? AND status='waiting';", (user_id,))
    if row:
        out["waiting"] = get(ctx, row["attack_id"])
    return out
