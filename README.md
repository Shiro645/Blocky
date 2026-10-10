# 🧱 Blocky

A modular Discord bot built for a modded Minecraft server community.

It connects to the Minecraft server through **RCON** to manage the whitelist, shows the server status, and runs a Minecraft-themed economy and competition system directly in Discord.

---

## 🚀 Features

### 🌍 Minecraft

- `/server_status` — Server status (players & ping)
- `/ip` — Join instructions
- `/modpacks` — Modpack information
- `/link <username>` — Link your Minecraft account. A staff member approves the request with a button, which whitelists the account. `/link_status` shows your link.
- `/help` — List the available commands

### ⛏️ Mining & economy

- **Passive mining**: chatting mines 1–6 random blocks (cobblestone, gravel, deepslate, rare obsidian, very rare bedrock), with a cooldown.
- `/inventory` — Blocks, emeralds, items and gear
- `/sell` — Sell all your blocks (cobblestone 1, gravel 3, deepslate 5, obsidian 7, bedrock 10 emeralds)
- `/market` — Buy sticks and gold / iron / diamond / netherite ingots
- `/daily` — Daily reward. Each consecutive day adds a bonus (up to 7 days), every 7th day gives a diamond ingot, and missing a day resets the streak.

### 🛠️ Crafting & equipment

- `/craft <item> <material>` and `/craftlist` — Swords, tools and armor in gold, iron, diamond or netherite.
- `/equip`, `/equip_best`, `/unequip`, `/gear` — One piece per slot. Freshly crafted gear is equipped if the slot is empty.
- What gear does:
  - **Pickaxe**: more blocks per message + chance to upgrade the block
  - **Shovel**: extra gravel
  - **Axe**: finds sticks while mining
  - **Hoe**: more XP
  - **Sword**: damage in duels and against bosses
  - **Armor**: damage reduction in duels
- Gear loses **durability** when used and breaks at 0, so players keep crafting.

### ✨ Enchanting

- **Lapis lazuli** is found while mining (about 1 mining reward in 40, 1–2 lapis) and in drops.
- **Enchanted books** (levels I to III: 60% / 30% / 10%) come from drops, the top damage dealer of a boss (II or III), completing every weekly challenge of the week, and other players.
- `/enchant apply <book> <piece>` — Costs 2 / 4 / 8 lapis for a level I / II / III book. A higher level replaces a lower one.
- `/enchant combine <book>` — Two identical books make one book of the next level (I + I = II, II + II = III).
- `/enchant info` — Your books and lapis, and every effect.
- Enchantments follow the piece in `/trade` and `/auction` (the suggestions list enchanted pieces separately) and are lost when it breaks.

| Enchantment | On | I / II / III |
|---|---|---|
| Efficiency | pickaxe | mining cooldown −2 s / −4 s / −6 s (never below the minimum) |
| Fortune | pickaxe, shovel, axe, hoe | +1 / +2 / +3 blocks (pickaxe), gravel (shovel), sticks (axe); +5% / +10% / +15% XP (hoe) |
| Unbreaking | all gear | 25% / 40% / 50% chance a use costs no durability |
| Sharpness | sword | +1 / +2 / +3 damage (duels, bosses, tournament) |
| Looting | sword | +10% / +20% / +30% boss reward |
| Protection | armor | +1 / +2 / +3 armor points per piece |

### ⭐ XP & talents

- `/xp`, `/talents`, `/talent_buy <branch> [points]`
- XP comes from activity; 1 talent point every 5 levels.
- Branches (each has a cap): **Miner** (better blocks), **Trader** (sell bonus), **Lucky** (bedrock chance), **Efficiency** (shorter cooldown).
- Level-ups are announced, and configurable **level roles** are given automatically.

### 🤝 Trading

- `/pay <member> <amount>` — Send emeralds
- `/trade <member> <give> [give_amount] [get] [get_amount]` — Trade or gift emeralds, blocks, sticks, ingots or gear. The other player accepts with a button.
- `/auction sell | browse | buy | cancel | mine` — Player auction house: 5% tax, 10 listings per player, unsold items come back after 7 days.

### 🏆 Competition

