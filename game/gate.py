"""Gate bosses (/boss): the Wither, the Ender Dragon and the Warden open the next dimension.

- A boss lives in a dimension and guards the next one: the Wither (Nether → End), the Ender Dragon
  (End → Deep Dark) and the Warden (Deep Dark → Shimmer). The Nether itself opens by clearing the
  Nightmare dungeon (game/pve.py).
- A group of 1 to 4 players who reached the boss's dimension pays an entry each, then fights turn by turn:
  each player in order (they may drink a potion, then Attack or Attack + block with a shield), then the boss.
  A boss is made for 4: a smaller group faces only part of its health (its small_group_hp). Each player can drink
  gate_bosses.max_potions potions per fight. No move in time: the player attacks; after afk_turns missed turns
  in a row their turns play by themselves.
- The boss's turn: the Wither hits everyone and withers them (they lose health on its next turns); the
  Ender Dragon strikes players at random (twice a turn), and breathes on everyone every few turns; the Warden smashes one player,
  and every few turns its Sonic Boom ignores armor and shields. A raised shield blocks the next strike or hit
  aimed at its player (not the breath, the withering or the Sonic Boom).
- The survivors of a victory open the next dimension (if they hadn't yet) and get the bounty (less when they
  had already beaten it; Looting adds to it), a book (sometimes Mending) and XP. The dead get nothing.
- One fight every gate_bosses.cooldown_hours per player. Gear wears out like in duels.

This part is the fight itself (no database); the fights are stored below.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field

from game import beacon, cooldowns, dimensions, duel, enchants, gear, players, potions, settings
from game.catalog import ARMOR, DIMENSIONS, SHIELD
from game.db import Ctx
from game.errors import GameError


@dataclass(frozen=True)
class Boss:
    key: str
    name: str
    emoji: str
    home: str  # the dimension where it lives (the players must have reached it)
    opens: str  # the dimension its survivors open


BOSSES: dict[str, Boss] = {b.key: b for b in (
    Boss("wither", "Wither", "💀", "nether", "end"),
    Boss("ender_dragon", "Ender Dragon", "🐉", "end", "deep_dark"),
    Boss("warden", "Warden", "👁️", "deep_dark", "shimmer"),
)}


def _cfg() -> dict:
    return settings.get()["gate_bosses"]


def boss_cfg(key: str) -> dict:
    return _cfg()[key]


def label(key: str) -> str:
    b = BOSSES[key]
    return f"{b.emoji} {b.name}"


# ---------------- the fight ----------------
@dataclass
class Player:
    user_id: int
    attack: float  # maximum damage of a hit
    min_attack: float
    reduction: float
    hp: float
    max_hp: float = 0.0
    potion_boost: float = 0.0
    blocks_left: int = 0
    blocking: bool = False
    blocks_used: int = 0
    blocked_damage: float = 0.0
    attacks: int = 0
    hits_taken: int = 0
    damage: float = 0.0  # dealt to the boss
    potions_used: int = 0
    strong_potions_used: int = 0
    speed_turns: int = 0
    speed_chance: float = 0.0
    withered: int = 0  # boss turns left losing health to the Wither
    afk: int = 0  # turns missed in a row
    gear_ids: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.max_hp = self.max_hp or self.hp

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Fight:
    boss: str
    hp: float
    max_hp: float
    players: list[Player]
    index: int = 0  # whose turn it is (in players)
    rounds: int = 0  # boss turns played
    drank: bool = False  # the current player drank this turn
    min_bonus: float = 0.0  # Strength drunk this turn
    log: list[str] = field(default_factory=list)  # what happened since the last message (shown, then cleared)
    result: str | None = None  # "won" | "lost"

    # ---- state ----
    @property
    def over(self) -> bool:
        return self.result is not None

    @property
    def current(self) -> Player:
        return self.players[self.index]

    def player(self, user_id: int) -> Player:
        for p in self.players:
            if p.user_id == user_id:
                return p
        raise GameError("You're not in this fight.")

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> "Fight":
        data = json.loads(text)
        data["players"] = [Player(**p) for p in data["players"]]
        return Fight(**data)

    def potions_left(self, p: Player) -> int:
        return max(0, int(_cfg()["max_potions"]) - p.potions_used)

    # ---- the players' turns ----
    def _check_turn(self, user_id: int) -> Player:
        if self.over:
            raise GameError("This fight is over.")
        if self.current.user_id != user_id:
            raise GameError(f"It's <@{self.current.user_id}>'s turn.")
        return self.current

    def check_potion(self, user_id: int, key: str) -> None:
        p = self._check_turn(user_id)
        potions.check(key)
        if self.drank:
            raise GameError("You already drank a potion this turn: now attack!")
        if self.potions_left(p) <= 0:
            raise GameError(f"You already drank {_cfg()['max_potions']} potions in this fight.")
        if potions.parse(key)[1] >= 2 and p.strong_potions_used >= potions.strong_per_fight():
            raise GameError(potions.strong_limit_text("fight"))
        if potions.parse(key)[0] == "healing" and p.hp >= p.max_hp:
            raise GameError("You are already at full health.")

    def drink(self, user_id: int, key: str) -> None:
        """The current player drinks a potion; their turn goes on (they attack next)."""
        self.check_potion(user_id, key)
        p = self.current
        kind, level = potions.parse(key)
        boost = 1.0 + p.potion_boost
        p.potions_used += 1
        p.strong_potions_used += 1 if level >= 2 else 0
        self.drank = True
        if kind == "healing":
            healed = min(potions.effect(key, "healing_hp") * boost, p.max_hp - p.hp)
            p.hp += healed
            self.log.append(f"🧪 <@{p.user_id}> drinks {potions.label(key)}: +{healed:.1f} HP")
        elif kind == "harming":
            damage = min(potions.effect(key, "harming_damage") * boost, self.hp)
            self.hp -= damage
            p.damage += damage
            self.log.append(f"🧪 <@{p.user_id}> throws {potions.label(key)}: {damage:.1f} damage")
        elif kind == "speed":
            p.speed_turns = int(settings.get()["potions"]["speed_turns"])
            p.speed_chance = min(1.0, potions.effect(key, "speed_chance") * boost)
            self.log.append(f"🧪 <@{p.user_id}> drinks {potions.label(key)}")
        elif kind == "strength":
            self.min_bonus = potions.effect(key, "strength_min_bonus") * boost
            self.log.append(f"🧪 <@{p.user_id}> drinks {potions.label(key)}")
        self._check_won()

    def _hit(self, rng: random.Random, p: Player, min_bonus: float = 0.0) -> float:
        d = settings.get()["duel"]
        p.attacks += 1
        low = min(p.min_attack + min_bonus, p.attack)
        damage = rng.uniform(low, p.attack)
        crit = rng.random() < float(d["crit_chance"])
        if crit:
            damage *= float(d["crit_multiplier"])
        damage = min(damage, self.hp)
        self.hp -= damage
        p.damage += damage
        return damage if not crit else -damage  # negative: a critical hit (for the log)

    def attack(self, rng: random.Random, user_id: int, block: bool = False) -> None:
        """The current player attacks (`block`: then raises the shield). Then the next player, or the boss."""
        p = self._check_turn(user_id)
        if block and p.blocks_left <= 0:
            raise GameError("Your shield can't block anymore in this fight." if p.blocks_used
                            else "You need a shield to block.")
        if self.hp > 0:
            hits = [self._hit(rng, p, self.min_bonus)]
            if p.speed_turns > 0:
                p.speed_turns -= 1
                if self.hp > 0 and rng.random() < p.speed_chance:
                    hits.append(self._hit(rng, p))
            text = " + ".join(f"**{-h:.1f}** (critical!)" if h < 0 else f"{h:.1f}" for h in hits)
            self.log.append(f"⚔️ <@{p.user_id}> hits for {text}" + (" and raises their shield" if block else ""))
        if block:
            p.blocking = True
        self.drank, self.min_bonus = False, 0.0
        if not self._check_won():
            self._next(rng)

    def _check_won(self) -> bool:
        if self.hp <= 0 and not self.over:
            self.hp = 0.0
            self.result = "won"
            b = BOSSES[self.boss]
            self.log.append(f"🏆 **The {b.name} is defeated!**")
        return self.over

    def _next(self, rng: random.Random) -> None:
        """The next living player, or the boss's turn when everyone played."""
        for i in range(self.index + 1, len(self.players)):
            if self.players[i].alive:
                self.index = i
                return
        self.boss_turn(rng)
        if not self.over:
            self.index = next(i for i, p in enumerate(self.players) if p.alive)

    # ---- the boss's turn ----
    def _strike(self, rng: random.Random, p: Player, low: float, high: float, *, armor: bool = True,
                blockable: bool = True) -> float:
        """The boss hits a player. Returns the damage (0 when the shield blocked it)."""
        damage = rng.uniform(low, high)
        if rng.random() < float(_cfg()["crit_chance"]):
            damage *= float(_cfg()["crit_multiplier"])
        if armor:
            damage = max(float(_cfg()["min_hit_after_armor"]), damage * (1 - p.reduction))
        if blockable and p.blocking:
            p.blocking = False
            p.blocks_left -= 1
            p.blocks_used += 1
            p.blocked_damage += damage
            return 0.0
        p.hp = max(0.0, p.hp - damage)
        p.hits_taken += 1
        return damage

    def boss_turn(self, rng: random.Random) -> None:
        c = boss_cfg(self.boss)
        b = BOSSES[self.boss]
        alive = [p for p in self.players if p.alive]
        self.rounds += 1
        if self.boss == "wither":
            for p in alive:  # the withering of its last turns
                if p.withered > 0:
                    p.withered -= 1
                    loss = min(float(c["wither_damage"]), p.hp)
                    p.hp = max(0.0, p.hp - loss)
                    self.log.append(f"🖤 <@{p.user_id}> withers: -{max(loss, 0.1):.1f} HP")
            parts = []
            for p in [p for p in alive if p.alive]:
                dealt = self._strike(rng, p, float(c["min_damage"]), float(c["max_damage"]))
                if dealt:
                    p.withered = int(c["wither_turns"])
                    parts.append(f"<@{p.user_id}> -{dealt:.1f}")
                else:
                    parts.append(f"<@{p.user_id}> 🛡️ blocked")
            if parts:
                self.log.append(f"{b.emoji} The Wither blasts everyone: " + ", ".join(parts))
        elif self.boss == "ender_dragon":
            if self.rounds % int(c["breath_every"]) == 0:
                parts = [f"<@{p.user_id}> -{self._strike(rng, p, float(c['breath_min']), float(c['breath_max']), blockable=False):.1f}"
                         for p in alive]
                self.log.append(f"{b.emoji} The Ender Dragon breathes fire on everyone: " + ", ".join(parts))
            else:
                for _ in range(int(c["strikes"])):
                    targets = [p for p in alive if p.alive]
                    if not targets:
                        break
                    p = rng.choice(targets)
                    dealt = self._strike(rng, p, float(c["min_damage"]), float(c["max_damage"]))
                    self.log.append(f"{b.emoji} The Ender Dragon strikes <@{p.user_id}>: "
                                    + (f"-{dealt:.1f}" if dealt else "🛡️ blocked!"))
        else:  # the Warden
            p = rng.choice(alive)
            if self.rounds % int(c["boom_every"]) == 0:
                dealt = self._strike(rng, p, float(c["boom_min"]), float(c["boom_max"]), armor=False, blockable=False)
                self.log.append(f"{b.emoji} **Sonic Boom** on <@{p.user_id}>: -{dealt:.1f} (no armor or shield stops it)")
            else:
                dealt = self._strike(rng, p, float(c["min_damage"]), float(c["max_damage"]))
                self.log.append(f"{b.emoji} The Warden smashes <@{p.user_id}>: "
                                + (f"-{dealt:.1f}" if dealt else "🛡️ blocked!"))
        for p in alive:
            if not p.alive:
                self.log.append(f"☠️ <@{p.user_id}> falls.")
        if not any(p.alive for p in self.players):
            self.result = "lost"
            self.log.append(f"💀 **Everyone fell. The {b.name} wins.**")
        elif self.rounds >= int(_cfg()["max_rounds"]):
            self.result = "lost"
            self.log.append(f"⌛ **The {b.name} outlasted you.**")

    def auto_play(self, rng: random.Random) -> None:
        """Play the remaining turns: everyone attacks (tests and simulations)."""
        while not self.over:
            self.attack(rng, self.current.user_id)


