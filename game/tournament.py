"""Weekend tournament: a single elimination bracket fought automatically.

- Registrations open on Friday 18:00 and close on Saturday 21:00 (local time,
  see settings "tournament"). Entering costs an entry fee, refunded when a
  player leaves before the draw or when too few players entered.
- When registrations close, the bracket is drawn at random. When the number
  of players isn't a power of 2, some players (drawn at random) skip the
  first round.
- From Sunday 18:00, one round is played every hour. Fights use the duel
  engine with the gear equipped at that moment, and don't wear it out.
- The pot (entry fees + a server bonus) goes 60% to the winner, 25% to the
  runner-up and 15% to the semi-finalists. Only the part that comes from the
  server bonus counts as earned (weekly seasons), the entry fees are just
  moving between players.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from game import duel, players, settings
from game.db import Ctx
from game.errors import GameError


def _cfg() -> dict:
    return settings.get()["tournament"]


# ---------------- schedule ----------------
def _at(ctx: Ctx, monday: date, day: int, hour: int) -> int:
    moment = datetime.combine(monday + timedelta(days=int(day)), time(hour=int(hour)), tzinfo=ctx.local_now.tzinfo)
    return int(moment.timestamp())


def schedule(ctx: Ctx, weeks_ahead: int = 0) -> dict[str, int]:
    """Timestamps of this week's registrations and first round."""
    c = _cfg()
    today = ctx.today
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=weeks_ahead)
    return {
        "opens": _at(ctx, monday, c["opens_day"], c["opens_hour"]),
        "closes": _at(ctx, monday, c["closes_day"], c["closes_hour"]),
        "starts": _at(ctx, monday, c["start_day"], c["start_hour"]),
    }


def next_opening(ctx: Ctx) -> int:
    this_week = schedule(ctx)
    return this_week["opens"] if ctx.now < this_week["opens"] else schedule(ctx, 1)["opens"]


def round_name(rnd: int, rounds: int) -> str:
    left = rounds - rnd
    if left == 0:
        return "Final"
    if left == 1:
        return "Semi-finals"
    if left == 2:
        return "Quarter-finals"
    return f"Round {rnd}"


# ---------------- lookups ----------------
def active(ctx: Ctx) -> dict | None:
    """The tournament taking registrations or being played, if any."""
    row = ctx.one(
        "SELECT * FROM tournaments WHERE status IN ('open', 'running') ORDER BY tournament_id DESC LIMIT 1;"
    )
    return dict(row) if row else None


def latest(ctx: Ctx) -> dict | None:
    row = ctx.one("SELECT * FROM tournaments ORDER BY tournament_id DESC LIMIT 1;")
    return dict(row) if row else None


def get(ctx: Ctx, tournament_id: int) -> dict:
    return dict(ctx.one("SELECT * FROM tournaments WHERE tournament_id=?;", (tournament_id,)))


def entrants(ctx: Ctx, tournament_id: int) -> list[dict]:
    rows = ctx.all(
        "SELECT * FROM tournament_players WHERE tournament_id=? ORDER BY joined_at, user_id;", (tournament_id,)
    )
    return [dict(r) for r in rows]


def matches(ctx: Ctx, tournament_id: int, rnd: int | None = None) -> list[dict]:
    if rnd is None:
        rows = ctx.all(
            "SELECT * FROM tournament_matches WHERE tournament_id=? ORDER BY round, slot;", (tournament_id,)
        )
    else:
        rows = ctx.all(
            "SELECT * FROM tournament_matches WHERE tournament_id=? AND round=? ORDER BY slot;", (tournament_id, rnd)
        )
    return [dict(r) for r in rows]


def pot_of(entries: int) -> int:
    c = _cfg()
    return entries * int(c["entry_fee"]) + int(c["house_bonus"])


# ---------------- registrations ----------------
def open_registrations(ctx: Ctx, closes_at: int | None, starts_at: int | None) -> dict:
    if active(ctx):
        raise GameError("A tournament is already open or running.")
    cur = ctx.execute(
        """
        INSERT INTO tournaments(week_id, status, closes_at, starts_at, house_bonus, pot, created_at)
        VALUES(?, 'open', ?, ?, ?, ?, ?);
        """,
        (ctx.week_id, closes_at, starts_at, int(_cfg()["house_bonus"]), pot_of(0), int(ctx.now)),
    )
    return get(ctx, cur.lastrowid)


