"""/rewind_ingots (staff): the 2.2.1 new prices for ingots.

Ingots are worth far more since 2.2.1 (and drop far less). The ingots players hold were mined or bought at the old
prices: every ingot (in the inventory or listed at the auction house) is taken back and paid back at its OLD value
(gold 5, iron 10, diamond 60, netherite 300), and every netherite scrap at 70. The refund is given, not earned: it
doesn't count for the seasons. It can be done once only. The wandering villager's ingots still on sale get the new
prices too. Gear isn't touched.
"""
from __future__ import annotations

from game import assets, botstate, players, villager
from game.db import Ctx
from game.errors import GameError

DONE_KEY = "ingots_rewound_at"  # bot_state: when it was done (it's done once: the 2.2.1 new prices)
OLD_VALUES = {"gold": 5, "iron": 10, "diamond": 60, "netherite": 300}
SCRAP_VALUE = 70


def _unit_refund(key: str) -> int | None:
    """What one unit of an asset gives back (None: it isn't an ingot or a scrap)."""
    parts = assets.parse(key)
    if parts[0] == "ingot" and len(parts) == 2 and parts[1] in OLD_VALUES:
        return OLD_VALUES[parts[1]]
    if parts[0] == "scrap":
        return SCRAP_VALUE
    return None


def check_not_done(ctx: Ctx) -> None:
    done = botstate.get(ctx, DONE_KEY)
    if done:
        raise GameError(f"The ingot rewind was already done (<t:{done}:f>): it's done once.")


def plan(ctx: Ctx) -> dict[int, dict]:
    """user_id -> {"ingots", "scraps", "listings", "emeralds"}: what the rewind would take and pay back."""
    check_not_done(ctx)
    out: dict[int, dict] = {}

    def entry(uid: int) -> dict:
        return out.setdefault(uid, {"ingots": 0, "scraps": 0, "listings": 0, "emeralds": 0})

    for r in ctx.all("SELECT user_id, material, amount FROM items WHERE item='ingot' AND amount > 0;"):
        if r["material"] in OLD_VALUES:
            e = entry(r["user_id"])
            e["ingots"] += r["amount"]
            e["emeralds"] += r["amount"] * OLD_VALUES[r["material"]]
    for r in ctx.all("SELECT user_id, amount FROM items WHERE item='scrap' AND amount > 0;"):
        e = entry(r["user_id"])
        e["scraps"] += r["amount"]
        e["emeralds"] += r["amount"] * SCRAP_VALUE
    for r in ctx.all("SELECT seller_id, asset, amount FROM auctions;"):
        unit = _unit_refund(r["asset"])
        if unit is not None:
            e = entry(r["seller_id"])
            e["listings"] += 1
            e["emeralds"] += unit * int(r["amount"])
    return out


def summary(refunds: dict[int, dict]) -> dict:
    return {
        "players": len(refunds),
        "ingots": sum(e["ingots"] for e in refunds.values()),
        "scraps": sum(e["scraps"] for e in refunds.values()),
        "listings": sum(e["listings"] for e in refunds.values()),
        "emeralds": sum(e["emeralds"] for e in refunds.values()),
    }


def _reprice_villager(ctx: Ctx) -> None:
    """The ingots the villager still sells were priced at the old values: give them the new ones."""
    for r in ctx.all("SELECT * FROM villager_offers WHERE taken_by IS NULL AND kind='sell';"):
        if _unit_refund(r["asset"]) is not None:
            fresh = villager.priced(r["asset"], int(r["amount"]))
            ctx.execute("UPDATE villager_offers SET price=?, value=? WHERE visit_id=? AND slot=?;",
                        (fresh["price"], fresh["value"], r["visit_id"], r["slot"]))


def apply(ctx: Ctx) -> dict[int, dict]:
    """Take every ingot and scrap back and pay them back at the old values. Returns the plan that was applied."""
    refunds = plan(ctx)
    for r in ctx.all("SELECT auction_id, asset FROM auctions;"):
        if _unit_refund(r["asset"]) is not None:
            ctx.execute("DELETE FROM auctions WHERE auction_id=?;", (r["auction_id"],))
    ctx.execute(f"DELETE FROM items WHERE item='scrap' OR (item='ingot' AND material IN ({', '.join('?' * len(OLD_VALUES))}));",
                tuple(OLD_VALUES))
    for uid, e in refunds.items():
        players.give_emeralds(ctx, uid, e["emeralds"])
    _reprice_villager(ctx)
    botstate.put(ctx, DONE_KEY, str(int(ctx.now)))
    return refunds
