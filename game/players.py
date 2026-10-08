"""Player state: emeralds, blocks, items, stats, XP and talents."""
from __future__ import annotations

from game import settings
from game.catalog import BLOCK_TYPES, MATERIALS, TALENT_BRANCHES
from game.db import Ctx
from game.errors import GameError
from game.notices import LevelUp


# ---------------- users ----------------
def ensure_user(ctx: Ctx, user_id: int) -> None:
    ctx.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?, ?);",
        (user_id, int(ctx.now)),
    )


def get_user(ctx: Ctx, user_id: int) -> dict:
    ensure_user(ctx, user_id)
    return dict(ctx.one("SELECT * FROM users WHERE user_id=?;", (user_id,)))


# ---------------- emeralds ----------------
def get_emeralds(ctx: Ctx, user_id: int) -> int:
    return get_user(ctx, user_id)["emeralds"]


def earn_emeralds(ctx: Ctx, user_id: int, amount: int) -> None:
    """Emeralds created by playing (selling, rewards...). Counts as earned."""
    if amount <= 0:
        return
    give_emeralds(ctx, user_id, amount)
    bump_stat(ctx, user_id, "emeralds_earned", amount)


def give_emeralds(ctx: Ctx, user_id: int, amount: int) -> None:
    """Emeralds added without counting as earned (transfers, refunds, staff)."""
    if amount <= 0:
        return
    ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET emeralds = emeralds + ? WHERE user_id=?;", (amount, user_id))


def spend_emeralds(ctx: Ctx, user_id: int, amount: int) -> None:
    """Remove emeralds, or raise GameError if the player cannot afford it."""
    if amount <= 0:
        return
    ensure_user(ctx, user_id)
    cur = ctx.execute(
        "UPDATE users SET emeralds = emeralds - ? WHERE user_id=? AND emeralds >= ?;",
        (amount, user_id, amount),
    )
    if cur.rowcount == 0:
        have = get_emeralds(ctx, user_id)
        raise GameError(f"Not enough emeralds: you have **{have}**, you need **{amount}**.")


def remove_emeralds_clamped(ctx: Ctx, user_id: int, amount: int) -> int:
    """Staff only: remove up to `amount`, returns the new balance."""
    ensure_user(ctx, user_id)
    ctx.execute(
        "UPDATE users SET emeralds = MAX(0, emeralds - ?) WHERE user_id=?;",
        (amount, user_id),
    )
    return get_emeralds(ctx, user_id)


# ---------------- blocks ----------------
def get_blocks(ctx: Ctx, user_id: int) -> dict[str, int]:
    ensure_user(ctx, user_id)
    inv = {b: 0 for b in BLOCK_TYPES}
    for r in ctx.all("SELECT block_type, amount FROM blocks WHERE user_id=?;", (user_id,)):
        inv[r["block_type"]] = r["amount"]
    return inv


def add_blocks(ctx: Ctx, user_id: int, block_type: str, amount: int) -> None:
    if block_type not in BLOCK_TYPES:
        raise ValueError(f"Unknown block type: {block_type}")
    if amount <= 0:
        return
    ensure_user(ctx, user_id)
    ctx.execute(
        """
        INSERT INTO blocks(user_id, block_type, amount) VALUES(?, ?, ?)
        ON CONFLICT(user_id, block_type) DO UPDATE SET amount = amount + excluded.amount;
        """,
        (user_id, block_type, amount),
    )


def take_blocks(ctx: Ctx, user_id: int, block_type: str, amount: int) -> None:
    if amount <= 0:
        return
    cur = ctx.execute(
        "UPDATE blocks SET amount = amount - ? WHERE user_id=? AND block_type=? AND amount >= ?;",
        (amount, user_id, block_type, amount),
    )
    if cur.rowcount == 0:
        raise GameError(f"You don't have **{amount} {block_type}**.")


def block_value(block_type: str) -> int:
    return int(settings.get()["block_values"][block_type])


def trader_multiplier(trader_points: int) -> float:
    t = settings.get()["talents"]
    points = min(max(0, trader_points), t["caps"]["trader"])
    return 1.0 + t["trader_bonus_per_point"] * points