def staff_open(ctx: Ctx) -> dict:
    """Open registrations now. They close at the usual time if it is still ahead, else when staff draws."""
    sch = schedule(ctx)
    closes = sch["closes"] if sch["closes"] > ctx.now else None
    starts = sch["starts"] if closes is not None and sch["starts"] >= closes else None
    return open_registrations(ctx, closes, starts)


def _check_same(t: dict | None, tournament_id: int | None) -> None:
    """Buttons of an old registration message must not act on another tournament."""
    if tournament_id is not None and (t is None or t["tournament_id"] != tournament_id):
        raise GameError("These registrations are closed.")


def join(ctx: Ctx, user_id: int, tournament_id: int | None = None) -> dict:
    t = active(ctx)
    _check_same(t, tournament_id)
    if t is None or t["status"] != "open":
        if t is not None:
            raise GameError("Registrations are closed: the tournament has started.")
        raise GameError(f"Registrations are not open. Next registrations: <t:{next_opening(ctx)}:F>.")
    if ctx.one(
        "SELECT 1 FROM tournament_players WHERE tournament_id=? AND user_id=?;", (t["tournament_id"], user_id)
    ):
        raise GameError("You are already registered.")
    count = len(entrants(ctx, t["tournament_id"]))
    if count >= int(_cfg()["max_players"]):
        raise GameError(f"The tournament is full ({count} players).")
    fee = int(_cfg()["entry_fee"])
    players.ensure_user(ctx, user_id)
    players.spend_emeralds(ctx, user_id, fee)
    ctx.execute(
        "INSERT INTO tournament_players(tournament_id, user_id, paid, joined_at) VALUES(?, ?, ?, ?);",
        (t["tournament_id"], user_id, fee, int(ctx.now)),
    )
    _update_pot(ctx, t["tournament_id"])
    return {"tournament": get(ctx, t["tournament_id"]), "fee": fee, "players": count + 1}


def leave(ctx: Ctx, user_id: int, tournament_id: int | None = None) -> dict:
    t = active(ctx)
    _check_same(t, tournament_id)
    row = None
    if t is not None:
        row = ctx.one(
            "SELECT * FROM tournament_players WHERE tournament_id=? AND user_id=?;", (t["tournament_id"], user_id)
        )
    if row is None:
        raise GameError("You are not registered for the tournament.")
    if t["status"] != "open":
        raise GameError("The bracket is drawn: you can't leave the tournament anymore.")
    ctx.execute(
        "DELETE FROM tournament_players WHERE tournament_id=? AND user_id=?;", (t["tournament_id"], user_id)
    )
    players.give_emeralds(ctx, user_id, row["paid"])
    _update_pot(ctx, t["tournament_id"])
    return {"refund": row["paid"], "tournament": get(ctx, t["tournament_id"])}