def boss_hp(key: str, group: int) -> float:
    """A boss is made for a full group: a smaller one faces a share of its health (small_group_hp)."""
    full = int(_cfg()["max_players"])
    shares = boss_cfg(key)["small_group_hp"]
    share = 1.0 if group >= full else float(shares[min(max(1, group), len(shares)) - 1])
    return float(boss_cfg(key)["boss_hp"]) * share


def make_player(ctx: Ctx, user_id: int) -> Player:
    """A player as they go in: their gear and species like in a duel, and the Beacon's strength and resistance."""
    f, equipped = duel.make_fighter(ctx, user_id)
    strength, resistance = beacon.combat(ctx)
    p = Player(user_id, f.attack * (1 + strength), f.min_attack * (1 + strength),
               1 - (1 - f.reduction) * (1 - resistance), float(_cfg()["hp"]), potion_boost=f.potion_boost,
               blocks_left=f.blocks_left)
    p.gear_ids = dict(f.gear_ids)
    return p


def new_fight(key: str, heroes: list[Player]) -> Fight:
    hp = boss_hp(key, len(heroes))
    return Fight(key, hp, hp, heroes)


# ---------------- the fights (database) ----------------
MINUTE, HOUR = 60, 3600


def get(ctx: Ctx, fight_id: int) -> dict:
    row = ctx.one("SELECT * FROM gate_fights WHERE fight_id=?;", (fight_id,))
    if row is None:
        raise GameError("This boss fight doesn't exist anymore.")
    out = dict(row)
    out["members"] = [r["user_id"] for r in ctx.all(
        "SELECT user_id FROM gate_members WHERE fight_id=? ORDER BY joined_at, rowid;", (fight_id,))]
    out["fight"] = Fight.from_json(row["state"]) if row["state"] else None
    return out


