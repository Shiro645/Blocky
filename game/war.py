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

from game import botstate, bounty, duel, gear, loans, players, potions, robbery, settings, teams
from game.catalog import ARMOR, SHIELD
from game.db import Ctx
from game.errors import GameError
from game.raid_fight import GOLEM, Fighter, RaidFight

MINUTE, HOUR = 60, 3600


def _cfg() -> dict:
    return settings.get()["war"]


# ---------------- the chest ----------------
def _touch(ctx: Ctx, team_id: int) -> None:
    """Before the chest changes: add its time at the old amount to the week's average (the levy is taken on it)."""
    row = ctx.one("SELECT chest, chest_area, chest_from, chest_touched FROM teams WHERE team_id=?;", (team_id,))
    if row is None:
        return
    now = int(ctx.now)
    since = row["chest_touched"] if row["chest_touched"] is not None else now
    area = int(row["chest_area"]) + int(row["chest"]) * max(0, now - since)
    ctx.execute("UPDATE teams SET chest_area=?, chest_touched=?, chest_from=COALESCE(chest_from, ?) WHERE team_id=?;",
                (area, now, now, team_id))


def move_chest(ctx: Ctx, team_id: int, delta: int) -> None:
    """Add (or take, below 0) emeralds to a team's chest. What comes in pays the levy it owes first (into the pot)."""
    _touch(ctx, team_id)
    if delta > 0:
        row = ctx.one("SELECT chest_debt FROM teams WHERE team_id=?;", (team_id,))
        owed = min(int(delta), int(row["chest_debt"])) if row else 0
        if owed:
            ctx.execute("UPDATE teams SET chest_debt = chest_debt - ? WHERE team_id=?;", (owed, team_id))
            _week(ctx, ctx.week_id)
            ctx.execute("UPDATE war_weeks SET pot = pot + ? WHERE week_id=?;", (owed, ctx.week_id))
            delta -= owed
    ctx.execute("UPDATE teams SET chest = MAX(0, chest + ?) WHERE team_id=?;", (int(delta), team_id))


def average_chest(ctx: Ctx, team_id: int) -> int:
    """The chest's average since the last levy (weighted by time)."""
    _touch(ctx, team_id)
    row = ctx.one("SELECT chest, chest_area, chest_from FROM teams WHERE team_id=?;", (team_id,))
    span = int(ctx.now) - int(row["chest_from"])
    return int(row["chest_area"] / span) if span > 0 else int(row["chest"])


def chest(ctx: Ctx, team_id: int) -> int:
    row = ctx.one("SELECT chest FROM teams WHERE team_id=?;", (team_id,))
    return int(row["chest"]) if row else 0


def deposit(ctx: Ctx, user_id: int, amount: int) -> dict:
    team = teams.team_of(ctx, user_id)
    if team is None:
        raise GameError("You're not in a team.")
    if amount <= 0:
        raise GameError("Put at least 1 emerald.")
    loans.check_not_late(ctx, user_id, "chest deposits")  # a late borrower's wealth stays where it can be garnished
    players.spend_emeralds(ctx, user_id, amount)
    move_chest(ctx, team["team_id"], amount)
    players.bump_stat(ctx, user_id, "chest_deposits", amount)
    return {"team": team, "amount": amount, "chest": chest(ctx, team["team_id"])}


def withdraw(ctx: Ctx, user_id: int, amount: int) -> dict:
    team = teams.team_of(ctx, user_id)
    if team is None or team["leader_id"] != user_id:
        raise GameError("Only your team's leader can take emeralds out of the chest.")
    if amount <= 0:
        raise GameError("Take at least 1 emerald.")
    if ctx.one("SELECT 1 FROM raids WHERE defender_team=? AND status IN ('gathering', 'defending', 'fighting');",
               (team["team_id"],)):
        raise GameError("Your chest is being raided: nothing comes out of it until the raid is over.")
    have = chest(ctx, team["team_id"])
    if amount > have:
        raise GameError(f"The chest only holds **{have:,}** emeralds.")
    move_chest(ctx, team["team_id"], -amount)
    players.give_emeralds(ctx, user_id, amount)
    return {"team": team, "amount": amount, "chest": chest(ctx, team["team_id"])}


