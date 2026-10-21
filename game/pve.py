"""PVE dungeon (/pve): 5 waves of monsters, alone or in a group of up to `max_players` (5).

- Waves: 1 zombies, 2 skeletons (they shoot before the first attack), 3 both,
  4 spiders (two bites a turn), a creeper (it explodes on its 2nd turn unless
  killed before) and a skeleton, 5 a mix with a Ravager. Every wave is
  `wave_growth` stronger than the previous one, and the difficulty multiplies
  the monsters' health and damage. A group faces as many monsters per player.
- Health is not restored between waves. Each wave plays out automatically;
  between waves every member says they're ready (the next wave starts when they
  all are) or leaves with their loot, and anyone can drink a potion (it heals
  now, or helps during the next wave). No answer in time = leaving with the loot.
- The loot of every wave cleared adds up, but a player who dies loses it (and
  the entry fee). Clearing wave 5 adds `clear_bonus` and pays everyone left.
- Clearing the Nightmare difficulty opens the **Nether** to the members still there at the end of wave 5.
- Gear works like in duels (Dwarves hit harder, Witches drink better). The sword
  wears out like in duels (1 per attack), but each hit taken wears only one armor
  piece (drawn at random) instead of all four: the monsters hit often and softly.

This part is the fight itself (no database); the runs are below.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field

from game import beacon, biomes, cooldowns, dimensions, duel, gear, players, potions, settings, teams
from game.db import Ctx
from game.errors import GameError

MAX_ROUNDS = 60
NETHER_GATE = "nightmare"  # clearing it opens the Nether (game/dimensions.py)


@dataclass(frozen=True)
class Kind:
    key: str
    name: str
    emoji: str
    ranged: bool = False  # attacks once before the heroes' first turn
    bites: int = 1  # attacks per turn
    fuse: int = 0  # explodes on this turn (then it's gone), 0 = never

    @property
    def hp(self) -> float:
        """Health at strength 1 (settings pve.monsters)."""
        return float(_cfg()["monsters"][self.key]["hp"])

    @property
    def dmg(self) -> tuple[float, float]:
        m = _cfg()["monsters"][self.key]
        return float(m["min_damage"]), float(m["max_damage"])


# Their health and damage are settings (pve.monsters).
MONSTERS: dict[str, Kind] = {k.key: k for k in (
    Kind("zombie", "Zombie", "🧟"),
    Kind("skeleton", "Skeleton", "💀", ranged=True),
    Kind("spider", "Spider", "🕷️", bites=2),
    Kind("creeper", "Creeper", "🟩", fuse=2),
    Kind("ravager", "Ravager", "🐂"),
    Kind("phantom", "Phantom", "👻"),  # only at night (game/night.py), never in the dungeon's waves
)}
WAVES: tuple[tuple[tuple[str, int], ...], ...] = (
    (("zombie", 3),),
    (("skeleton", 3),),
    (("zombie", 2), ("skeleton", 2)),
    (("spider", 2), ("creeper", 1), ("skeleton", 1)),
    (("zombie", 2), ("skeleton", 1), ("ravager", 1)),
)
DIFFICULTIES: dict[str, tuple[str, str]] = {
    "easy": ("Easy", "🟢"),
    "normal": ("Normal", "🟡"),
    "hard": ("Hard", "🟠"),
    "hardcore": ("Hardcore", "🔴"),
    "nightmare": ("Nightmare", "💀"),
}


def _cfg() -> dict:
    return settings.get()["pve"]


def label(difficulty: str) -> str:
    name, emoji = DIFFICULTIES[difficulty]
    return f"{emoji} {name}"


def wave_text(wave: int, players_count: int = 1, difficulty: str | None = None) -> str:
    """'3 🧟 Zombie, 2 💀 Skeleton' for wave 1..5."""
    return ", ".join(f"{group_count(n, players_count, difficulty)} {MONSTERS[k].emoji} {MONSTERS[k].name}"
                     for k, n in WAVES[wave - 1])


def group_count(count: int, heroes: int, difficulty: str | None = None) -> int:
    """How many of a wave's monsters a group of `heroes` faces: pve.group_monsters per extra player, or the
    difficulty's own share (Nightmare: fewer, it's a raid for a full group)."""
    c = _cfg()
    per = float(c["difficulties"][difficulty].get("group_monsters", c["group_monsters"]) if difficulty
                else c["group_monsters"])
    return count + round(count * per * (max(1, heroes) - 1))


def strength(difficulty: str, wave: int) -> float:
    """Multiplier of the monsters' health and damage."""
    c = _cfg()
    return float(c["difficulties"][difficulty]["strength"]) * (1 + float(c["wave_growth"])) ** (wave - 1)


