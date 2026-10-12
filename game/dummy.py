"""Training dummy (/dummy): a damage tester with a leaderboard, and training duels.

- /dummy hit: a series of hits on a dummy without armor, with your gear and
  species, rolled like in a duel. Your best series (total damage) and your best
  hit go on the leaderboard. The dummy doesn't hit back; nothing wears out.
- /dummy duel: a duel against a dummy that hits back like a player of the gear
  you pick, with the duel buttons (Attack, Attack + block, any potion). No
  stake, nothing used up, nothing won.
"""
from __future__ import annotations

import random

from game import duel, players, settings
from game.catalog import ARMOR
from game.db import Ctx
from game.errors import GameError

DUMMY_ID = 0  # the dummy's "user id" in a training fight
GEARS: dict[str, str] = {"none": "No gear", "gold": "Gold", "iron": "Iron", "diamond": "Diamond", "netherite": "Netherite"}


def _cfg() -> dict:
    return settings.get()["dummy"]


def hit_series(ctx: Ctx, user_id: int) -> dict:
    """Hit the dummy `hits` times. Returns the hits, the totals, the records and the rank."""
    c, d = _cfg(), settings.get()["duel"]
    players.ensure_user(ctx, user_id)
    row = ctx.one("SELECT * FROM dummy_scores WHERE user_id=?;", (user_id,))
    ready = (row["last_at"] if row else 0) + int(c["cooldown_seconds"])
    if row and ctx.now < ready:
        raise GameError(f"The dummy is still wobbling. Hit it again <t:{int(ready)}:R>.")
    fighter, _ = duel.make_fighter(ctx, user_id)
    hits: list[tuple[float, bool]] = []
    for _ in range(max(1, int(c["hits"]))):
        damage = ctx.rng.uniform(min(fighter.min_attack, fighter.attack), fighter.attack)
        crit = ctx.rng.random() < float(d["crit_chance"])
        if crit:
            damage *= float(d["crit_multiplier"])
        hits.append((round(damage, 1), crit))
    total = round(sum(h for h, _ in hits), 1)
    best_hit = max(h for h, _ in hits)
    before = dict(row) if row else {"best_total": 0.0, "best_hit": 0.0}
    ctx.execute(
        """
        INSERT INTO dummy_scores(user_id, best_total, best_hit, series, last_at) VALUES(?, ?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET best_total = MAX(best_total, excluded.best_total),
            best_hit = MAX(best_hit, excluded.best_hit), series = series + 1, last_at = excluded.last_at;
        """,
        (user_id, total, best_hit, int(ctx.now)),
    )
    table = ranking(ctx)
    rank = next((i for i, r in enumerate(table, start=1) if r["user_id"] == user_id), None)
    return {
        "hits": hits, "total": total, "average": round(total / len(hits), 1), "min": min(h for h, _ in hits),
        "max": best_hit, "crits": sum(1 for _, c in hits if c), "attack": (fighter.min_attack, fighter.attack),
        "record": total > before["best_total"], "best_total": max(total, before["best_total"]),
        "best_hit": max(best_hit, before["best_hit"]), "rank": rank, "players": len(table),
    }


def ranking(ctx: Ctx, limit: int | None = None) -> list[dict]:
    """Best series first (then the best hit)."""
    rows = ctx.all("SELECT * FROM dummy_scores WHERE series > 0 ORDER BY best_total DESC, best_hit DESC, user_id;")
    out = [dict(r) for r in rows]
    return out[:limit] if limit else out


def dummy_fighter(gear_key: str) -> duel.Fighter:
    """A dummy that fights like a player wearing a full set of `gear_key` (sword and armor)."""
    if gear_key not in GEARS:
        raise GameError("Unknown dummy.")
    g, d = settings.get()["gear"], settings.get()["duel"]
    attack = float(g["sword_max_damage"]["none" if gear_key == "none" else gear_key])
    points = 0.0 if gear_key == "none" else sum(float(g["armor_points"][gear_key][slot]) for slot in ARMOR)
    reduction = min(float(g["max_damage_reduction"]), points * float(g["damage_reduction_per_armor_point"]))
    return duel.Fighter(DUMMY_ID, attack, reduction, float(d["hp"]), min_attack=float(d["min_damage"]))


def training_fight(ctx: Ctx, user_id: int, gear_key: str, rng: random.Random) -> duel.Fight:
    """The player (their gear, species and shield) against a dummy. Nothing is saved."""
    player, _ = duel.make_fighter(ctx, user_id)
    return duel.Fight(rng, player, dummy_fighter(gear_key))
