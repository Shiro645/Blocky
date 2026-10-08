"""Player to player economy: payments, trades and the auction house.

Emeralds moving between players never count as "earned", so they don't
inflate the weekly season score.
"""
from __future__ import annotations

from game import assets, players, settings
from game.db import Ctx
from game.errors import GameError

DAY = 86400


# ---------------- pay ----------------
def pay(ctx: Ctx, from_id: int, to_id: int, amount: int) -> dict:
    if from_id == to_id:
        raise GameError("You can't pay yourself.")
    minimum = int(settings.get()["pay"]["min_amount"])
    if amount < minimum:
        raise GameError(f"The minimum payment is **{minimum}** emeralds.")
    players.spend_emeralds(ctx, from_id, amount)
    players.give_emeralds(ctx, to_id, amount)
    players.bump_stat(ctx, from_id, "emeralds_sent", amount)
    return {"balance": players.get_emeralds(ctx, from_id)}


# ---------------- trade ----------------
def check_owns(ctx: Ctx, user_id: int, key: str, amount: int) -> None:
    """Raise GameError if the player doesn't have `amount` of `key` (nothing is moved)."""
    assets.parse(key)
    if amount <= 0:
        raise GameError("Amounts must be greater than 0.")
    if assets.is_gear(key) and amount != 1:
        raise GameError("Gear can only be traded one piece at a time.")
    have = dict(assets.owned(ctx, user_id)).get(key, 0)
    if have < amount:
        raise GameError(f"<@{user_id}> doesn't have **{assets.describe(key, amount)}** (has {have}).")


def trade(ctx: Ctx, a_id: int, b_id: int, a_key: str, a_amount: int, b_key: str | None, b_amount: int) -> None:
    """A gives `a_amount` of `a_key` to B, and B gives `b_amount` of `b_key` to A (if any)."""
    if a_id == b_id:
        raise GameError("You can't trade with yourself.")
    check_owns(ctx, a_id, a_key, a_amount)
    if b_key:
        check_owns(ctx, b_id, b_key, b_amount)
    assets.transfer(ctx, a_id, b_id, a_key, a_amount)
    if b_key:
        assets.transfer(ctx, b_id, a_id, b_key, b_amount)
    players.bump_stat(ctx, a_id, "trades_completed")
    players.bump_stat(ctx, b_id, "trades_completed")


# ---------------- auction house ----------------
def tax_for(price: int) -> int:
    return price * int(settings.get()["auction"]["tax_percent"]) // 100


def list_for_sale(ctx: Ctx, seller_id: int, key: str, amount: int, price: int) -> dict:
    a = settings.get()["auction"]
    if key == "emeralds":
        raise GameError("You can't sell emeralds for emeralds.")
    if price <= 0:
        raise GameError("The price must be greater than 0.")
    count = ctx.one("SELECT COUNT(*) AS n FROM auctions WHERE seller_id=?;", (seller_id,))["n"]
    if count >= int(a["max_listings"]):
        raise GameError(f"You can't have more than **{a['max_listings']}** listings at once.")
    piece = assets.take(ctx, seller_id, key, amount)
    cur = ctx.execute(
        """
        INSERT INTO auctions(seller_id, asset, amount, durability, max_durability, price, created_at, expires_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            seller_id, key, amount,
            piece["durability"] if piece else None,
            piece["max_durability"] if piece else None,
            price, int(ctx.now), int(ctx.now + int(a["duration_days"]) * DAY),
        ),
    )
    return get_listing(ctx, int(cur.lastrowid))


def get_listing(ctx: Ctx, auction_id: int) -> dict:
    row = ctx.one("SELECT * FROM auctions WHERE auction_id=?;", (auction_id,))
    if row is None:
        raise GameError(f"Listing **#{auction_id}** doesn't exist (already sold or removed?).")
    return dict(row)


def _return_to_seller(ctx: Ctx, listing: dict) -> None:
    assets.give(ctx, listing["seller_id"], listing["asset"], listing["amount"], durability=listing["durability"])
    ctx.execute("DELETE FROM auctions WHERE auction_id=?;", (listing["auction_id"],))


def buy(ctx: Ctx, buyer_id: int, auction_id: int) -> dict:
    listing = get_listing(ctx, auction_id)
    if listing["seller_id"] == buyer_id:
        raise GameError("That's your own listing. Use `/auction cancel` to take it back.")
    players.spend_emeralds(ctx, buyer_id, listing["price"])
    tax = tax_for(listing["price"])
    players.give_emeralds(ctx, listing["seller_id"], listing["price"] - tax)
    assets.give(ctx, buyer_id, listing["asset"], listing["amount"], durability=listing["durability"])
    ctx.execute("DELETE FROM auctions WHERE auction_id=?;", (auction_id,))
    players.bump_stat(ctx, listing["seller_id"], "auction_sales")
    players.bump_stat(ctx, buyer_id, "auction_purchases")
    return {**listing, "tax": tax, "balance": players.get_emeralds(ctx, buyer_id)}


def cancel(ctx: Ctx, user_id: int, auction_id: int) -> dict:
    listing = get_listing(ctx, auction_id)
    if listing["seller_id"] != user_id:
        raise GameError("This isn't your listing.")
    _return_to_seller(ctx, listing)
    return listing


def expire(ctx: Ctx) -> list[dict]:
    """Give expired listings back to their sellers."""
    rows = [dict(r) for r in ctx.all("SELECT * FROM auctions WHERE expires_at <= ?;", (int(ctx.now),))]
    for listing in rows:
        _return_to_seller(ctx, listing)
    return rows


def browse(ctx: Ctx, search: str = "", page: int = 1, per_page: int = 10) -> dict:
    rows = [dict(r) for r in ctx.all("SELECT * FROM auctions ORDER BY created_at DESC, auction_id DESC;")]
    if search:
        s = search.lower()
        rows = [r for r in rows if s in assets.describe(r["asset"]).lower()]
    pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    return {"rows": rows[(page - 1) * per_page: page * per_page], "page": page, "pages": pages, "total": len(rows)}


def listings_of(ctx: Ctx, seller_id: int) -> list[dict]:
    return [dict(r) for r in ctx.all("SELECT * FROM auctions WHERE seller_id=? ORDER BY auction_id;", (seller_id,))]