def _open_fight_of(ctx: Ctx, user_id: int) -> int | None:
    row = ctx.one(
        """
        SELECT f.fight_id FROM gate_fights f JOIN gate_members m ON m.fight_id = f.fight_id
        WHERE m.user_id=? AND f.status IN ('lobby', 'active');
        """,
        (user_id,),
    )
    return int(row["fight_id"]) if row else None


def ready_at(ctx: Ctx, user_id: int) -> int:
    """When the player can fight a boss again (0: now)."""
    row = ctx.one(
        """
        SELECT MAX(f.started_at) AS t FROM gate_fights f JOIN gate_members m ON m.fight_id = f.fight_id
        WHERE m.user_id=? AND f.started_at IS NOT NULL;
        """,
        (user_id,),
    )
    last = row["t"]
    if last is None or cooldowns.cleared(ctx, user_id, "boss", last):
        return 0
    ready = int(last + float(_cfg()["cooldown_hours"]) * HOUR)
    return ready if ready > ctx.now else 0


def _check_can_enter(ctx: Ctx, user_id: int, key: str) -> None:
    b = BOSSES[key]
    if not dimensions.has(ctx, user_id, b.home):
        raise GameError(f"The {b.name} lives in the {dimensions.label(b.home)}: <@{user_id}> hasn't reached it yet.")
    if _open_fight_of(ctx, user_id):
        raise GameError(f"<@{user_id}> is already in a boss fight.")
    ready = ready_at(ctx, user_id)
    if ready:
        raise GameError(f"<@{user_id}> is still recovering from their last boss fight: ready <t:{ready}:R>.")


