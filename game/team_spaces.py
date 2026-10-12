"""Team spaces: a private Discord category per team, with channels its leader manages.

The leader unlocks it once (`teams.space_cost` emeralds). The Discord side (a team
role, the category and its channels) is made and kept in sync by the teams cog; this
module only keeps what was paid and which role and category belong to which team.
A space whose team is gone (disbanded, deleted by the staff) is cleaned up by the cog:
team ids are never reused, so it can't be confused with a new team.
"""
from __future__ import annotations

from game import players, settings, teams
from game.db import Ctx
from game.errors import GameError


def cost() -> int:
    return int(settings.get()["teams"]["space_cost"])


def max_channels() -> int:
    return int(settings.get()["teams"]["max_channels"])


def get(ctx: Ctx, team_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM team_spaces WHERE team_id=?;", (team_id,))
    return dict(row) if row else None


def check_unlock(ctx: Ctx, user_id: int) -> dict:
    """The leader's team, if it can unlock its space now (nothing is paid)."""
    team = teams._require_leader(ctx, user_id)
    if get(ctx, team["team_id"]) is not None:
        raise GameError("Your team already has its category.")
    price = cost()
    if players.get_emeralds(ctx, user_id) < price:
        raise GameError(f"Unlocking the team category costs **{price:,}** emeralds.")
    return team


def unlock(ctx: Ctx, user_id: int) -> dict:
    team = check_unlock(ctx, user_id)
    price = cost()
    players.spend_emeralds(ctx, user_id, price)
    ctx.execute("INSERT INTO team_spaces(team_id, payer_id, paid, unlocked_at) VALUES(?, ?, ?, ?);",
                (team["team_id"], user_id, price, int(ctx.now)))
    return {"team": team, "paid": price}


def refund(ctx: Ctx, team_id: int) -> int:
    """The Discord side couldn't be made: the space is cancelled and the payer refunded."""
    space = get(ctx, team_id)
    if space is None or space["category_id"]:
        return 0
    ctx.execute("DELETE FROM team_spaces WHERE team_id=?;", (team_id,))
    players.give_emeralds(ctx, space["payer_id"], space["paid"])
    return space["paid"]


def set_discord(ctx: Ctx, team_id: int, role_id: int | None, category_id: int | None) -> None:
    ctx.execute("UPDATE team_spaces SET role_id=?, category_id=? WHERE team_id=?;", (role_id, category_id, team_id))


def forget(ctx: Ctx, team_id: int) -> None:
    ctx.execute("DELETE FROM team_spaces WHERE team_id=?;", (team_id,))


def leader_space(ctx: Ctx, user_id: int) -> dict:
    """The leader's team and its space, for the channel commands."""
    team = teams._require_leader(ctx, user_id)
    space = get(ctx, team["team_id"])
    if space is None or not space["category_id"]:
        raise GameError(f"Your team has no category yet: unlock it with `/team category` ({cost():,} emeralds).")
    return {"team": team, "space": space}


def every(ctx: Ctx) -> list[dict]:
    """Every space with its team (None once the team is gone) and the members' ids."""
    out = []
    for row in ctx.all("SELECT * FROM team_spaces;"):
        space = dict(row)
        team = teams.get_team(ctx, space["team_id"])
        space["team"] = team
        space["members"] = [m["user_id"] for m in teams.members(ctx, team["team_id"])] if team else []
        out.append(space)
    return out