def set_chest(ctx: Ctx, team_id: int, amount: int) -> None:
    """Staff: set a chest."""
    move_chest(ctx, team_id, max(0, amount) - chest(ctx, team_id))


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
            carried = int(share)  # what no team takes (fewer teams scored than places) goes to the next pot
            for place, (team, prize) in enumerate(zip(ranked, c["prizes"]), start=1):
                paid = int(share * float(prize))
                carried -= paid
                move_chest(ctx, team["team_id"], paid)
                podium.append({**team, "place": place, "paid": paid})
                if place == 1:
                    for m in teams.members(ctx, team["team_id"]):
                        players.bump_stat(ctx, m["user_id"], "wars_won")
            ctx.execute("UPDATE war_weeks SET settled_at=?, results=? WHERE week_id=?;",
                        (int(ctx.now), json.dumps(podium), last))
            _week(ctx, ctx.week_id)
            ctx.execute("UPDATE war_weeks SET pot = pot + ? WHERE week_id=?;", (max(0, carried), ctx.week_id))
    # This week's pot: a share of every chest of the teams at war, on its average over the week (emptying it just
    # before Monday doesn't dodge it), never more than it holds. The average then starts over.
    pot = 0
    for t in ctx.all("SELECT team_id, chest FROM teams;"):
        if at_war(ctx, t["team_id"]):
            due = int(average_chest(ctx, t["team_id"]) * float(c["levy"]))
            take = min(int(t["chest"]), due)
            if take > 0:
                move_chest(ctx, t["team_id"], -take)
                pot += take
            if due > take:  # emptied before Monday: what's missing is owed, paid by the next emeralds put in
                ctx.execute("UPDATE teams SET chest_debt = chest_debt + ? WHERE team_id=?;", (due - take, t["team_id"]))
        ctx.execute("UPDATE teams SET chest_area=0, chest_from=?, chest_touched=? WHERE team_id=?;",
                    (int(ctx.now), int(ctx.now), t["team_id"]))
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
        "WHERE m.user_id=? AND r.status IN ('gathering', 'defending', 'fighting');", (user_id,))
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
        "SELECT 1 FROM raids WHERE status IN ('gathering', 'defending', 'fighting') "
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


# ---------------- the chest's defenses ----------------
DEFENSES: dict[str, str] = {"walls": "🧱 Walls", "archers": "🏹 Archers", "golem": "🛡️ Iron Golem"}


def defenses(ctx: Ctx, team_id: int) -> dict[str, list]:
    """kind -> [level (0-3), solidity (0-1)]."""
    row = ctx.one("SELECT defenses FROM teams WHERE team_id=?;", (team_id,))
    saved = json.loads(row["defenses"]) if row and row["defenses"] else {}
    return {k: list(saved.get(k, [0, 1.0])) for k in DEFENSES}


def _save_defenses(ctx: Ctx, team_id: int, d: dict) -> None:
    ctx.execute("UPDATE teams SET defenses=? WHERE team_id=?;", (json.dumps(d), team_id))


def defense_price(kind: str, level: int) -> int:
    return int(_cfg()["defenses"][kind]["price"][level - 1])


def repair_price(kind: str, level: int, solidity: float) -> int:
    return int(round(defense_price(kind, level) * float(_cfg()["defenses"]["repair"]) * (1 - solidity)))


def _leader_team(ctx: Ctx, user_id: int) -> dict:
    team = teams.team_of(ctx, user_id)
    if team is None or team["leader_id"] != user_id:
        raise GameError("Only your team's leader can do that.")
    if teams.in_raid(ctx, team["team_id"]):
        raise GameError("Not during a raid.")
    return team


