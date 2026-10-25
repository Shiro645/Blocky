"""Player state: emeralds, blocks, items, stats, XP and talents."""
from __future__ import annotations

from game import biomes, live_events, settings
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
    """Emeralds created by playing (rewards, the trader bonus...).

    Counts as earned, and as score for the weekly season.
    """
    if amount <= 0:
        return
    give_emeralds(ctx, user_id, amount)
    add_score(ctx, user_id, amount)


def add_score(ctx: Ctx, user_id: int, amount: int) -> None:
    """Value created by playing, without giving emeralds (blocks mined are scored when mined).

    Weekly season score, team season score and the "emeralds earned" stat.
    Blocks are scored when they are mined, not when they are sold: giving
    blocks to another player doesn't move the score.
    """
    if amount <= 0:
        return
    bump_stat(ctx, user_id, "emeralds_earned", amount)
    ctx.execute(
        """
        INSERT INTO season_scores(season_id, user_id, score) VALUES(?, ?, ?)
        ON CONFLICT(season_id, user_id) DO UPDATE SET score = score + excluded.score;
        """,
        (ctx.week_id, user_id, amount),
    )
    # Imported here: teams depends on this module.
    from game import teams

    teams.add_score(ctx, user_id, amount)


def give_emeralds(ctx: Ctx, user_id: int, amount: int) -> None:
    """Emeralds added without counting as earned (transfers, refunds, staff).

    A late borrower gives part of it to their lender (game/loans.py).
    """
    if amount <= 0:
        return
    ensure_user(ctx, user_id)
    # Imported here: loans depends on this module.
    from game import loans

    amount -= loans.garnish(ctx, user_id, amount)
    if amount <= 0:
        return
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


def sell_blocks(ctx: Ctx, user_id: int, block: str | None = None, amount: int | None = None) -> dict:
    """Sell blocks: everything, every block of one type, or `amount` of them (never more than the player has;
    without a type, the least valuable blocks go first). Returns {"sold": {type: amount}, "base": n,
    "bonus": n, "balance": n, "left": {type: amount}}."""
    user = get_user(ctx, user_id)
    blocks = get_blocks(ctx, user_id)
    if block is not None and block not in BLOCK_TYPES:
        raise GameError(f"Unknown block. You can sell: {', '.join(BLOCK_TYPES)}.")
    if amount is not None and amount <= 0:
        raise GameError("Sell at least 1 block.")
    order = [block] if block else sorted(BLOCK_TYPES, key=block_value)  # the cheapest first
    sold: dict[str, int] = {}
    wanted = amount
    for b in order:
        have = blocks.get(b, 0)
        n = have if wanted is None else min(have, wanted)
        if n > 0:
            sold[b] = n
            if wanted is not None:
                wanted -= n
                if wanted <= 0:
                    break
    base = sum(amt * block_value(b) for b, amt in sold.items())
    if not sold:
        raise GameError(f"You have no **{block}** to sell." if block else "You have no blocks to sell.")
    # Imported here: species depends on this module.
    from game import species

    from game import beacon  # beacon depends on this module

    golden = live_events.sell_bonus(ctx)  # a Golden Hour
    biome = biomes.multiplier(ctx, "sell") - 1.0  # the week's biome (can be a malus)
    from game import teams  # teams depends on this module

    biome += teams.chest_bonus(ctx, user_id, "trade")  # the team chest's Trade bonus
    extra = (trader_multiplier(user["trader_points"]) - 1.0 + species.bonus(ctx, user_id, "villager") + golden
             + beacon.sell_bonus(ctx, user_id) + biome + prestige_bonus(user))
    bonus = int(round(base * extra))  # below 0 when the biome's malus is bigger than the bonuses
    for b, n in sold.items():
        take_blocks(ctx, user_id, b, n)
    # The blocks' value was scored when they were mined: only the trader bonus is new.
    give_emeralds(ctx, user_id, base + min(0, bonus))
    earn_emeralds(ctx, user_id, bonus)
    bump_stat(ctx, user_id, "emeralds_from_sales", base + bonus)
    left = {b: n for b, n in get_blocks(ctx, user_id).items() if n > 0}
    return {"sold": sold, "base": base, "bonus": bonus, "golden": golden, "biome": biome,
            "balance": get_emeralds(ctx, user_id),
            "left": left}


def prestige_bonus(user: dict) -> float:
    """The permanent mining XP and /sell bonus of every prestige (game/prestige.py)."""
    return float(settings.get()["prestige"]["bonus"]) * int(user.get("prestige") or 0)


