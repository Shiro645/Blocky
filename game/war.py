"""Gang wars: the teams' chests, the weekly war and the raids.

- Team chest (/team chest): members put emeralds in, only the leader takes them out. A personal /rob can't
  reach it, but other teams can raid it.
- The weekly war (Monday to Sunday) is automatic: every team of at least war.min_members fights every other one.
  Each Monday war.levy of every chest goes into the week's pot. Points: a duel won against a member of another
  team (a few a day per pair at most), a successful /rob on one (and stopping one), a raid won or pushed back.
  When the week ends, the top teams share the pot (war.prizes, after war.tax), paid into their chests.
- Raids (/team raid): a member opens one against another team, 2 to 4 members of their team gather, then the
  target's members have a while to come and defend. Then the attackers and the defenders fight it out (like
  duels, all at once). Attackers win, or nobody defended: they take war.raid_steal of the chest. No raid at
  night (like /rob), one raid a day per team, and a raided chest is safe for a day.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass

from game import botstate, bounty, duel, gear, players, robbery, settings, teams
from game.catalog import ARMOR
from game.db import Ctx
from game.errors import GameError

MINUTE, HOUR = 60, 3600


def _cfg() -> dict:
    return settings.get()["war"]


# ---------------- the chest ----------------
def chest(ctx: Ctx, team_id: int) -> int:
    row = ctx.one("SELECT chest FROM teams WHERE team_id=?;", (team_id,))
    return int(row["chest"]) if row else 0


def deposit(ctx: Ctx, user_id: int, amount: int) -> dict:
    team = teams.team_of(ctx, user_id)
    if team is None:
        raise GameError("You're not in a team.")
    if amount <= 0:
        raise GameError("Put at least 1 emerald.")
    players.spend_emeralds(ctx, user_id, amount)
    ctx.execute("UPDATE teams SET chest = chest + ? WHERE team_id=?;", (amount, team["team_id"]))
    players.bump_stat(ctx, user_id, "chest_deposits", amount)
    return {"team": team, "amount": amount, "chest": chest(ctx, team["team_id"])}


def withdraw(ctx: Ctx, user_id: int, amount: int) -> dict:
    team = teams.team_of(ctx, user_id)
    if team is None or team["leader_id"] != user_id:
        raise GameError("Only your team's leader can take emeralds out of the chest.")
    if amount <= 0:
        raise GameError("Take at least 1 emerald.")
    have = chest(ctx, team["team_id"])
    if amount > have:
        raise GameError(f"The chest only holds **{have:,}** emeralds.")
    ctx.execute("UPDATE teams SET chest = chest - ? WHERE team_id=?;", (amount, team["team_id"]))
    players.give_emeralds(ctx, user_id, amount)
    return {"team": team, "amount": amount, "chest": chest(ctx, team["team_id"])}


def set_chest(ctx: Ctx, team_id: int, amount: int) -> None:
    """Staff: set a chest."""
    ctx.execute("UPDATE teams SET chest=? WHERE team_id=?;", (max(0, amount), team_id))


# ---------------- the war ----------------
def at_war(ctx: Ctx, team_id: int) -> bool:
    return teams.member_count(ctx, team_id) >= int(_cfg()["min_members"])


def _war_team(ctx: Ctx, user_id: int) -> dict | None:
    team = teams.team_of(ctx, user_id)
    return team if team and at_war(ctx, team["team_id"]) else None


def enemies(ctx: Ctx, a: int, b: int) -> tuple[dict, dict] | None:
    """The two players' teams when both are at war against each other (different teams)."""
    ta, tb = _war_team(ctx, a), _war_team(ctx, b)
    if ta is None or tb is None or ta["team_id"] == tb["team_id"]:
        return None
    return ta, tb


def add_points(ctx: Ctx, team_id: int, reason: str, user_id: int | None = None, other_id: int | None = None) -> int:
    points = int(_cfg()["points"][reason])
    if points <= 0:
        return 0
    ctx.execute(
        "INSERT INTO war_points(week_id, team_id, user_id, other_id, reason, points, day, at) VALUES(?, ?, ?, ?, ?, ?, ?, ?);",
        (ctx.week_id, team_id, user_id, other_id, reason, points, ctx.today.isoformat(), int(ctx.now)),
    )
    if user_id:
        players.bump_stat(ctx, user_id, "war_points", points)
    return points


