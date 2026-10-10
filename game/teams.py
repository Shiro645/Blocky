"""Teams: small groups of players with a tag, a weekly team season and an XP bonus.

- Anyone can create a team and becomes its leader. The leader invites players
  (invitations expire), kicks members, hands over the lead, renames or disbands.
- Team season: a team's score is the emeralds its members earned while in the
  team this week. The rewards of the top teams are shared between the players
  who earned them, in proportion to what each one brought (so joining the
  leading team on Sunday is worth little).
- Team bonus: mining XP +X% for each other member who already mined today.
"""
from __future__ import annotations

import re

from game import players, seasons, settings
from game.db import Ctx
from game.errors import GameError

NAME_MIN, NAME_MAX = 3, 24
# Letters and digits (any language), plus spaces and a few harmless signs.
# No underscores, asterisks, backticks...: they would be read as Markdown.
_NAME_RE = re.compile(r"^[^\W_](?:[^\W_]|[ '\-.!?&])*$")
_TAG_RE = re.compile(r"^[A-Z0-9]{2,4}$")


def _cfg() -> dict:
    return settings.get()["teams"]


def max_members() -> int:
    return int(_cfg()["max_members"])


# ---------------- names ----------------
def clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise GameError(f"The team name must be {NAME_MIN} to {NAME_MAX} characters long.")
    if not _NAME_RE.match(name):
        raise GameError("The team name can only use letters, numbers, spaces and - ' . ! ? &")
    return name


def clean_tag(tag: str) -> str:
    tag = tag.strip().strip("[]").upper()
    if not _TAG_RE.match(tag):
        raise GameError("The tag must be 2 to 4 letters or numbers, e.g. **ABC**.")
    return tag


def _check_free(ctx: Ctx, name: str | None, tag: str | None, team_id: int = 0) -> None:
    if name is not None:
        row = ctx.one("SELECT name FROM teams WHERE name=? COLLATE NOCASE AND team_id != ?;", (name, team_id))
        if row:
            raise GameError(f"A team called **{row['name']}** already exists.")
    if tag is not None:
        row = ctx.one("SELECT name FROM teams WHERE tag=? COLLATE NOCASE AND team_id != ?;", (tag, team_id))
        if row:
            raise GameError(f"The tag **[{tag}]** is already used by **{row['name']}**.")


# ---------------- lookups ----------------
def get_team(ctx: Ctx, team_id: int) -> dict | None:
    row = ctx.one("SELECT * FROM teams WHERE team_id=?;", (team_id,))
    return dict(row) if row else None


def team_of(ctx: Ctx, user_id: int) -> dict | None:
    row = ctx.one(
        "SELECT t.* FROM team_members m JOIN teams t USING(team_id) WHERE m.user_id=?;",
        (user_id,),
    )
    return dict(row) if row else None


def find_team(ctx: Ctx, query: str) -> dict:
    """A team by tag ("ABC", "[ABC]") or by name, ignoring case."""
    text = " ".join(query.split())
    row = ctx.one(
        "SELECT * FROM teams WHERE tag=? COLLATE NOCASE OR name=? COLLATE NOCASE ORDER BY tag=? COLLATE NOCASE DESC;",
        (text.strip("[]"), text, text.strip("[]")),
    )
    if row is None:
        raise GameError(f"No team found for **{text}** (use its tag or its full name).")
    return dict(row)


def search(ctx: Ctx, text: str, limit: int = 25) -> list[dict]:
    """Teams whose tag or name contains `text` (for autocomplete)."""
    like = f"%{text.strip().strip('[]')}%"
    rows = ctx.all(
        "SELECT * FROM teams WHERE tag LIKE ? OR name LIKE ? ORDER BY name COLLATE NOCASE LIMIT ?;",
        (like, like, limit),
    )
    return [dict(r) for r in rows]


