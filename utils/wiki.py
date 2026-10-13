"""The wiki: every feature for players, explained in detail, kept in a channel by the bot.

Each section is an explanation followed by its current numbers, which come from the
/help pages (utils/manual.py) so they follow /config like the manual does. Staff
commands are left out: they are in /help, for the staff only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from game import profiles, progress
from utils import manual

Settings = dict[str, Any]


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    text: str
    pages: tuple[str, ...] = ()  # /help pages whose current numbers are shown
    extra: Callable[[Settings], list[str]] | None = None  # more lines (lists that aren't in /help)


def _achievements(s: Settings) -> list[str]:
    return [f"{a.icon} **{a.name}** — {a.description} (+{a.reward:,})" for a in progress.achievements()]


def _titles(s: Settings) -> list[str]:
    return [f"🏷️ Title **{t.name}** — {t.how}" for t in profiles.TITLES.values()]


SECTIONS: tuple[Section, ...] = (
    Section(
        "start", "📚 Start here",
        "**Blocky** is the game of this server: you **mine by chatting**, earn emeralds, craft gear, fight players and "
        "monsters, team up and climb the leaderboards. Everything is done with slash commands: type `/` and Discord "
        "lists them, with what each option means.\n\n"
        "**How to read this wiki**: one part per topic, from the basics to the end game (the contents at the top has a "
        "link to each part). Each part explains how things work, then lists the **📊 current numbers**: prices, "
        "rewards and waiting times as they are set on this server right now. They are updated here automatically.\n\n"
        "**Quick start**\n"
        "1. Chat in the server: your messages mine blocks.\n"
        "2. Claim `/daily` every day and `/sell` your blocks for emeralds.\n"
        "3. Buy ingots at the `/market` and `/craft` your first pickaxe and sword.\n"
        "4. Pick a species with `/species choose` (the first choice is free).\n"
        "5. Hit the training dummy (`/dummy hit`), then try duels, the dungeon and bosses.\n\n"
        "**Need one detail?** `/help` has a page for every command: its options, examples and numbers. "
        "`/help command:<name>` opens one directly. `/guide` shows your checklist of first steps.\n"
        "**Public or private?** Rewards (`/daily`, `/sell`, `/craft`, drops…) are shown in the channel. Personal "
        "things (`/inventory`, `/gear`, `/xp`…) and errors are only shown to you. Buttons keep working after a "
        "restart; an expired one tells you so.",
        ("guide",),
    ),
    Section(
        "mining", "⛏️ Mining, selling and the daily reward",
        "**Chat to mine.** When you write a message in the server (not in your private guide channel), you get a "
        "**mining reward**: a pile of **1 to 6 blocks**. Big "
        "piles are cobblestone; the smaller the pile, the rarer the block can be: gravel and deepslate come in "
        "smaller piles, obsidian and bedrock only alone. Then you wait the **cooldown** before the next reward: "
        "messages in between give nothing, so spamming doesn't help. Each reward also gives **XP**, sometimes "
        "**lapis lazuli**, and sometimes makes a **drop** appear (see Bosses, drops and the villager).\n"
        "**Spam channels** (set by the staff) give only a tiny emerald reward: no blocks, XP, drops or challenge "
        "progress.\n\n"
        "**What makes you mine better**: a pickaxe (more cobblestone and a chance to upgrade the block), a shovel "
        "(more gravel), an axe (sticks), a hoe (more XP), the Efficiency enchantment and talent (shorter cooldown), "
        "the Miner and Lucky talents (better blocks), and the Miner species.\n\n"
        "**Your blocks**: `/inventory` shows them, with your emeralds, items and gear. `/sell` sells **all** your "
        "blocks at once (the Trader talent and the Villager species pay more). Rare blocks are worth much more than "
        "cobblestone.\n"
        "**The market**: `/market` sells sticks and ingots, what you need to craft, at fixed prices. The market "
        "channel shows them too, above the auctions.\n"
        "**Daily reward**: `/daily` once a day. Coming back every day grows your **streak**: a bigger reward each "
        "day up to the cap, and an ingot every 7th day in a row. Miss a day and the streak starts over.",
        ("mining", "sell", "market", "daily"),
    ),
    Section(
        "xp", "⭐ XP, levels and talents",
        "You earn **XP** by mining, with `/daily`, in duels (even when you lose), against bosses, in the tournament, "
        "the dungeon, Blockdle and the quiz. Each level needs a bit more XP than the one before. Level-ups are "
        "announced, and some levels give a role.\n\n"
        "**Talents**: every few levels you get a **talent point**. Spend it with `/talent_buy <branch> [points]` in "
        "one of 4 branches, each with a maximum: **Miner** (better blocks), **Trader** (better sale prices), "
        "**Lucky** (more obsidian and bedrock) and **Efficiency** (shorter mining cooldown). `/talents` shows your "
        "points and what each branch does. Choose your style: points can only be reset by the staff.\n"
        "`/xp` shows your level, your XP bar and your talent points.",
        ("xp", "talents"),
    ),
    Section(
        "gear", "🛠️ Crafting and gear",
        "**Crafting**: `/craft <item> <material>` turns ingots and sticks into gear. Materials, from the weakest: "
        "**gold, iron, diamond, netherite**. `/craftlist` shows every recipe with its price at the market. A new "
        "piece is equipped right away if that slot is empty.\n"
        "**Equipping**: one piece per slot (pickaxe, shovel, axe, hoe, sword, helmet, chestplate, leggings, boots, "
        "shield). `/gear` shows what you wear and its durability, `/equip` picks a piece, `/equip_best` equips your "
        "best pieces, `/unequip` takes one off.\n\n"
        "**What each piece does**: tools make mining better, the **sword** raises your maximum damage, **armor** "
        "lowers the damage you take (duels, tournament, dungeon).\n"
        "**The shield** (iron only): in a duel, on your turn, **Attack + block** attacks, then blocks the "
        "opponent's whole next attack, a few times per duel. Nobody sees it coming: the duel only says how much it "
        "blocked. It isn't used in the tournament, the dungeon or against bosses.\n\n"
        "**Durability**: gear wears out when you use it and **breaks at 0**: the piece is gone, with its "
        "enchantments. Watch it in `/gear` and `/repair` a piece before it breaks: it costs part of its crafting "
        "value and keeps its enchantments. A shield at 0 doesn't break: it stays unusable until repaired.",
        ("craftlist", "gear", "repair"),
    ),
    Section(
        "enchanting", "✨ Enchanting",
        "**Lapis lazuli** is found while mining and in drops. **Enchanted books** (levels I to III) come from "
        "drops, bosses (the top damage dealer gets a strong one), completing every weekly challenge, the wandering "
        "villager (level III) and other players.\n\n"
        "`/enchant apply <book> <piece>` puts a book on a piece for some lapis. A piece can carry several different "
        "enchantments; a higher level replaces a lower one of the same enchantment. `/enchant combine <book>` merges "
        "two identical books into one of the next level (I + I = II, II + II = III). `/enchant info` lists your "
        "books, your lapis and every effect.\n"
        "Enchantments stay on the piece when you trade or sell it, and are lost if it breaks: repair it in time! "
        "The Mage species makes every effect stronger.",
        ("enchant info",),
    ),
    Section(
        "species", "🧬 Species",
        "A **species** gives you a small bonus for good. Your **first choice is free** (`/species choose`); changing "
        "later costs emeralds and is only possible once in a while (you confirm before paying). `/species list` "
        "shows every species, how many players chose it and when you can change.\n"
        "Your species shows on your profile card and as an emoji next to your name in the rankings, and it can give "
        "you a role.",
        ("species choose",),
    ),
    Section(
        "trading", "🤝 Trading, auctions and loans",
        "**Paying and trading**: `/pay <member> <amount>` sends emeralds. `/trade` offers a trade (or a gift) of "
        "emeralds, blocks, sticks, ingots or gear: the other player accepts with a button, and nothing moves before. "
        "Enchanted pieces keep their enchantments.\n\n"
        "**Auctions**: `/auction sell <item> <price>` lists an item for everyone. The market channel shows every "
        "listing with a menu to buy; `/auction browse` and `/auction buy` work anywhere. `/auction mine` shows your "
        "listings and `/auction cancel` takes one back. The seller pays a small tax when it sells, and unsold items "
        "come back after a while.\n\n"
        "**Loans**: `/loan offer` lends emeralds to a player, with the interest and the time to repay that you "
        "choose; `/loan ask` asks a player for a loan. The other player accepts with a button and the emeralds move "
        "at once. `/loan repay` pays back (all or part), `/loan list` shows what you owe and what you're owed, and "
        "`/loan forgive` cancels a debt. A **late** borrower pays a penalty, part of everything they earn goes to "
        "the lender until it's paid, and until then they can't pay, trade, sell at the auction or take new loans.\n"
        "The **Top senders** leaderboard ranks who sends and lends the most.",
        ("pay", "auction sell", "loan offer"),
    ),
    Section(
        "fighting", "⚔️ Duels, potions and the training dummy",
        "**Duels**: `/duel <member> <stake>` challenges a player: both bet the same stake and the winner takes it "
        "all. The fight is played **turn by turn** in the message. On your turn you can drink a potion (its effect "
        "shows right away), then press **Attack**, or **Attack + block** with a shield. If you don't play in time "
        "the bot attacks for you; after a few missed turns the rest is played automatically.\n"
        "**How damage works**: each hit deals a random amount between the minimum and your sword's maximum, "
        "sometimes a **critical hit** (double damage). Armor lowers the damage you take, and the player who strikes "
        "second gets a few extra HP. Better gear wins more often, but not always: luck matters.\n\n"
        "**Potions** (`/potions`): at most one per turn and a few per duel. Found in drops and on bosses; "
        "**reinforced** potions (II) are twice as strong (only one per duel) and sold by the wandering villager. "
        "Witches make potions stronger.\n\n"
        "**Training dummy**: `/dummy hit` hits a dummy with your gear and shows every hit, your total and your "
        "records, with a leaderboard (`/dummy top`). `/dummy duel [gear]` is a whole training duel against a dummy "
        "that hits back: every potion is free, nothing is used up, nothing is won or lost. The best way to learn.",
        ("duel", "potions", "dummy hit"),
    ),
    Section(
        "dungeon", "🏰 The PVE dungeon",
        "`/pve start <difficulty>` opens a run of **5 waves** of monsters: 🧟 zombies, then 💀 skeletons (they "
        "shoot before you attack), both together, 🕷️ spiders (two bites a turn) with a 🟩 creeper (it explodes on "
        "its 2nd turn unless you kill it first) and a skeleton, then a mix with a 🐂 ravager.\n"
        "Play **alone or in a group**: others join with the button (each pays the entry, refunded if they leave "
        "before the start) and the leader starts. Each wave plays out on its own with your gear and species; the "
        "message shows the fight, everyone's health and the loot.\n\n"
        "**Health isn't restored between waves.** Between two waves the leader starts the next one, anyone can drink "
        "a potion (Healing heals now, Strength and Speed help in the next wave, Harming hits every monster) or "
        "**leave with their loot**. Each wave cleared adds to your loot, but **if you die you lose it** and the "
        "entry. Clearing all 5 waves pays a bonus. Gear wears out like in duels. `/pve info` shows the difficulties "
        "and when you can play again.",
        ("pve start",),
    ),
    Section(
        "events", "🐉 Bosses, drops and the wandering villager",
        "**Drops**: when someone mines, a drop sometimes appears (emeralds, ingots, bedrock, lapis, a book, "
        "potions…). The **first player to click** gets it.\n\n"
        "**Bosses**: a boss with shared health. Everyone can attack (`/attack` or the button) once in a while; when "
        "it's defeated, the rewards are shared by damage dealt and the top damage dealer gets a bonus and a book. "
        "If nobody defeats it in time, it escapes. `/boss` shows the current one.\n\n"
        "**The wandering villager** comes every day at the same hours in the events channel, with 3 offers: a sale "
        "below the value, a purchase of your blocks above the /sell price, and an exclusive (a level III book or a "
        "reinforced potion). Each offer exists **once**: the first to click gets it. `/villager` says when he's "
        "next here.",
        ("boss", "villager"),
    ),
    Section(
        "competition", "🏆 Seasons, challenges, achievements and leaderboards",
        "**Weekly season** (`/season`): from Monday to Sunday, your score is the value you **create**: the value of "
        "the blocks you mine (counted when mined), daily rewards, drops, bosses, challenges and the bonus when you "
        "sell. Spending doesn't lower it, and what other players give you doesn't count. At the end of the week "
        "the top 3 win emeralds and the winner gets the **champion role** until the next season ends.\n"
        "**Leaderboards** (`/leaderboard`): emeralds, level, total fortune, this week's season, top senders, blocks "
        "mined, bedrock, crafts, duels won, boss damage and achievements.\n\n"
        "**Weekly challenges** (`/challenges`): a few goals each week, the same for everyone, with a reward each, "
        "and an enchanted book when you finish them all.\n"
        "**Achievements** (`/achievements`): milestones with a reward, announced when you unlock them. You can show "
        "your favourite ones on your profile card.",
        ("season", "challenges"),
        _achievements,
    ),
    Section(
        "tournament", "🏟️ The weekend tournament",
        "**Registrations** open before the weekend (dates below): click **Join** on the announcement or use "
        "`/tournament join` "
        "(there's an entry fee, and the server adds a bonus to the pot). **Leave** refunds you until the draw.\n"
        "**The draw** happens when registrations close: a random bracket, single elimination (some players skip "
        "the first round when needed).\n"
        "**Rounds** are then played automatically, one at a time (schedule below), with the duel rules and the gear "
        "you wear at that "
        "moment (it doesn't wear out). Each fight won gives XP.\n"
        "**Prizes**: the winner, the runner-up and the semi-finalists share the pot, and the winner gets the "
        "tournament champion role until the next tournament. `/tournament info` and `/tournament bracket` show "
        "everything.",
        ("tournament join",),
    ),
    Section(
        "teams", "🛡️ Teams",
        "`/team create <name> <tag>` creates a team (you become its leader); `/team invite` invites a player, who "
        "answers with the buttons or later with `/team join`. `/team leave` leaves it. The leader can also "
        "`/team kick`, `/team transfer`, `/team rename` and `/team disband`, and designs the team's **banner** with "
        "`/team banner`: a Minecraft-style banner shown in `/team info` and on every member's profile card.\n\n"
        "**Why join a team**: your tag `[ABC]` is shown next to your name; you get **more mining XP** for each "
        "teammate who already mined today; and there's a **weekly team season** (`/team top`): a team's score comes "
        "from what its members made for the season. The best player counts in full and the next ones less and "
        "less, so a big team doesn't win just by being big. The top teams share their reward in proportion to what "
        "each member brought. Team leaders can get a role.\n\n"
        "**Your team's own category**: the leader unlocks it once with `/team category`. Only the members and the "
        "staff see it (members get a team role). The leader manages its text and voice channels: "
        "`/team channel create`, `/team channel rename` and `/team channel delete`.",
        ("team create", "team banner", "team category"),
    ),
    Section(
        "profile", "🎨 Your profile and customization",
        "`/profile [member]` shows a **profile card**: avatar, title, level and XP bar, emeralds and fortune rank, "
        "species, team and banner, bio and showcased achievements, with the details below.\n\n"
        "Make it yours with `/customize` (each change shows a preview only you see; what costs emeralds asks first):\n"
        "• `bio`: a few words about you (free).\n"
        "• `color`: one of the 16 Minecraft dye colors, bought once each; `hex`: any color code, unlocked once.\n"
        "• `frame`: a patterned frame. Some are sold, the rarest are **earned** only.\n"
        "• `title`: a title under your name, earned by playing (or given by the staff).\n"
        "• `showcase`: up to 3 achievements shown first (free).\n"
        "`/customize list` shows what you have and how to get the rest.",
        ("customize color", "customize bio"),
        _titles,
    ),
    Section(
        "games", "🎲 Mini-games",
        "They're played in the game channels (and in your guide channel).\n"
        "**Lucky Block**: `/luckyblock <amount>`: bet emeralds and break the block. A creeper or a pile of dirt "
        "and you lose your bet; cobblestone gives half of it back, iron all of it, then gold, diamonds, emeralds and, "
        "very rarely, netherite pay more. The bank wins a little in the long run, and there's a daily limit on "
        "what you can win.\n"
        "**Roulette**: `/roulette <bet> <amount> [number]` (when the staff opens it): red/black, even/odd, "
        "1-18/19-36, a dozen or a number.\n"
        "**Blockdle**: guess the Minecraft block of the day with `/blockdle guess`. After each guess you see how "
        "your block compares on 6 properties (tool, hardness, blast resistance, transparent, craftable, version). "
        "The fewer guesses, the bigger the reward. `/blockdle today` and `/blockdle top`.\n"
        "**Minecraft quiz**: from time to time a question appears with 4 answers: the first right click wins (one "
        "try each).\n"
        "**Robbery**: `/rob <member> <mode>`: **risky** (they get pinged, big loot) or **discreet** (no ping, small "
        "loot). The victim has a while to press **Stop the thief!**: then the thief pays them a fine instead. "
        "Low-level players can't be robbed, and a robbed player is safe for a while.\n"
        "Winnings from these games don't count for the seasons.",
        ("luckyblock", "roulette", "blockdle guess", "quiz", "rob"),
    ),
    Section(
        "minecraft", "🌍 The Minecraft server",
        "`/ip` explains how to join the server and `/modpacks` which modpack to install. `/server_status` shows if "
        "it's online, the players and the ping.\n"
        "`/link <username>` links your Minecraft account: a staff member approves it, which adds you to the "
        "whitelist. `/link_status` shows your link.",
    ),
)

BY_KEY = {s.key: s for s in SECTIONS}


def numbers(section: Section, s: Settings) -> list[str]:
    """The current numbers of a section: its /help pages' values (no line twice), then its extras."""
    out: list[str] = []
    for name in section.pages:
        for line in manual.BY_NAME[name].current_values(s):
            if line not in out:
                out.append(line)
    if section.extra is not None:
        out += section.extra(s)
    return out
