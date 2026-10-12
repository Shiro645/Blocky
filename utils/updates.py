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
)