- `/leaderboard [board]` — Rankings by emeralds, level, total fortune, this week's season, blocks mined, bedrock, crafts, duels won, boss damage, achievements.
- `/profile [member]` — Public profile: level, fortune and rank, team, equipment, achievements, stats, linked account, champion badge.
- **Weekly seasons** (`/season`) — The score is the value you *created* during the week (Monday to Sunday): the value of the blocks you mine (counted when mined, not when sold), daily rewards, drops, bosses, challenges, the server share of the tournament pot, and the trader/villager bonus when you sell. Spending doesn't lower it; emeralds or blocks received from other players, duel pots and auction sales don't count. At the end of the week, the top 3 get emeralds and the winner gets the **champion role** until the next season ends.
- `/duel <member> <stake>` — Both players bet the same stake and the winner takes it all. The fight is played **turn by turn** in the message: on your turn you can drink a potion (its effect shows right away), then click **Attack**, in the same turn. You have 30 s per turn, then the bot attacks for you; after 2 missed turns in a row the rest of the duel is played automatically. Damage comes from the sword, armor reduces it, with random variance and critical hits. If the bot restarts during a duel, both stakes are refunded.
- **Potions** (`/potions`) — Duels only (not the tournament, not bosses): one potion per turn, up to 3 per duel, the effect is for that turn. Found in drops (a witch's stash: 2 potions) and on bosses (the top 3 damage dealers get one); reinforced potions (II, effect doubled) are sold by the villager. They can be traded and sold at auction.

  | Potion | Effect |
  |---|---|
  | Strength | this turn's attack +50% |
  | Speed | 1 chance in 5 to strike twice, this turn and your next 2 turns |
  | Healing | heals 6 HP (max 20) |
  | Harming | 4 direct damage to the opponent, ignoring armor (on top of your attack) |
- `/challenges` — 3 weekly challenges, the same for everyone.
- `/achievements [member]` — 28 achievements with emerald rewards, announced publicly.
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
  - ✨ an exclusive: a **level III book** or a **reinforced potion (II)**, whose effect is doubled (Strength +100%, Speed 40%, Healing 12 HP, Harming 8). Reinforced potions are only sold by the villager.
- Each offer exists **once**: the first player to click gets it. The buttons keep working after a restart, and the message shows who took what.
- `/villager` shows whether he is here and when he comes next.

### 🛡️ Teams

- `/team create <name> <tag>` — Anyone can create a team (name 3–24 characters, tag 2–4 letters or numbers) and becomes its leader. Up to 5 members.
- `/team invite <member>` — The leader invites a player, who answers with the buttons (they still work after a restart) or later with `/team join <tag>`. Invitations last 48h.
- `/team leave` — Leave the team. When the leader leaves, the oldest member becomes leader; the last one to leave disbands the team.
- Leader: `/team kick`, `/team transfer`, `/team rename [name] [tag]`, `/team disband`.
- `/team info [team]` — Members, what each one earned for the team this week, team rank, today's bonus.
- **Team tag** — `[ABC]` is shown in `/profile`, `/leaderboard` and `/season`.
- **Team bonus** — Mining XP +5% for each teammate who already mined today (up to +20%).
- **Weekly team season** (`/team top`) — A team's score is the season score (see above) its members made while in the team (Monday to Sunday). The top 3 teams win 600 / 300 / 150 emeralds, shared between the players in proportion to what each one earned for the team (players who left during the week keep their share). Results are announced with the season results.

### 🔐 Staff commands

Restricted to the staff role (or members with the *Manage Server* permission). **Every staff command is logged in the staff channel** (who, which command, which options).

- Moderation (the member gets a DM with the reason; everything is logged in the staff channel):
  - `/warn <member> <reason>` — warnings count for 30 days; 3 warnings = automatic 1h mute, 5 = 1 day, 7 = 7 days. `/unwarn <#>` removes one, `/clearwarns` removes them all.
  - `/history <member>` — warnings, mutes, kicks and bans, with their numbers.
  - `/mute <member> <duration> <reason>` (e.g. `30m`, `2h`, `3d`, `1w`, `perm`) and `/unmute`. Mutes use Discord timeouts; the bot renews them past Discord's 28-day limit (permanent mutes) and re-applies them if the member leaves and comes back.
  - `/kick`, `/ban <member> <reason> [duration] [delete_messages]` (permanent by default; temporary bans are lifted automatically) and `/unban <user_id>`.
  - `/clear <amount> [member]` (pinned messages are kept), `/lock` / `/unlock` (staff can still write), `/slowmode <seconds>`.
  - Members above the moderator or the bot, staff members and the owner can't be sanctioned. The bot needs the *Moderate Members*, *Kick*, *Ban*, *Manage Messages*, *Manage Channels* and *Manage Roles* permissions (`/lock` edits channel permissions; it keeps the bot and the staff role able to write, and `/unlock` puts back exactly the permissions the channel had).
- Whitelist: `/add_whitelist`, `/remove_whitelist`, `/check_whitelist`, `/unlink`
- Economy: `/add_block`, `/add_emerald`, `/remove_emerald`, `/add_item` (sticks, ingots, lapis), `/add_gear`, `/remove_gear`, `/add_book`, `/add_potion [level]`
- XP: `/xp_add`, `/xp_set`, `/level_set`, `/talent_add`, `/talent_reset` (refunds points), `/sync_level_roles`
- Events: `/boss_spawn [name] [hp]`, `/drop_spawn`
- Teams: `/team_remove <team>` deletes a team (offensive name…), logged in the staff channel
- Villager: `/villager_admin` makes him come now (for the usual visit length) or leave
- Tournament: `/tournament_admin` opens registrations now, runs the next step now (draw, then the next round) or cancels and refunds. Handy to test without waiting for the weekend.
- Settings: `/config` opens menus to change channels, roles (pick them from the Discord list), level roles, market prices, block values, gameplay numbers, team settings and the /ip and /modpacks texts. Values are checked before being saved (an invalid one is refused with the reason). Changes apply immediately, the previous `config.json` is copied to the backups folder and every change is logged in the staff channel. The RCON password, staff role and database path can't be seen or changed from Discord.
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
| `guild_id` | ID of your Discord server (slash commands are synced instantly to it) |
| `staff.role_id` | ID of the staff role allowed to use staff commands |
| `channels.announcements` | Channel for level-ups, achievements, challenges, season results (empty = no announcements) |
| `channels.events` | Channel for drops and bosses (empty = drops appear where people chat) |
| `channels.staff_log` | Staff channel receiving `/link` requests (required for `/link`) |
| `roles.level_roles` | `{"level": role_id}`, e.g. `{"10": 123, "25": 456}`. Members keep the highest role reached. |
| `roles.season_champion` | Role given to the winner of the last weekly season |
| `roles.tournament_champion` | Role given to the winner of the last weekend tournament |
| `roles.event_ping` | Role pinged when a boss appears (0 = no ping). Nobody else is pinged. |
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

The `balance` section is checked when the bot starts and on `/reload_config`: an unknown key (typo), a wrong type, an invalid time zone or an incoherent schedule is reported. At startup the invalid values are ignored (logged as warnings); `/reload_config` refuses the whole file and keeps the current settings.

Every number of the game (rewards, prices, durability, cooldowns, boss HP, tax, timezone…) has a default in [`game/settings.py`](game/settings.py). To change one, copy its path under `balance` in `config.json`, for example:

```json
"balance": {
  "timezone": "Europe/Paris",
  "mining": { "cooldown_seconds": 20 },
  "daily": { "base_reward": 50 },
  "boss": { "auto_spawn_hours": 48, "hp": 2000 }
}
```

`balance.boss.auto_spawn_hours` spawns a boss automatically that many hours after the previous one ended (0 = only `/boss_spawn`).

Enchanting is tuned with `balance.enchants`: `lapis_chance`, `lapis_amount`, `apply_cost`, `book_weights`, `boss_book_weights`, `challenges_book`, the effects (`efficiency_seconds`, `fortune_bonus`, `fortune_hoe_xp`, `unbreaking_chance`, `sharpness_damage`, `looting_boss_bonus`, `protection_points`) and the reference values `lapis_value` / `book_values`.

Duels and potions are tuned with `balance.duel` (`turn_seconds`, `afk_turns`, `hp`, `min_stake`…) and `balance.potions`: `max_per_duel`, `strength_bonus`, `speed_chance`, `speed_turns`, `healing_hp`, `harming_damage`, `boss_top` and the reference `value`.

Moderation is tuned with `balance.moderation`: `warn_expire_days` (0 = warnings never expire) and `warn_mutes`, e.g. `{"3": "1h", "5": "1d", "7": "7d"}` (automatic mute when a member reaches that many warnings).

The villager is tuned with `balance.villager`: `arrive_hour`, `leave_hour`, `sell_discount`, `buy_bonus`, `goods` (what he can sell), `buys` (blocks he buys and how many), `book_iii_price` and `potion_ii_price`. Reinforced potions use `balance.potions.level2_multiplier` and `value_ii`.

The tournament is tuned with `balance.tournament`: `entry_fee`, `house_bonus`, `min_players`, `max_players`, the schedule (`opens_day`/`opens_hour`, `closes_day`/`closes_hour`, `start_day`/`start_hour`, days 0 = Monday … 6 = Sunday), `round_minutes`, `prize_split` (`[60, 25, 15]`) and `xp_per_win`.

Teams are tuned with `balance.teams`: `max_members`, `create_cost` (emeralds, 0 = free), `invite_hours`, `xp_bonus_per_active_member`, `max_xp_bonus` and `season_rewards` (e.g. `[600, 300, 150]`).

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
├── leaderboard.py · seasons.py · duel.py
├── teams.py                 # teams, team bonus and weekly team season
├── tournament.py            # weekend tournament
├── enchants.py              # enchanted books, lapis and enchantment effects
├── potions.py               # duel potions
├── villager.py              # the wandering villager
├── moderation.py            # warnings, mutes, kicks and bans (records and timers)
├── progress.py              # achievements and weekly challenges
├── events.py                # drops and bosses
└── links.py                 # Discord <-> Minecraft links
cogs/                        # slash commands, one file per feature
utils/                       # config, checks, announcer, RCON, Mojang, UI helpers
tests/                       # unit tests
```

Generated at runtime (not versioned): `.env`, `config.json`, `economy.db`.