def members(ctx: Ctx, team_id: int) -> list[dict]:
    """Leader first, then by arrival."""
    rows = ctx.all(
        """
        SELECT m.user_id, m.joined_at, m.last_active, (m.user_id = t.leader_id) AS is_leader
        FROM team_members m JOIN teams t USING(team_id)
        WHERE m.team_id=? ORDER BY is_leader DESC, m.joined_at, m.user_id;
        """,
        (team_id,),
    )
    return [dict(r) for r in rows]


def member_count(ctx: Ctx, team_id: int) -> int:
    return ctx.one("SELECT COUNT(*) AS n FROM team_members WHERE team_id=?;", (team_id,))["n"]


def tags_of(ctx: Ctx, user_ids: list[int]) -> dict[int, str]:
    """user_id -> team tag, for the players who are in a team."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = ctx.all(
        f"SELECT m.user_id, t.tag FROM team_members m JOIN teams t USING(team_id) WHERE m.user_id IN ({marks});",
        tuple(ids),
    )
    return {r["user_id"]: r["tag"] for r in rows}


def _require_team(ctx: Ctx, user_id: int) -> dict:
    team = team_of(ctx, user_id)
    if team is None:
        raise GameError("You are not in a team. Create one with `/team create` or ask a leader for an invite.")
    return team


def _require_leader(ctx: Ctx, user_id: int) -> dict:
    team = _require_team(ctx, user_id)
    if team["leader_id"] != user_id:
        raise GameError(f"Only the leader of **[{team['tag']}] {team['name']}** (<@{team['leader_id']}>) can do that.")
    return team


def _require_member(ctx: Ctx, team: dict, user_id: int) -> None:
    row = ctx.one("SELECT team_id FROM team_members WHERE user_id=?;", (user_id,))
    if row is None or row["team_id"] != team["team_id"]:
        raise GameError(f"<@{user_id}> is not in your team.")


def _add_member(ctx: Ctx, team_id: int, user_id: int) -> None:
    players.ensure_user(ctx, user_id)
    ctx.execute(
        "INSERT INTO team_members(user_id, team_id, joined_at) VALUES(?, ?, ?);",
        (user_id, team_id, int(ctx.now)),
    )
    ctx.execute("DELETE FROM team_invites WHERE user_id=?;", (user_id,))


# ---------------- membership ----------------
def create(ctx: Ctx, user_id: int, name: str, tag: str) -> dict:
    name, tag = clean_name(name), clean_tag(tag)
    if team_of(ctx, user_id):
        raise GameError("You are already in a team. Leave it first with `/team leave`.")
    _check_free(ctx, name, tag)
    players.spend_emeralds(ctx, user_id, int(_cfg()["create_cost"]))
    cur = ctx.execute(
        "INSERT INTO teams(name, tag, leader_id, created_at) VALUES(?, ?, ?, ?);",
        (name, tag, user_id, int(ctx.now)),
    )
    _add_member(ctx, cur.lastrowid, user_id)
    return get_team(ctx, cur.lastrowid)  # type: ignore[return-value]


def invite(ctx: Ctx, leader_id: int, target_id: int) -> dict:
    team = _require_leader(ctx, leader_id)
    if target_id == leader_id:
        raise GameError("You are already in your team.")
    other = team_of(ctx, target_id)
    if other:
        raise GameError(f"<@{target_id}> is already in **[{other['tag']}] {other['name']}**.")
    count = member_count(ctx, team["team_id"])
    if count >= max_members():
        raise GameError(f"Your team is full ({count}/{max_members()}).")
    expires_at = int(ctx.now + float(_cfg()["invite_hours"]) * 3600)
    ctx.execute(
        """
        INSERT INTO team_invites(team_id, user_id, invited_by, expires_at) VALUES(?, ?, ?, ?)
        ON CONFLICT(team_id, user_id) DO UPDATE SET invited_by=excluded.invited_by, expires_at=excluded.expires_at;
        """,
        (team["team_id"], target_id, leader_id, expires_at),
    )
    return {"team": team, "members": count, "expires_at": expires_at}


def pending_invites(ctx: Ctx, user_id: int) -> list[dict]:
    rows = ctx.all(
        """
        SELECT t.*, i.invited_by, i.expires_at FROM team_invites i JOIN teams t USING(team_id)
        WHERE i.user_id=? AND i.expires_at > ? ORDER BY i.expires_at DESC;
        """,
        (user_id, int(ctx.now)),
    )
    return [dict(r) for r in rows]


def accept(ctx: Ctx, user_id: int, team_id: int) -> dict:
    """Join a team the player was invited to."""
    invite_row = ctx.one(
        "SELECT 1 FROM team_invites WHERE team_id=? AND user_id=? AND expires_at > ?;",
        (team_id, user_id, int(ctx.now)),
    )
    team = get_team(ctx, team_id)
    if invite_row is None or team is None:
        raise GameError("This invitation has expired or was cancelled. Ask the leader for a new one.")
    if team_of(ctx, user_id):
        raise GameError("You are already in a team. Leave it first with `/team leave`.")
    count = member_count(ctx, team_id)
    if count >= max_members():
        raise GameError(f"**[{team['tag']}] {team['name']}** is full ({count}/{max_members()}).")
    _add_member(ctx, team_id, user_id)
    return {"team": team, "members": count + 1}


def join(ctx: Ctx, user_id: int, query: str) -> dict:
    """/team join <tag or name>: accept a pending invitation."""
    return accept(ctx, user_id, find_team(ctx, query)["team_id"])


def decline(ctx: Ctx, user_id: int, team_id: int) -> bool:
    cur = ctx.execute("DELETE FROM team_invites WHERE team_id=? AND user_id=?;", (team_id, user_id))
    return cur.rowcount > 0


def leave(ctx: Ctx, user_id: int) -> dict:
    """Leave the team. A leaving leader hands the lead to the oldest member; the last one disbands it."""
    team = _require_team(ctx, user_id)
    ctx.execute("DELETE FROM team_members WHERE user_id=?;", (user_id,))
    result = {"team": team, "new_leader": None, "disbanded": False}
    if team["leader_id"] == user_id:
        rest = members(ctx, team["team_id"])
        if rest:
            result["new_leader"] = rest[0]["user_id"]
            ctx.execute("UPDATE teams SET leader_id=? WHERE team_id=?;", (rest[0]["user_id"], team["team_id"]))
        else:
            _drop_team(ctx, team)
            result["disbanded"] = True
    return result


def kick(ctx: Ctx, leader_id: int, target_id: int) -> dict:
    team = _require_leader(ctx, leader_id)
    if target_id == leader_id:
        raise GameError("You can't kick yourself: use `/team leave` or `/team disband`.")
    _require_member(ctx, team, target_id)
    ctx.execute("DELETE FROM team_members WHERE user_id=?;", (target_id,))
    return team


def transfer(ctx: Ctx, leader_id: int, target_id: int) -> dict:
    team = _require_leader(ctx, leader_id)
    if target_id == leader_id:
        raise GameError("You are already the leader.")
    _require_member(ctx, team, target_id)
    ctx.execute("UPDATE teams SET leader_id=? WHERE team_id=?;", (target_id, team["team_id"]))
    return team


def rename(ctx: Ctx, leader_id: int, name: str | None = None, tag: str | None = None) -> dict:
    team = _require_leader(ctx, leader_id)
    if name is None and tag is None:
        raise GameError("Give a new name, a new tag, or both.")
    new_name = clean_name(name) if name is not None else None
    new_tag = clean_tag(tag) if tag is not None else None
    _check_free(ctx, new_name, new_tag, team["team_id"])
    ctx.execute(
        "UPDATE teams SET name=?, tag=? WHERE team_id=?;",
        (new_name or team["name"], new_tag or team["tag"], team["team_id"]),
    )
    return {"before": team, "after": get_team(ctx, team["team_id"])}


def _drop_team(ctx: Ctx, team: dict) -> None:
    """Delete a team (members and invitations go with it).

    This week's score goes too (a team that no longer exists can't win the
    current week), but finished weeks waiting to be closed keep it: disbanding
    right after Sunday midnight must not take the reward away from the members.
    """
    ctx.execute(
        "INSERT OR REPLACE INTO team_archive(team_id, name, tag) VALUES(?, ?, ?);",
        (team["team_id"], team["name"], team["tag"]),
    )
    ctx.execute("DELETE FROM team_season_scores WHERE team_id=? AND season_id=?;", (team["team_id"], ctx.week_id))
    ctx.execute("DELETE FROM teams WHERE team_id=?;", (team["team_id"],))


def _delete(ctx: Ctx, team: dict) -> dict:
    team["members"] = [m["user_id"] for m in members(ctx, team["team_id"])]
    _drop_team(ctx, team)
    return team


def disband(ctx: Ctx, leader_id: int) -> dict:
    return _delete(ctx, _require_leader(ctx, leader_id))


def remove(ctx: Ctx, query: str) -> dict:
    """Staff: delete any team (offensive name...)."""
    return _delete(ctx, find_team(ctx, query))


# ---------------- team bonus ----------------
def activity_bonus(ctx: Ctx, user_id: int) -> float:
    """Mark the member as active today and return their mining XP bonus (0.1 = +10%)."""
    row = ctx.one("SELECT team_id FROM team_members WHERE user_id=?;", (user_id,))
    if row is None:
        return 0.0
    today = ctx.today.isoformat()
    ctx.execute("UPDATE team_members SET last_active=? WHERE user_id=?;", (today, user_id))
    others = ctx.one(
        "SELECT COUNT(*) AS n FROM team_members WHERE team_id=? AND last_active=? AND user_id != ?;",
        (row["team_id"], today, user_id),
    )["n"]
    return bonus_for(others + 1)


def bonus_for(active_members: int) -> float:
    """XP bonus of a member when `active_members` (them included) mined today."""
    cfg = _cfg()
    return max(0.0, min(float(cfg["max_xp_bonus"]), float(cfg["xp_bonus_per_active_member"]) * (active_members - 1)))


# ---------------- team season ----------------
def add_score(ctx: Ctx, user_id: int, amount: int) -> None:
    """Called by players.earn_emeralds: what a member earns counts for their team."""
    if amount <= 0:
        return
    row = ctx.one("SELECT team_id FROM team_members WHERE user_id=?;", (user_id,))
    if row is None:
        return
    ctx.execute(
        """
        INSERT INTO team_season_scores(season_id, team_id, user_id, score) VALUES(?, ?, ?, ?)
        ON CONFLICT(season_id, team_id, user_id) DO UPDATE SET score = score + excluded.score;
        """,
        (ctx.week_id, row["team_id"], user_id, amount),
    )


def standings(ctx: Ctx, season_id: str) -> list[dict]:
    rows = ctx.all(
        """
        SELECT s.team_id, COALESCE(t.name, a.name) AS name, COALESCE(t.tag, a.tag) AS tag, SUM(s.score) AS score
        FROM team_season_scores s
        LEFT JOIN teams t USING(team_id)
        LEFT JOIN team_archive a USING(team_id)
        WHERE s.season_id=? AND COALESCE(t.name, a.name) IS NOT NULL
        GROUP BY s.team_id HAVING SUM(s.score) > 0
        ORDER BY score DESC, s.team_id;
        """,
        (season_id,),
    )
    return [dict(r) for r in rows]


def contributions(ctx: Ctx, season_id: str, team_id: int) -> list[tuple[int, int]]:
    """[(user_id, emeralds earned for the team)], best first. Includes players who left since."""
    rows = ctx.all(
        """
        SELECT user_id, score FROM team_season_scores
        WHERE season_id=? AND team_id=? AND score > 0 ORDER BY score DESC, user_id;
        """,
        (season_id, team_id),
    )
    return [(r["user_id"], r["score"]) for r in rows]


def split_reward(reward: int, shares: list[tuple[int, int]]) -> dict[int, int]:
    """Share `reward` in proportion to the scores; leftovers go to the best contributors."""
    total = sum(score for _, score in shares)
    if reward <= 0 or total <= 0:
        return {}
    out = {uid: reward * score // total for uid, score in shares}
    left = reward - sum(out.values())
    for uid, _ in sorted(shares, key=lambda s: (-s[1], s[0]))[:left]:
        out[uid] += 1
    return out


def season_rewards() -> list[int]:
    return [int(r) for r in _cfg()["season_rewards"]]


def close_finished(ctx: Ctx) -> list[dict]:
    """Close every past team season not closed yet: share the rewards of the top teams."""
    rewards = season_rewards()
    rows = ctx.all(
        """
        SELECT DISTINCT season_id FROM team_season_scores
        WHERE season_id < ? AND season_id NOT IN (SELECT season_id FROM team_seasons_closed)
        ORDER BY season_id;
        """,
        (ctx.week_id,),
    )
    closed = []
    for r in rows:
        season_id = r["season_id"]
        podium = []
        for rank, team in enumerate(standings(ctx, season_id)[: len(rewards)], start=1):
            reward = rewards[rank - 1]
            shares = contributions(ctx, season_id, team["team_id"])
            payout = split_reward(reward, shares)
            for uid, amount in payout.items():
                # Not "earned": the reward must not count for the new season.
                players.give_emeralds(ctx, uid, amount)
            if rank == 1:
                for uid, _ in shares:
                    players.bump_stat(ctx, uid, "team_seasons_won")
            ctx.execute(
                """
                INSERT INTO team_season_results(season_id, rank, team_id, name, tag, score, reward)
                VALUES(?, ?, ?, ?, ?, ?, ?);
                """,
                (season_id, rank, team["team_id"], team["name"], team["tag"], team["score"], reward),
            )
            podium.append({
                "rank": rank, "team_id": team["team_id"], "name": team["name"], "tag": team["tag"],
                "score": team["score"], "reward": reward,
                "payout": sorted(payout.items(), key=lambda p: (-p[1], p[0])),
            })
        ctx.execute(
            "INSERT INTO team_seasons_closed(season_id, closed_at) VALUES(?, ?);", (season_id, int(ctx.now))
        )
        closed.append({"season_id": season_id, "podium": podium})
    return closed


def last_winner(ctx: Ctx) -> dict | None:
    row = ctx.one("SELECT * FROM team_season_results WHERE rank=1 ORDER BY season_id DESC LIMIT 1;")
    return dict(row) if row else None


# ---------------- overviews ----------------
def overview(ctx: Ctx, team_id: int) -> dict:
    """Everything /team info shows."""
    team = get_team(ctx, team_id)
    if team is None:
        raise GameError("This team no longer exists.")
    week = ctx.week_id
    earned = dict(contributions(ctx, week, team_id))
    today = ctx.today.isoformat()
    rows = members(ctx, team_id)
    for m in rows:
        m["score"] = earned.get(m["user_id"], 0)
        m["active"] = m["last_active"] == today
    table = standings(ctx, week)
    rank = next((i for i, t in enumerate(table, start=1) if t["team_id"] == team_id), None)
    active = sum(1 for m in rows if m["active"])
    wins = ctx.one("SELECT COUNT(*) AS n FROM team_season_results WHERE team_id=? AND rank=1;", (team_id,))["n"]
    return {
        "team": team,
        "members": rows,
        "max_members": max_members(),
        "rank": rank,
        "teams_ranked": len(table),
        "score": table[rank - 1]["score"] if rank else 0,
        "active_today": active,
        "bonus": bonus_for(active) if active else 0.0,
        "wins": wins,
        "ends_at": seasons.season_end(ctx),
    }


def season_overview(ctx: Ctx, user_id: int, limit: int = 10) -> dict:
    """Everything /team top shows."""
    table = standings(ctx, ctx.week_id)
    mine = team_of(ctx, user_id)
    rank = None
    if mine:
        rank = next((i for i, t in enumerate(table, start=1) if t["team_id"] == mine["team_id"]), None)
    return {
        "season_id": ctx.week_id,
        "ends_at": seasons.season_end(ctx),
        "top": table[:limit],
        "team": mine,
        "rank": rank,
        "score": table[rank - 1]["score"] if rank else 0,
        "rewards": season_rewards(),
        "last_winner": last_winner(ctx),
    }