def on_duel(ctx: Ctx, winner_id: int, loser_id: int) -> int:
    """A duel won against an enemy: points, a few a day for the same pair."""
    pair = enemies(ctx, winner_id, loser_id)
    if pair is None:
        return 0
    done = ctx.one(
        "SELECT COUNT(*) AS n FROM war_points WHERE reason='duel' AND user_id=? AND other_id=? AND day=?;",
        (winner_id, loser_id, ctx.today.isoformat()),
    )["n"]
    if done >= int(_cfg()["duel_pair_cap"]):
        return 0
    return add_points(ctx, pair[0]["team_id"], "duel", winner_id, loser_id)


def on_rob(ctx: Ctx, rob: dict) -> int:
    """A robbery between enemies: done = the thief's team scores, stopped = the victim's."""
    pair = enemies(ctx, rob["thief_id"], rob["victim_id"])
    if pair is None:
        return 0
    if rob["status"] == "done" and rob.get("stolen"):
        return add_points(ctx, pair[0]["team_id"], "rob", rob["thief_id"], rob["victim_id"])
    if rob["status"] == "stopped":
        return add_points(ctx, pair[1]["team_id"], "rob_stopped", rob["victim_id"], rob["thief_id"])
    return 0


def _week(ctx: Ctx, week_id: str) -> dict:
    ctx.execute("INSERT OR IGNORE INTO war_weeks(week_id) VALUES(?);", (week_id,))
    return dict(ctx.one("SELECT * FROM war_weeks WHERE week_id=?;", (week_id,)))


def standings(ctx: Ctx, week_id: str | None = None) -> list[dict]:
    """Teams at war with their points this week, best first (teams still there)."""
    week_id = week_id or ctx.week_id
    rows = ctx.all(
        """
        SELECT t.team_id, t.name, t.tag, t.chest, COALESCE(SUM(p.points), 0) AS points
        FROM teams t LEFT JOIN war_points p ON p.team_id = t.team_id AND p.week_id = ?
        GROUP BY t.team_id ORDER BY points DESC, t.team_id;
        """,
        (week_id,),
    )
    return [dict(r) for r in rows if at_war(ctx, r["team_id"]) or r["points"]]


def overview(ctx: Ctx) -> dict:
    week = _week(ctx, ctx.week_id)
    feats = [dict(r) for r in ctx.all(
        "SELECT p.*, t.tag FROM war_points p LEFT JOIN teams t ON t.team_id = p.team_id "
        "WHERE p.week_id=? ORDER BY p.at DESC LIMIT 8;", (ctx.week_id,))]
    return {"pot": week["pot"], "standings": standings(ctx), "feats": feats}


def weekly(ctx: Ctx) -> dict | None:
    """Once a week: settle the week that ended (the podium shares the pot) and take this week's levy."""
    last = botstate.get(ctx, "war_week")
    if last == ctx.week_id:
        return None
    c = _cfg()
    podium = []
    if last is not None:
        week = _week(ctx, last)
        if week["settled_at"] is None:
            ranked = [t for t in standings(ctx, last) if t["points"] > 0][: len(c["prizes"])]
            share = week["pot"] * (1 - float(c["tax"]))
            for place, (team, prize) in enumerate(zip(ranked, c["prizes"]), start=1):
                paid = int(share * float(prize))
                ctx.execute("UPDATE teams SET chest = chest + ? WHERE team_id=?;", (paid, team["team_id"]))
                podium.append({**team, "place": place, "paid": paid})
                if place == 1:
                    for m in teams.members(ctx, team["team_id"]):
                        players.bump_stat(ctx, m["user_id"], "wars_won")
            ctx.execute("UPDATE war_weeks SET settled_at=?, results=? WHERE week_id=?;",
                        (int(ctx.now), json.dumps(podium), last))
    # This week's pot: a share of every chest of the teams at war.
    pot = 0
    for t in ctx.all("SELECT team_id, chest FROM teams;"):
        if at_war(ctx, t["team_id"]):
            take = int(t["chest"] * float(c["levy"]))
            if take > 0:
                ctx.execute("UPDATE teams SET chest = chest - ? WHERE team_id=?;", (take, t["team_id"]))
                pot += take
    _week(ctx, ctx.week_id)
    ctx.execute("UPDATE war_weeks SET pot = pot + ? WHERE week_id=?;", (pot, ctx.week_id))
    botstate.put(ctx, "war_week", ctx.week_id)
    return {"settled": last, "podium": podium, "pot": pot}