def prestige_stars(n: int) -> str:
    """'⭐⭐' for Prestige II, '⭐×4' from Prestige IV ('' without one)."""
    if n <= 0:
        return ""
    return "⭐" * n if n <= 3 else f"⭐×{n}"


def prestige_marks(ctx: Ctx, user_ids: list[int]) -> dict[int, str]:
    """user_id -> their prestige stars (players without a prestige are left out)."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = ctx.all(f"SELECT user_id, prestige FROM users WHERE prestige > 0 AND user_id IN ({','.join('?' * len(ids))});",
                   tuple(ids))
    return {r["user_id"]: prestige_stars(r["prestige"]) for r in rows}


def sell_all_blocks(ctx: Ctx, user_id: int) -> dict:
    """Sell every block."""
    return sell_blocks(ctx, user_id)


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
        name = {"stick": "stick(s)", "lapis": "lapis lazuli"}.get(item) or f"{material} {item}(s)"
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
    _stat_changed(ctx, user_id, stat, amount)


def _stat_changed(ctx: Ctx, user_id: int, stat: str, amount: int) -> None:
    # Imported here: progress depends on this module.
    from game import progress

    progress.on_stat(ctx, user_id, stat, amount)


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
    _stat_changed(ctx, user_id, stat, 0)


def get_stats(ctx: Ctx, user_id: int) -> dict[str, int]:
    rows = ctx.all("SELECT stat, value FROM stats WHERE user_id=?;", (user_id,))
    return {r["stat"]: r["value"] for r in rows}


def get_stat(ctx: Ctx, user_id: int, stat: str) -> int:
    row = ctx.one("SELECT value FROM stats WHERE user_id=? AND stat=?;", (user_id, stat))
    return row["value"] if row else 0


# ---------------- XP / levels ----------------
def xp_required_for_level(level: int) -> int:
    lv = settings.get()["levels"]
    return max(1, round(int(lv["xp_first_level"]) * float(lv["xp_growth_per_level"]) ** (max(1, level) - 1)))


def talent_points_for_level(level: int) -> int:
    return level // settings.get()["talents"]["points_every_levels"]


def _spent_talent_points(user: dict) -> int:
    return sum(user[f"{b}_points"] for b in TALENT_BRANCHES)


def add_xp(ctx: Ctx, user_id: int, amount: int, mending: bool = True) -> dict:
    """XP earned by playing. With Mending gear, it repairs that gear first (`mending=False`: the staff's XP).
    The player's row comes back with "mended": the XP Mending took."""
    mended = 0
    if mending and amount > 0:
        from game import gear  # here: gear depends on this module

        left = gear.mend(ctx, user_id, amount)
        mended, amount = amount - left, left
    user = get_user(ctx, user_id)
    if amount <= 0:
        return {**user, "mended": mended}
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
        _stat_changed(ctx, user_id, "level", 0)
    return {**get_user(ctx, user_id), "mended": mended}


def xp_text(xp: int, mended: int) -> str:
    """'+15 XP', or '+5 XP (🔧 10 XP repaired your gear: Mending)'."""
    if not mended:
        return f"+{xp} XP"
    return f"+{xp - mended} XP (🔧 {mended} XP repaired your gear: Mending)"


def set_xp(ctx: Ctx, user_id: int, xp: int) -> dict:
    """Staff: set the XP inside the current level (levels up if it overflows)."""
    ensure_user(ctx, user_id)
    ctx.execute("UPDATE users SET xp=0 WHERE user_id=?;", (user_id,))
    return add_xp(ctx, user_id, max(0, xp), mending=False)


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
        _stat_changed(ctx, user_id, "level", 0)
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


def talent_reset_cost(user: dict) -> int:
    """What /talent_reset costs: a price per spent point, never under the minimum."""
    t = settings.get()["talents"]
    return max(int(t["reset_cost_min"]), int(t["reset_cost_per_point"]) * _spent_talent_points(user))


def buy_talent_reset(ctx: Ctx, user_id: int) -> dict:
    """/talent_reset: the player pays to get every spent point back."""
    user = get_user(ctx, user_id)
    if not _spent_talent_points(user):
        raise GameError("You haven't spent any talent point: nothing to reset.")
    cost = talent_reset_cost(user)
    spend_emeralds(ctx, user_id, cost)
    bump_stat(ctx, user_id, "talent_resets")
    return {**reset_talents(ctx, user_id), "cost": cost}


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