def set_message(ctx: Ctx, tournament_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute(
        "UPDATE tournaments SET channel_id=?, message_id=? WHERE tournament_id=?;",
        (channel_id, message_id, tournament_id),
    )


def registration(ctx: Ctx, tournament_id: int) -> dict:
    """What the registration message shows."""
    return {"tournament": get(ctx, tournament_id), "players": len(entrants(ctx, tournament_id))}


def _update_pot(ctx: Ctx, tournament_id: int) -> None:
    ctx.execute(
        """
        UPDATE tournaments SET pot = house_bonus
            + (SELECT COALESCE(SUM(paid), 0) FROM tournament_players WHERE tournament_id=?)
        WHERE tournament_id=?;
        """,
        (tournament_id, tournament_id),
    )


# ---------------- draw ----------------
def close_registrations(ctx: Ctx, t: dict) -> dict:
    """Draw the bracket, or cancel and refund when too few players entered."""
    entries = entrants(ctx, t["tournament_id"])
    minimum = max(2, int(_cfg()["min_players"]))
    if len(entries) < minimum:
        cancel(ctx, t)
        return {"type": "cancelled", "tournament": get(ctx, t["tournament_id"]), "players": len(entries), "minimum": minimum}

    ids = [e["user_id"] for e in entries]
    ctx.rng.shuffle(ids)
    size = 1
    while size < len(ids):
        size *= 2
    byes = size - len(ids)
    pairs: list[tuple[int, int | None]] = [(uid, None) for uid in ids[:byes]]
    rest = ids[byes:]
    pairs += [(rest[i], rest[i + 1]) for i in range(0, len(rest), 2)]
    ctx.rng.shuffle(pairs)
    for slot, (p1, p2) in enumerate(pairs):
        ctx.execute(
            """
            INSERT INTO tournament_matches(tournament_id, round, slot, player1, player2, winner, played_at)
            VALUES(?, 1, ?, ?, ?, ?, ?);
            """,
            (t["tournament_id"], slot, p1, p2, p1 if p2 is None else None, int(ctx.now) if p2 is None else None),
        )
    rounds = size.bit_length() - 1
    first = max(int(ctx.now), t["starts_at"] or 0)
    ctx.execute(
        "UPDATE tournaments SET status='running', rounds=?, next_round_at=? WHERE tournament_id=?;",
        (rounds, first, t["tournament_id"]),
    )
    return {
        "type": "drawn",
        "tournament": get(ctx, t["tournament_id"]),
        "players": len(ids),
        "matches": matches(ctx, t["tournament_id"], 1),
    }


def cancel(ctx: Ctx, t: dict) -> list[dict]:
    """Cancel a tournament that hasn't finished: every entry fee is refunded."""
    entries = entrants(ctx, t["tournament_id"])
    for e in entries:
        players.give_emeralds(ctx, e["user_id"], e["paid"])
    ctx.execute(
        "UPDATE tournaments SET status='cancelled', finished_at=? WHERE tournament_id=?;",
        (int(ctx.now), t["tournament_id"]),
    )
    return entries


def staff_cancel(ctx: Ctx) -> dict:
    t = active(ctx)
    if t is None:
        raise GameError("There is no tournament to cancel.")
    return {"tournament": t, "refunded": cancel(ctx, t)}


# ---------------- rounds ----------------
def _fight(ctx: Ctx, p1: int, p2: int) -> tuple[int, int, float]:
    """(winner, loser, winner HP left). Same rules as duels, but the gear doesn't wear out."""
    a, _ = duel.make_fighter(ctx, p1)
    b, _ = duel.make_fighter(ctx, p2)
    result = duel.simulate(ctx.rng, a, b)
    winner, loser = (a, b) if result.winner == 0 else (b, a)
    return winner.user_id, loser.user_id, round(winner.hp, 1)


def play_round(ctx: Ctx, t: dict) -> dict:
    tid, rnd = t["tournament_id"], t["round"] + 1
    if rnd > 1 and not matches(ctx, tid, rnd):
        previous = matches(ctx, tid, rnd - 1)
        for slot in range(len(previous) // 2):
            ctx.execute(
                "INSERT INTO tournament_matches(tournament_id, round, slot, player1, player2) VALUES(?, ?, ?, ?, ?);",
                (tid, rnd, slot, previous[2 * slot]["winner"], previous[2 * slot + 1]["winner"]),
            )
    xp = int(_cfg()["xp_per_win"])
    for m in matches(ctx, tid, rnd):
        if m["winner"] is not None:
            continue  # bye
        winner, loser, hp = _fight(ctx, m["player1"], m["player2"])
        ctx.execute(
            "UPDATE tournament_matches SET winner=?, winner_hp=?, played_at=? WHERE tournament_id=? AND round=? AND slot=?;",
            (winner, hp, int(ctx.now), tid, rnd, m["slot"]),
        )
        ctx.execute(
            "UPDATE tournament_players SET eliminated_round=? WHERE tournament_id=? AND user_id=?;",
            (rnd, tid, loser),
        )
        players.bump_stat(ctx, winner, "tournament_wins")
        players.add_xp(ctx, winner, xp)

    event = {"type": "round", "round": rnd, "rounds": t["rounds"], "matches": matches(ctx, tid, rnd)}
    if rnd >= t["rounds"]:
        ctx.execute("UPDATE tournaments SET round=? WHERE tournament_id=?;", (rnd, tid))
        event["final"] = finish(ctx, get(ctx, tid))
    else:
        next_at = max(int(ctx.now), t["next_round_at"] + int(_cfg()["round_minutes"]) * 60)
        ctx.execute("UPDATE tournaments SET round=?, next_round_at=? WHERE tournament_id=?;", (rnd, next_at, tid))
        event["next_round_at"] = next_at
    event["tournament"] = get(ctx, tid)
    return event


def staff_round(ctx: Ctx) -> dict:
    """Close registrations, or play the next round, right now."""
    t = active(ctx)
    if t is None:
        raise GameError("There is no tournament open or running.")
    if t["status"] == "open":
        return close_registrations(ctx, t)
    t["next_round_at"] = int(ctx.now)
    return play_round(ctx, t)


# ---------------- prizes ----------------
def prizes(pot: int, winner: int, runner_up: int, semis: list[int]) -> dict[int, int]:
    """Share the pot. What can't be split evenly goes to the winner."""
    first, second, third = (int(p) for p in (list(_cfg()["prize_split"]) + [0, 0, 0])[:3])
    out = {winner: pot * first // 100, runner_up: pot * second // 100}
    if semis:
        each = pot * third // 100 // len(semis)
        for uid in semis:
            out[uid] = out.get(uid, 0) + each
    out[winner] += max(0, pot - sum(out.values()))
    return out


def finish(ctx: Ctx, t: dict) -> dict:
    tid, rounds = t["tournament_id"], t["rounds"]
    final = matches(ctx, tid, rounds)[0]
    winner = final["winner"]
    runner_up = final["player2"] if final["player1"] == winner else final["player1"]
    semis = []
    if rounds >= 2:
        for m in matches(ctx, tid, rounds - 1):
            if m["player2"] is not None:
                semis.append(m["player2"] if m["winner"] == m["player1"] else m["player1"])
    pot, house = t["pot"], t["house_bonus"]
    payout = prizes(pot, winner, runner_up, semis)
    for uid, amount in payout.items():
        # Only the share paid by the server counts for the seasons.
        earned = amount * house // pot if pot else 0
        players.give_emeralds(ctx, uid, amount - earned)
        players.earn_emeralds(ctx, uid, earned)
        ctx.execute(
            "UPDATE tournament_players SET prize=? WHERE tournament_id=? AND user_id=?;", (amount, tid, uid)
        )
    players.bump_stat(ctx, winner, "tournaments_won")
    ctx.execute(
        "UPDATE tournaments SET status='finished', winner_id=?, finished_at=? WHERE tournament_id=?;",
        (winner, int(ctx.now), tid),
    )
    return {
        "winner": winner,
        "runner_up": runner_up,
        "semis": semis,
        "payout": sorted(payout.items(), key=lambda p: (-p[1], p[0])),
        "pot": pot,
    }


# ---------------- clock ----------------
def tick(ctx: Ctx) -> list[dict]:
    """Called every minute: open registrations, draw the bracket, play the rounds when it's time."""
    t = active(ctx)
    if t is None:
        sch = schedule(ctx)
        already = ctx.one("SELECT 1 FROM tournaments WHERE week_id=?;", (ctx.week_id,))
        if sch["opens"] <= ctx.now < sch["closes"] and not already:
            starts = sch["starts"] if sch["starts"] >= sch["closes"] else None
            return [{"type": "opened", "tournament": open_registrations(ctx, sch["closes"], starts)}]
        return []
    if t["status"] == "open":
        if t["closes_at"] is not None and ctx.now >= t["closes_at"]:
            return [close_registrations(ctx, t)]
        return []
    if ctx.now >= t["next_round_at"]:
        return [play_round(ctx, t)]
    return []


# ---------------- overviews ----------------
def overview(ctx: Ctx, user_id: int) -> dict:
    """Everything /tournament info shows."""
    t = active(ctx) or latest(ctx)
    data: dict = {"tournament": t, "next_opening": next_opening(ctx), "settings": dict(_cfg())}
    if t is None:
        return data
    entries = entrants(ctx, t["tournament_id"])
    me = next((e for e in entries if e["user_id"] == user_id), None)
    data.update({
        "players": len(entries),
        "entrants": [e["user_id"] for e in entries],
        "me": me,
        "alive": [e["user_id"] for e in entries if e["eliminated_round"] is None],
    })
    return data


def bracket(ctx: Ctx) -> dict:
    t = active(ctx) or latest(ctx)
    if t is None or t["status"] == "open" or not t["rounds"]:
        raise GameError("No bracket yet: it is drawn when registrations close.")
    return {"tournament": t, "matches": matches(ctx, t["tournament_id"])}


def last_winner(ctx: Ctx) -> int | None:
    row = ctx.one(
        "SELECT winner_id FROM tournaments WHERE status='finished' ORDER BY tournament_id DESC LIMIT 1;"
    )
    return row["winner_id"] if row else None
