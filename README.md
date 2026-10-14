# 🧱 Blocky

A modular Discord bot built for a modded Minecraft server community.

It connects to the Minecraft server through **RCON** to manage the whitelist, shows the server status, and runs a Minecraft-themed economy and competition system directly in Discord.

---

## 🚀 Features

### 📖 Manual

- `/help` — A menu by category, and a page for every command: what it does, its options, its **current numbers** (read from the settings, so they follow `/config`), examples and related commands. `/help command:<name>` opens a page directly (`/help command:mining` explains chat mining). Staff commands are only shown to staff, and the answer is only visible to the player who asked.

### 🆕 Updates channel

- **Each new feature is announced once** in the updates channel (`channels.updates`, `/config` → Channels), pinging the role `roles.updates_ping` if it's set (one ping, even when several announcements are posted together). The announcements are written in [`utils/updates.py`](utils/updates.py): the bot posts the ones it hasn't posted yet when it starts (so right after each update of the bot), when the channel is set and after `/reload_config`. Until a channel is set, they wait. The first one is a recap of everything new.
- **Adding a feature?** Add an entry at the end of `utils/updates.py` with a new key (never change the key of an entry already posted: it would be posted again).

### 📚 Wiki

- **A wiki channel kept by the bot** (`channels.wiki`, `/config` → Channels): every feature for players explained in detail, more than `/help` (which has one page per command). A contents message at the top links to each part, then one message per topic (start here, mining and the daily reward, XP and talents, crafting and gear, enchanting, species, trading/auctions/loans, duels/potions/dummy, the dungeon, timed events/bosses/drops/villager, seasons/challenges/achievements/leaderboards, the tournament, teams, profile, mini-games, the Minecraft server), and the contents again at the bottom.
- Each part ends with its **📊 current numbers**, read from the settings like the `/help` pages: when a setting changes in `/config` (or with `/reload_config`), the bot edits the parts that changed. If a wiki message is deleted, the bot posts the wiki again (checked at every start and every hour). Changing the channel moves the wiki; removing it deletes the messages.
- No staff commands in it (they stay in `/help`, for the staff). `/help` and the guide channels link to it.
- Best as a channel where members can't write. The bot needs *Send Messages*, *Embed Links* and *Read Message History* there.

### 📘 Guide

- **A private guide channel for every Blocky player** — Only members with the **Blocky player role** (`roles.blocky_player`, `/config` → Roles) get one. Give it with a question in Discord's onboarding (*Server Settings → Onboarding → Customization questions*, e.g. "Do you want to play Blocky?" with an answer giving the role): as soon as a member gets the role (when joining or later in *Channels & Roles*), the bot creates a channel only they and the staff can see, in the guide category (`channels.guide_category`, `/config` → Channels). If they lose the role, the channel is deleted (the checklist progress is kept). Without the role set, no guide channel is created. It holds a welcome message with a **checklist of first steps**, then the guide: mining and emeralds, gear, species and profile, fighting, playing with others, and how to get more info with `/help`.
- **Checklist**: mine by chatting, `/daily`, `/sell`, pick a species, look at your `/profile`, hit the training dummy (or play a training duel). Each step is checked by itself as soon as it's done, with a line in the channel; steps done before the guide count too. Doing them all pays **200 emeralds**, **once per player ever** (a guide sent again never pays twice). The reward doesn't count for the seasons.
- **Cleanup**: the channel is deleted 3 days after the checklist is done (or right away with the **Delete this channel now** button), after 30 days if it's never done (progress is kept), and when the member leaves. Each category holds 50 channels: when it's full the bot adds `"<name> 2"`, `"<name> 3"`… (removed once empty), and it stops a little before Discord's limit of 500 channels per server.
- Mini-games work in guide channels too, so new players can try what the guide explains. Writing in a guide channel doesn't mine (nobody else sees it: chat mining belongs in the server's channels).
- `/guide` — Your checklist and a link to your guide channel; if you don't have one anymore, it opens a new one. Without the Blocky player role, it tells you to answer the question in *Channels & Roles* (with a link). Without a guide category, it shows the whole guide privately and the checklist still works.
- Staff: `/guide_resend [member]` (see Staff commands). Blocky players already in the server when this is installed get a guide channel with `/guide_resend` (everyone) or `/guide`.
- The bot needs the **Manage Channels** and **Manage Roles** permissions (it sets the channel permissions). Tuned with `balance.guide` (`/config` → Guide).

### 🌍 Minecraft

- `/server_status` — Server status (players & ping)
- `/ip` — Join instructions
- `/modpacks` — Modpack information
- `/link <username>` — Link your Minecraft account. A staff member approves the request with a button, which whitelists the account. `/link_status` shows your link.

### ⛏️ Mining & economy

- **Passive mining**: chatting mines 1–6 random blocks (cobblestone, gravel, deepslate, rare obsidian, very rare bedrock), with a cooldown (30 s, at least 10 s with talents and enchantments).
- **Spam channels** (`channels.spam`, set in `/config`): messages there don't mine blocks, give no XP, no drops and no challenge progress — only a tiny reward (0.01 emerald per message by default, so about 1 emerald an hour of spam), with a cooldown of their own.
- `/inventory` — Blocks, emeralds, items and gear
- `/sell [block] [amount]` — Sell your blocks (cobblestone 1, gravel 3, deepslate 5, obsidian 7, bedrock 10 emeralds): all of them, only one kind (`block`), or a number of them (`amount`: more than you have sells all you have; without a kind, the least valuable blocks go first)
- `/sell gear:<piece>` — Sell a piece of gear back: **80%** of its value new (its craft + the books applied to it) × the durability it has left. A sword at 80% durability sells for 80% × 80% = 64% of its value. The suggestions show each price; you confirm first. A worn piece is taken off. Villagers get their 5% on top; it doesn't count for the seasons (`balance.market.gear_sell_rate`, `/config` → Market & daily).
- `/market` — Buy sticks and gold (5) / iron (10) / diamond (60) / netherite (300) ingots
- `/daily` — Daily reward. Each consecutive day adds a bonus (up to 7 days), every 7th day in a row gives a diamond ingot (`balance.daily.weekly_bonus_item`, `bonus_every_days`), and missing a day resets the streak.
- Rewards are public: the results of `/daily`, `/sell` and `/craft` are shown in the channel (level-ups and achievements go to the announcements channel). Personal info (`/inventory`, `/gear`, `/xp`…) and errors are only shown to the player.
- Buttons that don't work anymore (they expired, or the bot restarted) answer so, instead of Discord's "This interaction failed".

### 🛠️ Crafting & equipment

- `/craft <item> <material>` and `/craftlist` — Swords, tools and armor in gold, iron, diamond or netherite.
- **Shield** — `/craft item:shield material:iron` (iron only, **6 iron ingots**), equipped in its own slot. In a duel, on your turn, press **🛡️ Attack + block** instead of Attack: you attack, then the opponent's **next attack is entirely blocked** (all its hits, critical or not). Nobody sees it coming: the duel only shows "🛡️ Shiro blocked 7.2 damage" when it happens, and the result sums up the damage each shield stopped. **2 blocks per duel**. It has **100 durability** and each block uses **10**; at 0 it **stays in your inventory, unusable** until you `/repair` it (like any gear: 60% of its crafting value for a full repair). It isn't used in the tournament (fights play out on their own), the PVE dungeon nor against bosses, and can't take Unbreaking. There is no dodge anymore.
- `/equip`, `/equip_best`, `/unequip`, `/gear` — One piece per slot. Freshly crafted gear is equipped if the slot is empty.
- **Anvil** — `/craft item:anvil` (iron only, **22 iron ingots**, one at a time). Needed to repair gear and to combine books. Like in Minecraft it wears out: each use has a **12%** chance to damage it (new → chipped → damaged → broken). `/gear` shows it.
- `/repair <piece> [ingots]` — Repair a piece on your anvil with **ingots of its material** (iron for the shield); it keeps its enchantments. One ingot gives back **25%** of its durability at the first repair, and each repair the piece already had adds 25% to the ingots needed: **4, 5, 6, 7…** ingots for a full repair. You choose how many ingots to put in (empty = as many as needed, or all you have). The repair count follows the piece in trades and at the auction.
- What gear does:
  - **Pickaxe**: extra cobblestone each time you mine (+1 per tier) + chance to upgrade the block
  - **Shovel**: extra gravel
  - **Axe**: finds sticks while mining
  - **Hoe**: more XP
  - **Sword**: higher maximum damage per hit (duels, bosses, tournament)
  - **Armor**: damage reduction in duels (1.2% per armor point, 35% at most)
  - **Shield** (iron only): in duels, **Attack + block** blocks the opponent's next attack, twice per duel