def wave_reward(difficulty: str, wave: int) -> int:
    return round(int(_cfg()["wave_rewards"][wave - 1]) * float(_cfg()["difficulties"][difficulty]["reward"]))


# ---------------- the fight ----------------
@dataclass
class Hero:
    user_id: int
    attack: float  # maximum damage of a hit
    min_attack: float
    reduction: float
    hp: float
    max_hp: float
    potion_boost: float = 0.0  # Witches
    strength: float = 0.0  # next wave: minimum damage +X (Strength potion)
    speed: float = 0.0  # next wave: chance of a second hit (Speed potion)
    harming: float = 0.0  # start of the next wave: damage to every monster (Harming potion)
    attacks: int = 0
    hits_taken: int = 0
    gear_ids: dict[str, int] = field(default_factory=dict)
    fire: float = 0.0  # Fire Aspect: health a monster loses each round it burns
    thorns: float = 0.0  # Thorns: share of the damage taken sent back to the monster
    sweep: float = 0.0  # Sweeping Edge: share of each hit that also hits another monster

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class Monster:
    kind: str
    hp: float
    dmg: tuple[float, float]
    fuse: int = 0
    burning: int = 0  # rounds left on fire (Fire Aspect)
    burn: float = 0.0
    burner: int = 0  # whose fire it is (their kill)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def name(self) -> str:
        k = MONSTERS[self.kind]
        return f"{k.emoji} {k.name}"


def make_hero(ctx: Ctx, user_id: int) -> Hero:
    """A player as a hero: their gear and species, like in a duel."""
    f, equipped = duel.make_fighter(ctx, user_id)
    hp = float(_cfg()["hp"])
    strength, resistance = beacon.combat(ctx)  # the server's Beacon
    team = teams.chest_bonus(ctx, user_id, "combat")  # the team chest's Combat bonus
    strength += team
    taken = biomes.multiplier(ctx, "damage_taken") * (1 - team)  # the week's biome
    return Hero(user_id, f.attack * (1 + strength), f.min_attack * (1 + strength),
                1 - (1 - f.reduction) * (1 - resistance) * taken, hp, hp, f.potion_boost,
                gear_ids={slot: piece["gear_id"] for slot, piece in equipped.items()},
                fire=f.fire, thorns=f.thorns, sweep=gear.sweep(equipped))


def spawn(wave: int, difficulty: str, heroes: int) -> list[Monster]:
    mult = strength(difficulty, wave)
    out = []
    for kind, count in WAVES[wave - 1]:
        k = MONSTERS[kind]
        for _ in range(group_count(count, heroes, difficulty)):
            out.append(Monster(kind, k.hp * mult, (k.dmg[0] * mult, k.dmg[1] * mult), k.fuse))
    return out


def _target(monsters: list[Monster]) -> Monster | None:
    """Heroes kill creepers first, then finish off the weakest monster."""
    alive = [m for m in monsters if m.alive]
    if not alive:
        return None
    return min(alive, key=lambda m: (m.fuse == 0, m.fuse, m.hp))


