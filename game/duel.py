"""Duels: both players bet the same stake, the winner takes the pot.

The fight is turn based and luck matters a lot:
- each hit deals a random amount between a minimum (1, raised by a Strength
  potion) and a maximum (raised by a better sword and Sharpness);
- a hit can be a critical hit;
- with a shield, a player can end their turn with "Attack + block": the
  opponent's next attack (all its hits) is blocked, twice per duel at most.
  Nobody sees it coming: only "X blocked N damage" when it happens;
- armor reduces the damage taken, but only up to a cap.
Better gear wins more often, not always. The player who plays second starts
with a few extra HP to make up for not striking first. In a duel the players
play their turns one by one and can drink a potion before attacking (see
game/potions.py); tournament matches are simulated in one go, without potions.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from game import gear, players, potions, settings, species
from game.catalog import ARMOR, SHIELD
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
    strong_potions_used: int = 0  # level II potions: potions.strong_per_fight per duel
    speed_turns: int = 0  # own turns left with the Speed potion
    speed_chance: float = 0.0
    potion_boost: float = 0.0  # Witches: potion effects +X%
    blocks_left: int = 0  # blocks the shield still allows in this duel
    blocking: bool = False  # the shield is raised for the opponent's next attack
    blocks_used: int = 0
    blocked_damage: float = 0.0
    gear_ids: dict[str, int] = field(default_factory=dict)  # slot -> gear_id worn when the fight started

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp


@dataclass
class Hit:
    damage: float
    crit: bool
    blocked: bool = False  # by the defender's shield


@dataclass
class Turn:
    attacker: int  # user id
    defender: int
    potion: str | None = None
    healed: float = 0.0
    direct: float = 0.0  # Harming damage
    hits: list[Hit] = field(default_factory=list)
    blocked: float = 0.0  # damage the defender's shield stopped
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
        if potions.parse(key)[1] >= 2 and self.current.strong_potions_used >= potions.strong_per_fight():
            raise GameError(potions.strong_limit_text("duel"))
        if potions.parse(key)[0] == "healing" and self.current.hp >= self.current.max_hp:
            raise GameError("You are already at full health.")

    @property
    def can_drink(self) -> bool:
        return not self.over and self.pending is None and self.potions_left(self.current) > 0

    def _hit(self, rng: random.Random, min_bonus: float = 0.0) -> Hit:
        d = settings.get()["duel"]
        attacker, defender = self.current, self.other
        attacker.attacks += 1
        low = min(attacker.min_attack + min_bonus, attacker.attack)
        damage = rng.uniform(low, attacker.attack)
        crit = rng.random() < d["crit_chance"]
        if crit:
            damage *= d["crit_multiplier"]
        damage = max(float(d["min_hit_after_armor"]), damage * (1 - defender.reduction))
        if defender.blocking:
            return Hit(damage, crit, blocked=True)  # what it would have dealt
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
        boost = 1.0 + attacker.potion_boost
        attacker.potions_used += 1
        attacker.strong_potions_used += 1 if level >= 2 else 0
        if kind == "healing":
            turn.healed = min(potions.effect(potion, "healing_hp") * boost, attacker.max_hp - attacker.hp)
            attacker.hp += turn.healed
        elif kind == "harming":
            # Armor softens it too (it used to ignore armor and decided duels on its own).
            damage = potions.effect(potion, "harming_damage") * boost * (1 - defender.reduction)
            turn.direct = round(min(damage, defender.hp), 1)
            defender.hp = max(0.0, defender.hp - damage)
        elif kind == "speed":
            attacker.speed_turns = int(p["speed_turns"])
            attacker.speed_chance = min(1.0, potions.effect(potion, "speed_chance") * boost)
        elif kind == "strength":
            self._min_bonus = potions.effect(potion, "strength_min_bonus") * boost
        turn.attacker_hp, turn.defender_hp = round(attacker.hp, 1), round(defender.hp, 1)
        self.pending = turn
        return turn

    def play(self, rng: random.Random, potion: str | None = None, block: bool = False) -> Turn:
        """The current player attacks, with the potion drunk this turn (or `potion`, drunk first).

        `block`: then raise the shield against the opponent's next attack.
        """
        if self.over:
            raise GameError("The duel is over.")
        if block and self.current.blocks_left <= 0:
            raise GameError("Your shield can't block any more attacks in this duel.")
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
        if defender.blocking:  # this whole attack hit the shield
            turn.blocked = round(sum(h.damage for h in turn.hits if h.blocked), 1)
            defender.blocking = False
            defender.blocks_left -= 1
            defender.blocks_used += 1
            defender.blocked_damage += turn.blocked
        if block:
            attacker.blocking = True  # for the opponent's next attack (nobody is told)

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
    strength = 1.0 + species.bonus(ctx, user_id, "dwarf")  # Dwarves hit harder
    fighter = Fighter(
        user_id, float(gear.attack_damage(equipped)) * strength, gear.damage_reduction(equipped), hp,
        min_attack=float(settings.get()["duel"]["min_damage"]) * strength,
        potion_boost=species.bonus(ctx, user_id, "witch"),
        blocks_left=gear.shield_blocks(equipped),
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
def start(ctx: Ctx, challenger_id: int, opponent_id: int, stake: int, rng: random.Random | None = None,
          channel_id: int | None = None, message_id: int | None = None) -> dict:
    """Take both stakes and set up the fight. The stakes are held until `finish`.

    The message showing the fight is kept so a restart can tell the players their duel was undone."""
    if challenger_id == opponent_id:
        raise GameError("You can't duel yourself.")
    check_stake(ctx, challenger_id, stake)
    check_stake(ctx, opponent_id, stake)
    players.spend_emeralds(ctx, challenger_id, stake)
    players.spend_emeralds(ctx, opponent_id, stake)
    cur = ctx.execute(
        "INSERT INTO duels(challenger_id, opponent_id, stake, started_at, channel_id, message_id) "
        "VALUES(?, ?, ?, ?, ?, ?);",
        (challenger_id, opponent_id, stake, int(ctx.now), channel_id, message_id),
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
    from game import war  # war depends on this module

    war_points = war.on_duel(ctx, winner.user_id, loser.user_id)

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
        if fighter.blocks_used and SHIELD in equipped and gear.wear_shield(ctx, equipped[SHIELD], fighter.blocks_used):
            broken.append((fighter.user_id, "iron shield (worn out: /repair it)"))

    return {
        "winner": winner.user_id,
        "loser": loser.user_id,
        "stake": stake,
        "hp": {f.user_id: round(f.hp, 1) for f in fight.fighters},
        "max_hp": float(d["hp"]),
        "rounds": fight.rounds,
        "broken": broken,
        "war_points": war_points,
    }


def drink(ctx: Ctx, duel_id: int, user_id: int, key: str) -> None:
    """A potion drunk in a running duel: taken from the inventory, and noted to be given back if a restart
    cuts the duel."""
    potions.drink(ctx, user_id, key)
    row = ctx.one("SELECT potions FROM duels WHERE duel_id=?;", (duel_id,))
    if row is not None:
        drunk = json.loads(row["potions"]) + [[user_id, key]]
        ctx.execute("UPDATE duels SET potions=? WHERE duel_id=?;", (json.dumps(drunk), duel_id))


def refund_interrupted(ctx: Ctx) -> list[dict]:
    """Duels cut by a restart: both players get their stake and the potions they drank back."""
    rows = [dict(r) for r in ctx.all("SELECT * FROM duels;")]
    for r in rows:
        players.give_emeralds(ctx, r["challenger_id"], r["stake"])
        players.give_emeralds(ctx, r["opponent_id"], r["stake"])
        for user_id, key in json.loads(r["potions"]):
            potions.give(ctx, user_id, key)
            players.bump_stat(ctx, user_id, "potions_drunk", -1)
    ctx.execute("DELETE FROM duels;")
    return rows


def fight(ctx: Ctx, challenger_id: int, opponent_id: int, stake: int) -> dict:
    """A whole duel without potions, in one transaction."""
    setup = start(ctx, challenger_id, opponent_id, stake)
    setup["fight"].auto_play(ctx.rng)
    return finish(ctx, setup["duel_id"], setup["fight"])
