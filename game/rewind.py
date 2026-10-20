"""/blocky rewind_gear (staff): the 2.0 fresh start for gear.

Every piece of gear (weapons, armor, tools, shields, worn or spare, listed at the auction house or not) and every
netherite ingot is taken back and paid back in full: the ingots and sticks of its recipe at the market prices,
plus the enchanted books on it (netherite ingots at market.ingots.netherite). Repairs aren't paid back. The
refund is given, not earned: it doesn't count for the seasons. It can be done once only (a later netherite piece
is an upgraded diamond one: this refund would pay it far more than it cost).
"""
from __future__ import annotations

from game import assets, botstate, enchants, players, shop
from game.catalog import RECIPES
from game.db import Ctx
from game.errors import GameError

DONE_KEY = "gear_rewound_at"  # bot_state: when it was done (it's done once: the 2.0 fresh start)


def piece_refund(piece: dict) -> int:
    """What a piece was worth new: its recipe at the market prices and its books (a netherite piece made before
    the 2.0 was crafted with netherite ingots, like the others)."""
    ingots, sticks = RECIPES[piece["item"]]
    books = sum(shop.item_value("book", enchants.book_material(name, level)) for name, level in piece["enchants"].items())
    return round(ingots * shop.ingot_value(piece["material"]) + sticks * shop.stick_value() + books)


def _listing_refund(listing: dict) -> int | None:
    """What a listing gives back (None: it isn't gear or netherite and stays listed)."""
    key = listing["asset"]
    if assets.is_gear(key):
        parts = assets.parse(key)
        piece = {"item": parts[2], "material": parts[1], "enchants": assets.gear_enchants(key)}
        return piece_refund(piece) * int(listing["amount"])
    if key == "ingot:netherite":
        return shop.ingot_value("netherite") * int(listing["amount"])
    return None


def check_not_done(ctx: Ctx) -> None:
    """Once only: after it, netherite pieces are upgraded diamond ones, which this refund would overpay."""
    done = botstate.get(ctx, DONE_KEY)
    if done:
        raise GameError(f"The gear rewind was already done (<t:{done}:f>): it's the 2.0 fresh start, done once.")


def plan(ctx: Ctx) -> dict[int, dict]:
    """user_id -> {"pieces", "ingots", "listings", "emeralds"}: what the rewind would take and pay back."""
    check_not_done(ctx)
    out: dict[int, dict] = {}

    def entry(uid: int) -> dict:
        return out.setdefault(uid, {"pieces": 0, "ingots": 0, "listings": 0, "emeralds": 0})

    rows = enchants.attach(ctx, [dict(r) for r in ctx.all("SELECT * FROM gear;")])
    for piece in rows:
        e = entry(piece["user_id"])
        e["pieces"] += 1
        e["emeralds"] += piece_refund(piece)
    for r in ctx.all("SELECT user_id, amount FROM items WHERE item='ingot' AND material='netherite' AND amount > 0;"):
        e = entry(r["user_id"])
        e["ingots"] += r["amount"]
        e["emeralds"] += r["amount"] * shop.ingot_value("netherite")
    for r in ctx.all("SELECT * FROM auctions;"):
        refund = _listing_refund(dict(r))
        if refund is not None:
            e = entry(r["seller_id"])
            e["listings"] += 1
            e["emeralds"] += refund
    return out


def summary(refunds: dict[int, dict]) -> dict:
    return {
        "players": len(refunds),
        "pieces": sum(e["pieces"] for e in refunds.values()),
        "ingots": sum(e["ingots"] for e in refunds.values()),
        "listings": sum(e["listings"] for e in refunds.values()),
        "emeralds": sum(e["emeralds"] for e in refunds.values()),
    }


def apply(ctx: Ctx) -> dict[int, dict]:
    """Take every piece of gear and netherite ingot back and pay them back. Returns the plan that was applied."""
    refunds = plan(ctx)
    for r in ctx.all("SELECT * FROM auctions;"):
        if _listing_refund(dict(r)) is not None:
            ctx.execute("DELETE FROM auctions WHERE auction_id=?;", (r["auction_id"],))
    ctx.execute("DELETE FROM gear_enchants;")
    ctx.execute("DELETE FROM gear;")
    ctx.execute("DELETE FROM items WHERE item='ingot' AND material='netherite';")
    for uid, e in refunds.items():
        players.give_emeralds(ctx, uid, e["emeralds"])
    botstate.put(ctx, DONE_KEY, str(int(ctx.now)))
    return refunds