def fight_wave(rng: random.Random, heroes: list[Hero], wave: int, difficulty: str,
               monsters: list[Monster] | None = None) -> dict:
    """Play one wave (or these `monsters`: the night's, game/night.py). Heroes are changed in place.
    Returns {"cleared", "log", "deaths"}."""
    d = settings.get()["duel"]
    crit_chance, crit_mult = float(d["crit_chance"]), float(d["crit_multiplier"])
    fighting = [h for h in heroes if h.alive]
    monsters = spawn(wave, difficulty, len(fighting)) if monsters is None else monsters
    log: list[str] = []
    deaths: list[int] = []
    kills: dict[int, int] = {h.user_id: 0 for h in fighting}
    dealt: dict[int, float] = {h.user_id: 0.0 for h in fighting}  # damage to monsters (the combat challenge)

    def strike(uid: int, m: Monster, damage: float) -> None:
        """A hero's damage to a monster: what it really took counts (not the overkill)."""
        if uid in dealt:
            dealt[uid] += min(damage, max(0.0, m.hp))
        m.hp -= damage

    def hurt(hero: Hero, damage: float, by: Monster, exploded: bool = False) -> None:
        damage = max(float(_cfg()["min_hit_after_armor"]), damage * (1 - hero.reduction))
        hero.hp = max(0.0, hero.hp - damage)
        hero.hits_taken += 1
        if hero.thorns > 0 and not exploded and by.alive:
            strike(hero.user_id, by, damage * hero.thorns)
            if not by.alive:
                kills[hero.user_id] += 1
        if exploded:
            log.append(f"💥 A {by.name} exploded on <@{hero.user_id}> (-{damage:.1f} HP)")
        if not hero.alive:
            deaths.append(hero.user_id)
            log.append(f"☠️ <@{hero.user_id}> was killed by a {by.name}")

    def monster_turn(m: Monster) -> None:
        if m.fuse:
            m.fuse -= 1
            if m.fuse == 0:
                targets = [h for h in fighting if h.alive]
                if targets:
                    hurt(rng.choice(targets), rng.uniform(*m.dmg), m, exploded=True)
                m.hp = 0
            return
        for _ in range(MONSTERS[m.kind].bites):
            targets = [h for h in fighting if h.alive]
            if not targets:
                return
            hurt(rng.choice(targets), rng.uniform(*m.dmg), m)

    # A Harming potion drunk before the wave hits every monster.
    for hero in fighting:
        if hero.harming:
            alive = [m for m in monsters if m.alive]
            for m in alive:
                strike(hero.user_id, m, hero.harming)
            log.append(f"☠️ <@{hero.user_id}> throws a Harming potion: -{hero.harming:g} HP to every monster")
            kills[hero.user_id] += sum(1 for m in alive if not m.alive)  # only the ones this potion killed
    # Skeletons shoot first.
    for m in monsters:
        if m.alive and MONSTERS[m.kind].ranged:
            monster_turn(m)

    for _ in range(MAX_ROUNDS):
        for hero in fighting:
            if not hero.alive:
                continue
            hits = 2 if hero.speed and rng.random() < hero.speed else 1
            for _ in range(hits):
                target = _target(monsters)
                if target is None:
                    break
                low = min(hero.min_attack + hero.strength, hero.attack)
                damage = rng.uniform(low, hero.attack)
                if rng.random() < crit_chance:
                    damage *= crit_mult
                strike(hero.user_id, target, damage)
                hero.attacks += 1
                if not target.alive:
                    kills[hero.user_id] += 1
                elif hero.fire > 0 and (not target.burning or hero.fire >= target.burn):
                    target.burning, target.burn, target.burner = gear.burn_turns(), hero.fire, hero.user_id
                others = [m for m in monsters if m.alive and m is not target] if hero.sweep > 0 else []
                second = rng.choice(others) if others else None
                if second is not None:
                    strike(hero.user_id, second, damage * hero.sweep)
                    if not second.alive:
                        kills[hero.user_id] += 1
        if not any(m.alive for m in monsters) or not any(h.alive for h in fighting):
            break
        for m in monsters:  # the fire burns before the monsters play
            if m.alive and m.burning > 0:
                m.burning -= 1
                strike(m.burner, m, m.burn)
                if not m.alive and m.burner in kills:
                    kills[m.burner] += 1
        if not any(m.alive for m in monsters):
            break
        for m in monsters:
            if m.alive:
                monster_turn(m)
        if not any(h.alive for h in fighting):
            break

    cleared = not any(m.alive for m in monsters) and any(h.alive for h in fighting)
    for hero in fighting:  # potions last one wave
        hero.strength = hero.speed = hero.harming = 0.0
    summary = [f"⚔️ <@{uid}>: {n} kill{'s' if n != 1 else ''}" for uid, n in kills.items() if n]
    return {"cleared": cleared, "log": log + summary, "deaths": deaths, "monsters": len(monsters),
            "damage": {uid: int(round(d)) for uid, d in dealt.items()}}


