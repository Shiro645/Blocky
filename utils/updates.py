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
    Update(
        "2026-10-wheel", "2026-10-14", "The wheel is open",
        "The roulette is back, Minecraft style: **`/wheel <bet> <amount>`**.",
        (
            ("🎡 How it works",
             "The wheel has the numbers of a real roulette: the red ones are 🟥 **Redstone**, the black ones ⬛ "
             "**Obsidian**. Bet on one of them: if the wheel stops on it, you get **twice your bet**. The 💎 "
             "**Diamond blocks** (0 and 00) make every bet lose."),
            ("📏 The rules",
             "Same bets and the same daily limit as the Lucky Block (they add up). Pick your bet in the suggestions. "
             "`/help command:wheel` shows everything."),
        ),
    ),
    Update(
        "2026-10-wheel-numbers", "2026-10-14", "The wheel: bet on a number",
        "At `/wheel` you can now also bet on **one number** (0, 00 or 1 to 36): if the wheel stops on it, you win "
        "**36 times your bet**. Pick it in the suggestions or just type it, e.g. `/wheel bet:17 amount:10`.",
    ),
    Update(
        "2026-10-wheel-european", "2026-10-14", "The wheel: numbers 0 to 36",
        "The wheel is now a European roulette: the numbers go from **0 to 36**, and the 0 is the only 💎 Diamond "
        "block (no more 00). Bet on a number with `bet:A number` and the `number` option, or type it in `bet`.",
    ),
    Update(
        "2026-10-gambler", "2026-10-14", "A new species: the Gambler",
        "🎲 **Gambler**: a new species for the players who like taking risks. Gamblers can bet **50% more** at the "
        "Lucky Block and the wheel (300 emeralds instead of 200). Pick it with `/species choose`.",
    ),
    Update(
        "2026-10-sell-gear", "2026-10-14", "Sell your gear",
        "`/sell gear:<piece>` now sells a piece of gear back for **80%** of its value (its craft and the books on "
        "it), times the durability it has left: a sword at 80% durability sells for 64% of its value. The "
        "suggestions show each price, and you confirm before it's sold.",
    ),
    Update(
        "2026-10-events-challenges", "2026-10-14", "Timed events, daily challenges and new achievements",
        "Something new every day: timed events, daily challenges and 17 new achievements.",
        (
            ("⏱️ Timed events",
             "Once a day, at a random time, an event gives everyone a bonus for an hour: 🎰 **Gambling Frenzy** "
             "(bets and the daily limit ×2 at the Lucky Block and the wheel), ⛏️ **Mining Rush** (mining XP ×2), "
             "💰 **Golden Hour** (`/sell` +50%), 🍀 **Lucky Hour** (obsidian and bedrock ×2) or 🏷️ **Market "
             "Sale** (`/market` -25%). It's announced in the events channel; `/events` shows the one on now."),
            ("🎯 Daily challenges",
             "`/challenges` now has **3 small challenges every day** on top of the weekly ones, and both include "
             "the mini-games: Lucky Blocks, the wheel, Blockdle, the quiz, the dungeon, the training dummy and "
             "robberies. They're never the same as the day or the week before."),
            ("🏅 17 new achievements",
             "Mini-games (100 Lucky Blocks, 100 wheel spins, a number won at the wheel, Blockdle, quiz), "
             "robberies, the dungeon in Hard, Hardcore and Nightmare, challenges, the Gambling Frenzy, enchanting, "
             "repairs, the villager and loans. See them with `/achievements`."),
            ("🌙 No robberies at night",
             "Nobody can start a `/rob` from 22:00 to 06:00: everyone is asleep."),
        ),
    ),
    Update(
        "2026-10-armor-wear", "2026-10-14", "Armor lasts longer in the dungeon",
        "In the dungeon, each hit you take now wears **only one armor piece** (drawn at random) instead of all "
        "four. A full run costs your whole armor about 45 durability instead of 180 (about 11 per piece instead "
        "of 45): an iron set lasts 4 times longer between repairs. Duels and the sword don't change.",
    ),
    Update(
        "2026-10-dungeon-ready", "2026-10-14", "Dungeon: everyone decides",
        "Between two waves, the leader no longer starts the next one alone: everyone clicks **✅ Ready** (or leaves "
        "with their loot), and the next wave starts by itself when all are ready. The message shows who is ready. "
        "If you don't answer within 5 minutes, you leave with your loot and the others go on.",
    ),
    Update(
        "2026-10-mining-channels", "2026-10-15", "Mining channels",
        "The staff can now choose the **mining channels**: messages there mine blocks and give XP and drops. "
        "Until some are chosen, every channel mines, as before.",
    ),
    Update(
        "2026-10-armor-durability", "2026-10-15", "Armor durability, like in Minecraft",
        "Each armor piece now has its own durability, like in Minecraft: the **chestplate** lasts the longest, then "
        "the leggings, the boots and the helmet (iron: 250, 234, 203 and 172). Before, boots lasted as long as a "
        "chestplate for half the ingots. Your armor keeps the same share of durability it had.",
    ),
    Update(
        "2026-10-1-final", "2026-10-16", "Blocky 1.final",
        "The last update of Blocky 1: new games of chance, a better Lucky Block and a real raid in the dungeon.",
        (
            ("🃏 Blackjack", "`/blackjack <amount>`: beat the dealer without going over 21. Hit, stand or double; a "
             "blackjack pays 3:2."),
            ("💣 Mines", "`/mines <amount> [tnt]`: 20 blocks hide some TNT. Each safe block raises your multiplier: "
             "cash out before the boom!"),
            ("🟨 Lucky Block", "It now gives back **95%** of the bets on average (84% before): diamonds, emeralds and "
             "netherite fall out much more often, with an animation of the block breaking."),
            ("🏰 Dungeon", "Groups of up to **5**. **Nightmare** is now a raid: far stronger monsters, made for a full "
             "group of 5 in enchanted diamond."),
            ("⭐ Levels", "Each level now needs 5% more XP than the previous one: the first levels come faster, the "
             "highest ones take longer. You keep your level."),
            ("🎨 Cosmetics", "Colors, frames and team banners are **half price**."),
            ("🛠️ Small things", "`/unequip` without a slot takes everything off, and `/events` tells you whether "
             "today's event already came."),
        ),
    ),
    Update(
        "2026-10-blackjack-deck", "2026-10-18", "Blackjack: a real deck",
        "Each hand of `/blackjack` is now dealt from a real 52-card deck, shuffled: a card comes out only once "
        "(no more five cards of the same value).",
    ),
    Update(
        "2026-10-talent-reset", "2026-10-18", "Reset your talents",
        "Changed your mind about your talents? `/talent_reset` gives back every point you spent, to spend again "
        "with `/talent_buy`. It costs emeralds for each point given back.",
    ),
    Update(
        "2026-10-untouchables", "2026-10-18", "Untouchables",
        "Members with the **Untouchables** role can't be robbed, and can't rob anyone either.",
    ),
    Update(
        "2026-10-dimensions", "2026-10-19", "Season 2.0: the Dimensions",
        "A new season starts! Beyond the overworld wait four dimensions, each with its own mining channels and its "
        "own blocks, and each paying more than the one before. `/dimensions` shows them all.",
        (
            ("🌍 Five dimensions",
             "🌳 Overworld (now with dirt) → 🔥 Nether → 🌌 End → 🦇 Deep Dark → ✨ Shimmer. Each pays more per "
             "message: about ×1.25, ×1.5, ×1.75 and ×2 the overworld, with or without tools. Unlocking a dimension "
             "opens every one before it, and each has its role and its channels."),
            ("🔥 Netherite is a goal now",
             "It's only found from the Nether on: mining there sometimes digs up **Ancient debris**, a netherite "
             "scrap. 4 scraps + 4 gold ingots = a netherite ingot, and a diamond piece + 1 netherite ingot = the "
             "netherite piece, enchantments kept (`/craft`). It can't be bought, sold or traded anymore: a full "
             "set is about a month of mining."),
            ("♻️ New gear for everyone",
             "Everyone starts the season on equal terms: all gear and netherite ingots are taken back and paid "
             "back in full in emeralds (check your DMs). Time to craft!"),
        ),
    ),
    Update(
        "2026-10-gate-bosses", "2026-10-19", "Gate bosses",
        "The dimensions now open by fighting! The old server boss is gone: meet the **gate bosses**.",
        (
            ("🔥 The Nether",
             "Clear the 💀 **Nightmare** dungeon (`/pve start`): everyone still standing at the end of wave 5 reaches "
             "the Nether."),
            ("🖤 🐉 👁️ Wither, Ender Dragon, Warden",
             "`/boss fight` calls a group of up to 4: turn by turn, each player drinks a potion if they want, then "
             "attacks or blocks with their shield, then the boss strikes back. The Wither opens the End, the Dragon "
             "the Deep Dark, the Warden the Shimmer. Each survivor of a victory opens the next dimension and wins a "
             "bounty, a strong book and XP. They're made for 4 well-geared, well-prepared players: bring shields "
             "and potions. `/boss info` shows them all."),
            ("✨ Enchantments up to VII",
             "Combine two books to go beyond III: IV with the Nether, V the End, VI the Deep Dark, VII the Shimmer. "
             "Protection IV and above lets your armor stop more damage."),
        ),
    ),
    Update(
        "2026-10-beacon", "2026-10-20", "The Beacon",
        "The server gets its own **Beacon**, built by everyone and helping everyone!",
        (
            ("🌟 Lighting it",
             "The first group to beat the 🖤 Wither brings back a **Nether Star**: it lights the Beacon."),
            ("🧱 Building it together",
             "`/beacon give` gives ingots, by whole blocks (9, 18, 27…). The 4 levels are built in gold first, then "
             "again in iron, diamond and netherite: each better material makes the level's effects stronger."),
            ("✨ What it gives everyone",
             "Faster mining and more mining XP, more emeralds with `/sell`, then more damage and less damage taken "
             "in the dungeon and against the gate bosses."),
            ("🔧 Keeping it up",
             "Every week it needs a little upkeep, or its last step crumbles. Giving enough in a week also gives you "
             "a small bonus of your own. `/beacon info` shows it all."),
        ),
    ),
    Update(
        "2026-10-gang-wars", "2026-10-20", "Gang wars",
        "Teams are now at war! Every week, all the teams fight each other for points and a pot of emeralds.",
        (
            ("💰 The team chest",
             "`/team chest deposit` puts emeralds in your team's chest: safe from /rob, but not from raids. Only the "
             "leader takes them out. Every Monday a share of every chest goes into the war's pot."),
            ("🎯 Points",
             "Win duels against members of other teams, rob them (or stop their robberies), and raid their chests. "
             "`/war` shows the standings, the pot and the latest feats."),
            ("🏴 Raids",
             "`/team raid <team>`: gather a few teammates and attack another team's chest. They're pinged and have "
             "30 minutes to defend it; then both sides fight. Win (or find nobody home) and you take 15% of their "
             "chest."),
            ("🏆 The end of the week",
             "The top 3 teams share the pot, straight into their chests."),
        ),
    ),
    Update(
        "2026-10-bounties", "2026-10-20", "Bounties",
        "Put a price on someone's head!",
        (
            ("🎯 Wanted",
             "`/bounty place <member> <amount>`: 250, 500, 1,000 or 2,500 emeralds on a player's head (level 10 and "
             "up). Nobody knows who paid, and bounties on the same player add up."),
            ("🗡️ Claim it",
             "Beat them in a duel, rob them, or make them fall in a raid: you take everything on their head. Never "
             "on a teammate."),
            ("⏳ A week",
             "Unclaimed after 7 days, the bounty goes back to its payer minus 10%. A player who just lost a bounty is "
             "safe from new ones for a day. `/bounty list` shows who is wanted."),
        ),
    ),
    Update(
        "2026-10-biomes", "2026-10-20", "Biomes of the week",
        "Every Monday, the whole server moves to a new biome!",
        (
            ("🗺️ 10 biomes",
             "Desert, Mountains, Badlands, Forest, Dark Forest, Jungle, Swamp, Ocean, Mushroom Fields and Tundra: "
             "one is drawn every Monday, never the same twice in a row. `/biome` shows this week's."),
            ("⚖️ A bonus and a malus",
             "Each biome helps something and slows something else, like the real one: the Mountains have emerald ore "
             "(`/sell` +15%) but steep slopes (mining 10% slower), the Ocean has shipwrecks (more drops) but you mine "
             "underwater…"),
            ("🎯 The biome's challenge",
             "Each biome has a challenge of its own, worth 250 emeralds, on top of the weekly challenges."),
        ),
    ),
    Update(
        "2026-10-prestige", "2026-10-20", "Prestige",
        "The end of the game… and a new beginning: Prestige!",
        (
            ("🌟 Becoming Prestige",
             "Level 50, every achievement, every dimension and the Beacon lit: `/prestige` lets you start over. Your "
             "wealth, gear, achievements and dimensions go, your talents are given back to spend again, and your level "
             "stays."),
            ("💪 Stronger for good",
             "Each prestige gives +5% mining XP and /sell forever, a ⭐ next to your name, the Prestige role and "
             "exclusive cosmetics: the titles Reborn and Mythic and the Prestige frame."),
            ("🔟 Up to Prestige X",
             "Each next prestige needs 10 more levels: Prestige II at 60, III at 70… X at 140."),
        ),
    ),
    Update(
        "2026-10-day-night", "2026-10-20", "Day and night",
        "The sun now sets on the server… and monsters come out!",
        (
            ("🌙 The night",
             "From 22:00 to 06:00 it's night: `/time` tells you. Every night, monsters attack players who aren't "
             "asleep. Beat them with your gear for emeralds, or they take some of yours."),
            ("👻 Phantoms",
             "Haven't slept for 3 nights? A Phantom comes for you: tougher, it pays more… and takes more."),
            ("🛏️ /sleep",
             "Sleep at night to be safe from monsters until the morning, and your next `/daily` pays 25% more."),
        ),
    ),
    Update(
        "2026-10-fixes-2-1", "2026-10-21", "Fixes",
        "A few fixes after the 2.0 updates.",
        (
            ("🌟 Prestige",
             "Prestige no longer needs the achievements only one player or team can win each time (Champion, Arena "
             "Champion, Squad Goals, Warlord), nor Legend (level 100): Prestige I really is at level 50."),
            ("📖 /help",
             "The challenges page shows all its values again."),
        ),
    ),
    Update(
        "2026-10-team-chest", "2026-10-21", "Team chests and raids",
        "Your team's chest now does something: fill it up, defend it… or raid the others'!",
        (
            ("💰 The chest's bonus",
             "The leader picks a bonus for the whole team with `/team chest bonus`: ⛏️ mining XP, 💰 /sell, ⚔️ combat "
             "or 🍀 luck. The more emeralds in the chest, the stronger: up to +15% at 100,000."),
            ("🛡️ Defenses",
             "Build 🧱 walls, 🏹 archers and an 🛡️ Iron Golem with the chest's emeralds (`/team chest defense`). The "
             "golem defends even when nobody's online. Raids wear them out: repair them."),
            ("⚔️ Turn-by-turn raids",
             "Raids are now played turn by turn with buttons, like the gate bosses: potions, shields, every move "
             "counts. A won raid takes 30% of the chest (up to 30,000)."),
        ),
    ),
    Update(
        "2026-10-ingots-2-2-1", "2026-10-22", "Ingots and tools",
        "Ingots are now precious, and tools really pay for themselves.",
        (
            ("💎 Ingots are worth much more",
             "Gold 300, iron 1,000, diamond 5,000, netherite 20,000. They drop 10 times less often (1 ingot each). "
             "The ingots you had were paid back at their old price."),
            ("⛏️ Better tools",
             "The pickaxe gives +3 cobblestone per tier (was +1), and every piece lasts much longer: gold 300, iron "
             "1,000, diamond 3,000, netherite 5,000. Your gear already has its new durability."),
            ("🎁 /daily",
             "The bonus every few days in a row is now an iron ingot."),
            ("🎰 Games of chance",
             "The wheel, blackjack and mines now show what you won or lost and your balance, like the Lucky Block."),
        ),
    ),
)
