"""Duels: both players bet the same stake, the winner takes the pot.

The fight is turn based and luck matters a lot:
- each hit deals a random amount between a minimum (1, raised by a Strength
  potion) and a maximum (raised by a better sword and Sharpness);
- a hit can be dodged, or be a critical hit;
- armor reduces the damage taken, but only up to a cap.
Better gear wins more often, not always. The player who plays second starts
with a few extra HP to make up for not striking first. In a duel the players
play their turns one by one and can drink a potion before attacking (see
game/potions.py); tournament matches are simulated in one go, without potions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game import gear, players, potions, settings
from game.catalog import ARMOR
from game.db import Ctx
from game.errors import GameError

@dataclass
class Fighter:
    user_id: int
    attack: float  # maximum damage of a hit
    reduction: float
    hp: float
    max_hp: float = 0.0
    min_attack: float = 1.0  # minimum damage of a hit
    attacks: int = 0
    hits_taken: int = 0
    potions_used: int = 0
    strong_potion_used: bool = False  # level II potions: one per duel
    speed_turns: int = 0  # own turns left with the Speed potion
    speed_chance: float = 0.0
    gear_ids: dict[str, int] = field(default_factory=dict)  # slot -> gear_id worn when the fight started

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp


@dataclass
class Hit:
    damage: float
    crit: bool
    dodged: bool = False


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
        # The turn being played: set when the current player drank a potion and hasn't attacked yet.
        self.pending: Turn | None = None
        self._min_bonus = 0.0
        # Striking first is an advantage: the other player starts with a few extra HP.
        second = self.fighters[1 - self.index]
        bonus = float(settings.get()["duel"]["second_player_bonus_hp"])
        second.hp += bonus
        second.max_hp += bonus

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
        if self.pending is not None:
            raise GameError("You already drank a potion this turn: now attack!")
        if self.potions_left(self.current) <= 0:
            raise GameError(f"You already drank {potions.max_per_duel()} potions in this duel.")
        if potions.parse(key)[1] >= 2 and self.current.strong_potion_used:
            raise GameError("Only one reinforced (II) potion per duel.")

    @property
    def can_drink(self) -> bool:
        return not self.over and self.pending is None and self.potions_left(self.current) > 0

    def _hit(self, rng: random.Random, min_bonus: float = 0.0) -> Hit:
        d = settings.get()["duel"]
        attacker, defender = self.current, self.other
        attacker.attacks += 1
        if rng.random() < float(d["dodge_chance"]):
            return Hit(0.0, False, dodged=True)
        low = min(attacker.min_attack + min_bonus, attacker.attack)
        damage = rng.uniform(low, attacker.attack)
        crit = rng.random() < d["crit_chance"]
        if crit:
            damage *= d["crit_multiplier"]
        damage = max(0.5, damage * (1 - defender.reduction))
        defender.hp = max(0.0, defender.hp - damage)
        defender.hits_taken += 1
        return Hit(damage, crit)

    def drink(self, potion: str) -> Turn:
        """The current player drinks a potion. The turn goes on: they attack next (see play)."""
        self.check_potion(potion)
        p = settings.get()["potions"]
        attacker, defender = self.current, self.other
        turn = Turn(attacker.user_id, defender.user_id, potion)
        kind, level = potions.parse(potion)
        attacker.potions_used += 1
        attacker.strong_potion_used = attacker.strong_potion_used or level >= 2
        if kind == "healing":
            turn.healed = min(potions.effect(potion, "healing_hp"), attacker.max_hp - attacker.hp)
            attacker.hp += turn.healed
        elif kind == "harming":
            # Armor softens it too (it used to ignore armor and decided duels on its own).
            damage = potions.effect(potion, "harming_damage") * (1 - defender.reduction)
            turn.direct = round(min(damage, defender.hp), 1)
            defender.hp = max(0.0, defender.hp - damage)
        elif kind == "speed":
            attacker.speed_turns = int(p["speed_turns"])
            attacker.speed_chance = min(1.0, potions.effect(potion, "speed_chance"))
        elif kind == "strength":
            self._min_bonus = potions.effect(potion, "strength_min_bonus")
        turn.attacker_hp, turn.defender_hp = round(attacker.hp, 1), round(defender.hp, 1)
        self.pending = turn
        return turn

    def play(self, rng: random.Random, potion: str | None = None) -> Turn:
        """The current player attacks, with the potion drunk this turn (or `potion`, drunk first)."""
        if self.over:
            raise GameError("The duel is over.")
        if potion:
            self.drink(potion)
        attacker, defender = self.current, self.other
        turn = self.pending or Turn(attacker.user_id, defender.user_id)
        min_bonus = self._min_bonus
        self.pending, self._min_bonus = None, 0.0

        if defender.hp > 0:
            turn.hits.append(self._hit(rng, min_bonus))
        if attacker.speed_turns > 0:
            attacker.speed_turns -= 1
            if defender.hp > 0 and rng.random() < attacker.speed_chance:
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
    fighter = Fighter(
        user_id, gear.attack_damage(equipped), gear.damage_reduction(equipped), hp,
        min_attack=float(settings.get()["duel"]["min_damage"]),
    )
    fighter.gear_ids = {slot: piece["gear_id"] for slot, piece in equipped.items()}
    return fighter, equipped


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

    # The pot only moves between the two players: it doesn't count for the seasons.
    players.give_emeralds(ctx, winner.user_id, stake * 2)
    players.bump_stat(ctx, winner.user_id, "duels_won")
    players.bump_stat(ctx, loser.user_id, "duels_lost")
    players.bump_stat(ctx, winner.user_id, "duel_winnings", stake)
    players.add_xp(ctx, winner.user_id, int(d["xp_win"]))
    players.add_xp(ctx, loser.user_id, int(d["xp_loss"]))

    broken: list[tuple[int, str]] = []
    for fighter in fight.fighters:
        # The pieces worn when the fight started, even if they were unequipped or traded since.
        equipped = gear.get_pieces(ctx, fighter.gear_ids)
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