# ---------------- runs ----------------
ACTIVE = ("lobby", "between")
MINUTE = 60


def _hero_of(row) -> Hero | None:
    if not row["hero"]:
        return None
    data = json.loads(row["hero"])
    data["gear_ids"] = {k: int(v) for k, v in data.get("gear_ids", {}).items()}
    return Hero(**data)


def _save_hero(ctx: Ctx, run_id: int, hero: Hero) -> None:
    ctx.execute("UPDATE pve_members SET hero=? WHERE run_id=? AND user_id=?;",
                (json.dumps(asdict(hero)), run_id, hero.user_id))


def get(ctx: Ctx, run_id: int) -> dict:
    """A run with its members (in the order they joined) and their heroes."""
    row = ctx.one("SELECT * FROM pve_runs WHERE run_id=?;", (run_id,))
    if row is None:
        raise GameError("This dungeon run doesn't exist anymore.")
    run = dict(row)
    run["members"] = []
    for m in ctx.all("SELECT * FROM pve_members WHERE run_id=? ORDER BY joined_at, user_id;", (run_id,)):
        member = dict(m)
        member["hero"] = _hero_of(m)
        run["members"].append(member)
    run["in"] = [m for m in run["members"] if m["status"] == "in"]
    return run


def active_run_of(ctx: Ctx, user_id: int) -> int | None:
    row = ctx.one(
        """
        SELECT r.run_id FROM pve_members m JOIN pve_runs r USING(run_id)
        WHERE m.user_id=? AND m.status='in' AND r.status IN ('lobby', 'between');
        """,
        (user_id,),
    )
    return row["run_id"] if row else None


def ready_at(ctx: Ctx, user_id: int) -> int:
    """When the player can enter the dungeon again (cooldown after their last run started)."""
    row = ctx.one(
        """
        SELECT MAX(r.started_at) AS t FROM pve_members m JOIN pve_runs r USING(run_id)
        WHERE m.user_id=? AND r.started_at IS NOT NULL;
        """,
        (user_id,),
    )
    if not row["t"] or cooldowns.cleared(ctx, user_id, "dungeon", row["t"]):
        return 0
    return int(row["t"] + float(_cfg()["cooldown_minutes"]) * MINUTE)


def _check_can_enter(ctx: Ctx, user_id: int) -> None:
    if active_run_of(ctx, user_id):
        raise GameError(f"<@{user_id}> is already in a dungeon run.")
    ready = ready_at(ctx, user_id)
    if ctx.now < ready:
        raise GameError(f"<@{user_id}> can enter the dungeon again <t:{ready}:R>.")


def _pay_entry(ctx: Ctx, run: dict, user_id: int) -> int:
    entry = int(_cfg()["difficulties"][run["difficulty"]]["entry"])
    players.spend_emeralds(ctx, user_id, entry)
    ctx.execute(
        "INSERT INTO pve_members(run_id, user_id, joined_at, entry) VALUES(?, ?, ?, ?);",
        (run["run_id"], user_id, int(ctx.now), entry),
    )
    return entry


def create(ctx: Ctx, user_id: int, difficulty: str) -> dict:
    """Open a run (the leader pays the entry). Others can join until the leader starts it."""
    if difficulty not in DIFFICULTIES:
        raise GameError("Unknown difficulty.")
    _check_can_enter(ctx, user_id)
    now = int(ctx.now)
    cur = ctx.execute(
        "INSERT INTO pve_runs(leader_id, difficulty, created_at, deadline) VALUES(?, ?, ?, ?);",
        (user_id, difficulty, now, now + int(float(_cfg()["lobby_minutes"]) * MINUTE)),
    )
    run = get(ctx, cur.lastrowid)
    _pay_entry(ctx, run, user_id)
    return get(ctx, run["run_id"])


