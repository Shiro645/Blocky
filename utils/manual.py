"""The manual shown by /help: one page per slash command, plus a few topics.

Pages are plain data (no discord), so the tests check that every command has
one. The "current values" of a page are computed from the live settings each
time it is shown, so they follow /config and config.json. Options come from the
command tree itself (see cogs/help_command.py), so they never go stale.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from game import blockdle, enchants, guide, live_events, luckyblock, mines, players, potions, progress, roulette
from game.assets import MAX_STAFF_GEAR
from game.catalog import RECIPES, TALENT_BRANCHES
from game.profiles import FRAMES
from game.pve import DIFFICULTIES as DUNGEON
from game.species import SPECIES
from utils.mc_commands import DEFAULT_BLOCKED, blocked_list

Settings = dict[str, Any]

# key -> (label, staff only)
CATEGORIES: dict[str, tuple[str, bool]] = {
    "start": ("🚀 Start here", False),
    "mining": ("⛏️ Mining & market", False),
    "gear": ("🛠️ Crafting & gear", False),
    "progress": ("⭐ Progress", False),
    "profile": ("🎨 Profile & species", False),
    "combat": ("⚔️ Combat", False),
    "events": ("🐉 Events", False),
    "games": ("🎲 Games", False),
    "trading": ("💰 Trading & loans", False),
    "teams": ("🛡️ Teams", False),
    "minecraft": ("🌍 Minecraft server", False),
    "staff_moderation": ("🔨 Staff · moderation", True),
    "staff_players": ("👤 Staff · players & economy", True),
    "staff_events": ("🎪 Staff · events", True),
    "staff_server": ("⚙️ Staff · bot & Minecraft", True),
}

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ROMAN = ("I", "II", "III")


@dataclass(frozen=True)
class Page:
    name: str  # the command without the slash ("team create"), or a topic name
    category: str
    text: str
    values: Callable[[Settings], list[str]] | None = None
    examples: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    title: str = ""  # topics only: commands are titled "/name"

    @property
    def is_topic(self) -> bool:
        return bool(self.title)

    @property
    def heading(self) -> str:
        return self.title or f"/{self.name}"

    @property
    def staff(self) -> bool:
        return CATEGORIES[self.category][1]

    def current_values(self, s: Settings) -> list[str]:
        return self.values(s) if self.values else []


# ---------------- formatting ----------------
def num(value: float) -> str:
    """1000 -> '1,000', 0.5 -> '0.5'"""
    value = float(value)
    return f"{int(value):,}" if value.is_integer() else f"{value:,.3f}".rstrip("0").rstrip(".")


def pct(value: float) -> str:
    """0.025 -> '2.5%'"""
    return f"{num(round(float(value) * 100, 2))}%"


def duration(seconds: float) -> str:
    """90 -> '1 min 30 s', 7200 -> '2 h', 172800 -> '2 days'"""
    seconds = int(seconds)
    if seconds <= 0:
        return "0 s"
    parts = []
    for size, unit in ((86400, "day"), (3600, "h"), (60, "min"), (1, "s")):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {unit}{'s' if unit == 'day' and n > 1 else ''}")
    return " ".join(parts[:2])


def per_level(values: list, fmt: Callable[[float], str] = num) -> str:
    """[2, 4, 8] -> 'I 2 · II 4 · III 8'"""
    return " · ".join(f"{ROMAN[i]} {fmt(v)}" for i, v in enumerate(values[:3]))


def listing(mapping: dict, fmt: Callable[[Any], str] = num) -> str:
    """{'gold': 5, 'iron': 10} -> 'gold 5 · iron 10'"""
    return " · ".join(f"{k} {fmt(v)}" for k, v in mapping.items())


def em(amount: float) -> str:
    return f"**{num(amount)}** emerald{'' if float(amount) == 1 else 's'}"


def hour(h: float) -> str:
    return f"{int(h):02d}:00"


# ---------------- shared values ----------------
def _block_values(s: Settings) -> str:
    return "Block values: " + listing(s["block_values"])


def _cooldown(s: Settings) -> str:
    base = s["mining"]["cooldown_seconds"]
    if base <= 0:
        return "Mining cooldown: **none**"
    return (
        f"Mining cooldown: **{duration(base)}** (the Efficiency talent and enchantment lower it, "
        f"never below **{duration(s['mining']['min_cooldown_seconds'])}**)"
    )


def _sword(s: Settings) -> str:
    return "Sword maximum damage: " + listing(s["gear"]["sword_max_damage"]) + " (Sharpness adds to it)"


def _armor(s: Settings) -> str:
    g = s["gear"]
    return (
        f"Armor: **{pct(g['damage_reduction_per_armor_point'])}** less damage per armor point, "
        f"at most **{pct(g['max_damage_reduction'])}**"
    )


def _shield(s: Settings) -> str:
    g = s["gear"]
    return (f"Shield (iron only), duels: **Attack + block** blocks the opponent's next attack, "
            f"**{num(g['shield_blocks_per_fight'])}** times per duel · durability **{num(g['shield_durability'])}**, "
            f"**{num(g['shield_wear_per_block'])}** per block · at 0 it stays, unusable until /repair")


def _mining(s: Settings) -> list[str]:
    m, e, d = s["mining"], s["enchants"], s["drops"]
    lo, hi = m["xp_per_message"]
    llo, lhi = e["lapis_amount"]
    return [
        _cooldown(s),
        f"XP per reward: **{num(lo)}–{num(hi)}**",
        f"Lapis lazuli: **{pct(e['lapis_chance'])}** chance per reward ({num(llo)}–{num(lhi)})",
        f"Drops: **{pct(d['chance'])}** chance per reward, at most one every **{duration(d['min_interval_seconds'])}**, "
        f"**{duration(d['claim_seconds'])}** to claim it",
        f"Spam channels: **{num(m['spam_reward'])}** emerald per reward",
        _block_values(s),
    ]


def _market(s: Settings) -> list[str]:
    m = s["market"]
    return [
        f"Sticks: **{num(m['stick_pack']['amount'])}** for {em(m['stick_pack']['price'])}",
        "Ingots: " + listing(m["ingots"]),
    ]


def _team_spaces(s: Settings) -> list[str]:
    t = s["teams"]
    return [f"Unlocking the category: {em(t['space_cost'])}, once (paid by the leader)",
            f"Up to **{num(t['max_channels'])}** channels (text and voice)"]


def _days(n: Any) -> str:
    return "kept" if not float(n) else f"**{float(n):g}** day{'s' if float(n) != 1 else ''}"


def _guide(s: Settings) -> list[str]:
    g = s["guide"]
    return [
        f"Steps: {', '.join(f'**{step.key}**' for step in guide.STEPS)}",
        f"Reward for every step: {em(g['reward'])} (once per player, ever)",
        f"A finished guide channel is deleted after: {_days(g['delete_after_days'])}",
        f"An unfinished one is deleted after: {_days(g['expire_days'])} (progress is kept)",
    ]


def _daily(s: Settings) -> list[str]:
    d = s["daily"]
    cap = int(d["streak_cap_days"])
    top = int(d["base_reward"]) + int(d["streak_bonus_per_day"]) * (max(1, cap) - 1)
    lines = [
        f"Day 1: {em(d['base_reward'])}, then **+{num(d['streak_bonus_per_day'])}** per day in a row, "
        f"up to {em(top)} from day **{cap}**",
        f"XP: **{num(d['xp'])}**",
    ]
    if d.get("weekly_bonus_item"):
        every = int(d["bonus_every_days"])
        lines.append(f"Every {'day' if every <= 1 else f'{every}th day'} in a row: **1 {d['weekly_bonus_item']} ingot**")
    lines.append(f"The day changes at midnight ({s['timezone']})")
    return lines


def _gear(s: Settings) -> list[str]:
    g = s["gear"]
    return [
        "Tiers: " + listing(g["tier"]),
        f"Pickaxe: **+{num(g['pickaxe_extra_blocks_per_tier'])}** cobblestone per tier each reward, "
        f"**{pct(g['pickaxe_upgrade_chance_per_tier'])}** chance per tier to upgrade the block",
        f"Shovel: **+{num(g['shovel_extra_gravel_per_tier'])}** gravel per tier when you mine gravel",
        f"Axe: **{pct(g['axe_stick_chance'])}** chance to find sticks (as many as its tier)",
        f"Hoe: **+{pct(g['hoe_xp_bonus_per_tier'])}** XP per tier",
        _sword(s),
        _armor(s),
        _shield(s),
        "Durability: " + listing(g["durability"]) + " · armor: helmet **" + pct(g["armor_durability_share"]["helmet"])
        + "**, chestplate **" + pct(g["armor_durability_share"]["chestplate"]) + "**, leggings **"
        + pct(g["armor_durability_share"]["leggings"]) + "**, boots **" + pct(g["armor_durability_share"]["boots"])
        + "** of it",
        "Wear: tools **1** per mining reward where they help · sword **1** per attack · armor: in duels **every "
        "piece** loses 1 per hit taken, in the dungeon **one piece** (drawn at random) per hit",
    ]


def _enchant_effects(s: Settings) -> list[str]:
    e = s["enchants"]

    def levels(key: str, fmt: Callable[[float], str] = num) -> str:
        return " / ".join(fmt(v) for v in e[key][: enchants.MAX_LEVEL])

    fortune = levels("fortune_bonus")
    effects = {
        "efficiency": f"mining cooldown -{levels('efficiency_seconds')} s",
        "fortune": f"pickaxe +{fortune} cobblestone, shovel +{fortune} gravel, axe +{fortune} sticks, "
        f"hoe +{levels('fortune_hoe_xp', pct)} XP",
        "unbreaking": f"{levels('unbreaking_chance', pct)} chance that a use costs no durability",
        "sharpness": f"+{levels('sharpness_damage')} maximum damage",
        "looting": f"+{levels('looting_boss_bonus', pct)} boss reward",
        "protection": f"+{levels('protection_points')} armor points",
        "mending": f"the XP you gain repairs the equipped piece first: **{num(e['mending_durability_per_xp'])}** "
        "durability per XP, and only the XP left goes to you. One level; the rarest book (the villager's exclusive "
        f"offer, or now and then a boss's top damage dealer: {pct(e['boss_mending_chance'])})",
    }
    lines = []
    for ench in enchants.ENCHANTS.values():
        items = "any gear" if len(ench.items) > 4 else ", ".join(ench.items)
        if ench.key == "protection":
            items = "armor"
        levels_text = " (I / II / III)" if ench.max_level > 1 else ""
        lines.append(f"**{ench.name}** ({items}): {effects[ench.key]}{levels_text}")
    return lines


def _apply_cost(s: Settings) -> str:
    return "Lapis to apply a book: " + per_level(s["enchants"]["apply_cost"])


def _xp(s: Settings) -> list[str]:
    m, d, du, b, t = s["mining"], s["daily"], s["duel"], s["boss"], s["tournament"]
    lo, hi = m["xp_per_message"]
    return [
        f"XP for the next level: **{num(s['levels']['xp_first_level'])}** at level 1, then "
        f"**×{float(s['levels']['xp_growth_per_level']):g}** each level (level 10: **{num(players.xp_required_for_level(10))}**, "
        f"level 50: **{num(players.xp_required_for_level(50))}**)",
        f"1 talent point every **{num(s['talents']['points_every_levels'])}** levels",
        f"XP sources: mining **{num(lo)}–{num(hi)}** per reward · daily **{num(d['xp'])}** · "
        f"duel won **{num(du['xp_win'])}** / lost **{num(du['xp_loss'])}** · boss defeated **{num(b['xp_reward'])}** · "
        f"tournament fight won **{num(t['xp_per_win'])}**",
    ]


def _talents(s: Settings) -> list[str]:
    t = s["talents"]
    caps = t["caps"]
    effects = {
        "miner": "better odds of gravel and deepslate, and a chance of a bonus block",
        "trader": f"**+{pct(t['trader_bonus_per_point'])}** emeralds per point when you /sell",
        "lucky": "more obsidian and bedrock on 1-block rolls",
        "efficiency": f"mining cooldown **-{num(t['efficiency_seconds_per_point'])} s** per point "
        f"(never below {duration(s['mining']['min_cooldown_seconds'])})",
    }
    return [f"**{b.capitalize()}** (max {num(caps[b])}): {effects[b]}" for b in TALENT_BRANCHES]


def _auction(s: Settings) -> list[str]:
    a = s["auction"]
    return [
        f"Tax: **{num(a['tax_percent'])}%** of the price, paid by the seller",
        f"Up to **{num(a['max_listings'])}** listings at once, each lasts **{num(a['duration_days'])} days**",
    ]


def _duel(s: Settings) -> list[str]:
    d, p = s["duel"], s["potions"]
    return [
        f"HP: **{num(d['hp'])}** each (**+{num(d['second_player_bonus_hp'])}** for the player who strikes second)",
        f"A hit deals **{num(d['min_damage'])}** to your sword's maximum",
        _sword(s),
        f"Critical hit: **{pct(d['crit_chance'])}** (×{num(d['crit_multiplier'])}) · no dodge: with a shield, "
        f"**Attack + block** blocks the opponent's next attack (**{num(s['gear']['shield_blocks_per_fight'])}** "
        "times per duel)",
        _armor(s),
        f"Potions: up to **{num(p['max_per_duel'])}** per duel, one per turn",
        f"Minimum stake: {em(d['min_stake'])} · **{duration(d['cooldown_seconds'])}** between two duels · "
        f"the challenge expires after **{duration(d['request_timeout_seconds'])}**",
        f"Turns: **{duration(d['turn_seconds'])}** to play, then the bot attacks for you; after "
        f"**{num(d['afk_turns'])}** missed turns the rest is played automatically",
        f"XP: won **{num(d['xp_win'])}** · lost **{num(d['xp_loss'])}**",
    ]


def _repair(s: Settings) -> list[str]:
    r = s["repair"]
    per, penalty = float(r["durability_per_ingot"]), float(r["penalty_per_repair"])
    fulls = [math.ceil(1 / (per / (1 + penalty * n)) - 1e-9) for n in range(4)]
    return [
        f"1 ingot = **{pct(per)}** of the piece's durability at its first repair; each repair it already had adds "
        f"**{pct(penalty)}** to the ingots needed",
        "Ingots for a full repair: " + " → ".join(f"**{n}**" for n in fulls) + " → …",
        f"Anvil: **{num(r['anvil_iron'])}** iron ingots · **{pct(r['anvil_damage_chance'])}** chance to wear at each use",
    ]


def _potions(s: Settings) -> list[str]:
    p = s["potions"]
    lines = [f"**{potion.name}**: {potions.effect_text(key)}" for key, potion in potions.POTIONS.items()]
    lines += [
        f"Reinforced (II): effect **×{num(p['level2_multiplier'])}**, **{num(p['strong_per_fight'])}** per duel or "
        "dungeon run at most",
        f"Up to **{num(p['max_per_duel'])}** potions per duel, one per turn",
        f"Bosses: the top **{num(p['boss_top'])}** damage dealers get **{num(p['boss_potions'])}** random "
        f"potion{'s' if int(p['boss_potions']) != 1 else ''}",
    ]
    return lines


def _season(s: Settings) -> list[str]:
    rewards = s["seasons"]["rewards"]
    places = " · ".join(f"#{i + 1} {num(r)}" for i, r in enumerate(rewards))
    return [f"Podium rewards (emeralds): {places or 'none'}", f"Weeks follow the server time ({s['timezone']})"]


def _challenges(s: Settings) -> list[str]:
    c = s["challenges"]
    lines = [f"**{num(c['per_day'])}** challenges per day and **{num(c['per_week'])}** per week, never the same "
             "as the day or the week before"]
    if s["enchants"]["challenges_book"]:
        lines.append("All the weekly ones done: a random enchanted book")
    daily = [f"{ch.text} ({em(ch.reward)})" for ch in progress.challenge_pool("day") if progress.available(ch)]
    weekly = [f"{ch.text} ({em(ch.reward)})" for ch in progress.challenge_pool("week") if progress.available(ch)]
    for title, items in (("Daily", daily if c["per_day"] else []), ("Weekly", weekly)):
        line = f"**{title}**:"
        for item in items:  # lines of 400 characters at most
            if len(line) + len(item) + 3 > 400:
                lines.append(line)
                line = f"**{title}** (more):"
            line += (" " if line.endswith(":") else " · ") + item
        if items:
            lines.append(line)
    return lines


def _live_events(s: Settings) -> list[str]:
    c = s["live_events"]
    lines = [f"{k.label}: {live_events.describe(key)}" for key, k in live_events.KINDS.items()]
    if c["daily_random"] and live_events.random_kinds():
        lines.append(f"One comes by itself every day at a random time, between **{int(c['earliest_hour']):02d}:00** "
                     f"and **{int(c['latest_hour']):02d}:00**, for **{duration(int(c['duration_minutes']) * 60)}**")
    else:
        lines.append("They only come when the staff starts one")
    return lines


def _boss(s: Settings) -> list[str]:
    b = s["boss"]
    spawn = (
        f"A boss appears every **{num(b['auto_spawn_hours'])} h**"
        if float(b["auto_spawn_hours"]) > 0
        else "Bosses only appear when staff summons one"
    )
    return [
        spawn,
        f"HP: **{num(b['hp'])}** · stays **{num(b['duration_hours'])} h**, then escapes (nobody is paid)",
        f"Reward pool: {em(b['reward_pool'])} shared by damage · top damage dealer: **+{num(b['top_damage_bonus'])}**",
        f"Top **{num(s['enchants']['boss_book_top'])}**: a book · top **{num(s['potions']['boss_top'])}**: "
        f"**{num(s['potions']['boss_potions'])}** random potion{'s' if int(s['potions']['boss_potions']) != 1 else ''} "
        f"· XP for everyone: **{num(b['xp_reward'])}**",
        "Looting: " + per_level(s["enchants"]["looting_boss_bonus"], pct) + " more reward",
    ]


def _attack(s: Settings) -> list[str]:
    b = s["boss"]
    return [
        f"Cooldown: **{duration(b['attack_cooldown_seconds'])}** between two attacks",
        f"A hit deals **{num(s['duel']['min_damage'])}** to your sword's maximum",
        _sword(s),
        f"Critical hit: **{pct(b['crit_chance'])}** (×{num(b['crit_multiplier'])})",
    ]


def _tournament(s: Settings) -> list[str]:
    t = s["tournament"]
    split = t["prize_split"]
    return [
        f"Registrations: **{DAYS[t['opens_day']]} {hour(t['opens_hour'])}** → "
        f"**{DAYS[t['closes_day']]} {hour(t['closes_hour'])}** (then the draw)",
        f"Fights: from **{DAYS[t['start_day']]} {hour(t['start_hour'])}**, one round every "
        f"**{duration(int(t['round_minutes']) * 60)}** ({s['timezone']})",
        f"Entry fee: {em(t['entry_fee'])} · server bonus in the pot: {em(t['house_bonus'])}",
        f"Players: **{num(t['min_players'])}–{num(t['max_players'])}** (cancelled and refunded below the minimum)",
        f"Pot: winner **{num(split[0])}%** · runner-up **{num(split[1])}%** · semi-finalists **{num(split[2])}%** (shared)",
        f"XP per fight won: **{num(t['xp_per_win'])}** · only the server bonus counts for the seasons",
    ]


def _villager(s: Settings) -> list[str]:
    v = s["villager"]
    return [
        f"Every day **{hour(v['arrive_hour'])}–{hour(v['leave_hour'])}** ({s['timezone']})",
        f"Sale: **{pct(v['sell_discount'])}** below the value · purchase: **{pct(v['buy_bonus'])}** above the /sell price",
        f"Exclusive: level III book {em(v['book_iii_price'])} · reinforced potion {em(v['potion_ii_price'])}",
        "Blocks he may buy: " + listing(v["buys"], lambda n: f"×{num(n)}"),
    ]


def _teams(s: Settings) -> list[str]:
    t = s["teams"]
    rewards = " · ".join(f"#{i + 1} {num(r)}" for i, r in enumerate(t["season_rewards"]))
    return [
        f"Creating a team: {em(t['create_cost'])} · up to **{num(t['max_members'])}** members",
        f"Invitations last **{num(t['invite_hours'])} h**",
        f"XP bonus: **+{pct(t['xp_bonus_per_active_member'])}** per other member who mined today "
        f"(max **+{pct(t['max_xp_bonus'])}**)",
        f"Team season rewards (emeralds): {rewards or 'none'} · ranked with at least "
        f"**{num(t['min_members_ranked'])}** members who scored",
        "Team score: " + ("**logarithmic** (5 members earning the same ≈ ×2.6)" if t["log_score"]
                          else "the **sum** of what the members earned"),
    ]


def _moderation(s: Settings) -> list[str]:
    m = s["moderation"]
    days = int(m["warn_expire_days"])
    mutes = sorted(m["warn_mutes"].items(), key=lambda kv: int(kv[0]))
    return [
        f"Warnings count for **{days} days**" if days else "Warnings count forever",
        "Automatic mutes: " + (" · ".join(f"{n} warnings → {d}" for n, d in mutes) or "none"),
    ]


def _games(s: Settings) -> list[str]:
    g = s["games"]
    cap = int(g["daily_win_cap"])
    gambler = int(round(int(g["max_bet"]) * (1 + float(s["species"]["gambler_max_bet"]))))
    more = f" (🎲 Gamblers: up to **{num(gambler)}**)" if gambler > int(g["max_bet"]) else ""
    return [
        f"Bets: **{num(g['min_bet'])}** to **{num(g['max_bet'])}** emeralds{more} · "
        f"**{duration(g['cooldown_seconds'])}** between two games",
        (f"Daily limit: once you won **{num(cap)}** emeralds today at games of chance (winnings minus losses), "
         "you play again tomorrow" if cap else "No daily limit"),
        "Played in the game channels set by the staff (anywhere when there are none)",
    ]


def _luckyblock(s: Settings) -> list[str]:
    lines = [f"{o.emoji} **{o.name}** ({pct(chance)}): " + ("nothing" if not payout else f"×{payout:g} the bet")
             for o, chance, payout in luckyblock.chances()]
    return lines + [f"On average a block gives back **{pct(luckyblock.return_rate())}** of the bet"] + _games(s) + [
        "Winnings don't count for the seasons"]


def _blackjack(s: Settings) -> list[str]:
    g = s["games"]
    closed = [] if g["blackjack_enabled"] else ["🔒 **Closed right now**"]
    return closed + [
        f"Win: **×2** the bet · blackjack: **×{1 + float(g['blackjack_natural_payout']):g}** · push: the bet back",
        f"The dealer draws until **{num(g['blackjack_dealer_stands'])}** · double: only with your first two cards",
        f"No move for **{num(g['move_minutes'])} min**: you stand",
    ] + _games(s) + ["Winnings don't count for the seasons"]


def _mines(s: Settings) -> list[str]:
    g = s["games"]
    closed = [] if g["mines_enabled"] else ["🔒 **Closed right now**"]
    examples = " · ".join(f"{t} TNT: ×{mines.multiplier(1, t):.2f} → ×{mines.multiplier(3, t):.2f} → "
                          f"×{mines.multiplier(5, t):.2f}" for t in (1, 3, 5))
    return closed + [
        f"20 blocks, **1 to {num(g['mines_tnt_max'])}** TNT · each safe block raises the multiplier "
        f"(**{pct(g['mines_return'])}** of a fair game)",
        f"After 1, 3 and 5 blocks: {examples}",
        f"The game cashes out by itself at **×{float(g['mines_max_multiplier']):g}** · no move for "
        f"**{num(g['move_minutes'])} min**: you cash out (nothing dug: the bet back)",
    ] + _games(s) + ["Winnings don't count for the seasons"]


def _roulette(s: Settings) -> list[str]:
    zeros = "0 and 00" if s["games"]["roulette_zeros"] == 2 else "0"
    rate = 36 / (36 + int(s["games"]["roulette_zeros"]))
    closed = [] if s["games"]["roulette_enabled"] else ["🔒 **Closed right now**"]
    names = {"red": "🟥 Redstone", "black": "⬛ Obsidian", "green": "💎 Diamond block", "even": "even", "odd": "odd",
             "low": "1-18", "high": "19-36", "dozens": "a dozen", "number": "a number"}
    pays = {"green": 36 // int(s["games"]["roulette_zeros"]), "dozens": 3, "number": 36}
    bets = [f"{name} **×{pays.get(key, 2)}**" for key, name in names.items() if s["games"]["roulette_bets"].get(key)]
    return closed + [
        "You can bet on: " + (" · ".join(bets) or "nothing right now") + " (your bet included)",
        (f"Diamond block: **{zeros}**: every other bet loses on it" if zeros == "0" else
         f"Diamond blocks: **{zeros}**: every other bet loses on them") + f". On average a bet gives back **{pct(rate)}**",
    ] + _games(s) + ["Winnings don't count for the seasons"]


def _blockdle(s: Settings) -> list[str]:
    g = s["games"]
    rewards = " · ".join(f"{i + 1}{'+' if i == len(g['blockdle_rewards']) - 1 else ''}: {num(r)}"
                         for i, r in enumerate(g["blockdle_rewards"]))
    return [
        f"Rewards by number of guesses: {rewards}",
        f"XP for finding it: **{num(g['blockdle_xp'])}** · **{len(blockdle.BLOCKS)}** possible blocks",
        f"A new block every day at midnight ({s['timezone']})",
    ]


def _quiz(s: Settings) -> list[str]:
    g = s["games"]
    every = f"A question every **{duration(int(g['quiz_every_minutes']) * 60)}** or so, in a game channel" \
        if g["quiz_every_minutes"] else "Questions only come when the staff asks one (/event quiz)"
    return [every, f"**{duration(g['quiz_seconds'])}** to answer · reward: {em(g['quiz_reward'])} and "
                   f"**{num(g['quiz_xp'])}** XP"]


def _species(s: Settings) -> list[str]:
    sp = s["species"]
    lines = [f"{v.emoji} **{v.name}**: " + v.text.format(pct(sp[v.setting])) for v in SPECIES.values()]
    lines.append(f"First choice free · changing costs {em(sp['change_cost'])}, once every "
                 f"**{num(sp['change_days'])}** day(s)")
    return lines


def _profiles(s: Settings) -> list[str]:
    p = s["profiles"]
    sold = " · ".join(f"{FRAMES[k].name} {num(v)}" for k, v in p["frame_prices"].items() if k in FRAMES)
    earned = " · ".join(f"{f.name} ({f.how})" for f in FRAMES.values() if f.unlock)
    return [
        f"Colors: {em(p['color_price'])} each (16 dye colors) · any #hex: {em(p['hex_price'])} once",
        f"Frames sold (emeralds): {sold}",
        f"Frames earned: {earned}",
        f"Team banner: {em(p['banner_cost'])} per change",
    ]


def _loans(s: Settings) -> list[str]:
    lo = s["loans"]
    return [
        f"From {em(lo['min_amount'])} to {em(lo['max_amount'])} · interest **0–{pct(lo['max_interest'])}** · "
        f"**{num(lo['min_days'])}–{num(lo['max_days'])}** day(s) to repay",
        f"One unpaid loan per borrower · up to **{num(lo['max_loans_out'])}** unpaid loans per lender · "
        f"an offer lasts **{duration(float(lo['offer_minutes']) * 60)}**",
        f"Late: **+{pct(lo['late_penalty'])}** of what's left, the bot takes what it can from the borrower's "
        f"emeralds, then **{pct(lo['garnish'])}** of every emerald they receive goes to the lender until it's "
        "paid (and no /pay, /trade, auction purchase or listing, or loan until then)",
        "Loans, repayments and interest don't count for the seasons",
    ]


def _pve(s: Settings) -> list[str]:
    p = s["pve"]
    lines = []
    for key, (name, emoji) in DUNGEON.items():
        d = p["difficulties"][key]
        loot = sum(round(int(r) * float(d["reward"])) for r in p["wave_rewards"])
        lines.append(f"{emoji} **{name}**: entry {em(d['entry'])} · monsters ×{num(d['strength'])} · "
                     f"loot up to {em(round(loot * (1 + float(p['clear_bonus']))))}")
    lines += [
        f"**{num(p['hp'])}** HP, not restored between waves · monsters **+{pct(p['wave_growth'])}** each wave",
        f"Up to **{num(p['max_players'])}** players (each extra player: **+{pct(p['group_monsters'])}** monsters, "
        f"**+{pct(p['difficulties']['nightmare'].get('group_monsters', p['group_monsters']))}** in Nightmare: a raid "
        "for a full group) · "
        "a run every "
        f"**{duration(float(p['cooldown_minutes']) * 60)}**",
        f"**{num(p['max_potions'])}** potions per run · **{num(p['xp_per_wave'])}** XP per wave cleared · "
        f"**{duration(float(p['decision_minutes']) * 60)}** to decide between waves",
    ]
    return lines


def _rob(s: Settings) -> list[str]:
    r = s["rob"]
    return [
        f"Risky: **{num(r['risky_min'])}–{num(r['risky_max'])}** emeralds, the victim is pinged · discreet: "
        f"**{num(r['discreet_min'])}–{num(r['discreet_max'])}**, no ping (never more than they have)",
        f"The victim has **{duration(int(r['minutes_to_stop']) * 60)}** to stop it; if they do, the thief pays them "
        f"**{num(r['fine_percent'])}%** of the loot as a fine",
        f"A robbery every **{num(r['cooldown_hours'])} h** · a robbed player is safe for "
        f"**{num(r['victim_protection_hours'])} h** · players below level **{num(r['min_victim_level'])}** are safe",
        (f"No robbery starts at night, from **{int(r['night_start_hour']):02d}:00** to "
         f"**{int(r['night_end_hour']):02d}:00** (one started before keeps going)"
         if int(r["night_start_hour"]) != int(r["night_end_hour"]) else "Robberies are possible day and night"),
        "Stolen emeralds and fines don't count for the seasons",
    ]


DURATIONS = "Durations: `30m`, `2h`, `3d`, `1w`, `1d12h`… (1 minute to 1 year) or `perm`"


# ---------------- pages ----------------
PAGES: list[Page] = [
    # ---- basics ----
    Page(
        "help", "start",
        "Opens this manual. Pick a category in the menu, then a command to read its page: what it does, "
        "its options, its current numbers (they follow the server settings), examples and related commands.\n"
        "You can also open a page directly with the `command` option.",
        examples=("/help", "/help command:duel", "/help command:mining"),
    ),
    Page(
        "mining", "mining",
        "There is no command to mine: **every message you send mines blocks**, at most once per cooldown (only in "
        "the mining channels when the staff set some). "
        "It's silent: check what you got with /inventory.\n"
        "Your equipped tools add bonuses (/gear), your talents improve the odds (/talents), and teammates who "
        "mined today give you more XP (/team info). Mining also finds lapis lazuli, and sometimes makes a "
        "**drop** appear: the first player to click it gets the reward.\n\n"
        "In **spam channels** you don't mine blocks: each reward is a tiny amount of emeralds instead, saved "
        "until it makes a whole emerald (no XP, no drops, doesn't count for the seasons). Messages in your private "
        "guide channel, in DMs or in another server don't mine at all.",
        _mining,
        related=("inventory", "sell", "gear", "talents"),
        title="⛏️ Mining (chat)",
    ),
    Page(
        "inventory", "start",
        "Shows everything you own: emeralds, blocks, sticks, ingots, lapis lazuli, enchanted books, potions "
        "and your gear with its durability.",
        lambda s: [_block_values(s)],
        examples=("/inventory",),
        related=("sell", "gear", "enchant info", "potions"),
    ),
    Page(
        "sell", "mining",
        "Sells your blocks for emeralds: **all** of them, only one **kind** (`block`), or a number of them "
        "(`amount`; asking for more than you have sells all you have, and without a kind your least valuable "
        "blocks go first). The Trader talent adds a bonus on top.\n"
        "**A piece of gear** (`gear`): pick it in the suggestions, which show its price. It sells for part of its "
        "value new (its craft and the books applied to it), times the durability it has left, and you confirm "
        "first. A piece you wear is taken off; its enchantments go with it.\n"
        "Blocks already counted for the season when you mined them, so selling only adds the Trader bonus to "
        "your season score; selling gear doesn't count. Ingots, books and potions aren't sold here: use /auction "
        "or /trade. The wandering villager sometimes buys a pile of blocks above this price (/villager).\n"
        "Everyone in the channel sees your sale.",
        lambda s: [
            _block_values(s),
            f"Trader talent: **+{pct(s['talents']['trader_bonus_per_point'])}** per point "
            f"(max **+{pct(s['talents']['trader_bonus_per_point'] * s['talents']['caps']['trader'])}**)",
            f"Gear: **{pct(s['market']['gear_sell_rate'])}** of its value × its durability left (e.g. at "
            f"**80%** durability: **{pct(s['market']['gear_sell_rate'] * 0.8)}** of its value) · Villagers get "
            f"**+{pct(s['species']['villager_trade'])}**",
        ],
        examples=("/sell", "/sell block:bedrock", "/sell block:cobblestone amount:500", "/sell amount:100",
                  "/sell gear:diamond sword"),
        related=("inventory", "talents", "villager", "auction sell"),
    ),
    Page(
        "market", "mining",
        "Opens the server market: choose an item in the menu, then type the quantity. "
        "Sticks and ingots are used to craft gear with /craft. The market is also always shown in the market "
        "channel, if the staff set one.",
        _market,
        examples=("/market",),
        related=("craft", "craftlist", "villager"),
    ),
    Page(
        "daily", "start",
        "Claims your daily reward, once per day. Claiming on consecutive days grows your **streak**: a bigger "
        "reward each day up to the cap, and a bonus ingot every few days in a row. Missing a day resets the streak.\n"
        "Everyone in the channel sees your reward.",
        _daily,
        examples=("/daily",),
        related=("challenges", "profile"),
    ),
    Page(
        "guide", "start",
        "Every Blocky player (the members with the Blocky player role, given by a question in Channels & Roles) "
        "gets a **private guide channel** (only them and the staff see it): how the game works, "
        "step by step, and a **checklist of first steps**: mine by chatting, `/daily`, `/sell`, pick a species, "
        "look at your `/profile`, and hit the training dummy (or play a training duel). Each step is checked by "
        "itself as soon as you do it, even if you did it before; doing them all pays a reward, once.\n"
        "`/guide` shows your checklist and a link to your guide channel. If you don't have one anymore (it's deleted "
        "a few days after the checklist is done, or after a while), it opens a new one; your progress is kept. "
        "Without the Blocky player role, it tells you where to get it. "
        "Mini-games work in your guide channel too.",
        _guide,
        examples=("/guide",),
        related=("help", "daily", "species choose"),
    ),
    # ---- gear ----
    Page(
        "craft", "gear",
        "Crafts a piece of gear from ingots and sticks (buy them with /market, or get them while mining, in "
        "drops or from other players). If that slot is empty, the new piece is equipped right away.\n"
        "Every piece has durability: it wears out when used and is **destroyed at 0**, so /repair it in time "
        "(except the shield: at 0 it stays, unusable until repaired).\n"
        "The **shield** is made of iron only (6 ingots). The **anvil** (iron only) is what you repair gear and "
        "combine books on; it wears out a little with each use. For both, leave out the material.\n"
        "Everyone in the channel sees what you crafted.",
        lambda s: ["Durability: " + listing(s["gear"]["durability"]), _shield(s),
                   f"Anvil: **{num(s['repair']['anvil_iron'])}** iron ingots", "Recipes and prices: /craftlist"],
        examples=("/craft item:pickaxe material:iron", "/craft item:anvil"),
        related=("craftlist", "market", "equip_best", "repair"),
    ),
    Page(
        "craftlist", "gear",
        "Shows every recipe: the ingots and sticks each piece needs, and what it costs at the market prices.",
        lambda s: [
            f"{item}: {ingots} ingot{'s' if ingots > 1 else ''}" + (f" + {sticks} stick{'s' if sticks > 1 else ''}" if sticks else "")
            for item, (ingots, sticks) in RECIPES.items()
        ],
        examples=("/craftlist",),
        related=("craft", "market"),
    ),
    Page(
        "gear", "gear",
        "Shows what you have equipped in each slot, what each piece does, its durability and enchantments, "
        "and your maximum damage and damage reduction for fights.\n"
        "Tools wear out when they give their bonus while mining. The sword wears out in duels, the dungeon and "
        "against bosses (1 per attack), armor in duels (every piece, 1 per hit taken) and in the dungeon (only one "
        "piece per hit, drawn at random), the shield each time it blocks an attack in a duel. Tournament fights don't "
        "wear anything (and nobody blocks there).",
        _gear,
        examples=("/gear",),
        related=("equip", "equip_best", "repair", "enchant info"),
    ),
    Page(
        "equip", "gear",
        "Equips one of your pieces in its slot (one per slot: sword, pickaxe, axe, shovel, hoe, helmet, "
        "chestplate, leggings, boots, shield). The piece that was there goes back to your inventory.",
        examples=("/equip piece:diamond pickaxe",),
        related=("equip_best", "unequip", "gear"),
    ),
    Page(
        "equip_best", "gear",
        "Fills every **empty** slot with your best piece for it: best material first, then the most "
        "enchantments, then the most durability. Slots that already have a piece don't change.",
        examples=("/equip_best",),
        related=("equip", "unequip", "gear"),
    ),
    Page(
        "unequip", "gear",
        "Takes off the piece in a slot, or **every piece** when you don't pick a slot. They go back to your "
        "inventory.",
        examples=("/unequip slot:sword", "/unequip"),
        related=("equip", "gear"),
    ),
    Page(
        "repair", "gear",
        "Repairs a piece of gear on your **anvil** (`/craft item:anvil`) with ingots of its material: gold, iron, "
        "diamond or netherite (iron for the shield). Like in Minecraft, put as many ingots as you want: each one "
        "gives back part of the durability, and the piece keeps its enchantments. Leave `ingots` empty to use as "
        "many as needed (or all you have). The suggestions show the ingots for a full repair.\n"
        "**Each repair makes the next one cost more**, and the anvil wears out a little with each use "
        "(new → chipped → damaged → broken).",
        _repair,
        examples=("/repair piece:iron sword", "/repair piece:diamond chestplate ingots:2"),
        related=("gear", "craft"),
    ),
    Page(
        "enchant apply", "gear",
        "Applies an enchanted book to a piece of gear. It costs lapis lazuli and uses up the book. "
        "A higher level replaces a lower level of the same enchantment, and a piece can have several "
        "different enchantments. Enchantments stay on the piece in trades and auctions, and disappear if it breaks.",
        lambda s: [_apply_cost(s)] + _enchant_effects(s),
        examples=("/enchant apply book:Sharpness II piece:diamond sword",),
        related=("enchant combine", "enchant info", "repair"),
    ),
    Page(
        "enchant combine", "gear",
        "Turns 2 identical books into 1 book of the next level (I + I → II, II + II → III), on your anvil "
        "(`/craft item:anvil`; it wears out a little with each use). Level III is the maximum. It's free.",
        examples=("/enchant combine book:Fortune I",),
        related=("enchant apply", "enchant info"),
    ),
    Page(
        "enchant info", "gear",
        "Shows your books and lapis lazuli, and what each enchantment does. "
        "Books come from drops, bosses (top damage dealer), completing all the weekly challenges, the villager "
        "and other players. Lapis lazuli comes from mining.",
        lambda s: [
            _apply_cost(s),
            "Book levels from drops and challenges: " + per_level(s["enchants"]["book_weights"], lambda w: f"{num(w)}%"),
        ] + _enchant_effects(s),
        examples=("/enchant info",),
        related=("enchant apply", "enchant combine", "villager"),
    ),
    # ---- xp ----
    Page(
        "xp", "progress",
        "Shows your level, your XP, what you need for the next level and your talent points. "
        "Every few levels you get a talent point to spend with /talent_buy, and some levels give a role.",
        _xp,
        examples=("/xp",),
        related=("talents", "talent_buy", "profile"),
    ),
    Page(
        "talents", "progress",
        "Shows the 4 talent branches, what they do, your points in each and their maximum.",
        _talents,
        examples=("/talents",),
        related=("talent_buy", "xp"),
    ),
    Page(
        "talent_buy", "progress",
        "Spends talent points in a branch. Points are permanent (only staff can reset talents), "
        "and a branch can't go above its maximum.",
        _talents,
        examples=("/talent_buy branch:efficiency points:2",),
        related=("talents", "xp"),
    ),
    Page(
        "species choose", "profile",
        "Picks your species, for a small bonus. Your first choice is free; changing later costs emeralds and "
        "can only be done once in a while (you confirm first). Your species is shown in /profile and as an "
        "emoji before your name in /leaderboard, /season and /team info, and the server can give a role per "
        "species.",
        _species,
        examples=("/species choose species:🔮 Mage",),
        related=("species list", "profile"),
    ),
    Page(
        "species list", "profile",
        "Shows every species, its bonus and how many players chose it, plus yours and when you can change. "
        "Only you see it.",
        _species,
        examples=("/species list",),
        related=("species choose",),
    ),
    # ---- trading ----
    Page(
        "pay", "trading",
        "Sends emeralds to another player, instantly. Payments don't count for the seasons, but they count in "
        "the **Top senders** leaderboard. Not possible while you have a late loan.",
        lambda s: [f"Minimum: {em(s['pay']['min_amount'])}"],
        examples=("/pay member:@Steve amount:100",),
        related=("trade", "loan offer"),
    ),
    Page(
        "loan offer", "trading",
        "Offers a loan to a player: the amount, the interest you ask (in %, 0 = free) and the days they have to "
        "repay. They accept or decline with the buttons (they still work after a restart); everything is checked "
        "again when they accept, and the emeralds move at once. What you lend counts in the **Top senders** "
        "leaderboard.",
        _loans,
        examples=("/loan offer member:@Steve amount:1000 interest:10 days:3",),
        related=("loan ask", "loan list", "loan forgive"),
    ),
    Page(
        "loan ask", "trading",
        "Asks a player for a loan, with the interest and the duration you propose. They accept or decline "
        "with the buttons.",
        _loans,
        examples=("/loan ask member:@Alex amount:500 interest:5 days:2",),
        related=("loan offer", "loan repay"),
    ),
    Page(
        "loan repay", "trading",
        "Pays back your loan: everything left by default, or part of it with `amount`. If the deadline passes, "
        "a penalty is added and the bot collects the rest automatically.",
        _loans,
        examples=("/loan repay", "/loan repay amount:300"),
        related=("loan list",),
    ),
    Page(
        "loan list", "trading",
        "Shows what you owe (and the deadline) and what the players you lent to still owe you. Only you see it.",
        _loans,
        examples=("/loan list",),
        related=("loan repay", "loan forgive"),
    ),
    Page(
        "loan forgive", "trading",
        "**Lender only.** Cancels what a player still owes you (asks for confirmation).",
        examples=("/loan forgive member:@Steve",),
        related=("loan list",),
    ),
    Page(
        "trade", "trading",
        "Proposes a trade: what you give and, optionally, what you want in return. The other player accepts "
        "or declines with the buttons; nothing moves until they accept, and both sides are checked again then. "
        "Leave `get` empty to make a **gift** (a gift doesn't count as a trade for achievements and challenges).\n"
        "You can trade emeralds, blocks, sticks, ingots, lapis, books, potions and gear (one piece at a time, "
        "it keeps its enchantments and durability).",
        lambda s: [f"A proposal waits **{duration(float(s['trade']['offer_minutes']) * 60)}** for an answer"],
        examples=(
            "/trade member:@Steve give:diamond ingot give_amount:3 get:emeralds get_amount:200",
            "/trade member:@Alex give:emeralds give_amount:50 → a gift",
        ),
        related=("pay", "auction sell"),
    ),
    Page(
        "auction sell", "trading",
        "Puts something up for sale for a **total** price. It leaves your inventory until it's sold, you "
        "cancel, or the listing expires (it then comes back to you). When it sells you get the price minus the tax.",
        _auction,
        examples=("/auction sell item:diamond sword price:500", "/auction sell item:bedrock price:300 amount:20"),
        related=("auction browse", "auction mine", "auction cancel"),
    ),
    Page(
        "auction browse", "trading",
        "Lists what's for sale, page by page, with the listing #number, price and seller. Filter by name with `search`.\n"
        "If the staff set a market channel, it always shows the market (fixed prices) and then every listing, "
        "each with a menu to buy.",
        examples=("/auction browse search:netherite", "/auction browse page:2"),
        related=("auction buy", "auction sell"),
    ),
    Page(
        "auction buy", "trading",
        "Buys a listing using its #number from /auction browse. The emeralds go to the seller (minus the tax), "
        "the item to you.",
        _auction,
        examples=("/auction buy listing:12",),
        related=("auction browse",),
    ),
    Page(
        "auction cancel", "trading",
        "Takes back one of your listings: the item comes back to your inventory, no tax.",
        examples=("/auction cancel listing:12",),
        related=("auction mine", "auction sell"),
    ),
    Page(
        "auction mine", "trading",
        "Shows your current listings with their #number, price and expiry.",
        examples=("/auction mine",),
        related=("auction cancel", "auction sell"),
    ),
    # ---- competition ----
    Page(
        "leaderboard", "progress",
        "Shows a server ranking: emeralds, level, total fortune (everything you own, valued in emeralds), "
        "this week's season, top senders (emeralds sent with /pay and lent with /loan), or a stat (blocks mined, "
        "bedrock found, duels won, boss damage, achievements…).",
        examples=("/leaderboard", "/leaderboard board:Level"),
        related=("profile", "season"),
    ),
    Page(
        "profile", "start",
        "Shows a player's profile card: their frame and color, avatar, name and team tag, title, level and XP, "
        "emeralds, fortune rank, species, bio, 3 showcased achievements and their team's banner; then their "
        "equipment, talents, achievements and stats. Yours by default. Customize yours with /customize.",
        examples=("/profile", "/profile member:@Steve"),
        related=("customize list", "leaderboard", "achievements")    ),
    Page(
        "season", "progress",
        "Shows this week's season standings. A season runs from Monday 00:00 to Sunday 23:59. Your score is "
        "the value you **created** during the week: blocks when you mine them, rewards (daily, drops, bosses, "
        "challenges, the server bonus of the tournament) and the Trader / villager bonus on sales. Spending never "
        "lowers it; payments, trades, gifts, duel pots and auction sales don't count.\n"
        "When the week ends the top 3 are paid and the winner gets the champion role until the next season ends.",
        _season,
        examples=("/season",),
        related=("leaderboard", "team top"),
    ),
    Page(
        "duel", "combat",
        "Challenges a player: both bet the stake and the winner takes the pot. The other player accepts with "
        "the button, then it's **turn by turn**: on your turn you can drink a potion first, then press **Attack**.\n"
        "Each hit deals a random amount between the minimum damage and your sword's maximum (potions of "
        "Strength raise the minimum). It can be a critical hit, and armor reduces it.\n"
        "With a **shield**, end your turn with **Attack + block** instead of Attack: the opponent's next attack "
        "(all its hits) is blocked. Nobody sees it coming; the duel then shows how much damage it stopped. "
        "Twice per duel at most.\n"
        "Your sword and armor wear out a little, the shield a little for each block. Duel pots don't count "
        "for the seasons.",
        _duel,
        examples=("/duel member:@Steve stake:100",),
        related=("potions", "gear", "enchant info", "tournament info"),
    ),
    Page(
        "customize bio", "profile",
        "Writes the bio of your profile card (leave it empty to remove it). Free.",
        lambda s: [f"**{num(s['profiles']['bio_max'])}** characters at most · emoji show in text, not on the card"],
        examples=("/customize bio text:Je mine donc je suis",),
        related=("profile", "customize list"),
    ),
    Page(
        "customize color", "profile",
        "Changes the color of your profile card (and of the profile message). The 16 Minecraft dye colors are "
        "bought once each, then yours for good; the default color is free. You see a preview before buying.",
        _profiles,
        examples=("/customize color color:Lime",),
        related=("customize hex", "customize list"),
    ),
    Page(
        "customize hex", "profile",
        "Uses any color by its code, like `#ff8800`. Paying once unlocks every code for good.",
        _profiles,
        examples=("/customize hex code:#ff8800",),
        related=("customize color",),
    ),
    Page(
        "customize frame", "profile",
        "Puts a patterned frame around your profile card. Some frames are bought (you see a preview first), the "
        "rarest are earned by playing: the suggestions show the price, or how to earn them.",
        _profiles,
        examples=("/customize frame frame:Diamond",),
        related=("customize list", "profile"),
    ),
    Page(
        "customize title", "profile",
        "Shows a title under your name: earned by playing (bosses, duels, dungeon, tournament, seasons, level…), "
        "or given by the staff. The suggestions list yours; /customize list shows how to earn the others.",
        examples=("/customize title title:Boss Slayer",),
        related=("customize list",),
    ),
    Page(
        "customize showcase", "profile",
        "Picks up to 3 of your achievements to show on your card. Leave them empty to show your latest ones.",
        examples=("/customize showcase badge1:Boss Slayer badge2:Squad Goals",),
        related=("achievements", "profile"),
    ),
    Page(
        "customize list", "profile",
        "Shows your colors, frames and titles, the prices of the others and how to earn the rare ones. "
        "Only you see it.",
        _profiles,
        examples=("/customize list",),
        related=("customize color", "customize frame", "customize title"),
    ),
    Page(
        "dummy hit", "combat",
        "Hits the training dummy a series of times with your current gear and species (rolled like duel hits, "
        "critical hits included). Shows every hit, the total, the average, the min and max. The dummy has no "
        "armor and doesn't hit back; nothing wears out and nothing is won. Your best series goes on the "
        "leaderboard.",
        lambda s: [f"**{num(s['dummy']['hits'])}** hits per series · one series every "
                   f"**{duration(s['dummy']['cooldown_seconds'])}**"],
        examples=("/dummy hit",),
        related=("dummy top", "dummy duel", "gear"),
    ),
    Page(
        "dummy top", "combat",
        "The training dummy leaderboard: everyone's best series (total damage), with their best hit.",
        examples=("/dummy top",),
        related=("dummy hit",),
    ),
    Page(
        "dummy duel", "combat",
        "Trains for duels against a dummy that hits back like a player wearing the gear you pick (sword and "
        "armor). Same buttons as a real duel: Attack, Attack + block with a shield, and **every potion for free** "
        "to try them. The dummy plays its turn right away. Nothing is used up (no wear, no potions taken), "
        "nothing is won or lost.",
        examples=("/dummy duel", "/dummy duel gear:Netherite dummy"),
        related=("duel", "dummy hit", "potions"),
    ),
    Page(
        "potions", "combat",
        "Shows your potions and what they do. In duels (not in the tournament): on your turn, drink one from "
        "the menu, then attack; the effect lasts for that turn (Speed lasts a few turns). In the dungeon "
        "(/pve), drink them between waves: Healing heals at once, the others help during the next wave "
        "(Harming hits every monster at its start). Potions come from drops, bosses and the villager.",
        _potions,
        examples=("/potions",),
        related=("duel", "pve start", "villager"),
    ),
    Page(
        "challenges", "progress",
        "Shows today's and this week's challenges (the same for everyone) and your progress. Each completed "
        "challenge pays emeralds, and they count for the season. New daily challenges every day at midnight, new "
        "weekly ones every Monday, never the same as the ones before. Mining, selling, duels, the Lucky Block, the "
        "wheel, Blockdle, the quiz, the dungeon, the training dummy, robberies…",
        _challenges,
        examples=("/challenges",),
        related=("achievements", "season"),
    ),
    Page(
        "achievements", "progress",
        "Shows the achievements unlocked and the ones left: permanent milestones that pay emeralds once.",
        examples=("/achievements", "/achievements member:@Steve"),
        related=("challenges", "profile"),
    ),
    # ---- events ----
    Page(
        "boss", "events",
        "Shows the current boss: health, time left and the best damage dealers. Everyone fights it together "
        "with /attack. When it's defeated, the reward pool is shared by damage dealt.",
        _boss,
        examples=("/boss",),
        related=("attack", "gear"),
    ),
    Page(
        "attack", "events",
        "Attacks the current boss once. Like in duels, a hit deals a random amount between the minimum damage "
        "and your sword's maximum, and can be a critical hit. Your sword wears out a little.",
        _attack,
        examples=("/attack",),
        related=("boss", "gear"),
    ),
    Page(
        "tournament join", "events",
        "Registers you for the weekend tournament and pays the entry fee (you can also click **Join** on the "
        "announcement). Fights are automatic, with the gear you have equipped at that moment: no potions, "
        "and nothing wears out.",
        _tournament,
        examples=("/tournament join",),
        related=("tournament info", "tournament leave", "tournament bracket"),
    ),
    Page(
        "tournament leave", "events",
        "Cancels your registration. The entry fee is refunded until the draw.",
        _tournament,
        examples=("/tournament leave",),
        related=("tournament join", "tournament info"),
    ),
    Page(
        "tournament info", "events",
        "Shows the tournament dates, the pot, the number of players and your status.",
        _tournament,
        examples=("/tournament info",),
        related=("tournament join", "tournament bracket"),
    ),
    Page(
        "tournament bracket", "events",
        "Shows the bracket: who fights whom, and the results of each round. When the number of players isn't "
        "a power of 2, some players (drawn at random) skip the first round.",
        examples=("/tournament bracket",),
        related=("tournament info",),
    ),
    Page(
        "events", "events",
        "Shows the **timed event** on now, whether **today's event** already came (which one and when), and what "
        "each one does. For a while (an hour by default) everyone gets a "
        "bonus: 🎰 **Gambling Frenzy** (bigger bets and daily limit at the Lucky Block and the wheel), ⛏️ **Mining "
        "Rush** (more mining XP), 💰 **Golden Hour** (/sell pays more), 🍀 **Lucky Hour** (more obsidian and "
        "bedrock) or 🏷️ **Market Sale** (/market cheaper). One comes by itself every day at a random time, and the "
        "staff can start one. It's announced in the events channel.",
        _live_events,
        examples=("/events",),
        related=("luckyblock", "wheel", "sell", "market"),
    ),
    Page(
        "villager", "events",
        "Shows whether the wandering villager is here and his 3 offers: a **sale** (goods below their value), "
        "a **purchase** (he buys a pile of blocks above the /sell price) and an **exclusive** (a level III book or "
        "a reinforced potion). Each offer exists once: the first player to click it gets it.",
        _villager,
        examples=("/villager",),
        related=("potions", "enchant info", "sell"),
    ),
    # ---- mini-games ----
    Page(
        "luckyblock", "games",
        "Bet emeralds and break a **Lucky Block**: a creeper explodes and you lose your bet, cobblestone gives "
        "half of it back, iron all of it, then gold, diamonds, emeralds and, rarely, **netherite** pay more and more. "
        "The bank wins a little on average.",
        _luckyblock,
        examples=("/luckyblock amount:50",),
        related=("blackjack", "mines", "wheel"),
    ),
    Page(
        "blackjack", "games",
        "A hand of **blackjack** against the dealer: get closer to 21 than him without going over. Aces count 1 or "
        "11, faces 10. **Hit** takes a card, **Stand** lets the dealer play, **Double** doubles your bet for one "
        "last card. Each hand uses a real 52-card deck, shuffled. 21 with your first two cards is a **blackjack** and pays 3:2. Only you can use the buttons.",
        _blackjack,
        examples=("/blackjack amount:50",),
        related=("mines", "luckyblock"),
    ),
    Page(
        "mines", "games",
        "**Mines**: 20 blocks, some hide TNT. Dig them one by one with the buttons: each safe block (💎) raises "
        "your multiplier, and you can **cash out** any time after the first one. Hit the TNT (💥) and you lose "
        "the bet. More TNT = bigger multipliers. Only you can use the buttons.",
        _mines,
        examples=("/mines amount:50", "/mines amount:20 tnt:5"),
        related=("blackjack", "luckyblock"),
    ),
    Page(
        "wheel", "games",
        "Spins the Minecraft wheel (a roulette) for you alone. Its numbers are those of a real roulette: the red "
        "ones are 🟥 **Redstone**, the black ones ⬛ **Obsidian**, and the green 0 is a 💎 **Diamond "
        "block**: when the wheel stops on it, every Redstone or Obsidian bet loses. In `bet`, pick Redstone, "
        "Obsidian or **A number**; for a number, pick it in the `number` option (type it to find it: Discord only "
        "lists 25 at a time), or just type the number in `bet`. The staff chooses which bets are open (`/config` → "
        "Games & events → Games of chance).",
        _roulette,
        examples=("/wheel bet:🟥 Redstone amount:50", "/wheel bet:🎯 A number amount:10 number:17",
                  "/wheel bet:17 amount:10"),
        related=("luckyblock", "blockdle guess"),
    ),
    Page(
        "blockdle guess", "games",
        "Find the Minecraft block of the day (the same for everyone, like Wordle). Guess any block: the bot compares "
        "it with the block of the day on 6 properties and answers in plain words, for example:\n"
        "🪨 Hardness: **1.5** → ⬆️ the block of the day is harder\n"
        "👁️ Transparent: **No** → ❌ the block of the day is transparent\n"
        "📅 Version: **1.14** → ⬇️ the block of the day is older\n"
        "The properties: the tool that mines it, its hardness, its blast resistance, if it's transparent, if it can be "
        "crafted, and the version it was added in. **📋 What you know so far** adds up every answer (e.g. \"harder "
        "than 0.6 and softer than 3\") and tells how many blocks are still possible; when 6 or fewer are left it "
        "names them. Some blocks have exactly the same 6 properties (e.g. Dandelion and Poppy): then try them one "
        "by one.\nGuesses are unlimited and private; the fewer you need, the bigger the reward.",
        _blockdle,
        examples=("/blockdle guess block:Stone",),
        related=("blockdle today", "blockdle top"),
    ),
    Page(
        "blockdle today", "games",
        "Shows your guesses of the day so far, how many players found the block and when the next one comes.",
        examples=("/blockdle today",),
        related=("blockdle guess", "blockdle top"),
    ),
    Page(
        "blockdle top", "games",
        "Today's ranking: who found the block of the day, with the fewest guesses first. Also tells yesterday's block.",
        examples=("/blockdle top",),
        related=("blockdle guess",),
    ),
    Page(
        "pve start", "combat",
        "Opens a dungeon run: 5 waves of monsters (zombies, then skeletons that shoot first, both, spiders and "
        "a creeper that explodes if you don't kill it fast, and a Ravager at the end). Others can join with the "
        "button (each pays the entry); the leader starts when ready. Each wave plays out on its own with your "
        "gear (and species). Your health isn't restored between waves: between two waves, everyone clicks **Ready** "
        "or **leaves with their loot**, and the next wave starts by itself when all are ready (whoever doesn't "
        "answer in time leaves with their loot). Anyone can drink a potion (Healing heals now, the others help "
        "during the next wave). Each wave cleared adds to your loot, but **if you die you lose it** and the entry. "
        "Clearing wave 5 gives a bonus. Gear wears out like in duels.",
        _pve,
        examples=("/pve start difficulty:🟡 Normal",),
        related=("pve info", "potions", "species choose"),
    ),
    Page(
        "pve info", "combat",
        "Shows the difficulties (entry, monster strength, loot), the waves and when you can play again. "
        "Only you see it.",
        _pve,
        examples=("/pve info",),
        related=("pve start",),
    ),
    Page(
        "rob", "games",
        "Robs a player. **Risky**: they get pinged, but the loot is big. **Discreet**: nobody is pinged, but the loot "
        "is small. The robbery is posted in the robberies channel (or here, when there is none) with a "
        "**Stop the thief!** button that only the victim can "
        "use: if they click it in time the robbery fails and you pay them a fine; otherwise you take the loot and "
        "they get a DM.",
        _rob,
        examples=("/rob member:@Steve mode:Risky: they get pinged, big loot", "/rob member:@Steve mode:Discreet: no ping, small loot"),
        related=("wheel", "pay"),
    ),
    Page(
        "quiz", "events",
        "Now and then a Minecraft question appears in a game channel with 4 answers. The first player to click the "
        "right one wins emeralds and XP. One try per player: a wrong answer leaves the others a chance.",
        _quiz,
        related=("wheel", "blockdle guess"),
        title="❓ Minecraft quiz",
    ),
    # ---- teams ----
    Page(
        "team create", "teams",
        "Creates a team and makes you its leader (with the team leader role, if the server set one). The tag "
        "(2 to 4 letters or digits) is shown next to the members' names. You can only be in one team.",
        _teams,
        examples=("/team create name:Diamond Diggers tag:DIG",),
        related=("team invite", "team info"),
    ),
    Page(
        "team invite", "teams",
        "**Leader only.** Invites a player. They accept with /team join before the invitation expires.",
        _teams,
        examples=("/team invite member:@Steve",),
        related=("team join", "team kick"),
    ),
    Page(
        "team join", "teams",
        "Accepts a team invitation (pick the team in the suggestions).",
        examples=("/team join team:DIG",),
        related=("team leave", "team info"),
    ),
    Page(
        "team leave", "teams",
        "Leaves your team (asks for confirmation). What you brought this week stays with the team. If the "
        "leader leaves, the oldest member becomes leader; the last member leaving disbands the team.",
        examples=("/team leave",),
        related=("team join", "team disband"),
    ),
    Page(
        "team kick", "teams",
        "**Leader only.** Removes a member from your team.",
        examples=("/team kick member:@Steve",),
        related=("team invite",),
    ),
    Page(
        "team transfer", "teams",
        "**Leader only.** Makes another member the leader. The team leader role (if the server set one) moves "
        "to them.",
        examples=("/team transfer member:@Steve",),
        related=("team info",),
    ),
    Page(
        "team banner", "teams",
        "**Leader only.** Designs the team banner, like in Minecraft: a base color and up to 3 patterns (stripes, "
        "chevron, cross, border, roundel, gradient, creeper…), each with its color, drawn on top of each other. "
        "You see it before saving. It shows on every member's profile card and in /team info.",
        lambda s: [f"Each change: {em(s['profiles']['banner_cost'])}"],
        examples=("/team banner base:Blue pattern1:Chevron color1:Yellow pattern2:Bordure color2:Black",),
        related=("team info", "profile"),
    ),
    Page(
        "team category", "teams",
        "**Leader only.** Unlocks your team's **private category** on the server, once: only your members and "
        "the staff see it. The bot creates a team role (given to every member, taken back when someone leaves), the "
        "category and a first text channel, `chat`. Then you create, rename and delete text and voice channels with "
        "`/team channel …`. If the team is disbanded, its category, channels and role are deleted.",
        _team_spaces,
        examples=("/team category",),
        related=("team channel create", "team info"),
    ),
    Page(
        "team channel create", "teams",
        "**Leader only.** Creates a **text** or **voice** channel in your team's category (unlock it first with "
        "`/team category`). Only your members and the staff see it.",
        _team_spaces,
        examples=("/team channel create name:strategy", "/team channel create name:Mining kind:Voice"),
        related=("team channel rename", "team channel delete", "team category"),
    ),
    Page(
        "team channel rename", "teams",
        "**Leader only.** Renames one of your team's channels (pick it in the suggestions). Discord allows 2 renames "
        "of the same channel per 10 minutes.",
        examples=("/team channel rename channel:chat name:headquarters",),
        related=("team channel create",),
    ),
    Page(
        "team channel delete", "teams",
        "**Leader only.** Deletes one of your team's channels, after a confirmation: its messages are lost for good. "
        "The category always keeps at least one channel.",
        examples=("/team channel delete channel:strategy",),
        related=("team channel create",),
    ),
    Page(
        "team rename", "teams",
        "**Leader only.** Changes the name and/or the tag. Leave an option empty to keep it.",
        examples=("/team rename tag:DIG2", "/team rename name:Netherite Ninjas"),
        related=("team info",),
    ),
    Page(
        "team disband", "teams",
        "**Leader only.** Deletes your team (asks for confirmation). All members become teamless.",
        examples=("/team disband",),
        related=("team leave",),
    ),
    Page(
        "team info", "teams",
        "Shows a team: tag, leader, members, this week's score and the current XP bonus. Yours by default.",
        _teams,
        examples=("/team info", "/team info team:DIG"),
        related=("team top",),
    ),
    Page(
        "team top", "teams",
        "This week's team season: teams ranked by the emeralds their members earned while in the team. "
        "The best earner counts in full and the others less and less (×0.69, ×0.41, ×0.29, ×0.22), so a big "
        "team doesn't win just by being big: 5 members earning the same score ×2.6, not ×5, and one more member "
        "earning anything never lowers the score. The rewards of the top teams are shared between their members "
        "in proportion to what each one brought, so joining the leading team on Sunday is worth little.",
        _teams,
        examples=("/team top",),
        related=("team info", "season"),
    ),
    # ---- minecraft ----
    Page(
        "server_status", "minecraft",
        "Shows whether the Minecraft server is online, how many players are connected and the latency.",
        examples=("/server_status",),
        related=("ip", "modpacks"),
    ),
    Page(
        "ip", "minecraft",
        "Shows the address to join the Minecraft server.",
        examples=("/ip",),
        related=("modpacks", "link"),
    ),
    Page(
        "modpacks", "minecraft",
        "Shows the modpack to install to play on the server.",
        examples=("/modpacks",),
        related=("ip",),
    ),
    Page(
        "link", "minecraft",
        "Links your Minecraft **Java** account to Discord. The name is checked with Mojang, then staff approves "
        "or rejects the request. Once approved, you're added to the server whitelist.",
        examples=("/link username:Steve",),
        related=("link_status", "ip"),
    ),
    Page(
        "link_status", "minecraft",
        "Shows the Minecraft account linked to you, or your pending request.",
        examples=("/link_status",),
        related=("link",),
    ),
    # ---- staff: moderation ----
    Page(
        "warn", "staff_moderation",
        "Warns a member: they get the reason by DM and it's saved in their history. Reaching some numbers of "
        "active warnings mutes them automatically (a longer mute already running is never shortened).",
        _moderation,
        examples=("/warn member:@Steve reason:Spam in #general",),
        related=("unwarn", "history", "mute"),
    ),
    Page(
        "unwarn", "staff_moderation",
        "Removes one warning, by its number (shown in /history).",
        examples=("/unwarn warning:12",),
        related=("history", "clearwarns"),
    ),
    Page(
        "clearwarns", "staff_moderation",
        "Removes all the warnings of a member.",
        examples=("/clearwarns member:@Steve",),
        related=("unwarn", "history"),
    ),
    Page(
        "blocky ban", "staff_moderation",
        "Blocks a player from Blocky: they can't use any of the bot's commands, buttons or menus until the end "
        "(`30m`, `2h`, `3d`, `1w`…) or until you lift it (`perm`). They keep everything they own and still mine "
        "by chatting. They get a DM with the reason and the end, and see it again when they try a command. "
        "A new block replaces the previous one. Staff members can't be blocked. Logged in the staff channel.",
        examples=("/blocky ban member:@Steve duration:3d reason:Auction scam", "/blocky ban member:@Steve duration:perm reason:Bug abuse"),
        related=("blocky unban", "blocky list"),
    ),
    Page(
        "blocky unban", "staff_moderation",
        "Lifts a player's Blocky block before its end. They get a DM.",
        examples=("/blocky unban member:@Steve",),
        related=("blocky ban", "blocky list"),
    ),
    Page(
        "blocky list", "staff_moderation",
        "Shows the players blocked from Blocky, until when, by whom and why.",
        examples=("/blocky list",),
        related=("blocky ban",),
    ),
    Page(
        "history", "staff_moderation",
        "Shows a member's warnings (with their numbers) and sanctions: mutes, kicks and bans, and which ones are "
        "still active. Works for users who left the server.",
        _moderation,
        examples=("/history member:@Steve",),
        related=("warn", "unwarn"),
    ),
    Page(
        "mute", "staff_moderation",
        "Mutes a member with a Discord timeout, for a duration or permanently. Discord limits timeouts to 28 "
        "days: the bot renews long and permanent mutes by itself, and applies them again if the member leaves "
        "and comes back. The member gets the reason by DM.",
        lambda s: [DURATIONS],
        examples=("/mute member:@Steve duration:2h reason:Spam", "/mute member:@Steve duration:perm reason:Insults"),
        related=("unmute", "warn", "history"),
    ),
    Page(
        "unmute", "staff_moderation",
        "Ends a member's mute right away.",
        examples=("/unmute member:@Steve",),
        related=("mute",),
    ),
    Page(
        "kick", "staff_moderation",
        "Kicks a member: they can come back with an invite. They get the reason by DM and it's saved.",
        examples=("/kick member:@Steve reason:Advertising",),
        related=("ban", "history"),
    ),
    Page(
        "ban", "staff_moderation",
        "Bans a user, for a duration or permanently (permanent by default), even if they already left. "
        "Temporary bans are lifted automatically. Can also delete their recent messages.",
        lambda s: [DURATIONS],
        examples=("/ban member:@Steve reason:Cheating duration:7d", "/ban member:@Steve reason:Raid delete_messages:Last 24 hours"),
        related=("unban", "kick", "history"),
    ),
    Page(
        "unban", "staff_moderation",
        "Lifts a ban using the user's ID (shown in /history and in the staff log).",
        examples=("/unban user_id:123456789012345678",),
        related=("ban", "history"),
    ),
    Page(
        "clear", "staff_moderation",
        "Deletes the last messages of this channel (up to 100), or only the last messages of one member. "
        "Pinned messages are kept.",
        examples=("/clear amount:20", "/clear amount:50 member:@Steve"),
        related=("lock", "slowmode"),
    ),
    Page(
        "lock", "staff_moderation",
        "Nobody can write in the channel anymore, except staff and the bot. The channel's permissions are saved "
        "first and /unlock restores them exactly.",
        examples=("/lock", "/lock channel:#general reason:Calm down please"),
        related=("unlock", "slowmode"),
    ),
    Page(
        "unlock", "staff_moderation",
        "Unlocks a channel locked with /lock: its permissions go back to exactly what they were.",
        examples=("/unlock", "/unlock channel:#general"),
        related=("lock",),
    ),
    Page(
        "slowmode", "staff_moderation",
        "Sets the slow mode of a channel: the seconds a member must wait between two messages (0 = off, max 6 h).",
        examples=("/slowmode seconds:10", "/slowmode seconds:0 channel:#general"),
        related=("lock", "clear"),
    ),
    # ---- staff: economy ----
    Page(
        "give", "staff_players",
        "Gives anything to a member: emeralds, blocks, sticks, ingots, lapis, books, potions or gear. Pick it in the "
        "suggestions; for an enchanted piece, type its full key, e.g. `gear:diamond:sword:sharpness3,unbreaking2`.\n"
        "The member gets a DM (with the reason, if any) and it's written in the staff log. What staff gives doesn't "
        "count for the seasons.",
        lambda s: [f"Gear: at most **{num(MAX_STAFF_GEAR)}** pieces at once (new, full durability)"],
        examples=(
            "/give member:@Steve item:emeralds amount:500 reason:Event winner",
            "/give member:@Steve item:Sharpness III book",
            "/give member:@Steve item:gear:netherite:sword:sharpness3",
        ),
        related=("take", "player xp_add"),
    ),
    Page(
        "take", "staff_players",
        "Removes something a member owns: the suggestions list what they really have. You confirm with a button "
        "first, and it never removes more than they have (spare gear goes before equipped gear).\n"
        "The member gets a DM (with the reason, if any) and it's written in the staff log.",
        examples=("/take member:@Steve item:emeralds amount:200 reason:Bug abuse",),
        related=("give",),
    ),
    Page(
        "guide_resend", "staff_players",
        "Sends the guide again in a **new private channel** (the old one is deleted): to one `member`, or to "
        "**every member with the Blocky player role** when it's empty (you confirm first; the newest members first). "
        "Steps already done stay "
        "checked and the checklist reward is never paid twice.\n"
        "Discord allows 500 channels per server and 50 per category: the bot adds categories named after the guide "
        "category (\"Guides 2\"…) when one is full, and stops a little before 500 (the report says who was left "
        "out). Sending to everyone runs in the background; the result is also posted in the staff channel.\n"
        "Needs the guide category (`/config` → Channels), the Blocky player role (`/config` → Roles, for everyone) "
        "and the *Manage Channels* and *Manage Roles* permissions.",
        _guide,
        examples=("/guide_resend member:@Steve", "/guide_resend"),
        related=("guide", "config"),
    ),
    Page(
        "reset", "staff_players",
        "A fresh start, for one player (`member`) or for **everyone** (leave `member` empty). Pick what to reset: "
        "emeralds, blocks and items (with auction listings, robberies in progress and loans), gear and enchantments, "
        "levels, XP and talents (level roles are removed), stats, achievements and seasons (with challenges, "
        "team season scores, the daily streak and the guide checklist, reward included). Then press **Reset…** and type `RESET`.\n"
        "A backup of the database is made just before (restore it to undo). Minecraft links, moderation, teams, "
        "settings, bosses, tournaments, the villager and the Blockdle are never touched.",
        examples=("/reset", "/reset member:@Steve"),
        related=("take", "player level", "backup_now"),
    ),
    Page(
        "player xp_add", "staff_players",
        "Gives XP to a member: levels and talent points follow, like normal XP. The member gets a DM.",
        examples=("/player xp_add member:@Steve amount:1000",),
        related=("player xp_set", "player level"),
    ),
    Page(
        "player xp_set", "staff_players",
        "Sets a member's XP inside their current level. The member gets a DM.",
        examples=("/player xp_set member:@Steve xp:50",),
        related=("player xp_add", "player level"),
    ),
    Page(
        "player level", "staff_players",
        "Sets a member's level: their unspent talent points are recomputed and their level role updated. "
        "The member gets a DM.",
        examples=("/player level member:@Steve level:25",),
        related=("player xp_add", "player talents_reset", "player sync_roles"),
    ),
    Page(
        "player talents_add", "staff_players",
        "Adds talent points to a member (a negative number removes some). The member gets a DM.",
        examples=("/player talents_add member:@Steve points:2", "/player talents_add member:@Steve points:-1"),
        related=("player talents_reset",),
    ),
    Page(
        "player talents_reset", "staff_players",
        "Resets a member's talents: every spent point is refunded, to spend again with /talent_buy. "
        "The member gets a DM.",
        examples=("/player talents_reset member:@Steve",),
        related=("player talents_add",),
    ),
    Page(
        "player species", "staff_players",
        "Sets a member's species (or none), for free and without the waiting time. Their species role "
        "follows. The member gets a DM.",
        _species,
        examples=("/player species member:@Steve species:🪓 Dwarf",),
        related=("species choose",),
    ),
    Page(
        "player title", "staff_players",
        "Gives a member a custom title (40 characters at most) and puts it on their profile card. They keep it "
        "in their titles. The member gets a DM.",
        examples=("/player title member:@Steve title:The Architect",),
        related=("player profile_reset", "customize title"),
    ),
    Page(
        "player profile_reset", "staff_players",
        "Removes a member's bio, their title (and the custom titles the staff gave them), or both. The member "
        "gets a DM with the reason.",
        examples=("/player profile_reset member:@Steve part:Bio reason:Insult",),
        related=("player title",),
    ),
    Page(
        "player sync_roles", "staff_players",
        "Gives every member the level role matching their level (after changing the level roles in /config).",
        examples=("/player sync_roles",),
        related=("config", "player level"),
    ),
    Page(
        "player cooldowns", "staff_players",
        "Resets a member's waiting times so they can play again right away: one of them, or all of them when "
        "`timer` is empty. Robbing again, the protection after being robbed, the dungeon, the training dummy, a "
        "boss attack, duels, the Lucky Block and roulette, mining, changing species, and the daily reward (today's "
        "claim is undone: claiming again gives today's reward once more, the streak doesn't grow twice). The "
        "member gets a DM and the staff channel keeps a trace.",
        examples=("/player cooldowns member:@Steve", "/player cooldowns member:@Steve timer:Robbing again"),
        related=("rob", "daily", "pve start"),
    ),
    # ---- staff: events ----
    Page(
        "event boss", "staff_events",
        "Summons a boss now (only one at a time), with the name and HP you choose or the default ones.",
        lambda s: [f"Default HP: **{num(s['boss']['hp'])}**", "Names: " + ", ".join(s["boss"]["names"])] + _boss(s)[:1],
        examples=("/event boss", "/event boss name:Herobrine hp:5000"),
        related=("boss", "event drop"),
    ),
    Page(
        "event drop", "staff_events",
        "Makes a drop appear in this channel right now: the first player to click it gets the reward.",
        examples=("/event drop",),
        related=("event boss",),
    ),
    Page(
        "event tournament", "staff_events",
        "Opens the registrations now, moves to the next step now (the draw, then the next round), or cancels the "
        "tournament and refunds everyone. Handy to test without waiting for the weekend.",
        _tournament,
        examples=("/event tournament action:Open registrations now",),
        related=("tournament info", "tournament bracket"),
    ),
    Page(
        "event quiz", "staff_events",
        "Posts a Minecraft quiz question in this channel right now.",
        _quiz,
        examples=("/event quiz",),
        related=("event drop",),
    ),
    Page(
        "event start", "staff_events",
        "Starts a timed event now, for everyone: Gambling Frenzy, Mining Rush, Golden Hour, Lucky Hour or Market "
        "Sale. It's announced in the events channel (with the events role). One at a time: end the current one "
        "first with /event stop. The daily random event still comes if none is on at its time.",
        _live_events,
        examples=("/event start event:🎰 Gambling Frenzy", "/event start event:💰 Golden Hour minutes:30"),
        related=("event stop", "events"),
    ),
    Page(
        "event stop", "staff_events",
        "Ends the timed event that is on now. Its announcement shows that it's over.",
        examples=("/event stop",),
        related=("event start", "events"),
    ),
    Page(
        "event villager", "staff_events",
        "Makes the villager come now (for the usual visit length) or leave now.",
        _villager,
        examples=("/event villager action:Come now (usual visit length)",),
        related=("villager",),
    ),
    Page(
        "team_remove", "staff_events",
        "Deletes a team (offensive name…). All its members become teamless.",
        examples=("/team_remove team:DIG",),
        related=("team info",),
    ),
    # ---- staff: server ----
    Page(
        "config", "staff_server",
        "Opens the settings panel: **almost every setting of the bot** (not the server and Minecraft connection, "
        "the staff role or the database: only config.json changes those). Pick a section (Server, Economy, Progress, "
        "Combat, Games & events), then a category. Each setting shows what it does, its value and its default, "
        "with buttons to change it or to reset it. Lists, automatic mutes, the drop table and the villager's goods "
        "have their own editors.\n"
        "Changes are saved in config.json (a copy of the old file is kept) and apply at once. Settings in the file "
        "that the bot doesn't use (left by an older version, or a typo) never block a change: they are removed.\n"
        "The RCON password, the staff role and the database path can't be seen or changed from Discord.",
        examples=("/config",),
        related=("reload_config", "backup_now"),
    ),
    Page(
        "bot_update", "staff_server",
        "Updates Blocky from GitHub. First it shows the **new changes** (their titles) and warnings, if any (files "
        "changed by hand in the Blocky folder, another branch…), with an **Update and restart** button. Then the "
        "**updater** (a small container next to the bot) pulls the changes, rebuilds the bot and restarts it: a "
        "few minutes. The result (the version and what changed, or the error) is posted in the staff channel. If "
        "the pull or the rebuild fails, the bot keeps running the old version.\n"
        "Needs the updater container: see the README, *Updating from Discord*. New features are then announced in "
        "the updates channel.",
        examples=("/bot_update",),
        related=("reload_config", "backup_now"),
    ),
    Page(
        "reload_config", "staff_server",
        "Reads config.json again after you edited it by hand, without restarting the bot. If the file isn't "
        "valid JSON, nothing changes and the error is shown. Wrong values in `balance` are ignored (the default "
        "is used) and listed.",
        examples=("/reload_config",),
        related=("config",),
    ),
    Page(
        "backup_now", "staff_server",
        "Saves a copy of the database right now, in the backups folder next to it. The bot also makes one "
        "every night.",
        lambda s: [f"Nightly copy at **{hour(s['backups']['hour'])}**, the last **{num(s['backups']['keep'])}** are kept"],
        examples=("/backup_now",),
        related=("config",),
    ),
    Page(
        "mc", "staff_server",
        "Runs a command on the Minecraft server console (RCON) and shows the answer. Dangerous commands are "
        "refused, also when hidden after `execute … run`.",
        lambda s: ["Blocked: " + (", ".join(f"`{c}`" for c in blocked_list()) or "nothing")
                   + ("" if tuple(blocked_list()) == DEFAULT_BLOCKED else " (the list set in config.json)")],
        examples=("/mc command:say Hello everyone", "/mc command:give Steve diamond 3"),
        related=("whitelist list", "server_status"),
    ),
    Page(
        "whitelist add", "staff_server",
        "Adds a Minecraft Java player to the server whitelist (the name is checked with Mojang).",
        examples=("/whitelist add username:Steve",),
        related=("whitelist remove", "whitelist list"),
    ),
    Page(
        "whitelist remove", "staff_server",
        "Removes a player from the server whitelist.",
        examples=("/whitelist remove username:Steve",),
        related=("whitelist add", "whitelist list"),
    ),
    Page(
        "whitelist list", "staff_server",
        "Shows the current server whitelist.",
        examples=("/whitelist list",),
        related=("whitelist add", "whitelist remove"),
    ),
    Page(
        "unlink", "staff_server",
        "Removes a member's Minecraft link, and their name from the whitelist.",
        examples=("/unlink member:@Steve",),
        related=("link", "whitelist remove"),
    ),
]

BY_NAME: dict[str, Page] = {p.name: p for p in PAGES}


def visible(staff: bool) -> list[Page]:
    return [p for p in PAGES if staff or not p.staff]


def categories(staff: bool) -> list[str]:
    return [key for key, (_, only_staff) in CATEGORIES.items() if staff or not only_staff]


def in_category(category: str) -> list[Page]:
    return [p for p in PAGES if p.category == category]


def find(text: str, staff: bool) -> Page | None:
    """'/Team  Create' -> the page of /team create (None if unknown or staff only)."""
    key = " ".join(text.strip().lstrip("/").lower().split())
    page = BY_NAME.get(key)
    if page is None or (page.staff and not staff):
        return None
    return page


def search(text: str, staff: bool, limit: int = 25) -> list[Page]:
    """Pages for an autocomplete: names starting with the text first, then names containing it."""
    key = " ".join(text.strip().lstrip("/").lower().split())
    pages = visible(staff)
    first = [p for p in pages if p.name.startswith(key)]
    then = [p for p in pages if key in p.name and p not in first]
    return (first + then)[:limit]