def _pay_from_chest(ctx: Ctx, team_id: int, price: int) -> None:
    have = chest(ctx, team_id)
    if price > have:
        raise GameError(f"That costs **{price:,}** emeralds from the chest: it only holds **{have:,}**.")
    move_chest(ctx, team_id, -price)


def buy_defense(ctx: Ctx, user_id: int, kind: str) -> dict:
    """The leader builds the next level of a defense with the chest's emeralds (spent)."""
    if kind not in DEFENSES:
        raise GameError("Unknown defense.")
    team = _leader_team(ctx, user_id)
    d = defenses(ctx, team["team_id"])
    level, solidity = d[kind]
    if level >= 3:
        raise GameError(f"Your {DEFENSES[kind]} are already at the highest level.")
    price = defense_price(kind, level + 1)
    _pay_from_chest(ctx, team["team_id"], price)
    d[kind] = [level + 1, 1.0]
    _save_defenses(ctx, team["team_id"], d)
    return {"team": team, "kind": kind, "level": level + 1, "price": price, "chest": chest(ctx, team["team_id"])}


def repair_defense(ctx: Ctx, user_id: int, kind: str) -> dict:
    """The leader repairs a defense worn by raids, with the chest's emeralds."""
    if kind not in DEFENSES:
        raise GameError("Unknown defense.")
    team = _leader_team(ctx, user_id)
    d = defenses(ctx, team["team_id"])
    level, solidity = d[kind]
    if level <= 0 or solidity >= 1:
        raise GameError(f"Your {DEFENSES[kind]} don't need repairs.")
    price = repair_price(kind, level, solidity)
    _pay_from_chest(ctx, team["team_id"], price)
    d[kind] = [level, 1.0]
    _save_defenses(ctx, team["team_id"], d)
    return {"team": team, "kind": kind, "level": level, "price": price, "chest": chest(ctx, team["team_id"])}


def _wear_defenses(ctx: Ctx, team_id: int) -> list[str]:
    """After a raid on the team: every defense loses some solidity; at 0 it loses a level. Returns the lost ones."""
    d = defenses(ctx, team_id)
    lost = []
    for kind, (level, solidity) in d.items():
        if level <= 0:
            continue
        solidity = round(solidity - float(_cfg()["defenses"]["wear"]), 4)
        if solidity <= 0:
            level, solidity = level - 1, 1.0
            lost.append(kind)
        d[kind] = [level, solidity]
    _save_defenses(ctx, team_id, d)
    return lost


# ---------------- the assault ----------------
def _fighter(ctx: Ctx, user_id: int, side: str) -> Fighter:
    """A player as they go in: their gear and species like in a duel, and their team chest's Combat bonus."""
    f, equipped = duel.make_fighter(ctx, user_id)
    bonus = teams.chest_bonus(ctx, user_id, "combat")
    return Fighter(user_id, side, f.attack * (1 + bonus), f.min_attack * (1 + bonus),
                   1 - (1 - f.reduction) * (1 - bonus), float(settings.get()["duel"]["hp"]),
                   potion_boost=f.potion_boost, blocks_left=f.blocks_left,
                   gear_ids={slot: piece["gear_id"] for slot, piece in equipped.items()})


def _golem(level: int) -> Fighter:
    g = _cfg()["defenses"]["golem"]
    i = level - 1
    return Fighter(GOLEM, "defend", float(g["max_damage"][i]), float(g["min_damage"][i]), float(g["reduction"][i]),
                   float(g["hp"][i]))


def _new_fight(ctx: Ctx, raid: dict) -> RaidFight | None:
    """The fight of a raid, or None when nobody (no player, no golem) defends the chest."""
    d = defenses(ctx, raid["defender_team"])
    attackers = [_fighter(ctx, uid, "attack") for uid in raid["attackers"]]
    defenders = [_fighter(ctx, uid, "defend") for uid in raid["defenders"]]
    if d["golem"][0] > 0:
        defenders.append(_golem(d["golem"][0]))
    if not defenders:
        return None
    a = _cfg()["defenses"]["archers"]
    walls, archers = d["walls"][0], d["archers"][0]
    return RaidFight(
        RaidFight.order(attackers, defenders),
        walls=float(_cfg()["defenses"]["walls"]["reduction"][walls - 1]) if walls else 0.0,
        arrows=int(a["arrows"][archers - 1]) if archers else 0,
        arrow_damage=(float(a["min_damage"]), float(a["max_damage"])),
    )