def set_message(ctx: Ctx, run_id: int, channel_id: int, message_id: int) -> None:
    ctx.execute("UPDATE pve_runs SET channel_id=?, message_id=? WHERE run_id=?;", (channel_id, message_id, run_id))


def _lobby(ctx: Ctx, run_id: int) -> dict:
    run = get(ctx, run_id)
    if run["status"] != "lobby":
        raise GameError("This run has already started or ended.")
    if ctx.now >= run["deadline"]:
        raise GameError("This group was closed: nobody started it in time.")
    return run


def join(ctx: Ctx, run_id: int, user_id: int) -> dict:
    run = _lobby(ctx, run_id)
    if any(m["user_id"] == user_id for m in run["members"]):
        raise GameError("You are already in this group.")
    if len(run["members"]) >= int(_cfg()["max_players"]):
        raise GameError(f"The group is full ({_cfg()['max_players']} players).")
    _check_can_enter(ctx, user_id)
    _pay_entry(ctx, run, user_id)
    return get(ctx, run_id)


def _refund_all(ctx: Ctx, run: dict, status: str) -> None:
    for m in run["members"]:
        players.give_emeralds(ctx, m["user_id"], m["entry"])
    ctx.execute("DELETE FROM pve_members WHERE run_id=?;", (run["run_id"],))
    ctx.execute("UPDATE pve_runs SET status=?, ended_at=? WHERE run_id=?;", (status, int(ctx.now), run["run_id"]))


def leave_lobby(ctx: Ctx, run_id: int, user_id: int) -> dict:
    """Leave a group before it starts (refunded). The leader leaving cancels the group."""
    run = get(ctx, run_id)
    if run["status"] != "lobby":
        raise GameError("This run has already started or ended.")
    member = next((m for m in run["members"] if m["user_id"] == user_id), None)
    if member is None:
        raise GameError("You are not in this group.")
    if user_id == run["leader_id"]:
        _refund_all(ctx, run, "cancelled")
    else:
        players.give_emeralds(ctx, user_id, member["entry"])
        ctx.execute("DELETE FROM pve_members WHERE run_id=? AND user_id=?;", (run_id, user_id))
    return get(ctx, run_id)


def _leader(run: dict, user_id: int) -> None:
    if user_id != run["leader_id"]:
        raise GameError(f"Only the leader (<@{run['leader_id']}>) can do that.")


def start(ctx: Ctx, run_id: int, user_id: int) -> dict:
    """The leader starts the run: the heroes are made from their gear, and wave 1 is played."""
    run = _lobby(ctx, run_id)
    _leader(run, user_id)
    for m in run["members"]:
        _save_hero(ctx, run_id, make_hero(ctx, m["user_id"]))
        players.bump_stat(ctx, m["user_id"], "pve_runs")
    ctx.execute("UPDATE pve_runs SET status='between', started_at=? WHERE run_id=?;", (int(ctx.now), run_id))
    return _play(ctx, get(ctx, run_id))


def is_ready(run: dict, member: dict) -> bool:
    """The member is ready to go on from the waves cleared so far."""
    return member["ready_for"] == run["wave"]


def _go_on_if_ready(ctx: Ctx, run_id: int) -> dict:
    """Everyone still in is ready: the next wave is played. Returns {"run", "last": the wave played or None}."""
    run = get(ctx, run_id)
    if run["status"] == "between" and run["in"] and all(is_ready(run, m) for m in run["in"]):
        last = _play(ctx, run)
        return {"run": last["run"], "last": last}
    return {"run": run, "last": None}


