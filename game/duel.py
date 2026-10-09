"""Duels: both players bet the same stake, the winner takes the pot.

The fight is turn based. Damage comes from the sword, armor reduces the
damage taken, and a bit of luck (damage variance and critical hits) keeps
underdogs in the game. In a duel, the players play their turns one by one
and can drink a potion before attacking (see game/potions.py); tournament
matches are simulated in one go, without potions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game import gear, players, potions, settings
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
    max_hp: float = 0.0
    attacks: int = 0
    hits_taken: int = 0
    potions_used: int = 0
    speed_turns: int = 0  # own turns left with the Speed potion

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp


@dataclass
class Hit:
    damage: float
    crit: bool


@dataclass
class Turn:
    attacker: int  # user id
    defender: int
    potion: str | None = None
    healed: float = 0.0
    direct: float = 0.0  # Harming damage
    hits: list[Hit] = field(default_factory=list)
    attacker_hp: float = 0.0
    defender_hp: float = 0.0


class Fight:
    """A duel being fought, one turn at a time. No database here."""

    def __init__(self, rng: random.Random, a: Fighter, b: Fighter):
        self.fighters = (a, b)
        self.index = rng.randint(0, 1)  # who plays now
        self.rounds = 0
        self.log: list[Turn] = []
        self.winner: Fighter | None = None

    @property
    def current(self) -> Fighter:
        return self.fighters[self.index]

    @property
    def other(self) -> Fighter:
        return self.fighters[1 - self.index]

    @property
    def over(self) -> bool:
        return self.winner is not None

    @property
    def loser(self) -> Fighter | None:
        if self.winner is None:
            return None
        return self.fighters[1] if self.winner is self.fighters[0] else self.fighters[0]

    def fighter(self, user_id: int) -> Fighter:
        return next(f for f in self.fighters if f.user_id == user_id)

    def potions_left(self, fighter: Fighter) -> int:
        return max(0, potions.max_per_duel() - fighter.potions_used)

    def check_potion(self, key: str) -> None:
        """Raise GameError if the current player can't drink this potion now."""
        potions.check(key)
        if self.over:
            raise GameError("The duel is over.")
        if self.potions_left(self.current) <= 0:
            raise GameError(f"You already drank {potions.max_per_duel()} potions in this duel.")

    def _hit(self, rng: random.Random, multiplier: float = 1.0) -> Hit:
        d = settings.get()["duel"]
        attacker, defender = self.current, self.other
        damage = attacker.attack * rng.uniform(1 - DAMAGE_VARIANCE, 1 + DAMAGE_VARIANCE) * multiplier
        crit = rng.random() < d["crit_chance"]
        if crit:
            damage *= d["crit_multiplier"]
        damage = max(0.5, damage * (1 - defender.reduction))
        defender.hp = max(0.0, defender.hp - damage)
        attacker.attacks += 1
        defender.hits_taken += 1
        return Hit(damage, crit)

    def play(self, rng: random.Random, potion: str | None = None) -> Turn:
        """The current player drinks `potion` (optional), then attacks."""
        if self.over:
            raise GameError("The duel is over.")
        p = settings.get()["potions"]
        attacker, defender = self.current, self.other
        turn = Turn(attacker.user_id, defender.user_id, potion)
        multiplier = 1.0
        if potion:
            self.check_potion(potion)
            attacker.potions_used += 1
            if potion == "healing":
                turn.healed = min(float(p["healing_hp"]), attacker.max_hp - attacker.hp)
                attacker.hp += turn.healed
            elif potion == "harming":
                turn.direct = min(float(p["harming_damage"]), defender.hp)
                defender.hp -= turn.direct
            elif potion == "speed":
                attacker.speed_turns = int(p["speed_turns"])
            elif potion == "strength":
                multiplier += float(p["strength_bonus"])

        if defender.hp > 0:
            turn.hits.append(self._hit(rng, multiplier))
        if attacker.speed_turns > 0:
            attacker.speed_turns -= 1
            if defender.hp > 0 and rng.random() < float(p["speed_chance"]):
                turn.hits.append(self._hit(rng))

        turn.attacker_hp, turn.defender_hp = round(attacker.hp, 1), round(defender.hp, 1)
        self.log.append(turn)
        self.rounds += 1
        if defender.hp <= 0:
            self.winner = attacker
        elif self.rounds >= int(settings.get()["duel"]["max_rounds"]):
            # Nobody fell: the one with the most health left wins (coin flip on a tie).
            a, b = self.fighters
            self.winner = self.fighters[rng.randint(0, 1)] if a.hp == b.hp else (a if a.hp > b.hp else b)
        else:
            self.index = 1 - self.index
        return turn

    def auto_play(self, rng: random.Random) -> None:
        """Play the remaining turns without potions."""
        while not self.over:
            self.play(rng)