- Gear loses **durability** when used and breaks at 0, so players keep crafting (the shield stays at 0, unusable until repaired). Tools lose 1 per mining reward where they help, the sword 1 per attack (duels, the dungeon, bosses), and every armor piece **1 per hit taken** in duels but only **1 every 2 hits** in the dungeon (`balance.pve.armor_hits_per_durability`, `/config` → Combat → Dungeon). A full dungeon run costs about 22 durability to the sword and 22 to each armor piece.

### ✨ Enchanting

- **Lapis lazuli** is found while mining (about 1 mining reward in 40, 1–2 lapis) and in drops.
- **Enchanted books** (levels I to III: 60% / 30% / 10%) come from drops, the top damage dealer of a boss (II or III), completing every weekly challenge of the week, the wandering villager and other players.
- **Mending** — the rarest book (one level, worth **600**): only the villager's exclusive offer (10% of his visits, 600 emeralds) or, 5% of the time, a boss's top damage dealer. On any gear: the XP you gain repairs your equipped Mending pieces first (**2 durability per XP**), and only the XP left goes to you. XP given by the staff doesn't repair.
- `/enchant apply <book> <piece>` — Costs 2 / 4 / 8 lapis for a level I / II / III book. A higher level replaces a lower one.
- `/enchant combine <book>` — Two identical books make one book of the next level (I + I = II, II + II = III), on your anvil (Mending can't be combined).
- `/enchant info` — Your books and lapis, and every effect.
- Enchantments follow the piece in `/trade` and `/auction` (the suggestions list enchanted pieces separately) and are lost when it breaks.

| Enchantment | On | I / II / III |
|---|---|---|
| Efficiency | pickaxe | mining cooldown −2 s / −4 s / −6 s (never below the minimum) |
| Fortune | pickaxe, shovel, axe, hoe | +1 / +2 / +3 cobblestone (pickaxe), gravel (shovel), sticks (axe); +5% / +10% / +15% XP (hoe) |
| Unbreaking | all gear | 25% / 40% / 50% chance a use costs no durability |
| Sharpness | sword | +1 / +2 / +3 maximum damage (duels, bosses, tournament) |
| Looting | sword | +10% / +20% / +30% boss reward |
| Protection | armor | +1 / +2 / +3 armor points per piece |
| Mending | all gear | one level: 2 durability per XP gained (the XP repairs the piece first) |

### ⭐ XP & talents

- `/xp`, `/talents`, `/talent_buy <branch> [points]`
- XP comes from activity; 1 talent point every 5 levels.
- Branches (each has a cap): **Miner** (better blocks), **Trader** (sell bonus), **Lucky** (bedrock chance), **Efficiency** (shorter cooldown).
- Level-ups are announced, and configurable **level roles** are given automatically.

### 🧬 Species

- `/species choose <species>` — Pick a species for a small bonus. The first choice is free; changing costs 1,000 emeralds (you confirm first) and is possible once every 7 days.
  - 🧑‍🌾 **Villager** — 5% better prices: `/sell` gives 5% more, the market and the wandering villager's goods cost 5% less, and he pays 5% more for blocks.
  - 🪓 **Dwarf** — +5% damage in every fight: duels, tournaments, bosses, the dungeon and the training dummy.
  - 🧪 **Witch** — +10% potion effects in duels and the dungeon.
  - 🔮 **Mage** — +10% enchantment effects (Efficiency, Fortune, Unbreaking, Sharpness, Looting, Protection). A Fortune that isn't a whole number gives the rest as a chance of one more.
  - ⚒️ **Miner** — 5% shorter mining cooldown (even below the minimum cooldown).
  - 🎲 **Gambler** — +50% maximum bet at the Lucky Block and the wheel (300 instead of 200).
- `/species list` — Every species, its bonus, how many players chose it, yours and when you can change (private).
- Your species is shown in `/profile` and as an emoji before your name in `/leaderboard`, `/season` and `/team info`.
- **Species roles** — `roles.species_villager`, `species_dwarf`, `species_witch`, `species_mage`, `species_miner`, `species_gambler` (`/config` → Roles): the bot gives each player the role of their species and takes the others back. Checked at every start and when a member rejoins; changing a role in `/config` moves it.
- All values in `/config` → 🧬 Species (`balance.species`). `/reset` doesn't change species.

### 🤝 Trading

- `/pay <member> <amount>` — Send emeralds
- **Loans** — `/loan offer <member> <amount> <interest> <days>` lends emeralds (you pick the interest, 0–20%, and 1–7 days to repay); `/loan ask` asks a player for one. The other player accepts or declines with the buttons (they still work after a restart, the offer lasts 15 min), everything is checked again when they accept and the emeralds move at once. One unpaid loan per borrower, up to 5 unpaid loans per lender. `/loan repay [amount]` pays back (everything by default, or part of it), `/loan list` shows what you owe and what you're owed (private), `/loan forgive <member>` cancels a debt. **Late** (not repaid at the deadline): +10% of what's left, the bot takes what it can from the borrower's emeralds at once, then 50% of every emerald they receive (mining, sales, payments…) goes to the lender until it's paid; until then they can't `/pay`, `/trade`, buy or list at the auction or take/give loans. Both get a DM when it's late and when it's paid. Loans, repayments and interest don't count for the seasons. All tuned with `balance.loans` (`/config` → Loans).
- `/trade <member> <give> [give_amount] [get] [get_amount]` — Trade or gift emeralds, blocks, sticks, ingots or gear. The other player accepts with a button within 5 minutes (`balance.trade.offer_minutes`). A gift doesn't count as a trade for achievements and challenges.
- `/auction sell | browse | buy | cancel | mine` — Player auction house: 5% tax, 10 listings per player, unsold items come back after 7 days.
- **Market channel** (`channels.market`, set in `/config`): the bot keeps two messages there, always up to date. First the **Market** (the server's fixed prices: sticks and ingots, with a menu to buy then the quantity, like `/market`; updated when the prices change in `/config`), then the **auction house** with every listing (pages ◀ ▶ and a menu to buy, with a confirmation), updated on every sale, purchase, cancellation and expiry. If someone deletes one of them, both are posted again in that order. Best as a channel where members can't write.

### 🏆 Competition

- `/leaderboard [board]` — Rankings by emeralds, level, total fortune, this week's season, top senders (emeralds sent with `/pay` plus emeralds lent with `/loan`; repayments don't count), blocks mined, bedrock, crafts, duels won, boss damage, achievements.
- `/profile [member]` — Public profile: level, fortune and rank, team, species, equipment, achievements, stats, linked account, champion badge. It comes with a **profile card** (an image): avatar, name, title, level and XP bar, emeralds and fortune rank, species, team tag and banner, bio and showcased achievements, in the player's color and frame (see **Profile customization** below). Without Pillow, the profile is text only.
- **Weekly seasons** (`/season`) — The score is the value you *created* during the week (Monday to Sunday): the value of the blocks you mine (counted when mined, not when sold), daily rewards, drops, bosses, challenges, the server share of the tournament pot, and the trader/villager bonus when you sell. Spending doesn't lower it; emeralds or blocks received from other players, duel pots and auction sales don't count. At the end of the week, the top 3 get emeralds and the winner gets the **champion role** until the next season ends.
- `/duel <member> <stake>` — Both players bet the same stake and the winner takes it all. The fight is played **turn by turn** in the message: on your turn you can drink a potion (its effect shows right away), then click **Attack**, in the same turn. You have 30 s per turn, then the bot attacks for you; after 2 missed turns in a row the rest of the duel is played automatically. If the bot restarts during a duel, both stakes are refunded.
- **Training dummy** — `/dummy hit` hits the dummy 10 times with your current gear and species (rolled like duel hits, critical hits included) and shows every hit, the total, the average, the min and max; one series per minute. The dummy has no armor and doesn't hit back, nothing wears out and nothing is won. Your best series (total damage) and best hit go on the leaderboard: `/dummy top`. `/dummy duel [gear]` is a **training duel** against a dummy that hits back like a player in no gear, gold, iron (default), diamond or netherite: same buttons as a real duel (Attack, Attack + block with a shield, and **every potion for free** to try them), the dummy plays its turn right away, nothing is used up and nothing is won or lost. Tuned with `balance.dummy` (`hits`, `cooldown_seconds`).
  - **Luck matters**: each hit deals a random amount between **1** and your sword's **maximum** (no sword 6 · gold 8 · iron 10 · diamond 12 · netherite 14, +1/+2/+3 with Sharpness). No dodging: with a **shield** you can **Attack + block** (see below). 15% of hits are **critical** (x2). Armor reduces the damage taken by 1.2% per point, 35% at most. The player who plays second starts with **+2 HP**.
  - Better gear wins more often, not always: one tier ahead (e.g. iron vs gold) wins about 70% of the time, netherite vs iron about 80%.
- **Potions** (`/potions`) — Duels and the PVE dungeon (not the tournament, not bosses). In a duel: one potion per turn, up to 3 per duel (at most one reinforced II potion), the effect is for that turn. Found in drops (a witch's stash: 2 potions) and on bosses (the top 3 damage dealers get one); reinforced potions (II, effect doubled) are sold by the villager. They can be traded and sold at auction.

  | Potion | Effect |
  |---|---|
  | Strength | this turn's attack: minimum damage +5 (never above your maximum) |
  | Speed | 40% chance to strike twice, this turn and your next 2 turns |
  | Healing | heals 3 HP (never above your maximum) |
  | Harming | 3 direct damage to the opponent, reduced by their armor (on top of your attack) |
- `/challenges` — **3 daily challenges** (small ones, new every day at midnight) and **3 weekly challenges** (new every Monday), the same for everyone, each with an emerald reward that counts for the season. They're picked from a pool of mining, selling, bedrock, crafting, duels, drops, bosses, the daily reward, trades and the mini-games (Lucky Blocks, wheel spins, the Blockdle block of the day, quiz questions, dungeon waves, the training dummy, successful robberies), and **never the same as the day or the week before**. A challenge for a game that is off isn't picked (no quiz challenge without the automatic quiz, no wheel challenge when the wheel is closed, no boss challenge without automatic bosses). The week running when the bot is updated keeps its challenges.
- `/achievements [member]` — 45 achievements with emerald rewards, announced publicly: mining, crafting, armor sets, levels, duels, daily streaks, trades, drops, bosses, seasons, and since this update the mini-games (100 Lucky Blocks, 100 wheel spins, a number won at the wheel, 10 Blockdle blocks, 10 quiz questions), robberies (10 successful, 5 thieves stopped), the dungeon (cleared in Hard, Hardcore, Nightmare), challenges (10 and 50 completed), playing during a Gambling Frenzy, and the economy (10 books applied, 10 repairs, 20 deals with the villager, 10,000 emeralds lent). Players who already reached one get it with their next action.
- **Timed events** (`/events`) — For an hour (`balance.live_events.duration_minutes`), a bonus for everyone, announced in the events channel (with the events role):
  - 🎰 **Gambling Frenzy** — the maximum bet **and** the daily win limit of the Lucky Block and the wheel ×2 (a Gambler can bet 600).
  - ⛏️ **Mining Rush** — mining XP ×2.
  - 💰 **Golden Hour** — `/sell` pays +50% for blocks (it counts for the season, like the Trader bonus).
  - 🍀 **Lucky Hour** — obsidian and bedrock ×2 more likely when mining.
  - 🏷️ **Market Sale** — `/market` 25% cheaper (during it, gear sold with `/sell gear` is valued at the sale prices, so buying cheap to sell gear back isn't a profit).
  - One comes by itself **every day** at a random time between 10:00 and 22:00, never the same as the day before; the staff can start one with `/event start` (one at a time) and end it with `/event stop`. Tuned with `balance.live_events` (`/config` → Games & events → Timed events): `daily_random`, `earliest_hour`, `latest_hour`, `duration_minutes`, `random_kinds` (which ones can come by themselves), `frenzy_multiplier`, `rush_xp_multiplier`, `golden_sell_bonus`, `lucky_rare_multiplier`, `market_sale_discount`.
- **Random drops** — Activity sometimes makes a drop appear (emeralds, ingots, bedrock, lapis, enchanted books, potions). The first player to click gets it.
- **Server bosses** (`/boss`, `/attack` or the button) — A boss with shared HP. Everyone attacks once a minute, rewards are shared by damage dealt, and the top damage dealer gets a bonus. A boss escapes after 24h.

### 🏟️ Weekend tournament

- **Registrations** from Friday 18:00 to Saturday 21:00: click **Join** on the announcement, or use `/tournament join` (entry fee 50 emeralds). **Leave** (or `/tournament leave`) refunds you until the draw. The announcement shows the number of players and the pot, and its buttons disappear when registrations close. The server adds 200 emeralds to the pot. 4 to 32 players: with fewer than 4 the tournament is cancelled and everyone is refunded.
- **Draw** when registrations close: a random single elimination bracket. When the number of players isn't a power of 2, some players (drawn at random) skip the first round.
- **Rounds** every hour from Sunday 18:00, announced in the events channel. Fights are automatic, with the duel rules and the gear equipped at that moment, and they don't wear the gear out. Each match won gives XP.
- **Prizes**: 60% of the pot for the winner, 25% for the runner-up, 15% shared by the semi-finalists, plus the tournament champion role until the next tournament ends. Only the server bonus part counts for the weekly seasons: the entry fees just move between players.
- `/tournament info` (dates, pot, your status) and `/tournament bracket` (matches and results).

### 🧑‍🌾 Wandering villager

- Comes **every day from 18:00 to 21:00** (local time) in the events channel, pinging the events role, with **3 offers**:
  - 🛒 a sale 30% below the value: iron, diamond or netherite ingots, lapis, a level I/II book or potions;
  - 💰 a purchase: he buys a pile of blocks (gravel, deepslate, obsidian or bedrock) 50% above the /sell price (his bonus counts for the season);
  - ✨ an exclusive: a **level III book** or a **reinforced potion (II)**, whose effect is doubled (Strength minimum +10, Speed 80%, Healing 6 HP, Harming 6). Reinforced potions are limited to one per duel. Reinforced potions are only sold by the villager.
- Each offer exists **once**: the first player to click gets it. The buttons keep working after a restart, and the message shows who took what.
- `/villager` shows whether he is here and when he comes next.

### 🎲 Mini-games

They work in the game channels set in `/config` (`channels.games`) and in the guide channels, or anywhere when there are none. `/rob`, `/pve start` and `/dummy hit` follow the same rule.

- `/luckyblock <amount>` — Bet emeralds and break a **Lucky Block**: 💥 a creeper loses the bet, 🪨 cobblestone gives half back, ⚙️ iron the bet back, then 🟨 gold ×1.5, 💎 diamonds ×2.5, 🟩 emeralds ×4 and, 1 time in 500, ⬛ netherite ×10. Each outcome is rarer than the one before (creeper 27%, cobblestone 25%, iron 23%, gold 18%, diamonds 5%, emeralds 1.8%, netherite 0.2%). It only pays emeralds (never items), gives back about 84% of the bets on average, and every outcome's weight and payout are in `/config` → Games & events → Lucky Block & roulette (`balance.games.lucky_block`).
- **Games of chance** (Lucky Block and the wheel): bets of `balance.games.min_bet`–`max_bet` (1–200; more for the 🎲 Gambler species), `cooldown_seconds` between two games of the same game, and a **daily limit** (`daily_win_cap`, 1,500): once a player won that much today at these games (winnings minus losses), they play again tomorrow. Winnings don't count for the seasons.
- `/wheel <bet> <amount>` — **The wheel**, a Minecraft roulette (`balance.games.roulette_enabled`). Its numbers are those of a real roulette: the red ones are 🟥 **Redstone**, the black ones ⬛ **Obsidian**, the green 0 a 💎 **Diamond block** (a European roulette; `roulette_zeros: 2` adds the 00 of an American one). For now players bet on **Redstone or Obsidian (×2)** or **a number (0–36, ×36)**: `bet:A number` then the `number` option (type it to find it), or the number typed straight in `bet`; the other bets stay in the game but are closed, and each one can be opened in `/config` (`balance.games.roulette_bets`: `green` = Diamond block ×18, `even`/`odd`, `low`/`high` ×2, `dozens` ×3, `number` ×36). The Diamond block makes the bank keep about 2.7% of the bets on average (5.3% with the 00). The bet is picked in the suggestions, and the wheel spins for a second or two before stopping. Winnings don't count for the seasons.
- `/blockdle guess <block>` — Guess the Minecraft block of the day, the same for everyone (like Wordle / MCdle). After each guess you see how your block compares with the block of the day on 6 properties: tool, hardness, blast resistance, transparent, craftable and version added (🟩 same, 🟥 different, 🔼/🔽 higher or lower). Unlimited private guesses; the fewer you need, the bigger the reward, and the channel is told when you find it. `/blockdle today` shows your guesses, `/blockdle top` today's best (and yesterday's block). 190 blocks, with their real values from Minecraft 1.21.1.
- **Minecraft quiz** — Every hour or so a question appears in a game channel with 4 answers; the first player to click the right one wins emeralds and XP (one try each). Staff can ask one now with `/event quiz`.
- **PVE dungeon** — `/pve start <difficulty>` opens a run of **5 waves**: 🧟 zombies, then 💀 skeletons (they shoot before you attack), both, 🕷️ spiders (two bites a turn) with a 🟩 creeper (it explodes on its 2nd turn unless you kill it first) and a skeleton, then a mix with a 🐂 Ravager. Alone or in a group of up to 4: others join with the button (each pays the entry, refunded if they leave before the start or if the group isn't started within 5 min) and the leader starts. Each wave plays out on its own with your gear and species (as in duels); the message shows the fight, everyone's health and loot. **Health isn't restored between waves.** Between two waves (buttons that still work after a restart): the leader starts the next wave, anyone can drink a potion (up to 3 per run: Healing heals now, Strength/Speed help during the next wave, Harming hits every monster at its start) or **leave with their loot**. Each wave cleared adds to your loot (+15 XP), but **if you die you lose it** and the entry. Clearing wave 5 pays the loot +50%. No decision within 5 min = everyone left leaves with their loot. A group faces as many monsters per player; if the leader leaves or dies, the next player leads. Gear wears out like in duels. One run per hour. `/pve info` shows the difficulties, the waves and when you can play again.

  | Difficulty | Entry | Monsters | Loot (all 5 waves) | Calibrated for (solo, no potions, ~chance to clear all 5) |
  |---|---|---|---|---|
  | 🟢 Easy | 30 | ×0.85 | 105 | iron gear ~98% · no gear ~20% |
  | 🟡 Normal | 75 | ×1 | 262 | diamond ~90% · iron ~60% |
  | 🟠 Hard | 200 | ×1.13 | 630 | netherite ~80% · diamond ~50% |
  | 🔴 Hardcore | 500 | ×1.26 | 1,470 | enchanted netherite ~80% · netherite ~40% |
  | 💀 Nightmare | 1,200 | ×1.42 | 3,360 | enchanted netherite ~35% (potions help) |

  Monsters get +10% health and damage every wave. Everything is tuned with `balance.pve` (`/config` → Combat → Dungeon and Dungeon monsters).
- `/rob <member> <mode>` — Rob a player. **Risky**: they get pinged, the loot is big (200-500 emeralds). **Discreet**: nobody is pinged, the loot is small (50-100). The robbery is posted in the robberies channel (`channels.robberies`, `/config` → Channels; game channels are busy with commands, so only the bot should write there) — or where `/rob` was used when none is set — with a **Stop the thief!** button only the victim can use: if they click it within the hour the thief pays them a fine (10% of the loot), otherwise the thief takes the loot (never more than the victim has) and the victim gets a DM. A thief robs once every 6 h, a robbed player is safe for 12 h, players below level 5 can't be robbed, **no robbery can start from 22:00 to 06:00** (server time; one started at 21:59 keeps going: `night_start_hour`, `night_end_hour`, the same hour twice = robberies all day), and stolen emeralds don't count for the seasons. All tuned with `balance.rob` (`/config` → Robberies).
- Tuned with `balance.games`: `min_bet`, `max_bet`, `cooldown_seconds`, `roulette_enabled`, `roulette_bets`, `roulette_zeros` (1 = 0 only, the default; 2 = 0 and 00), `blockdle_rewards` (by number of guesses), `blockdle_xp`, `blockdle_no_repeat_days` (days before a block of the day comes back), `quiz_every_minutes` (0 = only `/event quiz`), `quiz_every_jitter` (e.g. `0.25` = give or take 25%), `quiz_no_repeat` (the last questions not asked again), `quiz_seconds`, `quiz_reward`, `quiz_xp` — all in `/config` → Games & events (Lucky Block & roulette, Blockdle & quiz).

### 🛡️ Teams

- `/team create <name> <tag>` — Anyone can create a team for **500 emeralds** (name 3–24 characters, tag 2–4 letters or numbers) and becomes its leader. Up to 5 members.
- `/team invite <member>` — The leader invites a player, who answers with the buttons (they still work after a restart) or later with `/team join <tag>`. Invitations last 48h.
- `/team leave` — Leave the team. When the leader leaves, the oldest member becomes leader; the last one to leave disbands the team.
- Leader: `/team kick`, `/team transfer`, `/team rename [name] [tag]`, `/team disband`.
- **Team leader role** — If `roles.team_leader` is set (`/config` → Roles), the bot gives that role to every team leader and takes it back when they no longer lead a team (transfer, leaving, disbanding, team deleted by staff). It is checked again at every start and when a member rejoins the server; changing the role in `/config` moves it.
- `/team info [team]` — Members, what each one earned for the team this week, team rank, today's bonus, and its category's channels.
- **Team category** — `/team category` (leader, **1,000 emeralds**, once) unlocks a private category for the team: only its members and the staff see it. The bot creates a **team role** `[TAG] Name` (given to every member and taken back when someone leaves), the category and a first `chat` channel. The leader manages up to **5** text and voice channels with `/team channel create <name> [kind]`, `/team channel rename` and `/team channel delete` (the category keeps at least one). Renaming the team renames its role and category; disbanding it (or `/team_remove`) deletes the channels, the category and the role. If the role or the category is deleted by hand, the bot makes it again (checked every 30 min). If the bot can't create it (missing *Manage Channels* / *Manage Roles*), the leader is refunded. Tuned with `balance.teams.space_cost` and `max_channels`.
- **Team tag** — `[ABC]` is shown in `/profile`, `/leaderboard` and `/season`.
- **Team bonus** — Mining XP +5% for each teammate who already mined today (up to +20%).
- **Weekly team season** (`/team top`) — A team's score comes from the season score (see above) its members made while in the team (Monday to Sunday), and grows like a logarithm of the number of members: the best earner counts in full, the next ones ×0.69, ×0.41, ×0.29, ×0.22… So 5 members earning the same score ×2.6 instead of ×5 (2 → ×1.7, 3 → ×2.1), and one more member earning anything never lowers the score. `/team top` shows the score in points next to the emeralds earned. Only teams where at least **2 members** scored are ranked. The top 3 teams win 600 / 300 / 150 emeralds, shared between the players in proportion to what each one earned for the team (players who left during the week keep their share). Results are announced with the season results.

### 🎨 Profile customization

Everything shows on the profile card of `/profile`. Each change shows a preview card only you see; what costs emeralds asks for a confirmation first.

- `/customize bio [text]` — A few words about you (150 characters, free; empty = removed). Emoji show in the text profile but not on the card.
- `/customize color <color>` — The color of your card (accent, XP bar, name): one of the 16 Minecraft dye colors, **300 emeralds** each, bought once and kept for good (the default color is free).
- `/customize hex <code>` — Any color by its code (e.g. `#ff8800`): **1,500 emeralds** once, then every code is free.
- `/customize frame <frame>` — The patterned border of your card. Sold, bought once: Stone 200 · Gold 500 · Redstone 800 · Lapis 1,000 · Diamond 2,000 · Emerald 3,000. Earned only: **Netherite** (win a weekend tournament), **Ender** (clear the Nightmare dungeon), **Nether Flames** (help defeat 25 bosses), **Champion** (win a weekly season).
- `/customize title <title>` — The title under your name, earned by playing: Miner (1,000 blocks), Quarry Master (50,000), Bedrock Hunter (100 bedrock), Blacksmith (50 crafts), Duelist (25 duels won), Gladiator (100), Boss Slayer (10 bosses), Season Champion, Arena Champion, Team Champion, Dungeon Crawler (Hard dungeon), Nightmare Survivor (Nightmare dungeon), Tycoon (100,000 emeralds earned), Banker (10,000 lent), Merchant (50 trades), Heavy Hitter (150 damage in a `/dummy hit` series), Veteran (level 50), Legend (level 100). The staff can also give custom titles.
- `/customize showcase [badge1] [badge2] [badge3]` — Up to 3 of your achievements shown first on the card (none = your latest ones). Free.
- `/customize list` — Your colors, frames and titles, and how to get the others.
- **Team banner** — `/team banner <base> [pattern1] [color1] … [pattern3] [color3]` (leader): a Minecraft-style banner, a base color and up to 3 patterns (stripes, cross, chevron, border, creeper, skull, flower…) each in a dye color. It shows a preview first and costs **200 emeralds**. The banner shows in `/team info` and on the profile card of every member.
- Tuned with `balance.profiles` (`/config` → Profiles).

### 🔐 Staff commands

Restricted to the **staff role** (`staff.role_id`): even an administrator without it isn't staff for Blocky. Only when no staff role is set (or it was deleted), the administrators are staff, so the server is never locked out. **Every staff command is logged in the staff channel** (who, which command, which options).

**Players don't see the staff commands.** Discord can hide a command behind a permission, not behind a role, so at startup the bot picks a permission that **only the staff role has** (no other role, `@everyone` included; other bots' roles and admin roles aside, admins see every command anyway): *Timeout Members* first, then *Kick*, *Ban*, *Manage Messages*, *Manage Nicknames*, *View Audit Log*… Only members with it see the staff commands. If no permission belongs to the staff role only, the commands are hidden behind *Administrator* and the bot says so in the staff channel: give the staff role a permission no other role has (e.g. *Timeout Members*), or allow the staff role in *Server Settings → Integrations → Blocky*.

- Moderation (the member gets a DM with the reason; everything is logged in the staff channel):
  - `/warn <member> <reason>` — warnings count for 30 days; 3 warnings = automatic 1h mute, 5 = 1 day, 7 = 7 days. `/unwarn <#>` removes one, `/clearwarns` removes them all.
  - `/history <member>` — warnings, mutes, kicks and bans, with their numbers.
  - `/mute <member> <duration> <reason>` (e.g. `30m`, `2h`, `3d`, `1w`, `perm`) and `/unmute`. Mutes use Discord timeouts; the bot renews them past Discord's 28-day limit (permanent mutes) and re-applies them if the member leaves and comes back.
  - `/kick`, `/ban <member> <reason> [duration] [delete_messages]` (permanent by default; temporary bans are lifted automatically) and `/unban <user_id>`.
  - `/clear <amount> [member]` (pinned messages are kept), `/lock` / `/unlock` (staff can still write), `/slowmode <seconds>`.
  - Members above the moderator or the bot, staff members and the owner can't be sanctioned. The bot needs the *Moderate Members*, *Kick*, *Ban*, *Manage Messages*, *Manage Channels* and *Manage Roles* permissions (`/lock` edits channel permissions; it keeps the bot and the staff role able to write, and `/unlock` puts back exactly the permissions the channel had).
- Economy: `/give <member> <item> [amount] [reason]` gives anything (emeralds, blocks, sticks, ingots, lapis, books, potions, gear; type e.g. `gear:diamond:sword:sharpness3` for an enchanted piece). `/take <member> <item> [amount] [reason]` removes anything the member owns (the suggestions are what they have), after a confirmation button, and never more than they have. The member gets a DM with the reason. Staff gifts don't count for the seasons.
- Fresh start: `/reset [member]` resets, for one player or the whole server, what you pick: emeralds/blocks/items (and auction listings, loans: the debts are cancelled), gear, levels/XP/talents (level roles removed), stats/achievements/seasons (and the guide checklist). You confirm by typing `RESET`, and a backup of the database is made just before. Minecraft links, moderation, teams and settings are kept.
- Players: `/player xp_add`, `/player xp_set`, `/player level`, `/player talents_add`, `/player talents_reset` (refunds points), `/player species` (set or remove a member's species, free and without waiting), `/player title <member> <title>` (gives a custom title, the member can then pick it with `/customize title`), `/player profile_reset <member> <part> <reason>` (removes the bio, the title and the custom titles given by the staff, or both; colors, frames and earned titles are kept) — the member gets a DM — `/player cooldowns <member> [timer] [reason]` (resets their waiting times, one or all: robbing again, the protection after being robbed, the dungeon, the dummy, a boss attack, duels, the Lucky Block and roulette, mining, changing species and the daily reward, whose claim of the day is undone without growing the streak twice; the member gets a DM and the staff channel a log) and `/player sync_roles` (gives everyone the level role matching their level).
- Events: `/event start <event> [minutes]` (a timed event now: Gambling Frenzy, Mining Rush, Golden Hour, Lucky Hour or Market Sale), `/event stop` (ends it), `/event boss [name] [hp]`, `/event drop`, `/event quiz` (a quiz question in this channel now), `/event tournament` (open registrations now, run the next step now — draw, then the next round — or cancel and refund; handy to test without waiting for the weekend), `/event villager` (come now for the usual visit length, or leave).
- Whitelist: `/whitelist add`, `/whitelist remove`, `/whitelist list`, and `/unlink <member>` (removes a link and its whitelist entry)
- Blocky ban: `/blocky ban <member> <duration> <reason>` blocks a player who abuses the bot: they can't use any of Blocky's commands, buttons or menus until the end (`30m`, `2h`, `3d`, `1w`…) or until lifted (`perm`). They keep everything they own and still mine by chatting; they get a DM and see the end and the reason when they try a command. A new block replaces the previous one; staff can't be blocked. `/blocky unban <member>` lifts it, `/blocky list` shows who is blocked. Logged in the staff channel.
- Guide: `/guide_resend [member]` sends the guide again in a new private channel (the old one is deleted), to one member or to **every member with the Blocky player role** (after a confirmation, newest members first, in the background; the result is also posted in the staff channel). Steps already done stay checked and the reward is never paid twice. Members it can't reach because of the 500-channel limit are counted in the report.
- Teams: `/team_remove <team>` deletes a team (offensive name…), logged in the staff channel
- Settings: `/config` opens menus to change **almost every setting of the bot** from Discord (the bot token, server ID, Minecraft connection, `/mc` blocked list, staff role and database path stay in `config.json` only). You pick a **section**, then a **category**: 🖥️ **Server** (channels, roles, level roles, Minecraft texts, time zone & backups, moderation), 💰 **Economy** (mining & block values, mining odds, market/daily/repair, trading & auction, loans, villager), ⭐ **Progress** (XP/levels/talents, seasons, daily & weekly challenges, achievements, species, profiles, titles & earned frames, guide, teams), ⚔️ **Combat** (duels & dummy, potions, tools, swords/armor/shield, enchanting books and effects, dungeon, dungeon monsters, bosses, tournament) and 🎉 **Games & events** (timed events, Lucky Block & roulette, Blockdle & quiz, robberies, drops). The section page shows how many settings each category has and how many were changed. Each setting shows what it does, its current value and its default, with buttons to change it (percentages are typed as `25` or `25%`) or to reset it to the default; settings changed from the default are marked ✏️. Lists (boss names, season rewards…), automatic mutes, the drop table and the villager's goods have their own editors (add, change, delete a line). Values are checked before being saved (an invalid one is refused with the reason). Settings left in the file that the bot doesn't use (from an older version, or a typo) never block a change: they are removed from the file, and the reply lists them. Changes apply immediately, the previous `config.json` is copied to the backups folder and every change is logged in the staff channel. The RCON password, staff role and database path can't be seen or changed from Discord.
- Update: `/bot_update` pulls Blocky from GitHub and restarts it, after showing what's new (see *Updating from Discord*)
- Server: `/mc <command>` runs a Minecraft console command through RCON (dangerous commands such as `stop`, `op`, `whitelist off` are blocked, also when chained after `execute … run`; every use is logged in the staff channel), `/reload_config` applies `config.json` changes without restarting, `/backup_now` saves a copy of the database

---

# ⚙️ Configuration

### Discord

1. Create an application and a bot on the [Discord Developer Portal](https://discord.com/developers/applications).
2. In the **Bot** tab, enable the **Server Members Intent**.
3. Invite the bot to your server with the `bot` and `applications.commands` scopes.
4. For level roles and the champion role, give the bot the **Manage Roles** permission and put its role **above** those roles.

### `.env`

Copy `.env.example` to `.env` and fill in your bot token:

```
DISCORD_TOKEN=your_bot_token_here
```

### `config.json`

Copy `config.example.json` to `config.json` and fill in your values:

| Key | Description |
|---|---|
| `guild_id` | ID of your Discord server (slash commands are synced instantly to it; old global commands are removed so nothing shows twice). **Blocky only plays there**: commands, buttons, menus and chat mining don't work in DMs or in another server the bot was added to |
| `staff.role_id` | ID of the staff role allowed to use staff commands |
| `channels.announcements` | Channel for level-ups, achievements, challenges, season results (empty = no announcements) |
| `channels.events` | Channel for drops and bosses (empty = drops appear where people chat) |
| `channels.staff_log` | Staff channel receiving `/link` requests (required for `/link`) |
| `channels.robberies` | Robberies channel: every `/rob` is posted there with its *Stop the thief!* button (0 = where `/rob` is used) |
| `channels.market` | Market channel: the bot keeps two messages there, always up to date: the market (fixed prices) then every auction listing, each with a menu to buy |
| `channels.games` | List of game channels: `/luckyblock`, `/wheel`, `/blockdle`, `/rob`, `/pve start` and `/dummy hit` only work there (and in the guide channels), and the quiz is posted there (empty = they work anywhere, but no automatic quiz) |
| `channels.updates` | Updates channel: each new Blocky feature is announced there once, after the bot is updated (0 = the announcements wait) |
| `channels.wiki` | Wiki channel: the bot keeps every feature explained there, with the current numbers (0 = no wiki) |
| `channels.guide_category` | Category of the guide channels: every new member gets a private channel there with the guide and a checklist (0 = no guide channels; `/guide` still shows the guide) |
| `channels.spam` | List of spam channels: no blocks, XP or drops there, only `balance.mining.spam_reward` emeralds per message |
| `roles.level_roles` | `{"level": role_id}`, e.g. `{"10": 123, "25": 456}`. Members keep the highest role reached. In `/config` → Level roles, pick the role in the bot's list (roles above the bot's own role aren't listed: it couldn't give them), then type the level. |
| `roles.season_champion` | Role given to the winner of the last weekly season |
| `roles.tournament_champion` | Role given to the winner of the last weekend tournament |
| `roles.updates_ping` | Role pinged when a new feature is announced (0 = no ping) |
| `roles.blocky_player` | Blocky player role: only its members get a guide channel (give it with an onboarding question in *Channels & Roles*; 0 = no guide channels) |
| `roles.team_leader` | Role given to every team leader (and taken back when they no longer lead a team) |
| `roles.species_villager` … `species_gambler` | Role given to the players of each species (`species_villager`, `species_dwarf`, `species_witch`, `species_mage`, `species_miner`, `species_gambler`) |
| `roles.event_ping` | Role pinged when a boss appears, the wandering villager arrives or a tournament opens (0 = no ping). Nobody else is pinged. |
| `minecraft.server_host` / `server_port` | Minecraft server address used by `/server_status` |
| `minecraft.public_ip_text` | Text shown by `/ip` |
| `minecraft.modpack_text` | Text shown by `/modpacks` |
| `minecraft.rcon_host` / `rcon_port` / `rcon_password` | RCON connection to the Minecraft server |
| `minecraft.blocked_commands` | Optional list of console commands refused by `/mc`, e.g. `["stop", "op", "whitelist off"]` (replaces the default list) |
| `emojis.<name>` | Optional: overrides an emoji (see *Emojis* below). Usually left empty: `{}` |
| `balance` | Optional overrides of the game balance (see below) |
| `database_path` | Where the database is stored. With Docker use `db/economy.db` (see below), otherwise it is lost when the container is recreated |

To copy an ID in Discord, enable *Developer Mode* (Settings → Advanced), then right-click the server, channel or role → *Copy ID*.

### Emojis

The bot finds its emojis **by name** among the emojis uploaded to the application (Developer Portal → your app → **Emojis**). Upload the images with exactly these names and restart the bot, nothing else to configure:

| Names | What |
|---|---|
| `emerald`, `stick`, `xp` | Currency, sticks, XP |
| `lapis`, `enchanted_book` | Lapis lazuli, enchanted books |
| `potion_strength`, `potion_speed`, `potion_healing`, `potion_harming` | Potions |
| `gold`, `iron`, `diamond`, `netherite` | Ingots / materials |
| `cobblestone`, `gravel`, `deepslate`, `obsidian`, `bedrock` | Blocks |
| `<material>_<item>`, e.g. `iron_sword`, `gold_helmet`, `netherite_boots` | Gear (4 materials × sword, pickaxe, axe, shovel, hoe, helmet, chestplate, leggings, boots) |

At startup the logs show how many were found and list the missing names. A missing emoji is simply not shown (blocks fall back to 🪨 🟫 ⬛ 🟪, gear to its material).

To use another emoji for a name, set it in `config.json`, e.g. `"emojis": {"emerald": "<:my_emerald:123456789012345678>"}` (send `\:emoji_name:` in Discord to get the code).

After editing `config.json`, run `/reload_config` (or restart the bot). Changing `database_path` or `guild_id` needs a restart.

### Backups

Every night at 04:00 (config timezone) the bot copies the database to a `backups/` folder next to it (`bot/db/backups/` with Docker) and keeps the last 7 copies. Change it with `"balance": {"backups": {"hour": 4, "keep": 7}}`. `/backup_now` makes an extra copy at any time.

`/backup_now` copies are named `manual-…` and are kept apart: they never replace a nightly backup. To restore one: stop the bot, replace `economy.db` with the backup (and delete `economy.db-wal` / `economy.db-shm`), start the bot.

### Game balance

The `balance` section is checked when the bot starts and on `/reload_config`: an unknown key (typo), a wrong type, an invalid time zone or an incoherent schedule is reported. The invalid values are ignored (the default is used): at startup they are logged as warnings, and `/reload_config` lists them. A file that isn't valid JSON is refused and the current settings stay.

Every number of the game (rewards, prices, durability, cooldowns, boss HP, tax, timezone…) has a default in [`game/settings.py`](game/settings.py). To change one, copy its path under `balance` in `config.json`, for example:

```json
"balance": {
  "timezone": "Europe/Paris",
  "mining": { "cooldown_seconds": 20 },
  "daily": { "base_reward": 50 },
  "boss": { "auto_spawn_hours": 48, "hp": 2000 }
}
```

`/repair` and the anvil use `balance.repair`: `durability_per_ingot` (0.25), `penalty_per_repair` (0.25), `anvil_iron` (22) and `anvil_damage_chance` (0.12). Spam channels use `balance.mining.spam_reward` (0.01).

Everything below can also be changed from Discord with `/config`.

The XP curve is `balance.levels`: `xp_first_level` (100) and `xp_increase_per_level` (25).

Mining odds: each mining reward is a pile of 1 to 6 blocks (each size as likely). `balance.mining.odds_6_blocks`, `odds_4_5_blocks`, `odds_2_3_blocks` and `odds_1_block` give the weight of each block for that pile size (chance = weight ÷ total). The talents add to them: `balance.talents.miner_gravel_4_5`, `miner_gravel_2_3`, `miner_deepslate_2_3` (per point, with a `_max` each), `miner_bonus_block_chance` / `miner_bonus_block_max` and `lucky_rare_weight`.

Challenges: `balance.challenges.per_day` (0 = no daily challenges) and `per_week`, and the two pools: `balance.challenges.daily_goals.<challenge>` and `balance.challenges.goals.<challenge>` (weekly), each with `target` and `reward` (`/config` → Progress → Daily & weekly challenges). Achievements: `balance.achievements.<achievement>` (`reward`, and `goal` for those that count something). Their texts follow the numbers (e.g. "Mine 2,500 blocks").

`balance.moderation.warn_mutes` and `balance.villager.buys` are replaced as a whole when you set them (so you can remove a rule or a block).

`balance.boss.auto_spawn_hours` spawns a boss automatically that many hours after the previous one ended (0 = only `/event boss`).

Enchanting is tuned with `balance.enchants`: `lapis_chance`, `lapis_amount`, `apply_cost`, `book_weights`, `boss_book_weights`, `boss_book_top` (how many of a boss's top damage dealers get a book), `challenges_book`, the effects (`efficiency_seconds`, `fortune_bonus`, `fortune_hoe_xp`, `unbreaking_chance`, `sharpness_damage`, `looting_boss_bonus`, `protection_points`, `mending_durability_per_xp`), `boss_mending_chance` and the reference values `lapis_value` / `book_values` / `mending_value`.

Duels and potions are tuned with `balance.duel` (`hp`, `min_damage`, `min_hit_after_armor`, `crit_chance`, `crit_multiplier`, `second_player_bonus_hp`, `turn_seconds`, `afk_turns`, `min_stake`…), `balance.gear` (`sword_max_damage`, `damage_reduction_per_armor_point`, `max_damage_reduction`, and the shield: `shield_blocks_per_fight`, `shield_durability`, `shield_wear_per_block`) and `balance.potions`: `max_per_duel`, `strength_min_bonus`, `speed_chance`, `speed_turns`, `healing_hp`, `harming_damage`, `level2_multiplier`, `strong_per_fight` (reinforced potions per duel or dungeon run), `boss_top` and `boss_potions` (how many of a boss's top damage dealers get potions, and how many), `random_weights` (how often each kind comes from drops, bosses and the villager) and the reference values `value` / `value_ii`.

Moderation is tuned with `balance.moderation`: `warn_expire_days` (0 = warnings never expire) and `warn_mutes`, e.g. `{"3": "1h", "5": "1d", "7": "7d"}` (automatic mute when a member reaches that many warnings).

The villager is tuned with `balance.villager`: `arrive_hour`, `leave_hour`, `sell_discount`, `buy_bonus`, `goods` (what he can sell), `buys` (blocks he buys and how many), `book_iii_price`, `potion_ii_price`, `exclusive_mending_chance` and `mending_price` (the exclusive offer is a Mending book this often, checked first), `exclusive_book_chance` (else a level III book this often, or a potion) and `book_weights` (level I / II of the books he sells). Reinforced potions use `balance.potions.level2_multiplier` and `value_ii`.

The tournament is tuned with `balance.tournament`: `entry_fee`, `house_bonus`, `min_players`, `max_players`, the schedule (`opens_day`/`opens_hour`, `closes_day`/`closes_hour`, `start_day`/`start_hour`, days 0 = Monday … 6 = Sunday), `round_minutes`, `prize_split` (`[60, 25, 15]`) and `xp_per_win`.

The PVE dungeon is tuned with `balance.pve`: `hp` (players' health, not restored between waves), `max_players`, `cooldown_minutes`, `lobby_minutes`, `decision_minutes`, `max_potions`, `wave_growth` (e.g. `0.1` = monsters +10% each wave), `clear_bonus` (e.g. `0.5`), `xp_per_wave`, `wave_rewards` (5 values, multiplied by the difficulty's reward), `group_monsters` (share of a wave each extra player adds, `1` = a whole wave), `min_hit_after_armor`, `monsters` (each monster's `hp`, `min_damage` and `max_damage` at Normal) and `difficulties` (`easy`, `normal`, `hard`, `hardcore`, `nightmare`, each with `entry`, `strength` = monsters' health and damage, Normal = 1, and `reward`).

Species are tuned with `balance.species`: `change_cost`, `change_days`, and the bonus of each one: `villager_trade` (e.g. `0.05`), `dwarf_damage`, `witch_potions`, `mage_enchants`, `miner_speed`, `gambler_max_bet`.

Loans are tuned with `balance.loans`: `min_amount`, `max_amount`, `max_interest` (e.g. `0.2` = 20%), `min_days`, `max_days`, `max_loans_out` (unpaid loans per lender), `offer_minutes`, `late_penalty` (e.g. `0.1`) and `garnish` (share of a late borrower's income that goes to the lender, e.g. `0.5`).

Profiles are tuned with `balance.profiles`: `bio_max`, `color_price` (each dye color), `hex_price` (any #hex color), `banner_cost` (a team banner change) and `frame_prices` (`stone`, `gold`, `redstone`, `lapis`, `diamond`, `emerald`), `frame_goals` (what it takes to earn the other frames) and `title_goals` (what it takes to earn each title).

The guide is tuned with `balance.guide`: `reward` (emeralds for the whole checklist, once per player), `delete_after_days` (after the checklist is done, 0 = kept) and `expire_days` (if it's never done, 0 = kept).

Teams are tuned with `balance.teams`: `max_members`, `create_cost` (emeralds, 0 = free), `min_members_ranked`, `invite_hours`, `space_cost` (the team category, 0 = free), `max_channels` (channels per team category), `xp_bonus_per_active_member`, `max_xp_bonus`, `season_rewards` (e.g. `[600, 300, 150]`) and `log_score` (`true`: the logarithmic team score above; `false`: the sum of what the members earned).

> ⚠️ `.env`, `config.json`, the database files (`*.db`, `*.db-wal`, `*.db-shm`) and the `backups/` folder (it holds copies of `config.json`, with the RCON password) contain secrets or user data. They are ignored by git and Docker — never commit them.

---

# 🐳 Running with Docker (recommended)

The bot is designed to run next to a Minecraft server using the [`itzg/minecraft-server`](https://github.com/itzg/docker-minecraft-server) image. Both containers share a Docker network, so the bot reaches the server through its service name (`minecraft`).

```
my-server/
├── docker-compose.yml
├── data/               # Minecraft server files
├── Blocky/             # this repository
└── bot/
    ├── config.json     # with "database_path": "db/economy.db"
    └── db/             # the database lives here
```

```yaml
services:
  minecraft:                       # must match rcon_host / server_host
    image: itzg/minecraft-server:java21
    ports:
      - "25565:25565"              # RCON (25575) stays private
    environment:
      EULA: "TRUE"
      # ... your modpack settings ...
      RCON_PASSWORD: "same_as_config_json"
      ENABLE_WHITELIST: "true"
    volumes:
      - ./data:/data
    restart: unless-stopped

  blocky:
    build: ./Blocky
    environment:
      DISCORD_TOKEN: "your_bot_token_here"
    volumes:
      - ./bot/config.json:/app/config.json
      - ./bot/db:/app/db
    depends_on:
      - minecraft
    restart: unless-stopped
```

Set `"database_path": "db/economy.db"` in `config.json`, then start:

```bash
mkdir -p bot/db
docker compose up -d --build
```

> Mount the **folder**, not the `economy.db` file alone: SQLite also writes `economy.db-wal` and `economy.db-shm` next to it, and they must survive restarts too.

> Upgrading from an older Blocky: the old database format can't be converted. On first start the bot renames it to `economy.db.legacy-<timestamp>` (kept as a backup) and starts a new one.

### Updating from Discord (`/bot_update`)

`/bot_update` (staff) shows what's new on GitHub (the titles of the new changes, and warnings such as files changed by hand), then **Update and restart** pulls the changes, rebuilds the bot and restarts it. The result (new version and what changed, or the error) is posted in the staff channel; if the pull or the build fails, the old version keeps running.

The bot itself never gets access to Docker: a small **updater** container does the work. It only knows two fixed actions (check, update) that the bot asks for by dropping a file in a folder they share, and nothing in a request is ever run. When the updater's own code changes, it rebuilds itself after the bot.

1. The `Blocky` folder must be a **git clone** (`git clone https://github.com/Shiro645/Blocky.git Blocky`), on the `main` branch. The repository is public: no password needed.
2. Add the shared folder to `blocky`, and the `blocky-updater` service. The updater must see the folder of your `docker-compose.yml` **at the same path** as on the host (here `/volume1/docker/craftoria`: change it to yours):

```yaml
  blocky:
    # ... as above ...
    volumes:
      - ./bot/config.json:/app/config.json
      - ./bot/db:/app/db
      - ./bot/update:/app/update        # shared with the updater

  blocky-updater:
    build: ./Blocky/updater
    container_name: blocky-updater
    restart: unless-stopped
    working_dir: /volume1/docker/craftoria
    environment:
      REPO_DIR: /volume1/docker/craftoria/Blocky
      SERVICE: blocky                   # the bot's service name
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /volume1/docker/craftoria:/volume1/docker/craftoria
      - ./bot/update:/shared
```

3. `mkdir -p bot/update && docker compose up -d --build`, then `/bot_update` in Discord. `docker logs blocky-updater` shows what the updater does.

> ⚠️ The updater has the Docker socket, which gives full control of Docker on the machine: that's why it's a separate container that only accepts these two fixed actions. Don't give the socket to the bot's container.

---

# 💻 Running locally

```bash
git clone https://github.com/Shiro645/Blocky.git
cd Blocky

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
cp config.example.json config.json
# edit both files

python bot.py
```

When running locally, set `server_host` and `rcon_host` to the address of your Minecraft server (e.g. `127.0.0.1`), and make sure RCON is enabled in its `server.properties`.

---


---

# 🧪 Tests

The game logic (`game/`) doesn't depend on Discord and is covered by unit tests:

```bash
python -m unittest discover -s tests -t .
```

The tests also check that every slash command has a page in `utils/manual.py` (the `/help` manual) and a description for each of its options: when you add a command, add its page there.

---

# 🏗️ Project Structure

```
bot.py                       # entry point: database, announcer, cogs
config.example.json          # config template
.env.example                 # environment template
game/                        # game rules, no Discord code
├── db.py                    # async SQLite (one thread, one transaction per action) + migrations
├── settings.py              # balancing values (overridable in config.json)
├── catalog.py               # blocks, materials, gear, recipes
├── players.py               # emeralds, blocks, items, stats, XP, talents
├── mining.py                # passive mining
├── shop.py                  # market and crafting
├── gear.py                  # equipment, durability, combat stats
├── daily.py · exchange.py · assets.py   # daily, pay/trade/auction
├── loans.py                 # loans between players, late penalty and collection
├── species.py               # species and their bonus
├── pve.py                   # the PVE dungeon: monsters, waves, fights and runs
├── dummy.py                 # training dummy: damage tester, leaderboard, training duels
├── guide.py                 # the guide checklist (steps, reward once) and the guide channels' lifetime
├── profiles.py              # profile customization (bio, colors, frames, titles, showcase) and team banners
├── leaderboard.py · seasons.py · duel.py
├── teams.py                 # teams, team bonus and weekly team season
├── team_spaces.py           # team categories: unlocked once by the leader, kept in sync by the teams cog
├── tournament.py            # weekend tournament
├── enchants.py              # enchanted books, lapis and enchantment effects
├── potions.py               # duel potions
├── villager.py              # the wandering villager
├── roulette.py · blockdle.py · quiz.py   # mini-games (blockdle_blocks.py: the blocks and their values)
├── moderation.py            # warnings, mutes, kicks and bans (records and timers)
├── progress.py              # achievements and daily and weekly challenges
├── events.py                # drops and bosses
├── live_events.py           # timed events (Gambling Frenzy, Mining Rush, Golden Hour, Lucky Hour, Market Sale)
└── links.py                 # Discord <-> Minecraft links
cogs/                        # slash commands, one file per feature
utils/                       # config, checks, announcer, RCON, Mojang, UI helpers, manual (/help pages), wiki (the wiki channel),
                             # updates.py (what's new: the announcements of the updates channel),
                             # selfupdate.py (talks to the updater for /bot_update),
                             # profile_card.py (draws the profile cards and banners with Pillow)
updater/                     # the updater container: git pull + rebuild of the bot, asked by /bot_update
tests/                       # unit tests
```

Generated at runtime (not versioned): `.env`, `config.json`, `economy.db`.