def ready(ctx: Ctx, run_id: int, user_id: int, wave: int) -> dict:
    """A member is ready for the next wave (`wave` = waves cleared when they clicked, so an old button can't
    count for a later wave). The wave starts when everyone still in is ready. Returns {"run", "last"}."""
    run = get(ctx, run_id)
    if run["status"] != "between" or run["wave"] != wave:
        raise GameError("This wave has already started or the run is over.")
    member = next((m for m in run["in"] if m["user_id"] == user_id), None)
    if member is None:
        raise GameError("You are not fighting in this run.")
    if is_ready(run, member):
        raise GameError("You're already ready: waiting for the others.")
    ctx.execute("UPDATE pve_members SET ready_for=? WHERE run_id=? AND user_id=?;", (wave, run_id, user_id))
    return _go_on_if_ready(ctx, run_id)


def _end_member(ctx: Ctx, run: dict, member: dict, status: str, pay: int = 0) -> None:
    """A member's run is over: pay them, wear their gear out."""
    if pay:
        players.earn_emeralds(ctx, member["user_id"], pay)
        players.bump_stat(ctx, member["user_id"], "pve_loot", pay)
    ctx.execute("UPDATE pve_members SET status=?, paid=? WHERE run_id=? AND user_id=?;",
                (status, pay, run["run_id"], member["user_id"]))
    hero = member["hero"]
    if hero is None:
        return
    pieces = gear.get_pieces(ctx, hero.gear_ids)
    sword = pieces.get("sword")
    if sword and hero.attacks:
        gear.wear(ctx, sword, hero.attacks)
    gear.wear_one_piece_per_hit(ctx, pieces, hero.hits_taken)  # many small hits here: one piece each
    if status == "dead":
        gear.vanish(ctx, pieces)  # the Curse of Vanishing


def _close_if_empty(ctx: Ctx, run: dict) -> dict:
    run = get(ctx, run["run_id"])
    if not run["in"]:
        ctx.execute("UPDATE pve_runs SET status='done', ended_at=? WHERE run_id=?;", (int(ctx.now), run["run_id"]))
    elif run["leader_id"] not in [m["user_id"] for m in run["in"]]:
        # The leader died or left: the next member leads.
        ctx.execute("UPDATE pve_runs SET leader_id=? WHERE run_id=?;", (run["in"][0]["user_id"], run["run_id"]))
    return get(ctx, run["run_id"])


def _play(ctx: Ctx, run: dict) -> dict:
    """Play the next wave, then: deaths lose their loot, survivors earn the wave's reward."""
    wave = run["wave"] + 1
    members = {m["user_id"]: m for m in run["in"]}
    heroes = [m["hero"] for m in run["in"]]
    result = fight_wave(ctx.rng, heroes, wave, run["difficulty"])
    reward = int(round(wave_reward(run["difficulty"], wave) * biomes.multiplier(ctx, "dungeon_loot")))  # the Jungle
    xp = int(_cfg()["xp_per_wave"])
    for hero in heroes:
        _save_hero(ctx, run["run_id"], hero)
        players.bump_stat(ctx, hero.user_id, "monster_damage", result["damage"].get(hero.user_id, 0))
        member = {**members[hero.user_id], "hero": hero}
        if not hero.alive:
            players.bump_stat(ctx, hero.user_id, "pve_deaths")
            _end_member(ctx, run, member, "dead")
        elif result["cleared"]:
            ctx.execute("UPDATE pve_members SET loot = loot + ? WHERE run_id=? AND user_id=?;",
                        (reward, run["run_id"], hero.user_id))
            players.add_xp(ctx, hero.user_id, xp)
            players.bump_stat(ctx, hero.user_id, "pve_waves")
    ctx.execute(
        "UPDATE pve_runs SET wave=?, deadline=? WHERE run_id=?;",
        (wave if result["cleared"] else run["wave"], int(ctx.now + float(_cfg()["decision_minutes"]) * MINUTE),
         run["run_id"]),
    )
    run = get(ctx, run["run_id"])
    cleared_all = result["cleared"] and wave == len(WAVES)
    nether: list[int] = []  # the Nightmare's survivors open the Nether
    if cleared_all:
        bonus = float(_cfg()["clear_bonus"])
        for m in run["in"]:
            players.bump_stat(ctx, m["user_id"], f"pve_clears_{run['difficulty']}")
            _end_member(ctx, run, m, "cleared", round(m["loot"] * (1 + bonus)))
            if run["difficulty"] == NETHER_GATE and dimensions.unlock(ctx, m["user_id"], "nether"):
                nether.append(m["user_id"])
    run = _close_if_empty(ctx, run)
    return {"run": run, "wave": wave, "result": result, "reward": reward, "xp": xp, "cleared_all": cleared_all,
            "nether": nether}