def _turn_deadline(ctx: Ctx) -> int:
    return int(ctx.now + int(settings.get()["gate_bosses"]["turn_seconds"]))


def fight_of(raid: dict) -> RaidFight | None:
    return RaidFight.from_json(raid["state"]) if raid.get("state") else None


def _auto_turns(ctx: Ctx, fight: RaidFight) -> None:
    """Players who missed afk_turns turns in a row: their turns play by themselves."""
    while not fight.over and fight.current.afk >= int(settings.get()["gate_bosses"]["afk_turns"]):
        fight.attack(ctx.rng, fight.current.user_id)


def _save_fight(ctx: Ctx, raid: dict, fight: RaidFight) -> dict:
    _auto_turns(ctx, fight)
    if fight.over:
        return _finish(ctx, raid, fight)
    ctx.execute("UPDATE raids SET state=?, deadline=? WHERE raid_id=?;",
                (fight.to_json(), _turn_deadline(ctx), raid["raid_id"]))
    return get_raid(ctx, raid["raid_id"])


def resolve_raid(ctx: Ctx, raid_id: int) -> dict:
    """The assault: nobody defends (no player, no golem) = the chest is plundered; otherwise the fight starts."""
    raid = get_raid(ctx, raid_id)
    if raid["status"] != "defending":
        raise GameError("This raid isn't waiting for its assault.")
    fight = _new_fight(ctx, raid)
    if fight is None:
        return _finish(ctx, raid, None)
    fight.log.append("⚔️ **The assault begins!**")
    fight.start(ctx.rng)
    ctx.execute("UPDATE raids SET status='fighting' WHERE raid_id=?;", (raid_id,))
    return {**_save_fight(ctx, {**raid, "status": "fighting"}, fight), "started": True}


def _fighting(ctx: Ctx, raid_id: int) -> tuple[dict, RaidFight]:
    raid = get_raid(ctx, raid_id)
    if raid["status"] != "fighting":
        raise GameError("This raid isn't being fought.")
    return raid, fight_of(raid)


def raid_present(ctx: Ctx, raid_id: int, user_id: int) -> None:
    """A fighter clicked: they're here, their turns stop playing by themselves (saved on its own)."""
    raid = get_raid(ctx, raid_id)
    fight = fight_of(raid) if raid["status"] == "fighting" else None
    f = next((x for x in fight.fighters if x.user_id == user_id and not x.golem), None) if fight else None
    if f is not None and f.afk:
        f.afk = 0
        ctx.execute("UPDATE raids SET state=? WHERE raid_id=?;", (fight.to_json(), raid_id))


def raid_attack(ctx: Ctx, raid_id: int, user_id: int, block: bool = False) -> dict:
    raid, fight = _fighting(ctx, raid_id)
    fight.fighter(user_id).afk = 0
    fight.attack(ctx.rng, user_id, block)
    return _save_fight(ctx, raid, fight)


def raid_drink(ctx: Ctx, raid_id: int, user_id: int, key: str) -> dict:
    """The current fighter drinks a potion from their inventory, then still has to attack."""
    raid, fight = _fighting(ctx, raid_id)
    fight.check_potion(user_id, key)
    potions.drink(ctx, user_id, key)
    fight.drink(ctx.rng, user_id, key)
    fight.current.afk = 0
    if fight.over:
        return _finish(ctx, raid, fight)
    ctx.execute("UPDATE raids SET state=? WHERE raid_id=?;", (fight.to_json(), raid_id))
    return get_raid(ctx, raid_id)


