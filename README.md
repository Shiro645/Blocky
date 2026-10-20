# 🧱 Blocky

A modular Discord bot built for a modded Minecraft server community.

It connects to the Minecraft server through **RCON** to manage the whitelist, shows the server status, and runs a Minecraft-themed economy and competition system directly in Discord.

---

## 🚀 Features

### 🗂️ Where commands work
Every player command has its channel (`utils/routing.py`), set in `/config` → Channels:
- 🎰 **Casino** (`channels.casino`): `/luckyblock`, `/wheel`, `/blackjack`, `/mines`;
- 🌀 **Portal** (`channels.portal`): `/pve`, `/boss`, `/portal`, `/dimensions`;
- 🦹 **Robberies** (`channels.robberies`): `/rob`;
- 💬 **Commands** (`channels.commands`): every other player command.

Staff commands and `/help` work everywhere, and so does everything in a player's guide channel. Buttons work on their message. A command typed elsewhere answers (only to the player) where it goes. A channel that isn't set lets its commands work anywhere, so they can be set one at a time. Mining happens by chatting in `channels.mining`, the quiz comes in `channels.events`.

### 📖 Manual

- `/help` — A menu by category, and a page for every command: what it does, its options, its **current numbers** (read from the settings, so they follow `/config`), examples and related commands. `/help command:<name>` opens a page directly (`/help command:mining` explains chat mining). Staff commands are only shown to staff, and the answer is only visible to the player who asked.

### 🆕 Updates channel

- **Each new feature is announced once** in the updates channel (`channels.updates`, `/config` → Channels), pinging the role `roles.updates_ping` if it's set (one ping, even when several announcements are posted together). The announcements are written in [`utils/updates.py`](utils/updates.py): the bot posts the ones it hasn't posted yet when it starts (so right after each update of the bot), when the channel is set and after `/reload_config`. Until a channel is set, they wait. The first one is a recap of everything new.
- **Adding a feature?** Add an entry at the end of `utils/updates.py` with a new key (never change the key of an entry already posted: it would be posted again).

### 📚 Wiki

- **A wiki channel kept by the bot** (`channels.wiki`, `/config` → Channels): every feature for players explained in detail, more than `/help` (which has one page per command). A contents message at the top links to each part, then one message per topic (start here, mining and the daily reward, XP and talents, crafting and gear, enchanting, species, trading/auctions/loans, duels/potions/dummy, the dungeon, gate bosses, timed events/drops/villager, seasons/challenges/achievements/leaderboards, the tournament, teams, profile, mini-games, the Minecraft server), and the contents again at the bottom.
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