# ---------------- raids ----------------
def get_raid(ctx: Ctx, raid_id: int) -> dict:
    row = ctx.one("SELECT * FROM raids WHERE raid_id=?;", (raid_id,))
    if row is None:
        raise GameError("This raid doesn't exist anymore.")
    out = dict(row)
    members = ctx.all("SELECT user_id, side FROM raid_members WHERE raid_id=? ORDER BY joined_at, rowid;", (raid_id,))
    out["attackers"] = [m["user_id"] for m in members if m["side"] == "attack"]
    out["defenders"] = [m["user_id"] for m in members if m["side"] == "defend"]
    out["log"] = json.loads(row["log"]) if row["log"] else []
    out["attacker"] = teams.get_team(ctx, row["attacker_team"])
    out["defender"] = teams.get_team(ctx, row["defender_team"])
    return out


def _open_raid_of(ctx: Ctx, user_id: int) -> int | None:
    row = ctx.one(
        "SELECT r.raid_id FROM raids r JOIN raid_members m ON m.raid_id = r.raid_id "
        "WHERE m.user_id=? AND r.status IN ('gathering', 'defending');", (user_id,))
    return int(row["raid_id"]) if row else None


def protected_until(ctx: Ctx, team_id: int) -> int:
    row = ctx.one("SELECT MAX(deadline) AS t FROM raids WHERE defender_team=? AND status='won';", (team_id,))
    until = int((row["t"] or 0) + float(_cfg()["raid_protection_hours"]) * HOUR)
    return until if until > ctx.now else 0


