"""Bounties (/bounty): emeralds on a player's head, for whoever beats them.

- A player of at least bounty.min_level puts one of the fixed tiers (bounty.tiers) on another player of that
  level, never on themselves or a teammate, nor on someone who lost a bounty less than bounty.protection_hours
  ago. Bounties on the same player add up into one prize. The payer stays anonymous (only the staff log knows).
- Claimed by beating the target in a duel, a successful /rob on them, or the blow that makes them fall in a
  raid. Never by one of their teammates. The hunter takes everything on the target's head.
- Each bounty lasts bounty.days. Unclaimed, its payer gets it back minus bounty.refund_tax.
"""
from __future__ import annotations

from game import notices, players, settings, teams
from game.db import Ctx
from game.errors import GameError

HOUR, DAY = 3600, 86_400
VIA = {"duel": "a duel", "rob": "a robbery", "raid": "a raid"}


def _cfg() -> dict:
    return settings.get()["bounty"]


def tiers() -> list[int]:
    return [int(t) for t in _cfg()["tiers"]]


def teammates(ctx: Ctx, a: int, b: int) -> bool:
    ta, tb = teams.team_of(ctx, a), teams.team_of(ctx, b)
    return ta is not None and tb is not None and ta["team_id"] == tb["team_id"]


def on_head(ctx: Ctx, target_id: int) -> int:
    row = ctx.one("SELECT COALESCE(SUM(amount), 0) AS n FROM bounties WHERE target_id=? AND status='active';",
                  (target_id,))
    return int(row["n"])


def protected_until(ctx: Ctx, target_id: int) -> int:
    """A player whose bounty was just claimed is safe from new ones for a while (0 = not protected)."""
    row = ctx.one("SELECT MAX(ended_at) AS t FROM bounties WHERE target_id=? AND status='claimed';", (target_id,))
    if row["t"] is None:
        return 0
    until = int(row["t"] + float(_cfg()["protection_hours"]) * HOUR)
    return until if until > ctx.now else 0


def place(ctx: Ctx, payer_id: int, target_id: int, amount: int) -> dict:
    c = _cfg()
    if amount not in tiers():
        raise GameError("Pick one of the bounty tiers: " + " / ".join(f"**{t:,}**" for t in tiers()) + " emeralds.")
    if payer_id == target_id:
        raise GameError("You can't put a bounty on your own head.")
    need = int(c["min_level"])
    if players.get_user(ctx, payer_id)["level"] < need:
        raise GameError(f"You need to be level **{need}** to put a bounty.")
    if players.get_user(ctx, target_id)["level"] < need:
        raise GameError(f"<@{target_id}> is below level **{need}**: no bounty on them yet.")
    if teammates(ctx, payer_id, target_id):
        raise GameError("You can't put a bounty on a teammate.")
    from game import loans  # here: loans is only needed for this check

    loans.check_not_late(ctx, payer_id, "bounties")  # a friend claiming it would move a late borrower's wealth
    safe = protected_until(ctx, target_id)
    if safe:
        raise GameError(f"<@{target_id}> just lost a bounty: no new one on them before <t:{safe}:f>.")
    players.spend_emeralds(ctx, payer_id, amount)
    expires = int(ctx.now + float(c["days"]) * DAY)
    ctx.execute("INSERT INTO bounties(target_id, payer_id, amount, created_at, expires_at) VALUES(?, ?, ?, ?, ?);",
                (target_id, payer_id, amount, int(ctx.now), expires))
    players.bump_stat(ctx, payer_id, "bounties_placed")
    total = on_head(ctx, target_id)
    ctx.notices.append(notices.BountyPlaced(payer_id, target_id, amount, total, expires))
    return {"target_id": target_id, "amount": amount, "total": total, "expires_at": expires}


def claim(ctx: Ctx, hunter_id: int, target_id: int, via: str) -> dict | None:
    """The hunter beat the target (duel, robbery or raid): they take everything on the target's head."""
    if hunter_id == target_id or teammates(ctx, hunter_id, target_id):
        return None
    total = on_head(ctx, target_id)
    if total <= 0:
        return None
    ctx.execute("UPDATE bounties SET status='claimed', claimed_by=?, claimed_via=?, ended_at=? "
                "WHERE target_id=? AND status='active';", (hunter_id, via, int(ctx.now), target_id))
    players.give_emeralds(ctx, hunter_id, total)
    players.bump_stat(ctx, hunter_id, "bounties_claimed")
    players.bump_stat(ctx, hunter_id, "bounty_winnings", total)
    ctx.notices.append(notices.BountyClaimed(hunter_id, target_id, total, via))
    return {"hunter_id": hunter_id, "target_id": target_id, "amount": total, "via": via}


def expire(ctx: Ctx) -> list[dict]:
    """Called by a loop: bounties nobody claimed in time go back to their payers, minus the tax."""
    tax = float(_cfg()["refund_tax"])
    out = []
    for row in ctx.all("SELECT * FROM bounties WHERE status='active' AND expires_at <= ?;", (int(ctx.now),)):
        refund = int(row["amount"] * (1 - tax))
        ctx.execute("UPDATE bounties SET status='expired', ended_at=? WHERE bounty_id=?;", (int(ctx.now), row["bounty_id"]))
        players.give_emeralds(ctx, row["payer_id"], refund)
        ctx.notices.append(notices.BountyExpired(row["payer_id"], row["target_id"], row["amount"], refund))
        out.append({**dict(row), "refund": refund})
    return out


def board(ctx: Ctx) -> list[dict]:
    """Active bounties by target, the biggest prize first (payers never shown)."""
    rows = ctx.all(
        "SELECT target_id, SUM(amount) AS total, COUNT(*) AS n, MIN(expires_at) AS next_expiry "
        "FROM bounties WHERE status='active' GROUP BY target_id ORDER BY total DESC, target_id;")
    return [dict(r) for r in rows]


def mine(ctx: Ctx, user_id: int) -> dict:
    """What a player put on others' heads, and what is on theirs."""
    placed = [dict(r) for r in ctx.all(
        "SELECT target_id, amount, expires_at FROM bounties WHERE payer_id=? AND status='active' ORDER BY expires_at;",
        (user_id,))]
    return {"placed": placed, "on_head": on_head(ctx, user_id), "protected_until": protected_until(ctx, user_id)}


def cancel_all(ctx: Ctx, user_id: int | None = None) -> int:
    """Reset: active bounties are dropped, no refund (everyone's, or the ones this player put)."""
    if user_id is None:
        return ctx.execute("UPDATE bounties SET status='cancelled', ended_at=? WHERE status='active';",
                           (int(ctx.now),)).rowcount
    return ctx.execute("UPDATE bounties SET status='cancelled', ended_at=? WHERE status='active' AND payer_id=?;",
                       (int(ctx.now), user_id)).rowcount