def _pay_entry(ctx: Ctx, fight_id: int, user_id: int, key: str) -> int:
    entry = int(boss_cfg(key)["entry"])
    players.spend_emeralds(ctx, user_id, entry)
    ctx.execute("INSERT INTO gate_members(fight_id, user_id, joined_at, entry) VALUES(?, ?, ?, ?);",
                (fight_id, user_id, int(ctx.now), entry))
    return entry


def create(ctx: Ctx, user_id: int, key: str) -> dict:
    """Open a group to fight a boss: the leader pays the entry first."""
    if key not in BOSSES:
        raise GameError(f"Unknown boss. Pick one of: {', '.join(BOSSES)}.")
    _check_can_enter(ctx, user_id, key)
    cur = ctx.execute(
        "INSERT INTO gate_fights(boss, leader_id, created_at, deadline) VALUES(?, ?, ?, ?);",
        (key, user_id, int(ctx.now), int(ctx.now + float(_cfg()["lobby_minutes"]) * MINUTE)),
    )
    fight_id = int(cur.lastrowid)
    _pay_entry(ctx, fight_id, user_id, key)
    return get(ctx, fight_id)


def set_message(ctx: Ctx, fight_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE gate_fights SET channel_id=?, message_id=? WHERE fight_id=?;",
                (channel_id, message_id, fight_id))