def start_raid(ctx: Ctx, user_id: int, target_query: str) -> dict:
    c = _cfg()
    team = _war_team(ctx, user_id)
    if team is None:
        raise GameError(f"Raids are for teams at war: a team of at least {c['min_members']} members.")
    target = teams.find_team(ctx, target_query)
    if target["team_id"] == team["team_id"]:
        raise GameError("You can't raid your own team.")
    if not at_war(ctx, target["team_id"]):
        raise GameError(f"**{target['name']}** isn't at war (fewer than {c['min_members']} members).")
    opens = robbery.closed_until(ctx)
    if opens is not None:
        raise GameError(f"Everyone is asleep: no raids at night. Try again <t:{opens}:R>.")
    busy = ctx.one(
        "SELECT 1 FROM raids WHERE status IN ('gathering', 'defending') "
        "AND (attacker_team IN (?, ?) OR defender_team IN (?, ?));",
        (team["team_id"], target["team_id"], team["team_id"], target["team_id"]),
    )
    if busy:
        raise GameError("One of the two teams is already in a raid.")
    day_start = int(ctx.local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    launched = ctx.one("SELECT COUNT(*) AS n FROM raids WHERE attacker_team=? AND status NOT IN ('gathering', 'cancelled') "
                       "AND created_at >= ?;", (team["team_id"], day_start))["n"]
    if launched >= int(c["raids_per_day"]):
        raise GameError("Your team already raided today. Come back tomorrow.")
    safe = protected_until(ctx, target["team_id"])
    if safe:
        raise GameError(f"**{target['name']}**'s chest was raided recently: it's safe until <t:{safe}:f>.")
    cur = ctx.execute(
        "INSERT INTO raids(attacker_team, defender_team, leader_id, created_at, deadline) VALUES(?, ?, ?, ?, ?);",
        (team["team_id"], target["team_id"], user_id, int(ctx.now), int(ctx.now + float(c["raid_gather_minutes"]) * MINUTE)),
    )
    raid_id = int(cur.lastrowid)
    ctx.execute("INSERT INTO raid_members(raid_id, user_id, side, joined_at) VALUES(?, ?, 'attack', ?);",
                (raid_id, user_id, int(ctx.now)))
    return get_raid(ctx, raid_id)


def set_raid_message(ctx: Ctx, raid_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE raids SET channel_id=?, message_id=? WHERE raid_id=?;", (channel_id, message_id, raid_id))


def join_raid(ctx: Ctx, raid_id: int, user_id: int) -> dict:
    """An attacker joins while the raid gathers, or a defender comes while it's announced."""
    c = _cfg()
    raid = get_raid(ctx, raid_id)
    team = teams.team_of(ctx, user_id)
    tid = team["team_id"] if team else None
    if user_id in raid["attackers"] + raid["defenders"]:
        raise GameError("You're already in this raid.")
    if _open_raid_of(ctx, user_id):
        raise GameError("You're already in another raid.")
    if raid["status"] == "gathering":
        if tid != raid["attacker_team"]:
            raise GameError("Only the raiding team's members can join now.")
        if len(raid["attackers"]) >= int(c["raid_max_attackers"]):
            raise GameError(f"The raid party is full ({c['raid_max_attackers']}).")
        side = "attack"
    elif raid["status"] == "defending":
        if tid != raid["defender_team"]:
            raise GameError("Only the defending team's members can defend their chest.")
        if len(raid["defenders"]) >= int(c["raid_max_defenders"]):
            raise GameError(f"There are already {c['raid_max_defenders']} defenders.")
        side = "defend"
    else:
        raise GameError("This raid is over.")
    ctx.execute("INSERT INTO raid_members(raid_id, user_id, side, joined_at) VALUES(?, ?, ?, ?);",
                (raid_id, user_id, side, int(ctx.now)))
    return get_raid(ctx, raid_id)


def leave_raid(ctx: Ctx, raid_id: int, user_id: int) -> dict:
    raid = get_raid(ctx, raid_id)
    if raid["status"] != "gathering" or user_id not in raid["attackers"]:
        raise GameError("You can only leave a raid party while it gathers.")
    if user_id == raid["leader_id"]:
        ctx.execute("UPDATE raids SET status='cancelled' WHERE raid_id=?;", (raid_id,))
    else:
        ctx.execute("DELETE FROM raid_members WHERE raid_id=? AND user_id=?;", (raid_id, user_id))
    return get_raid(ctx, raid_id)


def launch_raid(ctx: Ctx, raid_id: int, user_id: int | None) -> dict:
    """The party leaves (the leader clicks Launch, or the gathering time is up): the defenders are called."""
    c = _cfg()
    raid = get_raid(ctx, raid_id)
    if raid["status"] != "gathering":
        raise GameError("This raid already left.")
    if user_id is not None and user_id != raid["leader_id"]:
        raise GameError("Only the raid's leader launches it.")
    if len(raid["attackers"]) < int(c["raid_min_attackers"]):
        if user_id is not None:
            raise GameError(f"A raid needs at least {c['raid_min_attackers']} attackers.")
        ctx.execute("UPDATE raids SET status='cancelled' WHERE raid_id=?;", (raid_id,))
        return get_raid(ctx, raid_id)
    ctx.execute("UPDATE raids SET status='defending', deadline=? WHERE raid_id=?;",
                (int(ctx.now + float(c["raid_defend_minutes"]) * MINUTE), raid_id))
    return {**get_raid(ctx, raid_id), "launched": True}


@dataclass
class Raider:
    user_id: int
    side: str
    attack: float
    min_attack: float
    reduction: float
    hp: float
    attacks: int = 0
    hits_taken: int = 0
    gear_ids: dict | None = None
    downed_by: int | None = None  # who dealt the blow that made them fall (bounties)


def fight(rng: random.Random, attackers: list[Raider], defenders: list[Raider]) -> tuple[str, list[str]]:
    """Both sides strike at once each round, every fighter on a random enemy still standing.
    Returns the winning side ("attack" / "defend") and the story."""
    d = settings.get()["duel"]
    log: list[str] = []
    for rnd in range(1, int(_cfg()["raid_max_rounds"]) + 1):
        hits = []
        for side, foes in ((attackers, defenders), (defenders, attackers)):
            for f in side:
                alive = [x for x in foes if x.hp > 0]
                if f.hp <= 0 or not alive:
                    continue
                target = rng.choice(alive)
                f.attacks += 1
                dmg = rng.uniform(min(f.min_attack, f.attack), f.attack)
                if rng.random() < float(d["crit_chance"]):
                    dmg *= float(d["crit_multiplier"])
                dmg = max(float(d["min_hit_after_armor"]), dmg * (1 - target.reduction))
                hits.append((f, target, dmg))
        for f, target, dmg in hits:  # at once: a fighter falling this round still strikes
            if target.hp > 0 and target.hp - dmg <= 0:
                target.downed_by = f.user_id
            target.hp = max(0.0, target.hp - dmg)
            target.hits_taken += 1
        down_a = sum(1 for f in attackers if f.hp <= 0)
        down_d = sum(1 for f in defenders if f.hp <= 0)
        log.append(f"Round {rnd}: attackers standing {len(attackers) - down_a}/{len(attackers)}, "
                   f"defenders {len(defenders) - down_d}/{len(defenders)}")
        if down_a == len(attackers) or down_d == len(defenders):
            break
    hp_a = sum(f.hp for f in attackers)
    hp_d = sum(f.hp for f in defenders)
    return ("attack" if hp_d <= 0 or (hp_a > 0 and hp_a > hp_d) else "defend"), log[-6:]


def _raider(ctx: Ctx, user_id: int, side: str) -> Raider:
    f, equipped = duel.make_fighter(ctx, user_id)
    return Raider(user_id, side, f.attack, f.min_attack, f.reduction, float(settings.get()["duel"]["hp"]),
                  gear_ids={slot: piece["gear_id"] for slot, piece in equipped.items()})


def _wear(ctx: Ctx, r: Raider) -> None:
    pieces = gear.get_pieces(ctx, r.gear_ids or {})
    if pieces.get("sword") and r.attacks:
        gear.wear(ctx, pieces["sword"], r.attacks)
    for slot in ARMOR:
        if pieces.get(slot) and r.hits_taken:
            gear.wear(ctx, pieces[slot], r.hits_taken)


def resolve_raid(ctx: Ctx, raid_id: int) -> dict:
    """The assault: attackers against defenders. Won (or nobody defended): a share of the chest is taken."""
    c = _cfg()
    raid = get_raid(ctx, raid_id)
    if raid["status"] != "defending":
        raise GameError("This raid isn't waiting for its assault.")
    attackers = [_raider(ctx, uid, "attack") for uid in raid["attackers"]]
    defenders = [_raider(ctx, uid, "defend") for uid in raid["defenders"]]
    claimed = []
    if defenders:
        winner, log = fight(ctx.rng, attackers, defenders)
        for r in attackers + defenders:
            _wear(ctx, r)
            got = bounty.claim(ctx, r.downed_by, r.user_id, "raid") if r.downed_by is not None else None
            if got:
                claimed.append(got)
    else:
        winner, log = "attack", ["Nobody came to defend the chest."]
    stolen = 0
    if winner == "attack":
        stolen = min(int(chest(ctx, raid["defender_team"]) * float(c["raid_steal"])), int(c["raid_steal_max"]))
        ctx.execute("UPDATE teams SET chest = chest - ? WHERE team_id=?;", (stolen, raid["defender_team"]))
        ctx.execute("UPDATE teams SET chest = chest + ? WHERE team_id=?;", (stolen, raid["attacker_team"]))
        add_points(ctx, raid["attacker_team"], "raid", raid["leader_id"], raid["defender_team"])
        for uid in raid["attackers"]:
            players.bump_stat(ctx, uid, "raids_won")
    else:
        add_points(ctx, raid["defender_team"], "raid_defended", raid["defenders"][0], raid["attacker_team"])
        for uid in raid["defenders"]:
            players.bump_stat(ctx, uid, "raids_defended")
    ctx.execute("UPDATE raids SET status=?, stolen=?, log=?, deadline=? WHERE raid_id=?;",
                ("won" if winner == "attack" else "lost", stolen, json.dumps(log), int(ctx.now), raid_id))
    return {**get_raid(ctx, raid_id), "bounties": claimed}


def due_raids(ctx: Ctx) -> list[dict]:
    """Called every minute: parties gathered long enough leave, assaults whose time came are fought."""
    out = []
    for r in ctx.all("SELECT raid_id, status FROM raids WHERE status IN ('gathering', 'defending') AND deadline <= ?;",
                     (int(ctx.now),)):
        if r["status"] == "gathering":
            out.append(launch_raid(ctx, r["raid_id"], None))
        else:
            out.append(resolve_raid(ctx, r["raid_id"]))
    return out