def clear_fight_log(ctx: Ctx, raid_id: int) -> None:
    """The log was shown: start a new one."""
    raid = get_raid(ctx, raid_id)
    if raid["status"] == "fighting" and raid.get("state"):
        fight = fight_of(raid)
        fight.log = []
        ctx.execute("UPDATE raids SET state=? WHERE raid_id=?;", (fight.to_json(), raid_id))


def play_out(ctx: Ctx, raid_id: int) -> dict:
    """Play the rest of a fight by itself (staff, tests)."""
    raid, fight = _fighting(ctx, raid_id)
    while not fight.over:
        fight.attack(ctx.rng, fight.current.user_id)
    return _finish(ctx, raid, fight)


def _finish(ctx: Ctx, raid: dict, fight: RaidFight | None) -> dict:
    """The raid is over: the loot, the points, the wear of the gear and of the defenses, the bounties."""
    c = _cfg()
    claimed = []
    if fight is None:
        winner, log = "attack", ["Nobody came to defend the chest."]
    else:
        winner, log = fight.result, fight.log[-12:]
        for f in fight.fighters:
            if f.golem:
                continue
            pieces = gear.get_pieces(ctx, f.gear_ids)
            if pieces.get("sword") and f.attacks:
                gear.wear(ctx, pieces["sword"], f.attacks)
            for slot in ARMOR:
                if pieces.get(slot) and f.hits_taken:
                    gear.wear(ctx, pieces[slot], f.hits_taken)
            if f.blocks_used and pieces.get(SHIELD):
                gear.wear_shield(ctx, pieces[SHIELD], f.blocks_used)
            got = bounty.claim(ctx, f.downed_by, f.user_id, "raid") if f.downed_by is not None else None
            if got:
                claimed.append(got)
    stolen = 0
    if winner == "attack":
        stolen = min(int(chest(ctx, raid["defender_team"]) * float(c["raid_steal"])), int(c["raid_steal_max"]))
        move_chest(ctx, raid["defender_team"], -stolen)
        move_chest(ctx, raid["attacker_team"], stolen)
        add_points(ctx, raid["attacker_team"], "raid", raid["leader_id"], raid["defender_team"])
        for uid in raid["attackers"]:
            players.bump_stat(ctx, uid, "raids_won")
    else:
        add_points(ctx, raid["defender_team"], "raid_defended",
                   raid["defenders"][0] if raid["defenders"] else None, raid["attacker_team"])
        for uid in raid["defenders"]:
            players.bump_stat(ctx, uid, "raids_defended")
    worn = _wear_defenses(ctx, raid["defender_team"]) if teams.get_team(ctx, raid["defender_team"]) else []
    ctx.execute("UPDATE raids SET status=?, stolen=?, log=?, deadline=?, state=NULL WHERE raid_id=?;",
                ("won" if winner == "attack" else "lost", stolen, json.dumps(log), int(ctx.now), raid["raid_id"]))
    return {**get_raid(ctx, raid["raid_id"]), "bounties": claimed, "worn": worn}


def due_raids(ctx: Ctx) -> list[dict]:
    """Called every few seconds: parties gathered long enough leave, assaults whose time came start, and a fighter
    who didn't play in time attacks (their missed turns count)."""
    out = []
    for r in ctx.all("SELECT raid_id, status FROM raids WHERE status IN ('gathering', 'defending', 'fighting') "
                     "AND deadline <= ?;", (int(ctx.now),)):
        if r["status"] == "gathering":
            out.append(launch_raid(ctx, r["raid_id"], None))
        elif r["status"] == "defending":
            out.append(resolve_raid(ctx, r["raid_id"]))
        else:
            raid, fight = _fighting(ctx, r["raid_id"])
            f = fight.current
            if not fight.drank:  # drinking a potion is playing: only a turn with nothing done counts as missed
                f.afk += 1
            fight.log.append(f"⏳ {f.mention} didn't play in time: they attack.")
            fight.attack(ctx.rng, f.user_id)
            out.append(_save_fight(ctx, raid, fight))
    return out