def _lobby(ctx: Ctx, fight_id: int) -> dict:
    row = get(ctx, fight_id)
    if row["status"] != "lobby":
        raise GameError("This group already left (or was cancelled).")
    return row


def join(ctx: Ctx, fight_id: int, user_id: int) -> dict:
    row = _lobby(ctx, fight_id)
    if user_id in row["members"]:
        raise GameError("You're already in this group.")
    if len(row["members"]) >= int(_cfg()["max_players"]):
        raise GameError(f"The group is full ({_cfg()['max_players']} players).")
    _check_can_enter(ctx, user_id, row["boss"])
    _pay_entry(ctx, fight_id, user_id, row["boss"])
    return get(ctx, fight_id)


def _refund(ctx: Ctx, fight_id: int, user_id: int) -> None:
    row = ctx.one("SELECT entry FROM gate_members WHERE fight_id=? AND user_id=?;", (fight_id, user_id))
    if row is not None:
        players.give_emeralds(ctx, user_id, int(row["entry"]))
        ctx.execute("DELETE FROM gate_members WHERE fight_id=? AND user_id=?;", (fight_id, user_id))


def _cancel(ctx: Ctx, row: dict) -> dict:
    for uid in row["members"]:
        _refund(ctx, row["fight_id"], uid)
    ctx.execute("UPDATE gate_fights SET status='cancelled', ended_at=? WHERE fight_id=?;",
                (int(ctx.now), row["fight_id"]))
    return {**get(ctx, row["fight_id"]), "members": row["members"]}


def leave_lobby(ctx: Ctx, fight_id: int, user_id: int) -> dict:
    """Leave a group before it starts (entry given back). The leader leaving cancels the group."""
    row = _lobby(ctx, fight_id)
    if user_id not in row["members"]:
        raise GameError("You're not in this group.")
    if user_id == row["leader_id"]:
        return _cancel(ctx, row)
    _refund(ctx, fight_id, user_id)
    return get(ctx, fight_id)


def start(ctx: Ctx, fight_id: int, user_id: int) -> dict:
    """The leader starts the fight: each member's gear, as worn now, goes in."""
    row = _lobby(ctx, fight_id)
    if user_id != row["leader_id"]:
        raise GameError("Only the group's leader can start the fight.")
    fight = new_fight(row["boss"], [make_player(ctx, uid) for uid in row["members"]])
    fight.log.append(f"{label(row['boss'])} appears with **{fight.hp:.0f} HP**! "
                     + " → ".join(f"<@{uid}>" for uid in row["members"]) + " → the boss.")
    for uid in row["members"]:
        players.bump_stat(ctx, uid, "gate_fights")
    ctx.execute(
        "UPDATE gate_fights SET status='active', state=?, started_at=?, deadline=? WHERE fight_id=?;",
        (fight.to_json(), int(ctx.now), int(ctx.now + int(_cfg()["turn_seconds"])), fight_id),
    )
    return get(ctx, fight_id)


def _active(ctx: Ctx, fight_id: int) -> dict:
    row = get(ctx, fight_id)
    if row["status"] != "active":
        raise GameError("This fight is over." if row["status"] in ("won", "lost") else "This fight hasn't started.")
    return row


def _auto_turns(ctx: Ctx, fight: Fight) -> None:
    """Players who missed afk_turns turns in a row: their turns play by themselves."""
    while not fight.over and fight.current.afk >= int(_cfg()["afk_turns"]):
        fight.attack(ctx.rng, fight.current.user_id)


def _save(ctx: Ctx, row: dict, fight: Fight) -> dict:
    _auto_turns(ctx, fight)
    if fight.over:
        return _finish(ctx, row, fight)
    ctx.execute("UPDATE gate_fights SET state=?, deadline=? WHERE fight_id=?;",
                (fight.to_json(), int(ctx.now + int(_cfg()["turn_seconds"])), row["fight_id"]))
    return get(ctx, row["fight_id"])


def drink(ctx: Ctx, fight_id: int, user_id: int, key: str) -> dict:
    """The current player drinks a potion from their inventory, then still has to attack."""
    row = _active(ctx, fight_id)
    fight = row["fight"]
    fight.check_potion(user_id, key)
    potions.drink(ctx, user_id, key)
    fight.drink(user_id, key)
    fight.current.afk = 0
    if fight.over:
        return _finish(ctx, row, fight)
    ctx.execute("UPDATE gate_fights SET state=? WHERE fight_id=?;", (fight.to_json(), fight_id))
    return get(ctx, fight_id)


