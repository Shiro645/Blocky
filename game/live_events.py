"""Timed events: a bonus for everyone for a while (an hour by default).

- 🎰 Gambling Frenzy: the maximum bet and the daily cap of the games of chance are multiplied.
- ⛏️ Mining Rush: more XP when mining.
- 💰 Golden Hour: /sell pays more for blocks.
- 🍀 Lucky Hour: obsidian and bedrock are more likely when mining.
- 🏷️ Market Sale: /market is cheaper.

One event at a time. The staff starts one with /event start (and ends it with /event stop), and one
comes by itself every day (settings "live_events"): at a random time between earliest_hour and
latest_hour (local time), picked from the day so a restart doesn't change it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from game import settings
from game.db import Ctx
from game.errors import GameError


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    emoji: str

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


KINDS: dict[str, Kind] = {
    "gambling_frenzy": Kind("gambling_frenzy", "Gambling Frenzy", "🎰"),
    "mining_rush": Kind("mining_rush", "Mining Rush", "⛏️"),
    "golden_hour": Kind("golden_hour", "Golden Hour", "💰"),
    "lucky_hour": Kind("lucky_hour", "Lucky Hour", "🍀"),
    "market_sale": Kind("market_sale", "Market Sale", "🏷️"),
}


def _cfg() -> dict:
    return settings.get()["live_events"]


def describe(kind: str) -> str:
    """What the event does, with the numbers of the current settings."""
    c = _cfg()
    if kind == "gambling_frenzy":
        x = f"×{float(c['frenzy_multiplier']):g}"
        return f"Bets and the daily limit of the Lucky Block and the wheel {x}"
    if kind == "mining_rush":
        return f"Mining XP ×{float(c['rush_xp_multiplier']):g}"
    if kind == "golden_hour":
        return f"/sell pays +{float(c['golden_sell_bonus']):.0%} for blocks"
    if kind == "lucky_hour":
        return f"Obsidian and bedrock ×{float(c['lucky_rare_multiplier']):g} more likely when mining"
    return f"/market costs {float(c['market_sale_discount']):.0%} less"


def get(ctx: Ctx, event_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM live_events WHERE event_id=?;", (event_id,))
    return dict(row) if row else None


def current(ctx: Ctx) -> dict | None:
    """The event running now, if any."""
    row = ctx.one(
        "SELECT * FROM live_events WHERE starts_at <= ? AND ends_at > ? ORDER BY event_id DESC LIMIT 1;",
        (int(ctx.now), int(ctx.now)),
    )
    return dict(row) if row else None


def active(ctx: Ctx, kind: str) -> bool:
    event = current(ctx)
    return event is not None and event["kind"] == kind


# ---------------- the bonuses ----------------
def bet_multiplier(ctx: Ctx) -> float:
    return float(_cfg()["frenzy_multiplier"]) if active(ctx, "gambling_frenzy") else 1.0


def xp_multiplier(ctx: Ctx) -> float:
    return float(_cfg()["rush_xp_multiplier"]) if active(ctx, "mining_rush") else 1.0


def sell_bonus(ctx: Ctx) -> float:
    return float(_cfg()["golden_sell_bonus"]) if active(ctx, "golden_hour") else 0.0


def rare_multiplier(ctx: Ctx) -> float:
    return float(_cfg()["lucky_rare_multiplier"]) if active(ctx, "lucky_hour") else 1.0


def market_discount(ctx: Ctx) -> float:
    return min(1.0, float(_cfg()["market_sale_discount"])) if active(ctx, "market_sale") else 0.0


# ---------------- starting and ending ----------------
def start(ctx: Ctx, kind: str, minutes: int | None = None, by: int | None = None, day: str | None = None) -> dict:
    """Start an event now (`by`: the staff member; `day`: the day of the random event)."""
    if kind not in KINDS:
        raise GameError("Unknown event.")
    running = current(ctx)
    if running is not None:
        raise GameError(f"**{KINDS[running['kind']].label}** is on until <t:{running['ends_at']}:t>: "
                        "end it first with `/event stop`.")
    minutes = int(minutes if minutes is not None else _cfg()["duration_minutes"])
    if minutes < 1:
        raise GameError("An event lasts at least 1 minute.")
    now = int(ctx.now)
    cur = ctx.execute(
        "INSERT INTO live_events(kind, starts_at, ends_at, day, started_by) VALUES(?, ?, ?, ?, ?);",
        (kind, now, now + minutes * 60, day, by),
    )
    return get(ctx, cur.lastrowid)


def stop(ctx: Ctx) -> dict:
    """End the running event now."""
    event = current(ctx)
    if event is None:
        raise GameError("No event is on.")
    ctx.execute("UPDATE live_events SET ends_at=? WHERE event_id=?;", (int(ctx.now), event["event_id"]))
    return get(ctx, event["event_id"])


def random_time(ctx: Ctx, day=None) -> int | None:
    """When the random event of this day starts (a timestamp), None when there is none."""
    c = _cfg()
    first, last = int(c["earliest_hour"]), int(c["latest_hour"])
    if not c["daily_random"] or last <= first or not random_kinds():
        return None
    day = day or ctx.today
    minute = random.Random(f"blocky-live-event-{day.isoformat()}").randrange(first * 60, last * 60)
    midnight = datetime.combine(day, time(), tzinfo=ctx.local_now.tzinfo)
    return int((midnight + timedelta(minutes=minute)).timestamp())


def random_kinds() -> list[str]:
    """The events that can come by themselves."""
    on = _cfg()["random_kinds"]
    return [k for k in KINDS if on.get(k)]


def tick(ctx: Ctx) -> list[dict]:
    """Called every minute. Returns the events to announce: {"type": "ended" | "started", "event"}."""
    out = []
    now = int(ctx.now)
    for row in ctx.all("SELECT * FROM live_events WHERE announced=1 AND ends_at <= ?;", (now,)):
        ctx.execute("UPDATE live_events SET announced=2 WHERE event_id=?;", (row["event_id"],))
        out.append({"type": "ended", "event": get(ctx, row["event_id"])})
    at = random_time(ctx)
    today = ctx.today.isoformat()
    last = datetime.combine(ctx.today, time(hour=int(_cfg()["latest_hour"]) % 24),
                            tzinfo=ctx.local_now.tzinfo).timestamp()
    if (at is not None and at <= now < last and current(ctx) is None
            and not ctx.one("SELECT 1 FROM live_events WHERE day=?;", (today,))):
        # Not the same as yesterday's when another one can come.
        kinds = random_kinds()
        yesterday = ctx.one("SELECT kind FROM live_events WHERE day=?;", ((ctx.today - timedelta(days=1)).isoformat(),))
        if yesterday and len(kinds) > 1 and yesterday["kind"] in kinds:
            kinds.remove(yesterday["kind"])
        event = start(ctx, ctx.rng.choice(kinds), day=today)
        out.append({"type": "started", "event": event})
    return out


def to_announce(ctx: Ctx) -> list[dict]:
    """Events started but not posted yet (just started, or the channel was missing)."""
    rows = ctx.all("SELECT * FROM live_events WHERE announced=0 AND ends_at > ?;", (int(ctx.now),))
    return [dict(r) for r in rows]


def set_message(ctx: Ctx, event_id: int, channel_id: int | None, message_id: int | None) -> None:
    ctx.execute("UPDATE live_events SET announced=1, channel_id=?, message_id=? WHERE event_id=?;",
                (channel_id, message_id, event_id))
