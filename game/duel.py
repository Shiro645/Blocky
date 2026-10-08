"""Duels: both players bet the same stake, the winner takes the pot.

The fight is turn based. Damage comes from the sword, armor reduces the
damage taken, and a bit of luck (damage variance and critical hits) keeps
underdogs in the game.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game import gear, players, settings
from game.catalog import ARMOR
from game.db import Ctx
from game.errors import GameError

DAMAGE_VARIANCE = 0.25  # damage is between 75% and 125% of the attack


@dataclass
class Fighter:
    user_id: int
    attack: float
    reduction: float
    hp: float
    attacks: int = 0
    hits_taken: int = 0


@dataclass
class FightResult:
    winner: int  # index 0 or 1
    log: list[tuple[int, float, bool, float]] = field(default_factory=list)  # attacker, damage, crit, defender hp left
    fighters: tuple[Fighter, Fighter] | None = None


def simulate(rng: random.Random, a: Fighter, b: Fighter) -> FightResult:
    d = settings.get()["duel"]
    fighters = (a, b)
    turn = rng.randint(0, 1)
    log = []
    for _ in range(int(d["max_rounds"])):
        attacker, defender = fighters[turn], fighters[1 - turn]
        damage = attacker.attack * rng.uniform(1 - DAMAGE_VARIANCE, 1 + DAMAGE_VARIANCE)
        crit = rng.random() < d["crit_chance"]
        if crit:
            damage *= d["crit_multiplier"]
        damage = max(0.5, damage * (1 - defender.reduction))
        defender.hp = max(0.0, defender.hp - damage)
        attacker.attacks += 1
        defender.hits_taken += 1
        log.append((turn, damage, crit, defender.hp))
        if defender.hp <= 0:
            return FightResult(winner=turn, log=log, fighters=fighters)
        turn = 1 - turn
    # Nobody fell: the one with the most health left wins (coin flip on a tie).
    if a.hp == b.hp:
        winner = rng.randint(0, 1)
    else:
        winner = 0 if a.hp > b.hp else 1
    return FightResult(winner=winner, log=log, fighters=fighters)


def _fighter(ctx: Ctx, user_id: int) -> tuple[Fighter, dict[str, dict]]:
    equipped = gear.get_equipped(ctx, user_id)
    hp = float(settings.get()["duel"]["hp"])
    return Fighter(user_id, gear.attack_damage(equipped), gear.damage_reduction(equipped), hp), equipped


def check_stake(ctx: Ctx, user_id: int, stake: int) -> None:
    minimum = int(settings.get()["duel"]["min_stake"])
    if stake < minimum:
        raise GameError(f"The minimum stake is **{minimum}** emeralds.")
    have = players.get_emeralds(ctx, user_id)
    if have < stake:
        raise GameError(f"<@{user_id}> doesn't have **{stake}** emeralds (has {have}).")


def fight(ctx: Ctx, challenger_id: int, opponent_id: int, stake: int) -> dict:
    if challenger_id == opponent_id:
        raise GameError("You can't duel yourself.")
    d = settings.get()["duel"]
    check_stake(ctx, challenger_id, stake)
    check_stake(ctx, opponent_id, stake)
    players.spend_emeralds(ctx, challenger_id, stake)
    players.spend_emeralds(ctx, opponent_id, stake)

    a, a_gear = _fighter(ctx, challenger_id)
    b, b_gear = _fighter(ctx, opponent_id)
    result = simulate(ctx.rng, a, b)
    winner, loser = (a, b) if result.winner == 0 else (b, a)

    # The winner gets their stake back, and the opponent's stake counts as earned.
    players.give_emeralds(ctx, winner.user_id, stake)
    players.earn_emeralds(ctx, winner.user_id, stake)
    players.bump_stat(ctx, winner.user_id, "duels_won")
    players.bump_stat(ctx, loser.user_id, "duels_lost")
    players.bump_stat(ctx, winner.user_id, "duel_winnings", stake)
    players.add_xp(ctx, winner.user_id, int(d["xp_win"]))
    players.add_xp(ctx, loser.user_id, int(d["xp_loss"]))

    broken: list[tuple[int, str]] = []
    for fighter, equipped in ((a, a_gear), (b, b_gear)):
        sword = equipped.get("sword")
        if sword and fighter.attacks and gear.wear(ctx, sword, fighter.attacks):
            broken.append((fighter.user_id, f"{sword['material']} sword"))
        for slot in ARMOR:
            piece = equipped.get(slot)
            if piece and fighter.hits_taken and gear.wear(ctx, piece, fighter.hits_taken):
                broken.append((fighter.user_id, f"{piece['material']} {slot}"))

    return {
        "winner": winner.user_id,
        "loser": loser.user_id,
        "stake": stake,
        "log": [
            ((a, b)[attacker].user_id, round(dmg, 1), crit, round(hp_left, 1))
            for attacker, dmg, crit, hp_left in result.log
        ],
        "hp": {a.user_id: round(a.hp, 1), b.user_id: round(b.hp, 1)},
        "max_hp": float(d["hp"]),
        "stats": {
            f.user_id: {"attack": f.attack, "reduction": f.reduction} for f in (a, b)
        },
        "broken": broken,
    }
