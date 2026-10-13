"""/reset: a fresh start for one player or the whole server, part by part.

What is never touched: Minecraft links, moderation (warnings, mutes, bans),
teams themselves, the settings, the closed seasons list (so old seasons are
never paid twice), bosses, tournaments, the villager and the Blockdle.
"""
from __future__ import annotations

from game.db import Ctx

PARTS: dict[str, str] = {
    "wealth": "Emeralds, blocks and items",  # + auction listings, robberies in progress, loans
    "gear": "Gear and enchantments",
    "levels": "Levels, XP and talents",
    "progress": "Stats, achievements and seasons",  # + challenges, team season scores, daily streak
}


def _where(column: str, user_id: int | None) -> tuple[str, tuple]:
    return ("", ()) if user_id is None else (f" WHERE {column}=?", (user_id,))


def apply(ctx: Ctx, parts: set[str] | list[str], user_id: int | None = None) -> dict:
    """Reset these parts for one player (`user_id`) or everyone (None). Returns what changed."""
    parts = set(parts)
    unknown = parts - set(PARTS)
    if unknown or not parts:
        raise ValueError(f"Unknown parts: {sorted(unknown) or 'none'}")
    where, args = _where("user_id", user_id)
    players = ctx.one(f"SELECT COUNT(*) AS n FROM users{where};", args)["n"]
    out: dict = {"players": players, "parts": sorted(parts)}

    if "wealth" in parts:
        ctx.execute(f"UPDATE users SET emeralds=0{where};", args)
        out["blocks"] = ctx.execute(f"DELETE FROM blocks{where};", args).rowcount
        out["items"] = ctx.execute(f"DELETE FROM items{where};", args).rowcount
        seller, seller_args = _where("seller_id", user_id)
        out["listings"] = ctx.execute(f"DELETE FROM auctions{seller};", seller_args).rowcount
        if user_id is None:
            ctx.execute("UPDATE robberies SET status='stopped' WHERE status='active';")
            out["loans"] = ctx.execute("DELETE FROM loans WHERE status IN ('active', 'late');").rowcount
            ctx.execute("DELETE FROM loan_offers WHERE status='open';")
        else:
            ctx.execute(
                "UPDATE robberies SET status='stopped' WHERE status='active' AND (thief_id=? OR victim_id=?);",
                (user_id, user_id),
            )
            # Their debts and the loans they gave are cancelled (emeralds are gone, nothing to pay back with).
            out["loans"] = ctx.execute(
                "DELETE FROM loans WHERE status IN ('active', 'late') AND (lender_id=? OR borrower_id=?);",
                (user_id, user_id),
            ).rowcount
            ctx.execute(
                "DELETE FROM loan_offers WHERE status='open' AND (lender_id=? OR borrower_id=?);", (user_id, user_id)
            )

    if "gear" in parts:
        ctx.execute(f"DELETE FROM gear_enchants WHERE gear_id IN (SELECT gear_id FROM gear{where});", args)
        out["gear"] = ctx.execute(f"DELETE FROM gear{where};", args).rowcount

    if "levels" in parts:
        ctx.execute(
            f"""
            UPDATE users SET level=1, xp=0, talent_points=0,
                miner_points=0, trader_points=0, lucky_points=0, efficiency_points=0{where};
            """,
            args,
        )

    if "progress" in parts:
        for table in ("stats", "achievements", "challenge_progress", "season_scores", "team_season_scores",
                      "dummy_scores"):
            ctx.execute(f"DELETE FROM {table}{where};", args)
        if user_id is None:
            # Past results only go for a whole-server fresh start: for one player, the champion of a past
            # week must stay who it was (the champion role follows the latest winner).
            ctx.execute("DELETE FROM season_results;")
            ctx.execute("DELETE FROM team_season_results;")
        # The guide checklist starts over (its steps are read from the stats).
        ctx.execute(f"UPDATE guides SET done='', completed_at=NULL{where};", args)
        # Rewards already paid (achievements, the guide) are only paid again after a reset of the emeralds too:
        # otherwise a player whose progress is reset would cash them in a second time.
        if "wealth" in parts:
            ctx.execute(f"DELETE FROM rewards_paid{where};", args)
            ctx.execute(f"UPDATE guides SET rewarded_at=NULL{where};", args)
        # Titles and earned frames worn without their condition anymore are taken off.
        from game import profiles  # imported here: profiles imports game modules that import this one

        targets = [user_id] if user_id is not None else [
            r["user_id"] for r in ctx.all("SELECT user_id FROM profiles WHERE title IS NOT NULL OR frame IS NOT NULL;")]
        for uid in targets:
            profiles.check_worn(ctx, uid)
        # The streak goes back to 0 but today's daily stays claimed (no free second claim).
        ctx.execute(f"UPDATE users SET daily_streak=0{where};", args)
    return out


def affected_users(ctx: Ctx, user_id: int | None = None) -> list[int]:
    if user_id is not None:
        return [user_id]
    return [r["user_id"] for r in ctx.all("SELECT user_id FROM users;")]