def sell_all_blocks(ctx: Ctx, user_id: int) -> dict:
    """Sell every block. Returns {"sold": {type: amount}, "base": n, "bonus": n, "balance": n}."""
    user = get_user(ctx, user_id)
    blocks = get_blocks(ctx, user_id)
    sold = {b: amt for b, amt in blocks.items() if amt > 0}
    base = sum(amt * block_value(b) for b, amt in sold.items())
    if base == 0:
        raise GameError("You have no blocks to sell.")
    bonus = int(round(base * (trader_multiplier(user["trader_points"]) - 1.0)))
    ctx.execute("UPDATE blocks SET amount = 0 WHERE user_id=?;", (user_id,))
    earn_emeralds(ctx, user_id, base + bonus)
    bump_stat(ctx, user_id, "emeralds_from_sales", base + bonus)
    return {"sold": sold, "base": base, "bonus": bonus, "balance": get_emeralds(ctx, user_id)}


# ---------------- items (sticks, ingots) ----------------
def get_items(ctx: Ctx, user_id: int) -> dict[tuple[str, str], int]:
    ensure_user(ctx, user_id)
    rows = ctx.all(
        "SELECT item, material, amount FROM items WHERE user_id=? AND amount > 0;", (user_id,)
    )
    return {(r["item"], r["material"]): r["amount"] for r in rows}


def item_amount(ctx: Ctx, user_id: int, item: str, material: str) -> int:
    row = ctx.one(
        "SELECT amount FROM items WHERE user_id=? AND item=? AND material=?;",
        (user_id, item, material),
    )
    return row["amount"] if row else 0


def add_item(ctx: Ctx, user_id: int, item: str, material: str, amount: int) -> int:
    if item == "ingot" and material not in MATERIALS:
        raise ValueError(f"Unknown material: {material}")
    if amount <= 0:
        return item_amount(ctx, user_id, item, material)
    ensure_user(ctx, user_id)
    ctx.execute(
        """
        INSERT INTO items(user_id, item, material, amount) VALUES(?, ?, ?, ?)
        ON CONFLICT(user_id, item, material) DO UPDATE SET amount = amount + excluded.amount;
        """,
        (user_id, item, material, amount),
    )
    return item_amount(ctx, user_id, item, material)


def take_item(ctx: Ctx, user_id: int, item: str, material: str, amount: int) -> None:
    if amount <= 0:
        return
    cur = ctx.execute(
        "UPDATE items SET amount = amount - ? WHERE user_id=? AND item=? AND material=? AND amount >= ?;",
        (amount, user_id, item, material, amount),
    )
    if cur.rowcount == 0:
        name = "stick(s)" if item == "stick" else f"{material} ingot(s)"
        have = item_amount(ctx, user_id, item, material)
        raise GameError(f"Not enough {name}: you have **{have}**, you need **{amount}**.")


# ---------------- stats ----------------
def bump_stat(ctx: Ctx, user_id: int, stat: str, amount: int = 1) -> None:
    if amount == 0:
        return
    ensure_user(ctx, user_id)
    ctx.execute(
        """
        INSERT INTO stats(user_id, stat, value) VALUES(?, ?, ?)
        ON CONFLICT(user_id, stat) DO UPDATE SET value = value + excluded.value;
        """,
        (user_id, stat, amount),
    )


def set_stat_max(ctx: Ctx, user_id: int, stat: str, value: int) -> None:
    """Keep the highest value ever reached (records like the best streak)."""
    ensure_user(ctx, user_id)
    ctx.execute(
        """
        INSERT INTO stats(user_id, stat, value) VALUES(?, ?, ?)
        ON CONFLICT(user_id, stat) DO UPDATE SET value = MAX(value, excluded.value);
        """,
        (user_id, stat, value),
    )


def get_stats(ctx: Ctx, user_id: int) -> dict[str, int]:
    rows = ctx.all("SELECT stat, value FROM stats WHERE user_id=?;", (user_id,))
    return {r["stat"]: r["value"] for r in rows}


