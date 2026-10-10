"""The manual shown by /help: one page per slash command, plus a few topics.

Pages are plain data (no discord), so the tests check that every command has
one. The "current values" of a page are computed from the live settings each
time it is shown, so they follow /config and config.json. Options come from the
command tree itself (see cogs/help_command.py), so they never go stale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from game import enchants, potions, progress
from game.assets import MAX_STAFF_GEAR
from game.catalog import RECIPES, TALENT_BRANCHES
from utils.mc_commands import DEFAULT_BLOCKED

Settings = dict[str, Any]

# key -> (label, staff only)
CATEGORIES: dict[str, tuple[str, bool]] = {
    "basics": ("⛏️ Basics & economy", False),
    "gear": ("🛠️ Crafting & gear", False),
    "xp": ("⭐ XP & talents", False),
    "trading": ("🤝 Trading", False),
    "competition": ("🏆 Competition", False),
    "events": ("🎉 Events", False),
    "teams": ("🛡️ Teams", False),
    "minecraft": ("🌍 Minecraft", False),
    "staff_moderation": ("🔨 Staff · moderation", True),
    "staff_economy": ("💰 Staff · economy & players", True),
    "staff_events": ("🎪 Staff · events & teams", True),
    "staff_server": ("⚙️ Staff · server & Minecraft", True),
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
        lines.append(f"Every 7th day in a row: **1 {d['weekly_bonus_item']} ingot**")
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
        "Durability: " + listing(g["durability"]),
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
    }
    lines = []
    for ench in enchants.ENCHANTS.values():
        items = "any gear" if len(ench.items) > 4 else ", ".join(ench.items)
        if ench.key == "protection":
            items = "armor"
        lines.append(f"**{ench.name}** ({items}): {effects[ench.key]} (I / II / III)")
    return lines


def _apply_cost(s: Settings) -> str:
    return "Lapis to apply a book: " + per_level(s["enchants"]["apply_cost"])


def _xp(s: Settings) -> list[str]:
    m, d, du, b, t = s["mining"], s["daily"], s["duel"], s["boss"], s["tournament"]
    lo, hi = m["xp_per_message"]
    return [
        f"XP for the next level: **{num(s['levels']['xp_first_level'])}** at level 1, "
        f"**+{num(s['levels']['xp_increase_per_level'])}** per level",
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
        f"Dodge: **{pct(d['dodge_chance'])}** · critical hit: **{pct(d['crit_chance'])}** (×{num(d['crit_multiplier'])})",
        _armor(s),
        f"Potions: up to **{num(p['max_per_duel'])}** per duel, one per turn",
        f"Minimum stake: {em(d['min_stake'])} · **{duration(d['cooldown_seconds'])}** between two duels · "
        f"the challenge expires after **{duration(d['request_timeout_seconds'])}**",
        f"Turns: **{duration(d['turn_seconds'])}** to play, then the bot attacks for you; after "
        f"**{num(d['afk_turns'])}** missed turns the rest is played automatically",
        f"XP: won **{num(d['xp_win'])}** · lost **{num(d['xp_loss'])}**",
    ]


def _potions(s: Settings) -> list[str]:
    p = s["potions"]
    lines = [f"**{potion.name}**: {potions.effect_text(key)}" for key, potion in potions.POTIONS.items()]
    lines += [
        f"Reinforced (II): effect **×{num(p['level2_multiplier'])}**, only one per duel",
        f"Up to **{num(p['max_per_duel'])}** potions per duel, one per turn",
        f"Bosses: the top **{num(p['boss_top'])}** damage dealers get a random potion",
    ]
    return lines


def _season(s: Settings) -> list[str]:
    rewards = s["seasons"]["rewards"]
    places = " · ".join(f"#{i + 1} {num(r)}" for i, r in enumerate(rewards))
    return [f"Podium rewards (emeralds): {places or 'none'}", f"Weeks follow the server time ({s['timezone']})"]


def _challenges(s: Settings) -> list[str]:
    lines = [f"**{num(s['challenges']['per_week'])}** challenges per week"]
    if s["enchants"]["challenges_book"]:
        lines.append("All of them done: a random enchanted book")
    lines += [f"{c.text}: {em(c.reward)}" for c in progress.challenge_pool() if progress.available(c)]
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
        f"Reward pool: {em(b['reward_pool'])} shared by damage · top damage dealer: **+{num(b['top_damage_bonus'])}** "
        f"and a book",
        f"Top **{num(s['potions']['boss_top'])}**: a random potion · XP for everyone: **{num(b['xp_reward'])}**",
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
    ]


def _moderation(s: Settings) -> list[str]:
    m = s["moderation"]
    days = int(m["warn_expire_days"])
    mutes = sorted(m["warn_mutes"].items(), key=lambda kv: int(kv[0]))
    return [
        f"Warnings count for **{days} days**" if days else "Warnings count forever",
        "Automatic mutes: " + (" · ".join(f"{n} warnings → {d}" for n, d in mutes) or "none"),
    ]


DURATIONS = "Durations: `30m`, `2h`, `3d`, `1w`, `1d12h`… (1 minute to 1 year) or `perm`"


# ---------------- pages ----------------
PAGES: list[Page] = [
    # ---- basics ----
    Page(
        "help", "basics",
        "Opens this manual. Pick a category in the menu, then a command to read its page: what it does, "
        "its options, its current numbers (they follow the server settings), examples and related commands.\n"
        "You can also open a page directly with the `command` option.",
        examples=("/help", "/help command:duel", "/help command:mining"),
    ),
    Page(
        "mining", "basics",
        "There is no command to mine: **every message you send mines blocks**, at most once per cooldown. "
        "It's silent: check what you got with /inventory.\n"
        "Your equipped tools add bonuses (/gear), your talents improve the odds (/talents), and teammates who "
        "mined today give you more XP (/team info). Mining also finds lapis lazuli, and sometimes makes a "
        "**drop** appear: the first player to click it gets the reward.\n\n"
        "In **spam channels** you don't mine blocks: each reward is a tiny amount of emeralds instead, saved "
        "until it makes a whole emerald (no XP, no drops, doesn't count for the seasons).",
        _mining,
        related=("inventory", "sell", "gear", "talents"),
        title="⛏️ Mining (chat)",
    ),
    Page(
        "inventory", "basics",
        "Shows everything you own: emeralds, blocks, sticks, ingots, lapis lazuli, enchanted books, potions "
        "and your gear with its durability.",
        lambda s: [_block_values(s)],
        examples=("/inventory",),
        related=("sell", "gear", "enchant info", "potions"),
    ),
    Page(
        "sell", "basics",
        "Sells **all** your blocks at once for emeralds. The Trader talent adds a bonus on top.\n"
        "Blocks already counted for the season when you mined them, so selling only adds the Trader bonus to "
        "your season score. Ingots, gear, books and potions aren't sold here: use /auction or /trade. "
        "The wandering villager sometimes buys a pile of blocks above this price (/villager).\n"
        "Everyone in the channel sees your sale.",
        lambda s: [
            _block_values(s),
            f"Trader talent: **+{pct(s['talents']['trader_bonus_per_point'])}** per point "
            f"(max **+{pct(s['talents']['trader_bonus_per_point'] * s['talents']['caps']['trader'])}**)",
        ],
        examples=("/sell",),
        related=("inventory", "talents", "villager", "auction sell"),
    ),
    Page(
        "market", "basics",
        "Opens the server market: choose an item in the menu, then type the quantity. "
        "Sticks and ingots are used to craft gear with /craft.",
        _market,
        examples=("/market",),
        related=("craft", "craftlist", "villager"),
    ),
    Page(
        "daily", "basics",
        "Claims your daily reward, once per day. Claiming on consecutive days grows your **streak**: a bigger "
        "reward each day up to the cap, and an ingot every 7th day in a row. Missing a day resets the streak.\n"
        "Everyone in the channel sees your reward.",
        _daily,
        examples=("/daily",),
        related=("challenges", "profile"),
    ),
    # ---- gear ----
    Page(
        "craft", "gear",
        "Crafts a piece of gear from ingots and sticks (buy them with /market, or get them while mining, in "
        "drops or from other players). If that slot is empty, the new piece is equipped right away.\n"
        "Every piece has durability: it wears out when used and is **destroyed at 0**, so /repair it in time.\n"
        "Everyone in the channel sees what you crafted.",
        lambda s: ["Durability: " + listing(s["gear"]["durability"]), "Recipes and prices: /craftlist"],
        examples=("/craft item:pickaxe material:iron",),
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
        "Tools wear out when they give their bonus while mining. The sword wears out in duels and against "
        "bosses, armor in duels. Tournament fights don't wear anything.",
        _gear,
        examples=("/gear",),
        related=("equip", "equip_best", "repair", "enchant info"),
    ),
    Page(
        "equip", "gear",
        "Equips one of your pieces in its slot (one per slot: sword, pickaxe, axe, shovel, hoe, helmet, "
        "chestplate, leggings, boots). The piece that was there goes back to your inventory.",
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
        "Takes off the piece in a slot. It goes back to your inventory.",
        examples=("/unequip slot:sword",),
        related=("equip", "gear"),
    ),
    Page(
        "repair", "gear",
        "Repairs a piece of gear to full durability for emeralds. The price depends on the durability "
        "missing, and the piece keeps its enchantments. The suggestions show the cost of each piece.",
        lambda s: [
            f"A piece with no durability left costs **{num(s['repair']['cost_percent'])}%** of its crafting value "
            "(ingots + sticks at the market prices); less if it's only partly worn"
        ],
        examples=("/repair piece:iron sword",),
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
        "Turns 2 identical books into 1 book of the next level (I + I → II, II + II → III). "
        "Level III is the maximum. It's free.",
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
        "xp", "xp",
        "Shows your level, your XP, what you need for the next level and your talent points. "
        "Every few levels you get a talent point to spend with /talent_buy, and some levels give a role.",
        _xp,
        examples=("/xp",),
        related=("talents", "talent_buy", "profile"),
    ),
    Page(
        "talents", "xp",
        "Shows the 4 talent branches, what they do, your points in each and their maximum.",
        _talents,
        examples=("/talents",),
        related=("talent_buy", "xp"),
    ),
    Page(
        "talent_buy", "xp",
        "Spends talent points in a branch. Points are permanent (only staff can reset talents), "
        "and a branch can't go above its maximum.",
        _talents,
        examples=("/talent_buy branch:efficiency points:2",),
        related=("talents", "xp"),
    ),
    # ---- trading ----
    Page(
        "pay", "trading",
        "Sends emeralds to another player, instantly. Payments don't count for the seasons.",
        lambda s: [f"Minimum: {em(s['pay']['min_amount'])}"],
        examples=("/pay member:@Steve amount:100",),
        related=("trade",),
    ),
    Page(
        "trade", "trading",
        "Proposes a trade: what you give and, optionally, what you want in return. The other player accepts "
        "or declines with the buttons; nothing moves until they accept, and both sides are checked again then. "
        "Leave `get` empty to make a **gift**.\n"
        "You can trade emeralds, blocks, sticks, ingots, lapis, books, potions and gear (one piece at a time, "
        "it keeps its enchantments and durability). The proposal expires after 5 minutes.",
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
        "Lists what's for sale, page by page, with the listing #number, price and seller. Filter by name with `search`.",
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
        "leaderboard", "competition",
        "Shows a server ranking: emeralds, level, total fortune (everything you own, valued in emeralds), "
        "this week's season, or a stat (blocks mined, bedrock found, duels won, boss damage, achievements…).",
        examples=("/leaderboard", "/leaderboard board:Level"),
        related=("profile", "season"),
    ),
    Page(
        "profile", "competition",
        "Shows a player's profile: level, emeralds, fortune and main stats. Yours by default.",
        examples=("/profile", "/profile member:@Steve"),
        related=("leaderboard", "achievements", "xp"),
    ),
    Page(
        "season", "competition",
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
        "duel", "competition",
        "Challenges a player: both bet the stake and the winner takes the pot. The other player accepts with "
        "the button, then it's **turn by turn**: on your turn you can drink a potion first, then press **Attack**.\n"
        "Each hit deals a random amount between the minimum damage and your sword's maximum (potions of "
        "Strength raise the minimum). It can be dodged or be a critical hit, and armor reduces it. "
        "Your sword and armor wear out a little. Duel pots don't count for the seasons.",
        _duel,
        examples=("/duel member:@Steve stake:100",),
        related=("potions", "gear", "enchant info", "tournament info"),
    ),
    Page(
        "potions", "competition",
        "Shows your potions and what they do. Potions only work in duels (not in the tournament): on your "
        "turn, drink one from the menu, then attack. The effect lasts for that turn (Speed lasts a few turns). "
        "Potions come from drops, bosses and the villager.",
        _potions,
        examples=("/potions",),
        related=("duel", "villager"),
    ),
    Page(
        "challenges", "competition",
        "Shows this week's challenges (the same for everyone) and your progress. Each completed challenge pays "
        "emeralds. New challenges every Monday.",
        _challenges,
        examples=("/challenges",),
        related=("achievements", "season"),
    ),
    Page(
        "achievements", "competition",
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
        "villager", "events",
        "Shows whether the wandering villager is here and his 3 offers: a **sale** (goods below their value), "
        "a **purchase** (he buys a pile of blocks above the /sell price) and an **exclusive** (a level III book or "
        "a reinforced potion). Each offer exists once: the first player to click it gets it.",
        _villager,
        examples=("/villager",),
        related=("potions", "enchant info", "sell"),
    ),
    # ---- teams ----
    Page(
        "team create", "teams",
        "Creates a team and makes you its leader. The tag (2 to 4 letters or digits) is shown next to the "
        "members' names. You can only be in one team.",
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
        "**Leader only.** Makes another member the leader.",
        examples=("/team transfer member:@Steve",),
        related=("team info",),
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
        "The rewards of the top teams are shared between their members in proportion to what each one brought, "
        "so joining the leading team on Sunday is worth little.",
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
        "give", "staff_economy",
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
        "take", "staff_economy",
        "Removes something a member owns: the suggestions list what they really have. You confirm with a button "
        "first, and it never removes more than they have (spare gear goes before equipped gear).\n"
        "The member gets a DM (with the reason, if any) and it's written in the staff log.",
        examples=("/take member:@Steve item:emeralds amount:200 reason:Bug abuse",),
        related=("give",),
    ),
    Page(
        "player xp_add", "staff_economy",
        "Gives XP to a member: levels and talent points follow, like normal XP. The member gets a DM.",
        examples=("/player xp_add member:@Steve amount:1000",),
        related=("player xp_set", "player level"),
    ),
    Page(
        "player xp_set", "staff_economy",
        "Sets a member's XP inside their current level. The member gets a DM.",
        examples=("/player xp_set member:@Steve xp:50",),
        related=("player xp_add", "player level"),
    ),
    Page(
        "player level", "staff_economy",
        "Sets a member's level: their unspent talent points are recomputed and their level role updated. "
        "The member gets a DM.",
        examples=("/player level member:@Steve level:25",),
        related=("player xp_add", "player talents_reset", "player sync_roles"),
    ),
    Page(
        "player talents_add", "staff_economy",
        "Adds talent points to a member (a negative number removes some). The member gets a DM.",
        examples=("/player talents_add member:@Steve points:2", "/player talents_add member:@Steve points:-1"),
        related=("player talents_reset",),
    ),
    Page(
        "player talents_reset", "staff_economy",
        "Resets a member's talents: every spent point is refunded, to spend again with /talent_buy. "
        "The member gets a DM.",
        examples=("/player talents_reset member:@Steve",),
        related=("player talents_add",),
    ),
    Page(
        "player sync_roles", "staff_economy",
        "Gives every member the level role matching their level (after changing the level roles in /config).",
        examples=("/player sync_roles",),
        related=("config", "player level"),
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
        "Opens the settings panel: **every setting of the bot**, in categories (channels, roles, mining and its "
        "odds, XP and talents, market, gear, duels, potions, enchanting, drops, bosses, seasons, challenges, "
        "achievements, teams, tournament, villager…). Each setting shows what it does, its value and its default, "
        "with buttons to change it or to reset it. Lists, automatic mutes, the drop table and the villager's goods "
        "have their own editors.\n"
        "Changes are saved in config.json (a copy of the old file is kept) and apply at once. Settings in the file "
        "that the bot doesn't use (left by an older version, or a typo) never block a change: they are removed.\n"
        "The RCON password, the staff role and the database path can't be seen or changed from Discord.",
        examples=("/config",),
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
        lambda s: ["Blocked: " + ", ".join(f"`{c}`" for c in DEFAULT_BLOCKED)],
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