- **Passive mining**: chatting mines 1–6 random blocks (dirt, cobblestone, gravel, deepslate, rare obsidian, very rare bedrock in the overworld), with a cooldown (30 s, at least 10 s with talents and enchantments).
- **Mining channels** (`channels.mining`, set in `/config` → Channels): when the staff pick some, only messages there (and in their threads) mine overworld blocks and give XP and drops; the other channels give nothing (spam channels keep their tiny reward). Not set = every channel mines the overworld (except the other dimensions' channels).
- **Dimensions** — `/dimensions` shows them all. After the overworld come the 🔥 **Nether** (netherrack 1, blackstone 4, nether bricks 11, gilded blackstone 18), the 🌌 **End** (end stone 1, end bricks 4, purpur 24), the 🦇 **Deep Dark** (sculk 2, sculk shrieker 5) and the ✨ **Shimmer** (shimmer stone 3). There is **one mining channel** (`channels.mining`): each player mines in the **dimension they are in**. `/portal dimension:<…>` takes them to any dimension they unlocked (no cooldown), and unlocking a new one takes them there (`users.current_dimension`, empty = their furthest). Each dimension pays more per message than the one before: about **5.2 emeralds** a message in the overworld (no gear), **×1.25**, **×1.5**, **×1.75** and **×2** in the others. Same odds shape everywhere (big piles of the common block, the rarest ones alone), a dimension with fewer blocks gives the missing ranks to its rarest one; the Miner, Lucky talents, the pickaxe's upgrade and the shovel work on the blocks of the same rank. The pickaxe's and shovel's extra blocks are worth their overworld value times `balance.dimensions.multipliers` (calibrated: with gold to netherite tools too, each dimension stays at ×1.25 / ×1.5 / ×1.75 / ×2). Unlocking a dimension opens every one before it. **Ores** add up from one dimension to the next (an ingot each, a reaction on the message shows it): **gold** from the Nether (**0.5%** per mining reward), **iron** from the End (**0.15%**), **diamond** from the Deep Dark (**0.04%**), and an **emerald ore** in the Shimmer (**0.2%**, **1,000 emeralds**); each adds about 20% to its dimension's income. **Fortune** on the pickaxe gives a chance of a second one: 10% / 20% / 30% · 35% / 37.5% / 38.8% / 39.4% (`balance.dimensions.ore_chances`, `emerald_ore_amount`, `ore_fortune_chance`). The **Nightmare** dungeon opens the Nether to the players still there at the end of wave 5, then the **gate bosses** open the others (see Gate bosses); the staff can set them too (`/player dimension`). **Dimension roles** (`roles.dimension_nether` … `dimension_shimmer`, `/config` → Roles): the bot gives every player the role of the dimension **they are in** (one at a time, none in the overworld; checked at every start, after `/portal` and when a member rejoins). Odds, values and multipliers: `/config` → Economy → 🌋 Dimensions & netherite and Mining & block values.
- **Netherite is a goal of its own**: it can't be bought (not at the market nor the villager), sold (`/sell gear`), traded, given (`/trade`) or put up for auction, and no drop, daily bonus or reward gives it. It's only found **from the Nether on**: each mining reward there finds **Ancient debris** 1.2% of the time (`balance.dimensions.scrap_chance`; a reaction on the message shows it) = one **netherite scrap**. `/craft item:netherite_ingot` turns **4 scraps + 4 gold ingots** into a netherite ingot, and `/craft item:<piece> material:netherite` upgrades a **diamond** piece (the worn one first, else the most enchanted) with **1 netherite ingot**: it keeps its enchantments and is as good as new. A full set (9 pieces) = 9 ingots = 36 scraps: about a month at ~100 mining rewards a day (24 to 37 days for 80% of players).
- **Spam channels** (`channels.spam`, set in `/config`): messages there don't mine blocks, give no XP, no drops and no challenge progress — only a tiny reward (0.01 emerald per message by default, so about 1 emerald an hour of spam), with a cooldown of their own.
- `/inventory` — Blocks, emeralds, items and gear
- `/sell [block] [amount]` — Sell your blocks (overworld: dirt 1, cobblestone 1, gravel 3, deepslate 5, obsidian 7, bedrock 10 emeralds; the other dimensions' above): all of them, only one kind (`block`), or a number of them (`amount`: more than you have sells all you have; without a kind, the least valuable blocks go first)
- `/sell gear:<piece>` — Sell a piece of gear back (not netherite): **80%** of its value new (its craft + the books applied to it) × the durability it has left. A sword at 80% durability sells for 80% × 80% = 64% of its value. The suggestions show each price; you confirm first. A worn piece is taken off. Villagers get their 5% on top; it doesn't count for the seasons (`balance.market.gear_sell_rate`, `/config` → Market & daily).
- `/market` — Buy sticks and gold (300) / iron (1,000) / diamond (5,000) ingots (netherite isn't sold: it's found in the Nether; its value, 20,000, is still used for fair prices). Since 2.2.1 ingots are worth far more and drop far less (an iron vein is 3 times in 1,000 drops, a diamond vein once, 1 ingot each)
- `/daily` — Daily reward. Each consecutive day adds a bonus (up to 7 days), every 7th day in a row gives an iron ingot (`balance.daily.weekly_bonus_item`, `bonus_every_days`), and missing a day resets the streak.
- Rewards are public: the results of `/daily`, `/sell` and `/craft` are shown in the channel (level-ups and achievements go to the announcements channel). Personal info (`/inventory`, `/gear`, `/xp`…) and errors are only shown to the player.
- Buttons that don't work anymore (they expired, or the bot restarted) answer so, instead of Discord's "This interaction failed".

### 🛠️ Crafting & equipment

- `/craft <item> <material>` and `/craftlist` — Swords, tools and armor in gold, iron or diamond; netherite pieces are diamond pieces upgraded with a netherite ingot, and `/craft item:netherite_ingot` makes the ingot (see Mining & economy).
- **Shield** — `/craft item:shield material:iron` (iron only, **6 iron ingots**), equipped in its own slot. In a duel, on your turn, press **🛡️ Attack + block** instead of Attack: you attack, then the opponent's **next attack is entirely blocked** (all its hits, critical or not). Nobody sees it coming: the duel only shows "🛡️ Shiro blocked 7.2 damage" when it happens, and the result sums up the damage each shield stopped. **2 blocks per duel**. It has **100 durability** and each block uses **10**; at 0 it **stays in your inventory, unusable** until you `/repair` it (like any gear: 60% of its crafting value for a full repair). Against the gate bosses it stops the boss's next strike on you (2 per fight). It isn't used in the tournament (fights play out on their own) nor the PVE dungeon, and can't take Unbreaking. There is no dodge anymore.
- `/equip`, `/equip_best`, `/unequip [slot]`, `/gear` — One piece per slot. Freshly crafted gear is equipped if the slot is empty. `/unequip` without a slot takes everything off.
- **Anvil** — `/craft item:anvil` (iron only, **22 iron ingots**, one at a time). Needed to repair gear and to combine books. Like in Minecraft it wears out: each use has a **12%** chance to damage it (new → chipped → damaged → broken). `/gear` shows it.
- `/repair <piece> [ingots]` — Repair a piece on your anvil with **ingots of its material** (iron for the shield); it keeps its enchantments. One ingot gives back **25%** of its durability at the first repair, and each repair the piece already had adds 25% to the ingots needed: **4, 5, 6, 7…** ingots for a full repair. You choose how many ingots to put in (empty = as many as needed, or all you have). The repair count follows the piece in trades and at the auction.
- What gear does:
  - **Pickaxe**: extra cobblestone each time you mine (+3 per tier) + chance to upgrade the block
  - **Shovel**: extra gravel
  - **Axe**: finds sticks while mining
  - **Hoe**: more XP
  - **Sword**: higher maximum damage per hit (duels, gate bosses, tournament)
  - **Armor**: damage reduction in duels (1.2% per armor point, 35% at most)
  - **Shield** (iron only): in duels, **Attack + block** blocks the opponent's next attack, twice per duel
- Gear loses **durability** when used and breaks at 0, so players keep crafting (the shield stays at 0, unusable until repaired). Tools have their material's durability (gold 300, iron 1,000, diamond 3,000, netherite 5,000); **armor pieces get a share of it, like in Minecraft**: chestplate 100%, leggings 94%, boots 81%, helmet 69% (iron: 1,000 / 938 / 813 / 688), in `balance.gear.armor_durability_share` (`/config` → Combat → Swords, armor & shield). When a durability setting changes, the pieces already made (and those at the auction) get the new maximum and keep the same share of durability left, at the next start or right away when changed in `/config`. Tools lose 1 per mining reward where they help, the sword 1 per attack (duels, the dungeon, gate bosses), and every armor piece **1 per hit taken** in duels and against gate bosses, but in the dungeon each hit wears **only one armor piece** (drawn at random among the 4 slots; an empty slot wears nothing), since monsters hit often and softly. A duel costs the whole armor about 15 durability, a full dungeon run about 45 (≈11 per piece) and the sword about 22.

### ✨ Enchanting

- **Lapis lazuli** is found while mining (about 1 mining reward in 40, 1–2 lapis) and in drops.
- **Enchanted books** (levels I to III: 60% / 30% / 10%) come from drops, each survivor of a gate boss victory (II or III), completing every weekly challenge of the week, the wandering villager and other players.
- **Levels IV to VII** — only made by combining two books of the level below, and only up to **III + one level per dimension** the player unlocked: Nether IV, End V, Deep Dark VI, Shimmer VII (`/enchant combine` and `/enchant apply` both refuse a level above it). Each level beyond III adds **half** of what the level before added (Sharpness +3 → +3.5 → +3.75 → +3.88 → +3.94), and applying one costs 16 / 32 / 64 / 128 lapis. **Protection IV to VII** raises the armor's damage reduction cap instead (+1% / +2% / +3% / +4% per piece, above the usual 35%: `balance.enchants.protection_cap_bonus`), since the armor points are already capped there. Older `config.json` values for levels I-III are kept, the new levels get their defaults.
- **Mending** — the rarest book (one level, worth **600**): only the villager's exclusive offer (10% of his visits, 600 emeralds) or, 5% of the time, the book of a gate boss survivor. On any gear: the XP you gain repairs your equipped Mending pieces first (**2 durability per XP**), and only the XP left goes to you. XP given by the staff doesn't repair.
- `/enchant apply <book> <piece>` — Costs 2 / 4 / 8 lapis for a level I / II / III book. A higher level replaces a lower one.
- `/enchant combine <book>` — Two identical books make one book of the next level (I + I = II, II + II = III), on your anvil (Mending can't be combined).
- **Enchanting table** — `/craft item:enchanting_table`: **4 obsidian + 2 diamond ingots + 1 enchanted book** (any: the least valuable one is used). One per player, it **never wears out** (`/gear` shows it; `/reset` gear takes it back). `/enchant table <piece>` enchants a piece **without any enchantment** (sword, tools, armor; not the shield) for **12 lapis**, at random: **1 / 2 / 3** different enchantments **60% / 30% / 10%** of the time (fewer when the piece can't take that many), never Mending. Each level is drawn with the weights 60 / 30 / 9 / 4 / 2 / 1 / 0.5 up to the player's maximum (III, +1 per dimension), and the maximum itself always weighs **1**: about **1%** (overworld: I 66%, II 33%, III 1%). **10%** of the uses add a **curse** on top (Binding or Vanishing, half and half), which can't be removed. Books can then add more enchantments, as on any piece. All of it in `/config` → Combat → 🪄 Enchanting table (`balance.enchanting_table`).
- `/enchant info` — Your books and lapis, and every effect.
- Enchantments follow the piece in `/trade` and `/auction` (the suggestions list enchanted pieces separately) and are lost when it breaks.

| Enchantment | On | I / II / III · IV / V / VI / VII |
|---|---|---|
| Efficiency | pickaxe | mining cooldown −2 s / −4 s / −6 s · −7 / −7.5 / −7.75 / −7.88 s (never below the minimum) |
| Fortune | pickaxe, shovel, axe, hoe | +1 / +2 / +3 · +3.5 / +3.75 / +3.88 / +3.94 cobblestone (pickaxe), gravel (shovel), sticks (axe) (a fraction is a chance of one more); +5% / +10% / +15% … +19.7% XP (hoe) |
| Unbreaking | all gear | 25% / 40% / 50% · 55% / 57.5% / 58.8% / 59.4% chance a use costs no durability |
| Sharpness | sword | +1 / +2 / +3 · +3.5 / +3.75 / +3.88 / +3.94 maximum damage (duels, gate bosses, tournament) |
| Looting | sword | +10% / +20% / +30% · +35% / +37.5% / +38.8% / +39.4% gate boss bounty |
| Protection | armor | +1 / +2 / +3 armor points per piece · then the damage reduction cap +1% / +2% / +3% / +4% per piece |
| Mending | all gear | one level: 2 durability per XP gained (the XP repairs the piece first) |
| Fire Aspect | sword | the target burns **3 turns** (renewed by each hit that lands), losing 0.5 / 1 / 1.5 · 1.75 / 1.88 / 1.94 / 1.97 health each, **through the armor** (duels and tournament: its own turns; raids, gate bosses, the dungeon and the night: each round). Several burning swords don't add up: the strongest fire burns |
| Thorns | armor | each piece sends back 2% / 4% / 6% · 7% / 7.5% / 7.75% / 7.88% of the damage taken to the attacker (no armor stops it): a full set at III, 24% |
| Sweeping Edge | sword | the dungeon: 2.5% / 4% / 5% · 5.5% / 5.75% / 5.88% / 5.94% of each hit also hits another monster, at random (calibrated: III ≈ Fire Aspect III ≈ +11 points of success on Nightmare) |
| Curse of Binding | all but the shield | only from the enchanting table: once worn, the piece can't be taken off, replaced, sold, traded or put up for auction until it breaks (the staff can still `/take` it) |
| Curse of Vanishing | all but the shield | only from the enchanting table: the piece vanishes when its owner falls (0 HP) in the dungeon, against a gate boss or at night (announced) |

### ⭐ XP & talents

- `/xp`, `/talents`, `/talent_buy <branch> [points]`, `/talent_reset` (every spent point back for 50 emeralds a point, at least 100: `balance.talents.reset_cost_per_point`, `reset_cost_min`; asks to confirm)
- XP comes from activity; 1 talent point every 5 levels.
- Branches (each has a cap): **Miner** (better blocks), **Trader** (sell bonus), **Lucky** (bedrock chance), **Efficiency** (shorter cooldown).
- Level-ups are announced, and configurable **level roles** are given automatically.

### 🌟 Prestige
- `/prestige` — Prestige I needs level **50**, every achievement but the ones of `balance.prestige.skip_achievements` (by default the ones only one player or team wins each time, Champion, Arena Champion, Squad Goals and Warlord, and Legend, level 100, since the level is its own condition), every dimension (up to the Shimmer) and the server's Beacon lit; each next one needs **10 more levels** (II at 60, III at 70… X at 140, the highest). It shows the conditions (✅/❌, the achievements still missing), what starts over and what you get; the **Become Prestige** button asks to confirm.
- **What starts over** (`balance.prestige.reset`, each switch in `/config`): `wealth` (emeralds, blocks, items; auction listings and the bounties put are cancelled), `gear` (with its enchantments and the anvil), `talents` (every spent point given back to spend again: the level stays, so none is lost), `achievements` (with the stats; this week's challenges stay done: earned titles and frames go until earned again; with `wealth` too, achievement rewards are paid again), `dimensions` (back to the overworld, dimension roles taken back). The **level always stays**, and so do the team, the bought cosmetics and the Minecraft link. A player with a loan (owed or given), an open loan offer or a game of chance going can't become Prestige until it's settled.
- **What you get**: **+5%** mining XP and `/sell` per prestige, for good (`balance.prestige.bonus`); ⭐ stars before the name in the leaderboards, the season and team lists and on the profile (⭐, ⭐⭐, ⭐⭐⭐, then ⭐×4…; the card shows "Level 52 · Prestige I"); the **Prestige role** (`roles.prestige`, given and taken back by the bot); the titles **Reborn** (Prestige I) and **Mythic** (Prestige V) and the **Prestige** frame (Prestige I). Announced to everyone.
- Staff: `/player prestige <member> <0-10>` sets it (nothing reset). `/reset` of the levels resets the prestige too. All in `balance.prestige` (`/config` → Progress → 🌟 Prestige).

### 🧬 Species

- `/species choose <species>` — Pick a species for a small bonus. The first choice is free; changing costs 1,000 emeralds (you confirm first) and is possible once every 7 days.
  - 🧑‍🌾 **Villager** — 5% better prices: `/sell` gives 5% more, the market and the wandering villager's goods cost 5% less, and he pays 5% more for blocks.
  - 🪓 **Dwarf** — +5% damage in every fight: duels, tournaments, gate bosses, the dungeon and the training dummy.
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
- **Weekly seasons** (`/season`) — The score is the value you *created* during the week (Monday to Sunday): the value of the blocks you mine (counted when mined, not when sold), daily rewards, drops, gate bosses, challenges, the server share of the tournament pot, and the trader/villager bonus when you sell. Spending doesn't lower it; emeralds or blocks received from other players, duel pots and auction sales don't count. At the end of the week, the top 3 get emeralds and the winner gets the **champion role** until the next season ends.
- `/duel <member> <stake>` — Both players bet the same stake and the winner takes it all. The fight is played **turn by turn** in the message: on your turn you can drink a potion (its effect shows right away), then click **Attack**, in the same turn. You have 30 s per turn, then the bot attacks for you; after 2 missed turns in a row the rest of the duel is played automatically. If the bot restarts during a duel, both stakes are refunded.
- **Training dummy** — `/dummy hit` hits the dummy 10 times with your current gear and species (rolled like duel hits, critical hits included) and shows every hit, the total, the average, the min and max; one series per minute. The dummy has no armor and doesn't hit back, nothing wears out and nothing is won. Your best series (total damage) and best hit go on the leaderboard: `/dummy top`. `/dummy duel [gear]` is a **training duel** against a dummy that hits back like a player in no gear, gold, iron (default), diamond or netherite: same buttons as a real duel (Attack, Attack + block with a shield, and **every potion for free** to try them), the dummy plays its turn right away, nothing is used up and nothing is won or lost. Tuned with `balance.dummy` (`hits`, `cooldown_seconds`).
  - **Luck matters**: each hit deals a random amount between **1** and your sword's **maximum** (no sword 6 · gold 8 · iron 10 · diamond 12 · netherite 14, +1/+2/+3 with Sharpness). No dodging: with a **shield** you can **Attack + block** (see below). 15% of hits are **critical** (x2). Armor reduces the damage taken by 1.2% per point, 35% at most. The player who plays second starts with **+2 HP**.
  - Better gear wins more often, not always: one tier ahead (e.g. iron vs gold) wins about 70% of the time, netherite vs iron about 80%.
- **Potions** (`/potions`) — Duels, the PVE dungeon and the gate bosses (not the tournament). In a duel: one potion per turn, up to 3 per duel (at most one reinforced II potion), the effect is for that turn; against a gate boss: one per turn, 2 per fight. Found in drops (a witch's stash: 2 potions); reinforced potions (II, effect doubled) are sold by the villager. They can be traded and sold at auction.

  | Potion | Effect |
  |---|---|
  | Strength | this turn's attack: minimum damage +5 (never above your maximum) |
  | Speed | 40% chance to strike twice, this turn and your next 2 turns |
  | Healing | heals 3 HP (never above your maximum) |
  | Harming | 3 direct damage to the opponent, reduced by their armor (on top of your attack) |
- `/challenges` — **3 daily challenges** (small ones, new every day at midnight) and **3 weekly challenges** (new every Monday), the same for everyone, each with an emerald reward that counts for the season. They're picked from a pool of mining, selling, bedrock, crafting, duels, drops, the daily reward, trades and the mini-games (Lucky Blocks, wheel spins, the Blockdle block of the day, quiz questions, dungeon waves, the training dummy, successful robberies), and **never the same as the day or the week before**. A challenge for a game that is off isn't picked (no quiz challenge without the automatic quiz, no wheel challenge when the wheel is closed, and never a boss challenge: the gate bosses need a group and a dimension). The week running when the bot is updated keeps its challenges.
- `/achievements [member]` — 51 achievements (since 2.0.2: Wither Slayer, Dragon Slayer, Warden Slayer, for the survivors of each gate boss; since 2.0.3: Beacon Builder; since 2.0.4: Warlord and Raider) with emerald rewards, announced publicly: mining, crafting, armor sets, levels, duels, daily streaks, trades, drops, bosses, seasons, and since this update the mini-games (100 Lucky Blocks, 100 wheel spins, a number won at the wheel, 10 Blockdle blocks, 10 quiz questions), robberies (10 successful, 5 thieves stopped), the dungeon (cleared in Hard, Hardcore, Nightmare), challenges (10 and 50 completed), playing during a Gambling Frenzy, and the economy (10 books applied, 10 repairs, 20 deals with the villager, 10,000 emeralds lent). Players who already reached one get it with their next action.
- **Timed events** (`/events`, which also says whether today's random event already came, which one and when, or is still to come) — For an hour (`balance.live_events.duration_minutes`), a bonus for everyone, announced in the events channel (with the events role):
  - 🎰 **Gambling Frenzy** — the maximum bet **and** the daily win limit of the Lucky Block and the wheel ×2 (a Gambler can bet 600).
  - ⛏️ **Mining Rush** — mining XP ×2.
  - 💰 **Golden Hour** — `/sell` pays +50% for blocks (it counts for the season, like the Trader bonus).
  - 🍀 **Lucky Hour** — obsidian and bedrock ×2 more likely when mining.
  - 🏷️ **Market Sale** — `/market` 25% cheaper (during it, gear sold with `/sell gear` is valued at the sale prices, so buying cheap to sell gear back isn't a profit).
  - One comes by itself **every day** at a random time between 10:00 and 22:00, never the same as the day before; the staff can start one with `/event start` (one at a time) and end it with `/event stop`. Tuned with `balance.live_events` (`/config` → Games & events → Timed events): `daily_random`, `earliest_hour`, `latest_hour`, `duration_minutes`, `random_kinds` (which ones can come by themselves), `frenzy_multiplier`, `rush_xp_multiplier`, `golden_sell_bonus`, `lucky_rare_multiplier`, `market_sale_discount`.
- **Biome of the week** (`/biome`) — Every Monday a biome is drawn for the whole server (never the same as the week before) and announced; the staff can set one with `/event biome`. Each has a bonus (**+15%**, or **×1.5** on a chance) and a malus (**-10%**, or **×0.9** on a chance), and a challenge paying **250** emeralds apart from the weekly challenges (not counted for their book; also in `/challenges`):
  - 🏜️ Desert: highest bet of the games of chance ×1.5 · mining XP -10% · break 30 Lucky Blocks
  - ⛰️ Mountains: /sell +15% · mining cooldown +10% · earn 1,500 emeralds selling blocks
  - 🏔️ Badlands: rare blocks ×1.5 · /sell -10% · find 6 bedrock
  - 🌲 Forest: /market -15% · rare blocks ×0.9 · craft 3 pieces of gear
  - 🌑 Dark Forest: /rob loot +15% · damage taken in the dungeon and against gate bosses +10% · 3 successful robberies
  - 🌴 Jungle: dungeon rewards +15% · mining XP -10% · clear 20 dungeon waves
  - 🌿 Swamp: potion effects +15% (duels, dungeon, gate bosses) · drop chance ×0.9 · win 3 duels
  - 🌊 Ocean: drop chance ×1.5 · mining cooldown +10% · claim 3 drops
  - 🍄 Mushroom Fields: damage taken in the dungeon and against gate bosses -15% · /market +10% · deal 250 damage to bosses
  - ❄️ Tundra: mining cooldown -15% · drop chance ×0.9 · mine 900 blocks
  - They add up with the other bonuses (Beacon, timed events, talents). All in `balance.biomes` (`/config` → Games & events → 🗺️ Biomes of the week): `bonus`, `malus`, `odds_bonus`, `odds_malus`, `enabled` (which ones are drawn), `challenge_reward`, `challenges` (each biome's target).
- **Day & night** (`/time`, `/sleep`) — The night is the robberies' hours (22:00–06:00, `balance.rob.night_start_hour`/`night_end_hour`); dusk and dawn are announced. Every night **4 monsters** come at random times (not in the first and last 30 minutes), each attacking a random member of level **10+** who didn't `/sleep` that night: pinged in the events channel with a **Fight** button, they have **15 min** to fight it alone with their gear (the dungeon's fight, Beacon and biome included; gear wears out). Beaten: 🧟 Zombie **40**, 💀 Skeleton **50**, 🕷️ Spider **60**, 🟩 Creeper **80** emeralds, +15 XP. Lost or ignored: **1%** of their emeralds (200 max). A 👻 **Phantom** also comes every night for a player who didn't sleep the **3** nights before: **200** emeralds, or **2%** lost (500 max). Calibrated alone: ~80% won in iron gear, ~95% in diamond (the Phantom ~50% / ~80%). `/sleep` (at night, once, not while a monster attacks you): safe until morning, and the next `/daily` pays **+25%**. Nobody to attack (everyone asleep or below level 10): the monster leaves. All in `balance.night` (`/config` → Games & events → 🌙 Day & night).
- **Random drops** — Activity sometimes makes a drop appear (emeralds, ingots, bedrock, lapis, enchanted books, potions). The first player to click gets it.

### 🚪 Gate bosses
- **They open the dimensions** — The Nether opens by clearing the 💀 **Nightmare** dungeon (the players still there at the end of wave 5). Then the 🖤 **Wither** (lives in the Nether) opens the End, the 🐉 **Ender Dragon** (End) the Deep Dark and the 👁️ **Warden** (Deep Dark) the Shimmer. They replace the old shared server boss (`/attack`, `/event boss` and the automatic bosses are gone).
- `/boss fight <boss>` — Calls a group of up to **4** players who reached the boss's dimension; each pays the entry when joining (Wither 1,500, Dragon 3,000, Warden 6,000; given back if the group isn't started within 5 min, or if the leader leaves). The leader starts with the button. One fight every **12 h** per player (`/player cooldowns` can reset it).
- **Turn by turn** — Each player in order (20 HP each) may drink a potion (**2 per fight**), then **⚔️ Attack** or **🛡️ Attack + block** with a shield (the boss's next strike or hit on that player is stopped, 2 per fight), then the boss plays. 30 s per turn, else the bot attacks for you; after 2 missed turns in a row your turns play by themselves. Hits work like in duels (sword, Sharpness, critical hits); the boss's hits are reduced by armor.
  - 🖤 **Wither** — 400 HP. Blasts everyone (3.1–7.1) and withers them: 1 HP lost on each of its next 2 turns.
  - 🐉 **Ender Dragon** — 440 HP. Strikes players at random twice a turn (9.85–22.2), and every 3rd turn breathes fire on everyone (3.7–7.4, no shield stops it).
  - 👁️ **Warden** — 480 HP. Smashes one player (18.1–36.2), and every 4th turn its **Sonic Boom** (15–24.1) ignores armor and shields.
- **Made for 4** — Calibrated so that 4 players in the best gear of the boss's dimension (netherite with Sharpness/Protection IV for the Wither, V for the Dragon, VI for the Warden), each with a shield and 2 healing potions, win **~35%** of the time; without potions or shields they rarely win (Warden: the potions barely help, the shields do). A smaller group faces a share of the boss's health (Wither 34% / 59% / 82% for 1 / 2 / 3 players, Dragon 15% / 36% / 66%, Warden 14% / 38% / 69%): a prepared group of 3 wins ~15%, of 2 ~8%, alone ~4%.
- **Rewards** — Each **survivor** of a victory opens the next dimension, and gets the bounty (Wither 3,000, Dragon 6,000, Warden 12,000; Looting adds 10-39%; a boss already beaten pays 25%), a level II-III book (5%: Mending) and XP (300 / 500 / 800), plus the achievement of that boss. The fallen get nothing. Gear wears out like in duels. Everything is in `balance.gate_bosses` (`/config` → Combat → 🐉 Gate bosses).
- `/boss info` — The bosses, where they live, what they open, their entry and bounty, the ones you beat and when you can fight again.

### 🔆 The Beacon
- **One Beacon for the whole server**, lit by the **Nether Star** of the first victory against the Wither (announced). Before that nothing can be given. The staff can light it or set its steps with `/event beacon`.
- `/beacon give <material> <ingots>` — Anyone gives ingots, by **whole blocks (multiples of 9)**, of the material it needs now. It's a pyramid of 4 levels (81 / 225 / 441 / 729 ingots, like Minecraft's 9 / 25 / 49 / 81 blocks) built in **16 steps**: the 4 levels in gold, then level 1 to 4 again in iron, diamond and netherite. A level rebuilt in a better material keeps working the whole time; extra ingots of the same material go on to the next step. Netherite can be given (it's the only thing it can be "traded" to).
- **Effects for everyone** — Level 1: mining cooldown −5% and mining XP +5%; level 2: `/sell` of blocks +5%; level 3: damage +1.5%; level 4: damage taken −1.5% (the last two in the dungeon and against the gate bosses). Each level's effects are ×1.5 in iron, ×2 in diamond, ×3 in netherite (full netherite: −15% cooldown, +15% XP and /sell, +4.5% damage, −4.5% damage taken). The combat ones are calibrated: a full-netherite Beacon takes a prepared group from ~35% to ~45-60% against a gate boss.
- **Upkeep** — Every week it needs 5% of its last step, in that material, rounded up to whole blocks (gold level 2: 18 gold ingots). What is given fills the week's upkeep first, and building a step covers the week's upkeep. Not given by Monday: that step crumbles (announced), and ingots already given to the next step stay only if they're of the material needed again.
- **Builders** — Giving at least 200 emeralds' worth (market value) in a week gives +5% mining XP and +5% `/sell` until the week ends. Everything given counts for the 🔆 leaderboard board and the **Beacon Builder** achievement (5,000 emeralds' worth). `/beacon info` shows the levels, the effects, the step being built, the upkeep and this week's builders.
- All in `balance.beacon` (`/config` → Progress → 🔆 Beacon). A `/reset` of the whole server's progress puts the Beacon out and empties it.

### 🏟️ Weekend tournament

- **Registrations** from Friday 18:00 to Saturday 21:00: click **Join** on the announcement, or use `/tournament join` (entry fee 50 emeralds). **Leave** (or `/tournament leave`) refunds you until the draw. The announcement shows the number of players and the pot, and its buttons disappear when registrations close. The server adds 200 emeralds to the pot. 4 to 32 players: with fewer than 4 the tournament is cancelled and everyone is refunded.
- **Draw** when registrations close: a random single elimination bracket. When the number of players isn't a power of 2, some players (drawn at random) skip the first round.
- **Rounds** every hour from Sunday 18:00, announced in the events channel. Fights are automatic, with the duel rules and the gear equipped at that moment, and they don't wear the gear out. Each match won gives XP.
- **Prizes**: 60% of the pot for the winner, 25% for the runner-up, 15% shared by the semi-finalists, plus the tournament champion role until the next tournament ends. Only the server bonus part counts for the weekly seasons: the entry fees just move between players.
- `/tournament info` (dates, pot, your status) and `/tournament bracket` (matches and results).

### 🧑‍🌾 Wandering villager

- Comes **every day from 18:00 to 21:00** (local time) in the events channel, pinging the events role, with **3 offers**:
  - 🛒 a sale 30% below the value: iron or diamond ingots, lapis, a level I/II book or potions (never netherite);
  - 💰 a purchase: he buys a pile of blocks (gravel, deepslate, obsidian or bedrock) 50% above the /sell price (his bonus counts for the season);
  - ✨ an exclusive: a **level III book** or a **reinforced potion (II)**, whose effect is doubled (Strength minimum +10, Speed 80%, Healing 6 HP, Harming 6). Reinforced potions are limited to one per duel. Reinforced potions are only sold by the villager.
- Each offer exists **once**: the first player to click gets it. The buttons keep working after a restart, and the message shows who took what.
- `/villager` shows whether he is here and when he comes next.

### 🎲 Mini-games

The games of chance (`/luckyblock`, `/wheel`, `/blackjack`, `/mines`) work in the **casino** (`channels.casino`) and in the guide channels, or anywhere when it isn't set; `/blockdle` and `/dummy` are in the commands channel (see **Where commands work** below).

- `/luckyblock <amount>` — Bet emeralds and break a **Lucky Block**: 💥 a creeper loses the bet, 🪨 cobblestone gives half back, ⚙️ iron the bet back, then 🟨 gold ×1.5, 💎 diamonds ×2.5, 🟩 emeralds ×4 and, 1 time in 200, ⬛ netherite ×10. Each outcome is rarer than the one before (creeper 31.5%, cobblestone 22%, iron 18%, gold 15%, diamonds 9%, emeralds 4%, netherite 0.5%): more than a quarter of the blocks pay more than the bet. A short ASCII animation shows the block cracking before the result. It only pays emeralds (never items), gives back about 95% of the bets on average, and every outcome's weight and payout are in `/config` → Games & events → Games of chance (`balance.games.lucky_block`).
- **Games of chance** (Lucky Block and the wheel): bets of `balance.games.min_bet`–`max_bet` (1–200; more for the 🎲 Gambler species), `cooldown_seconds` between two games of the same game, and a **daily limit** (`daily_win_cap`, 1,500): once a player won that much today at these games (winnings minus losses), they play again tomorrow. Winnings don't count for the seasons.
- `/blackjack <amount>` — A hand of **blackjack** against the dealer, with buttons: **Hit**, **Stand** or **Double** (first two cards only: twice the bet, one card, then you stand). Each hand is dealt from a real 52-card deck, shuffled (a card never comes out twice). Aces count 1 or 11, faces 10; the dealer draws until 17. A win pays ×2, a **blackjack** (21 with the first two cards) ×2.5 (3:2), a push gives the bet back. About 97% of the bets come back with a simple strategy. No move for 3 min: you stand.
- `/mines <amount> [tnt]` — **Mines**: 20 blocks, 1 to 10 hide TNT (3 by default). Dig them with the buttons: each safe block (💎) raises the multiplier (95% of a fair game: with 3 TNT ×1.12, then ×1.33, ×1.59…), and you **cash out** any time after the first one; the TNT (💥) loses the bet. The game cashes out by itself at ×25 or when every safe block is dug. No move for 3 min: you cash out (nothing dug: the bet back).
- Blackjack and mines share the bets, the waiting time and the daily limit of the other games of chance, and their games survive a restart of the bot. Tuned with `balance.games`: `move_minutes`, `blackjack_enabled`, `blackjack_natural_payout`, `blackjack_dealer_stands`, `mines_enabled`, `mines_return`, `mines_tnt_max`, `mines_max_multiplier` (`/config` → Games & events → Games of chance).
- `/wheel <bet> <amount>` — **The wheel**, a Minecraft roulette (`balance.games.roulette_enabled`). Its numbers are those of a real roulette: the red ones are 🟥 **Redstone**, the black ones ⬛ **Obsidian**, the green 0 a 💎 **Diamond block** (a European roulette; `roulette_zeros: 2` adds the 00 of an American one). For now players bet on **Redstone or Obsidian (×2)** or **a number (0–36, ×36)**: `bet:A number` then the `number` option (type it to find it), or the number typed straight in `bet`; the other bets stay in the game but are closed, and each one can be opened in `/config` (`balance.games.roulette_bets`: `green` = Diamond block ×18, `even`/`odd`, `low`/`high` ×2, `dozens` ×3, `number` ×36). The Diamond block makes the bank keep about 2.7% of the bets on average (5.3% with the 00). The bet is picked in the suggestions, and the wheel spins for a second or two before stopping. Winnings don't count for the seasons.
- `/blockdle guess <block>` — Guess the Minecraft block of the day, the same for everyone (like Wordle / MCdle). After each guess you see how your block compares with the block of the day on 6 properties: tool, hardness, blast resistance, transparent, craftable and version added (🟩 same, 🟥 different, 🔼/🔽 higher or lower). Unlimited private guesses; the fewer you need, the bigger the reward, and the channel is told when you find it. `/blockdle today` shows your guesses, `/blockdle top` today's best (and yesterday's block). 190 blocks, with their real values from Minecraft 1.21.1.
- **Minecraft quiz** — Every hour or so a question appears in the events channel (`channels.events`; not set = only `/event quiz`) with 4 answers; the first player to click the right one wins emeralds and XP (one try each). Staff can ask one now with `/event quiz`.
- **PVE dungeon** — `/pve start <difficulty>` opens a run of **5 waves**: 🧟 zombies, then 💀 skeletons (they shoot before you attack), both, 🕷️ spiders (two bites a turn) with a 🟩 creeper (it explodes on its 2nd turn unless you kill it first) and a skeleton, then a mix with a 🐂 Ravager. Alone or in a group of up to 5: others join with the button (each pays the entry, refunded if they leave before the start or if the group isn't started within 5 min) and the leader starts. Each wave plays out on its own with your gear and species (as in duels); the message shows the fight, everyone's health and loot. **Health isn't restored between waves.** Between two waves (buttons that still work after a restart): every player clicks **✅ Ready** or **leaves with their loot**, and the next wave **starts by itself when everyone still in is ready** (the message shows ✅ ready / ⏳ waiting next to each name; the leader can't go on alone). Anyone can drink a potion (up to 3 per run: Healing heals now, Strength/Speed help during the next wave, Harming hits every monster at its start). Each wave cleared adds to your loot (+15 XP), but **if you die you lose it** and the entry. Clearing wave 5 pays the loot +50%. Whoever hasn't answered within 5 min leaves with their loot, and the next wave starts for the players who were ready. A group faces as many monsters per player (half as many in **Nightmare**, a raid: its monsters are far stronger, made for a full group of 5 in enchanted diamond, who clear it about 35% of the time, while 4 players or fewer almost never do); if the leader leaves or dies, the next player leads. Gear wears out like in duels. One run per hour. `/pve info` shows the difficulties, the waves and when you can play again.

  | Difficulty | Entry | Monsters | Loot (all 5 waves) | Calibrated for (solo, no potions, ~chance to clear all 5) |
  |---|---|---|---|---|
  | 🟢 Easy | 30 | ×0.85 | 105 | iron gear ~98% · no gear ~20% |
  | 🟡 Normal | 75 | ×1 | 262 | diamond ~90% · iron ~60% |
  | 🟠 Hard | 200 | ×1.13 | 630 | netherite ~80% · diamond ~50% |
  | 🔴 Hardcore | 500 | ×1.26 | 1,470 | enchanted netherite ~80% · netherite ~40% |
  | 💀 Nightmare | 1,200 | ×1.42 | 3,360 | enchanted netherite ~35% (potions help) |

  Monsters get +10% health and damage every wave. Everything is tuned with `balance.pve` (`/config` → Combat → Dungeon and Dungeon monsters).
- `/rob <member> <mode>` — Rob a player. **Risky**: they get pinged, the loot is big (200-500 emeralds). **Discreet**: nobody is pinged, the loot is small (50-100). `/rob` is typed in the robberies channel (`channels.robberies`, `/config` → Channels; members need *Use Application Commands* there, not *Send Messages*) and the robbery is posted there — or anywhere, posted where `/rob` was used, when none is set — with a **Stop the thief!** button only the victim can use: if they click it within the hour the thief pays them a fine (10% of the loot), otherwise the thief takes the loot (never more than the victim has) and the victim gets a DM. A thief robs once every 6 h, a robbed player is safe for 12 h, players below level 5 can't be robbed, **no robbery can start from 22:00 to 06:00** (server time; one started at 21:59 keeps going: `night_start_hour`, `night_end_hour`, the same hour twice = robberies all day), and stolen emeralds don't count for the seasons. Members with the **Untouchables** role (`roles.untouchable`, `/config` → Roles, given by hand by the staff) can't be robbed and can't rob anyone. All tuned with `balance.rob` (`/config` → Robberies).
- Tuned with `balance.games`: `min_bet`, `max_bet`, `cooldown_seconds`, `roulette_enabled`, `roulette_bets`, `roulette_zeros` (1 = 0 only, the default; 2 = 0 and 00), `blockdle_rewards` (by number of guesses), `blockdle_xp`, `blockdle_no_repeat_days` (days before a block of the day comes back), `quiz_every_minutes` (0 = only `/event quiz`), `quiz_every_jitter` (e.g. `0.25` = give or take 25%), `quiz_no_repeat` (the last questions not asked again), `quiz_seconds`, `quiz_reward`, `quiz_xp` — all in `/config` → Games & events (Games of chance, Blockdle & quiz).

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

### 🏴 Gang wars
- **Team chest** — `/team chest deposit <amount>` (any member), `/team chest withdraw <amount>` (leader only), `/team chest view`. A personal `/rob` can't reach the chest, but other teams can raid it. `/team info` shows it. Disbanding a team gives its chest back to the leader (not during a raid; no withdrawal while the chest is raided). Late borrowers can't deposit. Staff: `/war_chest <team> <amount>`.
- **The chest's bonus** — `/team chest bonus <bonus>` (leader, once every 7 days): every member gets ⛏️ **Mining** (mining XP), 💰 **Trade** (`/sell`), ⚔️ **Combat** (damage dealt up, damage taken down: dungeon, gate bosses, raids) or 🍀 **Luck** (rare blocks and drops), stronger the fuller the chest: 5,000 / 20,000 / 50,000 / 100,000 emeralds → mining and trade +3/6/10/15%, combat +2/4/6/8%, luck ×1.1/1.2/1.35/1.5. Live: emptying the chest or a raid lowers it at once.
- **The chest's defenses** — `/team chest defense <build|repair> <defense>` (leader, paid from the chest, levels I–III): 🧱 **Walls** (hits on the defenders -4/7/10%; 5,000 / 15,000 / 40,000), 🏹 **Archers** (1/2/3 arrows of 0.5–1.2 at the attackers after every round; same prices), 🛡️ **Iron Golem** (a defender that fights even when no player comes: 60/62/62 HP, hits 8–20 / 8.8–22 / 9.6–24, armor 18/24/28.8%; 8,000 / 20,000 / 50,000). Every raid on the chest takes **25%** of their solidity (0 = a level lost); a full repair costs **25%** of the level's price. Calibrated with 3 diamond attackers: golem alone I/II/III ≈ 78/58/42% won by the attackers, all three defenses at I/II/III ≈ 70/39/15%, 4 netherite attackers against all three at III ≈ 96%.
- **The weekly war** (`/war`) — Automatic, Monday to Sunday: every team of at least **2** members is at war with all the others. Every Monday **5%** of every chest's **average over the week** (time-weighted) goes into the week's **pot**: emptying it just before Monday doesn't help, what can't be taken is owed and paid first by the next emeralds put in. Points: a duel won against a member of another team **+1** (at most 3 a day for the same winner and loser), a successful `/rob` on one **+2**, stopping one's `/rob` **+1**, a raid won **+5**, a raid pushed back **+3**. Duel and robbery results show the points. When the week ends the top 3 share the pot **50% / 30% / 20%** after a **10%** tax, paid into their chests (announced); the winners get the **Warlord** achievement. The shares of missing places go to the next week's pot.
- **Raids** — `/team raid <team>`: you open a raid against another team at war; **2 to 4** members of your team join with the button within **5 min** (the leader can launch earlier). Then the target's members are pinged and have **30 min** to click **Defend** (up to 4). Then the assault is played **turn by turn** in the message, like the gate bosses: an attacker, then a defender…; on your turn drink a potion if you want, then **Attack** (a random enemy) or **Attack + block** (with a shield: the next hit on you is stopped). 30 s a turn, else you attack; after 2 missed turns yours play by themselves (a click brings you back). The golem plays by itself, the archers shoot after every round, the walls lower every hit on the defenders; **15 rounds** at most, then the side with the most health left wins (the defenders on a tie). Gear wears out. The attackers win, or nobody defended (no player, no golem): they take **30%** of the chest (30,000 at most) into their own chest; the bounties of the fallen go to whoever downed them. No raids at night (22:00–06:00, like `/rob`), one raid a day per team, and a raided chest is safe for **24 h**. **Raider** achievement for 5 raids won.
- All in `balance.war` (`/config` → Games & events → 🏴 Gang wars).

### 🎯 Bounties
- `/bounty place <member> <amount>` — puts **250 / 500 / 1,000 / 2,500** emeralds (fixed tiers) on a player's head. The payer and the target need level **10**; never on yourself or a teammate. The payer stays anonymous: the announcement and `/bounty list` never name them (only the staff log does). The target gets a DM. Bounties on the same player add up.
- **Claiming** — the winner of a duel against the target, the thief of a successful `/rob` on them, or the raider (attacker or defender) whose blow makes them fall in a raid takes everything on their head, never one of their teammates. Announced, and shown in the duel, robbery and raid results.
- Each bounty lasts **7 days**; unclaimed, its payer gets it back minus **10%** (DM). After a claim, no new bounty on that player for **24 h**. `/bounty list` shows who is wanted, `/bounty info` the rules and your own. A reset of the emeralds drops the active bounties (no refund).
- All in `balance.bounty` (`/config` → Games & events → 💀 Bounties).

### 🎨 Profile customization

Everything shows on the profile card of `/profile`. Each change shows a preview card only you see; what costs emeralds asks for a confirmation first.

- `/customize bio [text]` — A few words about you (150 characters, free; empty = removed). Emoji show in the text profile but not on the card.
- `/customize color <color>` — The color of your card (accent, XP bar, name): one of the 16 Minecraft dye colors, **150 emeralds** each, bought once and kept for good (the default color is free).
- `/customize hex <code>` — Any color by its code (e.g. `#ff8800`): **750 emeralds** once, then every code is free.
- `/customize frame <frame>` — The patterned border of your card. Sold, bought once: Stone 100 · Gold 250 · Redstone 400 · Lapis 500 · Diamond 1,000 · Emerald 1,500. Earned only: **Netherite** (win a weekend tournament), **Ender** (clear the Nightmare dungeon), **Nether Flames** (survive 25 gate boss victories), **Champion** (win a weekly season).
- `/customize title <title>` — The title under your name, earned by playing: Miner (1,000 blocks), Quarry Master (50,000), Bedrock Hunter (100 bedrock), Blacksmith (50 crafts), Duelist (25 duels won), Gladiator (100), Boss Slayer (10 gate boss victories), Season Champion, Arena Champion, Team Champion, Dungeon Crawler (Hard dungeon), Nightmare Survivor (Nightmare dungeon), Tycoon (100,000 emeralds earned), Banker (10,000 lent), Merchant (50 trades), Heavy Hitter (150 damage in a `/dummy hit` series), Veteran (level 50), Legend (level 100). The staff can also give custom titles.
- `/customize showcase [badge1] [badge2] [badge3]` — Up to 3 of your achievements shown first on the card (none = your latest ones). Free.
- `/customize list` — Your colors, frames and titles, and how to get the others.
- **Team banner** — `/team banner <base> [pattern1] [color1] … [pattern3] [color3]` (leader): a Minecraft-style banner, a base color and up to 3 patterns (stripes, cross, chevron, border, creeper, skull, flower…) each in a dye color. It shows a preview first and costs **100 emeralds**. The banner shows in `/team info` and on the profile card of every member.
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
- **Gear rewind**: `/rewind_gear` takes back, for the whole server, every piece of gear (weapons, armor, tools, shields, worn or spare, auction listings of them too) and every netherite ingot, and **pays them back in full**: the ingots and sticks of the recipe at the market prices (netherite 300) + the books on them (repairs aren't). You see the totals first and confirm twice; a backup is made just before, the staff channel gets a summary and every player a DM with their refund. The refund doesn't count for the seasons. Meant for the 2.0 launch: `/bot_update`, then `/rewind_gear`.
- **Ingot rewind**: `/rewind_ingots` takes back, for the whole server, every ingot (inventories and auction listings) and pays it back at its **old** price (gold 5, iron 10, diamond 60, netherite 300), every netherite scrap at 70. Gear isn't touched; the ingots the villager still sells get the new prices. Same flow as the gear rewind (totals, two confirmations, backup, summary, DMs), and it can be done **once** only. Meant for the 2.2.1 update: `/bot_update`, then `/rewind_ingots`.
- Fresh start: `/reset [member]` resets, for one player or the whole server, what you pick: emeralds/blocks/items (and auction listings, loans: the debts are cancelled), gear, levels/XP/talents (level roles removed), stats/achievements/seasons (and the guide checklist, and the dimensions: back to the overworld). You confirm by typing `RESET`, and a backup of the database is made just before. Minecraft links, moderation, teams and settings are kept.
- Players: `/player xp_add`, `/player xp_set`, `/player level`, `/player talents_add`, `/player talents_reset` (refunds points), `/player species` (set or remove a member's species, free and without waiting), `/player dimension <member> <dimension>` (sets the furthest dimension they reached: every one before it opens, the ones after close; their dimension roles follow, they get a DM), `/player title <member> <title>` (gives a custom title, the member can then pick it with `/customize title`), `/player profile_reset <member> <part> <reason>` (removes the bio, the title and the custom titles given by the staff, or both; colors, frames and earned titles are kept) — the member gets a DM — `/player cooldowns <member> [timer] [reason]` (resets their waiting times, one or all: robbing again, the protection after being robbed, the dungeon, the dummy, a gate boss fight, duels, the Lucky Block and roulette, mining, changing species and the daily reward, whose claim of the day is undone without growing the streak twice; the member gets a DM and the staff channel a log) and `/player sync_roles` (gives everyone the level role matching their level).
- Events: `/event beacon <lit> [step]` (lights or puts out the Beacon, sets its steps built), `/event start <event> [minutes]` (a timed event now: Gambling Frenzy, Mining Rush, Golden Hour, Lucky Hour or Market Sale), `/event stop` (ends it), `/event drop`, `/event quiz` (a quiz question in this channel now), `/event tournament` (open registrations now, run the next step now — draw, then the next round — or cancel and refund; handy to test without waiting for the weekend), `/event villager` (come now for the usual visit length, or leave).
- Whitelist: `/whitelist add`, `/whitelist remove`, `/whitelist list`, and `/unlink <member>` (removes a link and its whitelist entry)
- Blocky ban: `/blocky ban <member> <duration> <reason>` blocks a player who abuses the bot: they can't use any of Blocky's commands, buttons or menus until the end (`30m`, `2h`, `3d`, `1w`…) or until lifted (`perm`). They keep everything they own and still mine by chatting; they get a DM and see the end and the reason when they try a command. A new block replaces the previous one; staff can't be blocked. `/blocky unban <member>` lifts it, `/blocky list` shows who is blocked. Logged in the staff channel.
- Guide: `/guide_resend [member]` sends the guide again in a new private channel (the old one is deleted), to one member or to **every member with the Blocky player role** (after a confirmation, newest members first, in the background; the result is also posted in the staff channel). Steps already done stay checked and the reward is never paid twice. Members it can't reach because of the 500-channel limit are counted in the report.
- Teams: `/team_remove <team>` deletes a team (offensive name…), logged in the staff channel
- Settings: `/config` opens menus to change **almost every setting of the bot** from Discord (the bot token, server ID, Minecraft connection, `/mc` blocked list, staff role and database path stay in `config.json` only). You pick a **section**, then a **category**: 🖥️ **Server** (channels, roles, level roles, Minecraft texts, time zone & backups, moderation), 💰 **Economy** (mining & block values, mining odds, market/daily/repair, trading & auction, loans, villager), ⭐ **Progress** (XP/levels/talents, seasons, daily & weekly challenges, achievements, species, profiles, titles & earned frames, guide, teams), ⚔️ **Combat** (duels & dummy, potions, tools, swords/armor/shield, enchanting books and effects, dungeon, dungeon monsters, gate bosses, tournament) and 🎉 **Games & events** (timed events, games of chance, Blockdle & quiz, robberies, drops). The section page shows how many settings each category has and how many were changed. Each setting shows what it does, its current value and its default, with buttons to change it (percentages are typed as `25` or `25%`) or to reset it to the default; settings changed from the default are marked ✏️. Lists (season rewards…), automatic mutes, the drop table and the villager's goods have their own editors (add, change, delete a line). Values are checked before being saved (an invalid one is refused with the reason). Settings left in the file that the bot doesn't use (from an older version, or a typo) never block a change: they are removed from the file, and the reply lists them. Changes apply immediately, the previous `config.json` is copied to the backups folder and every change is logged in the staff channel. The RCON password, staff role and database path can't be seen or changed from Discord.
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
| `channels.events` | Channel for drops, the wandering villager and the Minecraft quiz (empty = drops appear where people chat, no automatic quiz) |
| `channels.staff_log` | Staff channel receiving `/link` requests (required for `/link`) |
| `channels.robberies` | Robberies channel: `/rob` only works there, and every robbery is posted there with its *Stop the thief!* button (0 = `/rob` anywhere, posted where it's used) |
| `channels.market` | Market channel: the bot keeps two messages there, always up to date: the market (fixed prices) then every auction listing, each with a menu to buy |
| `channels.casino` | Casino channels: `/luckyblock`, `/wheel`, `/blackjack` and `/mines` only work there (empty = anywhere). The old `channels.games` is moved here at the first start |
| `channels.portal` | Portal channels: `/pve`, `/boss`, `/portal` and `/dimensions` only work there (empty = anywhere) |
| `channels.commands` | Commands channels: every other player command only works there (empty = anywhere) |
| `channels.updates` | Updates channel: each new Blocky feature is announced there once, after the bot is updated (0 = the announcements wait) |
| `channels.wiki` | Wiki channel: the bot keeps every feature explained there, with the current numbers (0 = no wiki) |
| `channels.guide_category` | Category of the guide channels: every new member gets a private channel there with the guide and a checklist (0 = no guide channels; `/guide` still shows the guide) |
| `channels.spam` | List of spam channels: no blocks, XP or drops there, only `balance.mining.spam_reward` emeralds per message |
| `channels.mining` | The mining channel(s): only messages there (and in their threads) mine and give XP and drops, in the dimension each player is in (empty = every channel). The old `mining_nether` … `mining_shimmer` lists aren't used anymore |
| `roles.level_roles` | `{"level": role_id}`, e.g. `{"10": 123, "25": 456}`. Members keep the highest role reached. In `/config` → Level roles, pick the role in the bot's list (roles above the bot's own role aren't listed: it couldn't give them), then type the level. |
| `roles.season_champion` | Role given to the winner of the last weekly season |
| `roles.tournament_champion` | Role given to the winner of the last weekend tournament |
| `roles.updates_ping` | Role pinged when a new feature is announced (0 = no ping) |
| `roles.blocky_player` | Blocky player role: only its members get a guide channel (give it with an onboarding question in *Channels & Roles*; 0 = no guide channels) |
| `roles.team_leader` | Role given to every team leader (and taken back when they no longer lead a team) |
| `roles.untouchable` | Untouchables: members with this role can't be robbed and can't rob (given by hand by the staff) |
| `roles.dimension_nether` … `dimension_shimmer` | Role given to the players who are in that dimension (`/portal`) |
| `roles.species_villager` … `species_gambler` | Role given to the players of each species (`species_villager`, `species_dwarf`, `species_witch`, `species_mage`, `species_miner`, `species_gambler`) |
| `roles.event_ping` | Role pinged when the wandering villager arrives or a tournament opens (0 = no ping). Nobody else is pinged. |
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
| `dirt`, `cobblestone`, `gravel`, `deepslate`, `obsidian`, `bedrock`, `netherrack`, `blackstone`, `nether_bricks`, `gilded_blackstone`, `end_stone`, `end_bricks`, `purpur`, `sculk`, `sculk_shrieker`, `shimmer_stone` | Blocks |
| `netherite_scrap` | Netherite scraps |
| `<material>_<item>`, e.g. `iron_sword`, `gold_helmet`, `netherite_boots` | Gear (4 materials × sword, pickaxe, axe, shovel, hoe, helmet, chestplate, leggings, boots) |

At startup the logs show how many were found and list the missing names. A missing emoji is simply not shown (blocks fall back to 🪨 🟫 ⬛ 🟪, gear to its material).

To use another emoji for a name, set it in `config.json`, e.g. `"emojis": {"emerald": "<:my_emerald:123456789012345678>"}` (send `\:emoji_name:` in Discord to get the code).

After editing `config.json`, run `/reload_config` (or restart the bot). Changing `database_path` or `guild_id` needs a restart.

### Backups

Every night at 04:00 (config timezone) the bot copies the database to a `backups/` folder next to it (`bot/db/backups/` with Docker) and keeps the last 7 copies. Change it with `"balance": {"backups": {"hour": 4, "keep": 7}}`. `/backup_now` makes an extra copy at any time.

Right after the nightly backup, the bot also checks GitHub (through the updater, see *Updating from Discord*): when there's a new version, it posts in the staff channel what changed and reminds to use `/bot_update` (once per new version).

`/backup_now` copies are named `manual-…` and are kept apart: they never replace a nightly backup. To restore one: stop the bot, replace `economy.db` with the backup (and delete `economy.db-wal` / `economy.db-shm`), start the bot.

### Game balance

The `balance` section is checked when the bot starts and on `/reload_config`: an unknown key (typo), a wrong type, an invalid time zone or an incoherent schedule is reported. The invalid values are ignored (the default is used): at startup they are logged as warnings, and `/reload_config` lists them. A file that isn't valid JSON is refused and the current settings stay.

Every number of the game (rewards, prices, durability, cooldowns, gate boss HP, tax, timezone…) has a default in [`game/settings.py`](game/settings.py). To change one, copy its path under `balance` in `config.json`, for example:

```json
"balance": {
  "timezone": "Europe/Paris",
  "mining": { "cooldown_seconds": 20 },
  "daily": { "base_reward": 50 },
  "gate_bosses": { "cooldown_hours": 8, "wither": { "boss_hp": 380 } }
}
```

`/repair` and the anvil use `balance.repair`: `durability_per_ingot` (0.25), `penalty_per_repair` (0.25), `anvil_iron` (22) and `anvil_damage_chance` (0.12). Spam channels use `balance.mining.spam_reward` (0.01).

Everything below can also be changed from Discord with `/config`.

The XP curve is `balance.levels`: `xp_first_level` (100) and `xp_growth_per_level` (1.05: each level needs 5% more XP than the previous one; level 10 needs 155, level 50 needs 1,092, level 100 needs 12,524). Players keep their level when it changes.

Mining odds: each mining reward is a pile of 1 to 6 blocks (each size as likely). `balance.mining.odds_6_blocks`, `odds_4_5_blocks`, `odds_2_3_blocks` and `odds_1_block` give the weight of each block for that pile size (chance = weight ÷ total). The talents add to them: `balance.talents.miner_gravel_4_5`, `miner_gravel_2_3`, `miner_deepslate_2_3` (per point, with a `_max` each), `miner_bonus_block_chance` / `miner_bonus_block_max` and `lucky_rare_weight`.

Challenges: `balance.challenges.per_day` (0 = no daily challenges) and `per_week`, and the two pools: `balance.challenges.daily_goals.<challenge>` and `balance.challenges.goals.<challenge>` (weekly), each with `target` and `reward` (`/config` → Progress → Daily & weekly challenges). Achievements: `balance.achievements.<achievement>` (`reward`, and `goal` for those that count something). Their texts follow the numbers (e.g. "Mine 2,500 blocks").

`balance.moderation.warn_mutes` and `balance.villager.buys` are replaced as a whole when you set them (so you can remove a rule or a block).

`balance.gate_bosses` tunes the gate bosses: group size, health, turn time, cooldown, potions per fight, and for each boss its entry, health, hits, special attack, bounty and XP.

Enchanting is tuned with `balance.enchants`: `lapis_chance`, `lapis_amount`, `apply_cost`, `book_weights`, `boss_book_weights` (the book of a gate boss survivor), `challenges_book`, the effects for levels I to VII (`efficiency_seconds`, `fortune_bonus`, `fortune_hoe_xp`, `unbreaking_chance`, `sharpness_damage`, `looting_boss_bonus`, `protection_points`, `protection_cap_bonus`, `mending_durability_per_xp`), `boss_mending_chance` and the reference values `lapis_value` / `book_values` / `mending_value`.

Duels and potions are tuned with `balance.duel` (`hp`, `min_damage`, `min_hit_after_armor`, `crit_chance`, `crit_multiplier`, `second_player_bonus_hp`, `turn_seconds`, `afk_turns`, `min_stake`…), `balance.gear` (`sword_max_damage`, `damage_reduction_per_armor_point`, `max_damage_reduction`, and the shield: `shield_blocks_per_fight`, `shield_durability`, `shield_wear_per_block`) and `balance.potions`: `max_per_duel`, `strength_min_bonus`, `speed_chance`, `speed_turns`, `healing_hp`, `harming_damage`, `level2_multiplier`, `strong_per_fight` (reinforced potions per duel or dungeon run), `random_weights` (how often each kind comes from drops and the villager) and the reference values `value` / `value_ii`.

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
├── events.py                # drops
├── gate.py                  # gate bosses (Wither, Ender Dragon, Warden)
├── beacon.py                # the server's Beacon
├── war.py                   # gang wars: team chests, the weekly war, raids
├── bounty.py                # bounties on players' heads
├── biomes.py                # the biome of the week
├── prestige.py              # prestige: start over for good bonuses
├── night.py                 # day and night: the night monsters, /sleep
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