def get_stat(ctx: Ctx, user_id: int, stat: str) -> int:
    row = ctx.one("SELECT value FROM stats WHERE user_id=? AND stat=?;", (user_id, stat))
    return row["value"] if row else 0


# ---------------- XP / levels ----------------
def xp_required_for_level(level: int) -> int:
    return 100 + (level - 1) * 25


def talent_points_for_level(level: int) -> int:
    return level // settings.get()["talents"]["points_every_levels"]


def _spent_talent_points(user: dict) -> int:
    return sum(user[f"{b}_points"] for b in TALENT_BRANCHES)


def add_xp(ctx: Ctx, user_id: int, amount: int) -> dict:
    user = get_user(ctx, user_id)
    if amount <= 0:
        return user
    xp, level = user["xp"] + amount, user["level"]
    while xp >= xp_required_for_level(level):
        xp -= xp_required_for_level(level)
        level += 1
    gained = talent_points_for_level(level) - talent_points_for_level(user["level"])
    ctx.execute(
        "UPDATE users SET xp=?, level=?, talent_points = talent_points + ? WHERE user_id=?;",
        (xp, level, gained, user_id),
    )
    if level > user["level"]:
        ctx.notices.append(LevelUp(user_id, user["level"], level, gained))
    return get_user(ctx, user_id)


def set_xp(ctx: Ctx, user_id: int, xp: int) -> dict:
    """Staff: set the XP inside the current level (levels up if it overflows)."""
    ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET xp=0 WHERE user_id=?;", (user_id,))
    return add_xp(ctx, user_id, max(0, xp))


def set_level(ctx: Ctx, user_id: int, level: int) -> dict:
    """Staff: set the level and recompute the unspent talent points."""
    user = get_user(ctx, user_id)
    level = max(1, level)
    unspent = max(0, talent_points_for_level(level) - _spent_talent_points(user))
    ctx.execute(
        "UPDATE users SET level=?, xp=0, talent_points=? WHERE user_id=?;",
        (level, unspent, user_id),
    )
    if level > user["level"]:
        ctx.notices.append(LevelUp(user_id, user["level"], level, 0))
    return get_user(ctx, user_id)


# ---------------- talents ----------------
def talent_cap(branch: str) -> int:
    return int(settings.get()["talents"]["caps"][branch])


def buy_talent(ctx: Ctx, user_id: int, branch: str, points: int) -> dict:
    if branch not in TALENT_BRANCHES:
        raise GameError(f"Unknown branch. Allowed: {', '.join(TALENT_BRANCHES)}.")
    if points <= 0:
        raise GameError("Points must be greater than 0.")
    user = get_user(ctx, user_id)
    if user["talent_points"] < points:
        raise GameError(f"Not enough talent points: you have **{user['talent_points']}**.")
    current, cap = user[f"{branch}_points"], talent_cap(branch)
    if current + points > cap:
        raise GameError(
            f"**{branch}** is capped at **{cap}** points (you have {current}). "
            "Extra points would have no effect."
        )
    col = f"{branch}_points"
    ctx.execute(
        f"UPDATE users SET talent_points = talent_points - ?, {col} = {col} + ? WHERE user_id=?;",
        (points, points, user_id),
    )
    return get_user(ctx, user_id)


def add_talent_points(ctx: Ctx, user_id: int, delta: int) -> dict:
    ensure_user(ctx, user_id)
    ctx.execute(
        "UPDATE users SET talent_points = MAX(0, talent_points + ?) WHERE user_id=?;",
        (delta, user_id),
    )
    return get_user(ctx, user_id)


def reset_talents(ctx: Ctx, user_id: int) -> dict:
    """Refund every spent point."""
    user = get_user(ctx, user_id)
    ctx.execute(
        """
        UPDATE users SET talent_points = talent_points + ?,
            miner_points=0, trader_points=0, lucky_points=0, efficiency_points=0
        WHERE user_id=?;
        """,
        (_spent_talent_points(user), user_id),
    )
    return get_user(ctx, user_id)
