"""The wandering villager: comes every day for a few hours with 3 offers.

- a sale: goods below their value (ingots, lapis, a book, potions);
- a purchase: he buys a pile of blocks above the /sell price;
- an exclusive: a level III book or a reinforced potion (II).

Each offer exists once: the first player to take it gets it.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from game import assets, enchants, players, potions, settings
from game.db import Ctx
from game.errors import GameError

HOUR = 3600
KINDS = ("sell", "buy", "exclusive")


def _cfg() -> dict:
    return settings.get()["villager"]


# ---------------- schedule ----------------
def _at(ctx: Ctx, day, hour: int) -> int:
    return int(datetime.combine(day, time(hour=int(hour) % 24), tzinfo=ctx.local_now.tzinfo).timestamp())


def hours(ctx: Ctx, day=None) -> tuple[int, int]:
    """(arrives_at, leaves_at) for a day (today by default)."""
    day = day or ctx.today
    c = _cfg()
    arrive = _at(ctx, day, c["arrive_hour"])
    leave_day = day if int(c["leave_hour"]) > int(c["arrive_hour"]) else day + timedelta(days=1)
    return arrive, _at(ctx, leave_day, c["leave_hour"])


def next_arrival(ctx: Ctx) -> int:
    arrive, _ = hours(ctx)
    return arrive if ctx.now < arrive else hours(ctx, ctx.today + timedelta(days=1))[0]


# ---------------- offers ----------------
def _sell_offer(ctx: Ctx) -> dict:
    good = ctx.rng.choice(_cfg()["goods"])
    asset, amount = good["asset"], int(good["amount"])
    if asset == "book":
        name, level = enchants.random_book(ctx.rng, [70, 30])
        asset = f"book:{name}:{level}"
    elif asset == "potion":
        asset = f"potion:{ctx.rng.choice(sorted(potions.POTIONS))}"
    value = int(round(assets.unit_value(asset) * amount))
    price = max(1, int(round(value * (1 - float(_cfg()["sell_discount"])))))
    return {"kind": "sell", "asset": asset, "amount": amount, "price": price, "value": value}


def _buy_offer(ctx: Ctx) -> dict:
    block, amount = ctx.rng.choice(sorted(_cfg()["buys"].items()))
    value = players.block_value(block) * int(amount)
    price = int(round(value * (1 + float(_cfg()["buy_bonus"]))))
    return {"kind": "buy", "asset": f"block:{block}", "amount": int(amount), "price": price, "value": value}


def _exclusive_offer(ctx: Ctx) -> dict:
    c = _cfg()
    if ctx.rng.random() < 0.5:
        asset, price = f"book:{ctx.rng.choice(sorted(enchants.ENCHANTS))}:3", int(c["book_iii_price"])
    else:
        asset, price = f"potion:{ctx.rng.choice(sorted(potions.POTIONS))}:2", int(c["potion_ii_price"])
    return {"kind": "exclusive", "asset": asset, "amount": 1, "price": price, "value": int(assets.unit_value(asset))}


# ---------------- visits ----------------
def get_visit(ctx: Ctx, visit_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM villager_visits WHERE visit_id=?;", (visit_id,))
    if row is None:
        return None
    visit = dict(row)
    visit["offers"] = [
        dict(r) for r in ctx.all("SELECT * FROM villager_offers WHERE visit_id=? ORDER BY slot;", (visit_id,))
    ]
    return visit


def current(ctx: Ctx) -> dict | None:
    row = ctx.one("SELECT visit_id FROM villager_visits WHERE status='here' ORDER BY visit_id DESC LIMIT 1;")
    return get_visit(ctx, row["visit_id"]) if row else None


def arrive(ctx: Ctx, leaves_at: int | None = None) -> dict:
    if current(ctx):
        raise GameError("The villager is already here.")
    if leaves_at is None:
        c = _cfg()
        length = (int(c["leave_hour"]) - int(c["arrive_hour"])) % 24 or 24
        leaves_at = int(ctx.now + length * HOUR)
    cur = ctx.execute(
        "INSERT INTO villager_visits(day, arrives_at, leaves_at, status) VALUES(?, ?, ?, 'here');",
        (ctx.today.isoformat(), int(ctx.now), leaves_at),
    )
    visit_id = int(cur.lastrowid)
    for slot, make in enumerate((_sell_offer, _buy_offer, _exclusive_offer)):
        o = make(ctx)
        ctx.execute(
            """
            INSERT INTO villager_offers(visit_id, slot, kind, asset, amount, price, value)
            VALUES(?, ?, ?, ?, ?, ?, ?);
            """,
            (visit_id, slot, o["kind"], o["asset"], o["amount"], o["price"], o["value"]),
        )
    return get_visit(ctx, visit_id)  # type: ignore[return-value]


def set_message(ctx: Ctx, visit_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute(
        "UPDATE villager_visits SET channel_id=?, message_id=? WHERE visit_id=?;", (channel_id, message_id, visit_id)
    )


def tick(ctx: Ctx) -> list[dict]:
    """Called every minute: the villager arrives at his hour and leaves at the end of his visit."""
    events = []
    visit = current(ctx)
    if visit and ctx.now >= visit["leaves_at"]:
        ctx.execute("UPDATE villager_visits SET status='gone' WHERE visit_id=?;", (visit["visit_id"],))
        events.append({"type": "left", "visit": get_visit(ctx, visit["visit_id"])})
        visit = None
    if visit is None:
        arrive_at, leave_at = hours(ctx)
        # A visit staff started earlier in the day doesn't cancel the evening one.
        came = ctx.one("SELECT 1 FROM villager_visits WHERE arrives_at >= ?;", (arrive_at,))
        if arrive_at <= ctx.now < leave_at and not came:
            events.append({"type": "arrived", "visit": arrive(ctx, leave_at)})
    return events


def take(ctx: Ctx, user_id: int, visit_id: int, slot: int) -> dict:
    """Take an offer: pay (or get paid) and get the goods (or give the blocks)."""
    visit = get_visit(ctx, visit_id)
    if visit is None or visit["status"] != "here" or ctx.now >= visit["leaves_at"]:
        raise GameError("The villager has left. Come back tomorrow!")
    offer = next((o for o in visit["offers"] if o["slot"] == slot), None)
    if offer is None:
        raise GameError("This offer doesn't exist.")
    if offer["taken_by"] is not None:
        raise GameError(f"Too late! <@{offer['taken_by']}> got it first.")
    if offer["kind"] == "buy":
        assets.take(ctx, user_id, offer["asset"], offer["amount"])
        # Like /sell, blocks sold to the villager count as earned.
        players.earn_emeralds(ctx, user_id, offer["price"])
    else:
        players.spend_emeralds(ctx, user_id, offer["price"])
        assets.give(ctx, user_id, offer["asset"], offer["amount"])
    ctx.execute(
        "UPDATE villager_offers SET taken_by=?, taken_at=? WHERE visit_id=? AND slot=?;",
        (user_id, int(ctx.now), visit_id, slot),
    )
    players.bump_stat(ctx, user_id, "villager_trades")
    return {"offer": {**offer, "taken_by": user_id}, "visit": get_visit(ctx, visit_id)}


def leave_now(ctx: Ctx) -> dict:
    """Staff: send the villager away."""
    visit = current(ctx)
    if visit is None:
        raise GameError("The villager isn't here.")
    ctx.execute("UPDATE villager_visits SET status='gone', leaves_at=? WHERE visit_id=?;", (int(ctx.now), visit["visit_id"]))
    return get_visit(ctx, visit["visit_id"])  # type: ignore[return-value]
