"""The fight of a raid (game/war.py): the attackers against the defenders, turn by turn (like the gate bosses).

Each player plays in turn (an attacker, then a defender, and so on): drink a potion, then Attack (a random enemy
still standing) or Attack + block (a shield stops the next hit on them). The team's 🛡️ Iron Golem fights with the
defenders by itself; after every round the 🏹 archers shoot at the attackers and the 🧱 walls lower every hit on
the defenders. A player who doesn't play in time attacks; after a few missed turns theirs play by themselves.
The fight ends when a side has nobody standing, or after war.raid_max_rounds rounds: the side with the most health
left wins (the defenders on a tie).
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field

from game import gear, potions, settings
from game.errors import GameError

GOLEM = 0  # the Iron Golem's user_id


def _cfg() -> dict:
    return settings.get()["war"]


@dataclass
class Fighter:
    user_id: int  # 0: the Iron Golem
    side: str  # attack | defend
    attack: float
    min_attack: float
    reduction: float
    hp: float
    max_hp: float = 0.0
    potion_boost: float = 0.0
    blocks_left: int = 0
    blocking: bool = False
    blocks_used: int = 0
    attacks: int = 0
    hits_taken: int = 0
    damage: float = 0.0
    potions_used: int = 0
    strong_potions_used: int = 0
    speed_turns: int = 0
    speed_chance: float = 0.0
    afk: int = 0
    downed_by: int | None = None  # who dealt the blow that made them fall (bounties)
    fire: float = 0.0  # Fire Aspect: health the target loses each round it burns
    thorns: float = 0.0  # Thorns: share of the damage taken sent back to the attacker
    burning: int = 0  # rounds left on fire
    burn_damage: float = 0.0
    burner: int | None = None  # whose fire it is (bounties)
    gear_ids: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def golem(self) -> bool:
        return self.user_id == GOLEM

    @property
    def mention(self) -> str:
        return "🛡️ the Iron Golem" if self.golem else f"<@{self.user_id}>"


@dataclass
class RaidFight:
    fighters: list[Fighter]
    walls: float = 0.0  # every hit on a defender is lowered by this
    arrows: int = 0  # the archers' arrows after every round
    arrow_damage: tuple[float, float] = (0.0, 0.0)
    index: int = 0
    rounds: int = 0
    drank: bool = False
    min_bonus: float = 0.0
    log: list[str] = field(default_factory=list)
    result: str | None = None  # attack | defend

    # ---- state ----
    @property
    def over(self) -> bool:
        return self.result is not None

    @property
    def current(self) -> Fighter:
        return self.fighters[self.index]

    def side(self, name: str) -> list[Fighter]:
        return [f for f in self.fighters if f.side == name]

    def fighter(self, user_id: int) -> Fighter:
        for f in self.fighters:
            if f.user_id == user_id and not f.golem:
                return f
        raise GameError("You're not in this fight.")

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> "RaidFight":
        data = json.loads(text)
        data["fighters"] = [Fighter(**f) for f in data["fighters"]]
        data["arrow_damage"] = tuple(data["arrow_damage"])
        return RaidFight(**data)

    @staticmethod
    def order(attackers: list[Fighter], defenders: list[Fighter]) -> list[Fighter]:
        """An attacker, a defender, an attacker…; the ones left at the end."""
        out: list[Fighter] = []
        for i in range(max(len(attackers), len(defenders))):
            out += [x[i] for x in (attackers, defenders) if i < len(x)]
        return out

    def potions_left(self, f: Fighter) -> int:
        return max(0, int(settings.get()["gate_bosses"]["max_potions"]) - f.potions_used)

    # ---- hits ----
    def _foes(self, f: Fighter) -> list[Fighter]:
        return [x for x in self.fighters if x.side != f.side and x.alive]

    def _strike(self, rng: random.Random, by: Fighter | None, target: Fighter, raw: float, what: str) -> str:
        """`by` (None: an arrow) hits `target` for `raw` before armor, walls and shield. Returns the log text."""
        if target.blocking:
            target.blocking = False
            target.blocks_used += 1
            return f"{what} {target.mention}: 🛡️ blocked"
        d = settings.get()["duel"]
        damage = max(float(d["min_hit_after_armor"]), raw * (1 - target.reduction))
        if target.side == "defend":
            damage *= 1 - self.walls
        before = target.hp
        target.hp = max(0.0, target.hp - damage)
        target.hits_taken += 1
        if by is not None:
            by.damage += before - target.hp
        down = ""
        if before > 0 and target.hp <= 0:
            target.downed_by = by.user_id if by is not None and not by.golem else None
            down = " ☠️"
        if by is None:
            return f"{what} {target.mention} -{damage:.1f}{down}"
        if by.fire > 0 and target.alive and (not target.burning or by.fire >= target.burn_damage):
            target.burning, target.burn_damage, target.burner = gear.burn_turns(), by.fire, by.user_id
        reflected = min(by.hp, damage * target.thorns)
        if reflected > 0:
            by.hp -= reflected
            target.damage += reflected
            if not by.alive:
                by.downed_by = None if target.golem else target.user_id
            down += f" · 🌵 -{reflected:.1f} to {by.mention}" + (" ☠️" if not by.alive else "")
        return f"{what} {target.mention} -{damage:.1f}{down}"

    def _burn(self) -> None:
        """At the end of a round, every fighter on fire loses health."""
        for f in self.fighters:
            if not f.alive or f.burning <= 0:
                continue
            f.burning -= 1
            damage = min(f.burn_damage, f.hp)
            f.hp -= damage
            for x in self.fighters:
                if x.user_id == f.burner and x.side != f.side:
                    x.damage += damage
            down = ""
            if not f.alive:
                f.downed_by = f.burner if f.burner else None
                down = " ☠️"
            self.log.append(f"🔥 {f.mention} burns -{damage:.1f}{down}")

    def _hit_raw(self, rng: random.Random, f: Fighter, min_bonus: float = 0.0) -> tuple[float, bool]:
        d = settings.get()["duel"]
        f.attacks += 1
        low = min(f.min_attack + min_bonus, f.attack)
        damage = rng.uniform(low, f.attack)
        crit = rng.random() < float(d["crit_chance"])
        return (damage * float(d["crit_multiplier"]) if crit else damage), crit

    def _swing(self, rng: random.Random, f: Fighter, min_bonus: float = 0.0) -> None:
        foes = self._foes(f)
        if not foes:
            return
        target = rng.choice(foes)
        raw, crit = self._hit_raw(rng, f, min_bonus)
        self.log.append(self._strike(rng, f, target, raw, f"⚔️ {f.mention}{' (critical!)' if crit else ''} →"))

    # ---- the players' turns ----
    def _check_turn(self, user_id: int) -> Fighter:
        if self.over:
            raise GameError("This fight is over.")
        if self.current.user_id != user_id or self.current.golem:
            raise GameError(f"It's {self.current.mention}'s turn.")
        return self.current

    def check_potion(self, user_id: int, key: str) -> None:
        f = self._check_turn(user_id)
        potions.check(key)
        if self.drank:
            raise GameError("You already drank a potion this turn: now attack!")
        if self.potions_left(f) <= 0:
            raise GameError("You already drank all the potions you can in this fight.")
        if potions.parse(key)[1] >= 2 and f.strong_potions_used >= potions.strong_per_fight():
            raise GameError(potions.strong_limit_text("fight"))
        if potions.parse(key)[0] == "healing" and f.hp >= f.max_hp:
            raise GameError("You are already at full health.")

    def drink(self, rng: random.Random, user_id: int, key: str) -> None:
        self.check_potion(user_id, key)
        f = self.current
        kind, level = potions.parse(key)
        boost = 1.0 + f.potion_boost
        f.potions_used += 1
        f.strong_potions_used += 1 if level >= 2 else 0
        self.drank = True
        if kind == "healing":
            healed = min(potions.effect(key, "healing_hp") * boost, f.max_hp - f.hp)
            f.hp += healed
            self.log.append(f"🧪 {f.mention} drinks {potions.label(key)}: +{healed:.1f} HP")
        elif kind == "harming":
            foes = self._foes(f)
            if foes:
                target = rng.choice(foes)
                self.log.append(self._strike(rng, f, target, potions.effect(key, "harming_damage") * boost,
                                             f"🧪 {f.mention} throws {potions.label(key)} at"))
            self._check_end()
        elif kind == "speed":
            f.speed_turns = int(settings.get()["potions"]["speed_turns"])
            f.speed_chance = min(1.0, potions.effect(key, "speed_chance") * boost)
            self.log.append(f"🧪 {f.mention} drinks {potions.label(key)}")
        elif kind == "strength":
            self.min_bonus = potions.effect(key, "strength_min_bonus") * boost
            self.log.append(f"🧪 {f.mention} drinks {potions.label(key)}")

    def attack(self, rng: random.Random, user_id: int, block: bool = False) -> None:
        f = self._check_turn(user_id)
        if block and f.blocks_left <= 0:
            raise GameError("Your shield can't block anymore in this fight." if f.blocks_used
                            else "You need a shield to block.")
        self._play(rng, f, block)

    def _play(self, rng: random.Random, f: Fighter, block: bool = False) -> None:
        self._swing(rng, f, self.min_bonus)
        if f.speed_turns > 0:
            f.speed_turns -= 1
            if f.alive and rng.random() < f.speed_chance:
                self._swing(rng, f)
        if block and f.alive:
            f.blocking = True
            f.blocks_left -= 1
        self.drank, self.min_bonus = False, 0.0
        if not self._check_end():
            self._next(rng)

    def _check_end(self) -> bool:
        if self.over:
            return True
        if not any(f.alive for f in self.side("defend")):
            self.result = "attack"
        elif not any(f.alive for f in self.side("attack")):
            self.result = "defend"
        return self.over

    def _next(self, rng: random.Random) -> None:
        """The next fighter standing (the golem plays by itself); after the last one, the archers and a new round."""
        while True:
            for i in range(self.index + 1, len(self.fighters)):
                if self.fighters[i].alive:
                    self.index = i
                    break
            else:
                self._end_round(rng)
                if self.over:
                    return
                self.index = next(i for i, f in enumerate(self.fighters) if f.alive)
            if not self.current.golem:
                return
            self._swing(rng, self.current)  # the golem's turn
            if self._check_end():
                return

    def _end_round(self, rng: random.Random) -> None:
        for _ in range(self.arrows):
            foes = [f for f in self.side("attack") if f.alive]
            if not foes:
                break
            self.log.append(self._strike(rng, None, rng.choice(foes), rng.uniform(*self.arrow_damage), "🏹 An arrow hits"))
        self._burn()
        self.rounds += 1
        if self._check_end():
            return
        if self.rounds >= int(_cfg()["raid_max_rounds"]):
            hp_a = sum(f.hp for f in self.side("attack"))
            hp_d = sum(f.hp for f in self.side("defend"))
            self.result = "attack" if hp_a > hp_d else "defend"
            self.log.append(f"⏱️ Time's up: {hp_a:.0f} HP left to the attackers, {hp_d:.0f} to the defenders.")

    def start(self, rng: random.Random) -> None:
        """Before the first turn: when the golem comes first, it plays."""
        if self.current.golem:
            self.index = -1
            self._next(rng)

    def auto_play(self, rng: random.Random) -> None:
        """Play the whole fight by itself (tests and calibration)."""
        self.start(rng)
        while not self.over:
            self._play(rng, self.current)