@dataclass
class FightResult:
    winner: int  # index 0 or 1
    fight: Fight


def simulate(rng: random.Random, a: Fighter, b: Fighter) -> FightResult:
    """A whole fight in one go, without potions (tournament matches)."""
    fight = Fight(rng, a, b)
    fight.auto_play(rng)
    return FightResult(winner=fight.fighters.index(fight.winner), fight=fight)


def make_fighter(ctx: Ctx, user_id: int) -> tuple[Fighter, dict[str, dict]]:
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


# ---------------- a duel from start to finish ----------------
def start(ctx: Ctx, challenger_id: int, opponent_id: int, stake: int, rng: random.Random | None = None) -> dict:
    """Take both stakes and set up the fight. The stakes are held until `finish`."""
    if challenger_id == opponent_id:
        raise GameError("You can't duel yourself.")
    check_stake(ctx, challenger_id, stake)
    check_stake(ctx, opponent_id, stake)
    players.spend_emeralds(ctx, challenger_id, stake)
    players.spend_emeralds(ctx, opponent_id, stake)
    cur = ctx.execute(
        "INSERT INTO duels(challenger_id, opponent_id, stake, started_at) VALUES(?, ?, ?, ?);",
        (challenger_id, opponent_id, stake, int(ctx.now)),
    )
    a, _ = make_fighter(ctx, challenger_id)
    b, _ = make_fighter(ctx, opponent_id)
    return {
        "duel_id": int(cur.lastrowid),
        "fight": Fight(rng or ctx.rng, a, b),
        "potions": {challenger_id: potions.owned(ctx, challenger_id), opponent_id: potions.owned(ctx, opponent_id)},
    }


def finish(ctx: Ctx, duel_id: int, fight: Fight) -> dict:
    """Pay the winner, give XP and wear the gear out."""
    row = ctx.one("SELECT * FROM duels WHERE duel_id=?;", (duel_id,))
    if row is None or not fight.over:
        raise GameError("This duel is not running anymore.")
    ctx.execute("DELETE FROM duels WHERE duel_id=?;", (duel_id,))
    d = settings.get()["duel"]
    stake = row["stake"]
    winner, loser = fight.winner, fight.loser

    # The winner gets their stake back, and the opponent's stake counts as earned.
    players.give_emeralds(ctx, winner.user_id, stake)
    players.earn_emeralds(ctx, winner.user_id, stake)
    players.bump_stat(ctx, winner.user_id, "duels_won")
    players.bump_stat(ctx, loser.user_id, "duels_lost")
    players.bump_stat(ctx, winner.user_id, "duel_winnings", stake)
    players.add_xp(ctx, winner.user_id, int(d["xp_win"]))
    players.add_xp(ctx, loser.user_id, int(d["xp_loss"]))

    broken: list[tuple[int, str]] = []
    for fighter in fight.fighters:
        equipped = gear.get_equipped(ctx, fighter.user_id)
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
        "hp": {f.user_id: round(f.hp, 1) for f in fight.fighters},
        "max_hp": float(d["hp"]),
        "rounds": fight.rounds,
        "broken": broken,
    }


def refund_interrupted(ctx: Ctx) -> list[dict]:
    """Duels cut by a restart: both players get their stake back."""
    rows = [dict(r) for r in ctx.all("SELECT * FROM duels;")]
    for r in rows:
        players.give_emeralds(ctx, r["challenger_id"], r["stake"])
        players.give_emeralds(ctx, r["opponent_id"], r["stake"])
    ctx.execute("DELETE FROM duels;")
    return rows


def fight(ctx: Ctx, challenger_id: int, opponent_id: int, stake: int) -> dict:
    """A whole duel without potions, in one transaction."""
    setup = start(ctx, challenger_id, opponent_id, stake)
    setup["fight"].auto_play(ctx.rng)
    return finish(ctx, setup["duel_id"], setup["fight"])