def attack(ctx: Ctx, fight_id: int, user_id: int, block: bool = False) -> dict:
    row = _active(ctx, fight_id)
    fight = row["fight"]
    fight.player(user_id).afk = 0
    fight.attack(ctx.rng, user_id, block)
    return _save(ctx, row, fight)


def clear_log(ctx: Ctx, fight_id: int) -> None:
    """The log was shown: start a new one."""
    row = ctx.one("SELECT state FROM gate_fights WHERE fight_id=? AND status='active';", (fight_id,))
    if row is not None:
        fight = Fight.from_json(row["state"])
        fight.log = []
        ctx.execute("UPDATE gate_fights SET state=? WHERE fight_id=?;", (fight.to_json(), fight_id))


def _finish(ctx: Ctx, row: dict, fight: Fight) -> dict:
    """Wear the gear out; the survivors of a victory open the next dimension and get the rewards."""
    b = BOSSES[row["boss"]]
    c = boss_cfg(row["boss"])
    ench = settings.get()["enchants"]
    rewards: dict[int, dict] = {}
    for p in fight.players:
        players.bump_stat(ctx, p.user_id, "boss_damage", int(round(p.damage)))
        pieces = gear.get_pieces(ctx, p.gear_ids)  # the pieces worn when the fight started
        sword = pieces.get("sword")
        if sword and p.attacks:
            gear.wear(ctx, sword, p.attacks)
        for slot in ARMOR:
            if pieces.get(slot) and p.hits_taken:
                gear.wear(ctx, pieces[slot], p.hits_taken)
        if p.blocks_used and SHIELD in pieces:
            gear.wear_shield(ctx, pieces[SHIELD], p.blocks_used)
        if fight.result != "won" or not p.alive:
            continue
        opened = dimensions.unlock(ctx, p.user_id, b.opens)
        bounty = int(c["bounty"]) if opened else int(int(c["bounty"]) * float(_cfg()["repeat_reward"]))
        looting = int(bounty * enchants.effect(sword, "looting")) if sword else 0
        players.earn_emeralds(ctx, p.user_id, bounty + looting)
        players.add_xp(ctx, p.user_id, int(c["xp"]))
        if ctx.rng.random() < float(ench["boss_mending_chance"]):
            book = ("mending", 1)  # the rarest book, now and then
            enchants.give_book(ctx, p.user_id, *book)
            players.bump_stat(ctx, p.user_id, "books_found")
        else:
            book = enchants.give_random_book(ctx, p.user_id, ench["boss_book_weights"])
        players.bump_stat(ctx, p.user_id, "bosses_defeated")
        players.bump_stat(ctx, p.user_id, f"{row['boss']}_defeated")
        rewards[p.user_id] = {"opened": b.opens if opened else None, "bounty": bounty, "looting": looting,
                              "book": enchants.label(*book), "xp": int(c["xp"])}
    # The first Wither ever beaten leaves a Nether Star: it lights the server's Beacon.
    lit = bool(fight.result == "won" and row["boss"] == "wither" and rewards
               and beacon.light(ctx, next(iter(rewards))))
    ctx.execute("UPDATE gate_fights SET status=?, state=?, ended_at=? WHERE fight_id=?;",
                (fight.result, fight.to_json(), int(ctx.now), row["fight_id"]))
    return {**get(ctx, row["fight_id"]), "rewards": rewards, "beacon_lit": lit}


def expire(ctx: Ctx) -> list[dict]:
    """Called every few seconds: lobbies not started in time are cancelled (entries back), and a player who
    didn't play in time attacks (their afk count grows)."""
    out = []
    for r in ctx.all("SELECT fight_id, status FROM gate_fights WHERE status IN ('lobby', 'active') AND deadline <= ?;",
                     (int(ctx.now),)):
        row = get(ctx, r["fight_id"])
        if row["status"] == "lobby":
            out.append({**_cancel(ctx, row), "expired": True})
            continue
        fight = row["fight"]
        p = fight.current
        p.afk += 1
        fight.log.append(f"⏳ <@{p.user_id}> didn't play in time: they attack.")
        fight.attack(ctx.rng, p.user_id)
        out.append(_save(ctx, row, fight))
    return out
