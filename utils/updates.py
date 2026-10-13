"""What's new in Blocky: each entry is announced once in the updates channel (channels.updates).

When a feature is added, add an entry at the END with a new key. The bot posts the
entries it hasn't posted yet when it starts (so after each update of the bot), or
when the updates channel is set. Never change the key of a posted entry: it would be
posted again.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Update:
    key: str  # unique, never changed: it's how the bot knows the entry was posted
    date: str  # YYYY-MM-DD
    title: str
    text: str
    parts: tuple[tuple[str, str], ...] = ()  # (title, text) shown as fields


UPDATES: tuple[Update, ...] = (
    Update(
        "2026-10-recap", "2026-10-12", "Everything new in Blocky",
        "A lot changed in Blocky! Here is everything new, in short. Each command has its page in `/help`, and the "
        "wiki explains it all in detail.",
        (
            ("⚔️ Turn-by-turn duels",
             "Duels are now played turn by turn in the message: drink a potion if you want, then **Attack**. Each hit "
             "deals a random amount up to your sword's maximum, with critical hits, so luck matters. Potions: "
             "Strength, Speed, Healing and Harming (`/potions`)."),
            ("🛡️ The shield",
             "Craft it with 6 iron ingots. In a duel, **Attack + block** attacks, then blocks the opponent's whole next "
             "attack, twice per duel, and nobody sees it coming. Dodging is gone."),
            ("🎯 The training dummy",
             "`/dummy hit` tests your damage, with a leaderboard (`/dummy top`). `/dummy duel` is a training duel "
             "against a dummy that hits back: free potions, nothing to lose."),
            ("🏰 The PVE dungeon",
             "`/pve start`: 5 waves of zombies, skeletons, spiders, creepers and a ravager, alone or with up to 3 "
             "friends, in 5 difficulties. Health isn't restored between waves: leave with your loot in time, or lose "
             "it."),
            ("🧬 Species",
             "Pick a species with `/species choose` for a small bonus: Villager, Dwarf, Witch, Mage or Miner. The "
             "first choice is free."),
            ("💳 Loans",
             "`/loan offer` and `/loan ask`: lend and borrow emeralds between players, with the interest and the time "
             "you choose. Late borrowers pay a penalty. New leaderboard: **Top senders**."),
            ("🛡️ Teams",
             "The team season score now favours good players over big teams, team leaders get a role, and the "
             "leader can design a Minecraft-style **banner** with `/team banner`."),
            ("🎨 Profile cards",
             "`/profile` now shows a card with your avatar, level, emeralds, species, team banner and achievements. "
             "Customize it with `/customize`: a bio, a color, a patterned frame, a title earned by playing and your "
             "favourite achievements."),
            ("🎲 Mini-games",
             "`/roulette`, `/blockdle` (guess the Minecraft block of the day), the Minecraft quiz now and then, and "
             "`/rob` (risky or discreet)."),
            ("🏪 The market channel",
             "The market prices and every auction are always on display there, with a menu to buy."),
            ("📖 Help, guide and wiki",
             "`/help` has a page for every command. Blocky players get a private **guide channel** with a checklist "
             "of first steps (and a reward when it's done; `/guide`). The **wiki** channel explains every feature in "
             "detail, with the current numbers."),
        ),
    ),
    Update(
        "2026-10-team-categories", "2026-10-13", "Team categories",
        "Teams can now have their **own private category** on the server.",
        (
            ("🏠 Unlock it",
             "The team leader unlocks it once with `/team category`. Only the team's members and the staff see it: "
             "every member gets the team's role."),
            ("💬 Your channels",
             "The leader creates text and voice channels in it with `/team channel create`, and can rename or delete "
             "them (`/team channel rename`, `/team channel delete`). `/team info` lists them."),
        ),
    ),
    Update(
        "2026-10-lucky-block", "2026-10-13", "The Lucky Block replaces the roulette",
        "A new, more Minecraft game of chance: **`/luckyblock <amount>`**. Bet emeralds and break the block!",
        (
            ("🟨 What can fall out",
             "💥 A creeper (your bet is lost), 🪨 cobblestone (half your bet back), ⚙️ iron (your bet back), "
             "🟨 gold (×1.5), 💎 diamonds (×2.5), 🟩 emeralds (×4) and, very rarely, ⬛ netherite (×10). "
             "It pays in emeralds."),
            ("📏 The rules",
             "Bets from 1 to 200 emeralds, and a daily limit on what you can win at games of chance. The roulette is "
             "closed for now. `/help command:luckyblock` shows the chances."),
        ),
    ),
    Update(
        "2026-10-help-and-fixes", "2026-10-13", "A clearer /help, and fixes",
        "`/help` is easier to find your way in, and a few things now work the way they should.",
        (
            ("📖 The new /help",
             "Commands are sorted by what you do: Start here, Mining & market, Crafting & gear, Progress, Profile & "
             "species, Combat, Events, Games, Trading & loans, Teams and the Minecraft server."),
            ("⚔️ Duels and the dungeon",
             "Healing can't be drunk at full health (it isn't offered then). In the dungeon, a Strength, Speed or "
             "Harming potion already working for the next wave can't be drunk again. If the bot restarts during a "
             "duel, the stakes **and the potions drunk** are given back, and the duel message says so."),
            ("🤝 Trades",
             "A gift (a `/trade` with nothing asked back) no longer counts as a trade for achievements and "
             "challenges. Bosses now show the potion each top fighter won."),
        ),
    ),
    Update(
        "2026-10-anvil-mending", "2026-10-13", "The anvil, Mending and selling",
        "Repairs now work like in Minecraft: on an **anvil**, with ingots. And a new, very rare book: **Mending**.",
        (
            ("🔨 The anvil",
             "Craft it with `/craft item:anvil` (22 iron ingots). You need it to `/repair` your gear and to "
             "`/enchant combine` books. It wears out a little with each use (new → chipped → damaged → broken)."),
            ("🔧 Repairs with ingots",
             "`/repair` now takes ingots of the piece's material instead of emeralds (iron for the shield). 1 ingot "
             "gives back a quarter of its durability, and you choose how many to put in. Each repair makes the next "
             "one cost more: 4, 5, 6, 7… ingots for a full repair."),
            ("📕 Mending",
             "The rarest book: only sold by the wandering villager (exclusive offer), or now and then won by a "
             "boss's top damage dealer. On any piece, the XP you gain repairs it first, and only the XP left goes "
             "to you."),
            ("💰 Selling",
             "`/sell` can now sell just one kind of block (`block`) and/or a number of them (`amount`). Asking for "
             "more than you have sells all you have; with only an amount, your least valuable blocks go first."),
            ("🎨 Profiles",
             "`/profile` now shows your card first, with the details under it."),
        ),
    ),
)