def leave(ctx: Ctx, run_id: int, user_id: int) -> dict:
    """Leave between two waves with the loot earned so far."""
    run = get(ctx, run_id)
    if run["status"] != "between":
        raise GameError("You can only leave between two waves.")
    member = next((m for m in run["in"] if m["user_id"] == user_id), None)
    if member is None:
        raise GameError("You are not fighting in this run.")
    _end_member(ctx, run, member, "left", member["loot"])
    _close_if_empty(ctx, run)
    # The others were all ready and only waited for this member: the next wave starts.
    return {**_go_on_if_ready(ctx, run_id), "paid": member["loot"]}


def drink(ctx: Ctx, run_id: int, user_id: int, key: str) -> dict:
    """Drink a potion between two waves: Healing heals now, the others help during the next wave."""
    run = get(ctx, run_id)
    if run["status"] != "between":
        raise GameError("Potions are drunk between two waves.")
    member = next((m for m in run["in"] if m["user_id"] == user_id), None)
    if member is None:
        raise GameError("You are not fighting in this run.")
    kind, level = potions.parse(key)
    if member["potions"] >= int(_cfg()["max_potions"]):
        raise GameError(f"You already drank {_cfg()['max_potions']} potions in this run.")
    if level >= 2 and member["strong_potion"] >= potions.strong_per_fight():
        raise GameError(potions.strong_limit_text("run"))
    hero = member["hero"]
    boost = 1.0 + hero.potion_boost
    if kind == "healing" and hero.hp >= hero.max_hp:
        raise GameError("You are already at full health.")
    if kind != "healing" and getattr(hero, kind):
        raise GameError(f"You already drank a {potions.POTIONS[kind].name} potion for the next wave.")
    potions.drink(ctx, user_id, key)
    effect = ""
    if kind == "healing":
        healed = min(potions.effect(key, "healing_hp") * boost, hero.max_hp - hero.hp)
        hero.hp += healed
        effect = f"+{healed:.1f} HP"
    elif kind == "strength":
        hero.strength = potions.effect(key, "strength_min_bonus") * boost
        effect = f"next wave: minimum damage +{hero.strength:g}"
    elif kind == "speed":
        hero.speed = min(1.0, potions.effect(key, "speed_chance") * boost)
        effect = f"next wave: {hero.speed:.0%} chance to strike twice"
    else:
        hero.harming = potions.effect(key, "harming_damage") * boost
        effect = f"next wave: -{hero.harming:g} HP to every monster at the start"
    _save_hero(ctx, run_id, hero)
    ctx.execute(
        "UPDATE pve_members SET potions = potions + 1, strong_potion = strong_potion + ? WHERE run_id=? AND user_id=?;",
        (1 if level >= 2 else 0, run_id, user_id),
    )
    return {"run": get(ctx, run_id), "effect": effect, "potion": key}


def expire(ctx: Ctx) -> list[dict]:
    """Called every minute: groups not started in time are refunded. Between two waves, the members who didn't
    say they were ready in time leave with their loot, and the next wave starts for the ones who did."""
    events = []
    for row in ctx.all("SELECT run_id, status FROM pve_runs WHERE status IN ('lobby', 'between') AND deadline <= ?;",
                       (int(ctx.now),)):
        run = get(ctx, row["run_id"])
        if run["status"] == "lobby":
            _refund_all(ctx, run, "cancelled")
            events.append({"type": "cancelled", "run": get(ctx, run["run_id"])})
        else:
            for m in run["in"]:
                if not is_ready(run, m):
                    _end_member(ctx, run, m, "left", m["loot"])
            _close_if_empty(ctx, run)
            res = _go_on_if_ready(ctx, run["run_id"])
            events.append({"type": "continued" if res["last"] else "timeout", **res})
    return events

