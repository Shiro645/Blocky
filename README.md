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
- `/profile [member]` — Public profile: level, fortune and rank, equipment, achievements, stats, linked account, champion badge.
- **Weekly seasons** (`/season`) — The score is the emeralds *earned* during the week (Monday to Sunday). Spending doesn't lower it, and emeralds received from other players don't count. At the end of the week, the top 3 get emeralds and the winner gets the **champion role** until the next season ends.
- `/duel <member> <stake>` — Both players bet the same stake and the winner takes it all. The fight is turn based: sword damage, armor reduction, random variance and critical hits.
- `/challenges` — 3 weekly challenges, the same for everyone.
- `/achievements [member]` — 26 achievements with emerald rewards, announced publicly.
- **Random drops** — Activity sometimes makes a drop appear (emeralds, ingots, bedrock). The first player to click gets it.
- **Server bosses** (`/boss`, `/attack` or the button) — A boss with shared HP. Everyone attacks once a minute, rewards are shared by damage dealt, and the top damage dealer gets a bonus. A boss escapes after 24h.

### 🔐 Staff commands

Restricted to the staff role (or members with the *Manage Server* permission).

- Whitelist: `/add_whitelist`, `/remove_whitelist`, `/check_whitelist`, `/unlink`
- Economy: `/add_block`, `/add_emerald`, `/remove_emerald`, `/add_item`, `/add_gear`, `/remove_gear`
- XP: `/xp_add`, `/xp_set`, `/level_set`, `/talent_add`, `/talent_reset` (refunds points), `/sync_level_roles`
- Events: `/boss_spawn [name] [hp]`, `/drop_spawn`
- Server: `/mc <command>` runs a Minecraft console command through RCON (dangerous commands such as `stop`, `op`, `whitelist off` are blocked; every use is logged in the staff channel), `/reload_config` applies `config.json` changes without restarting, `/backup_now` saves a copy of the database

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
| `gold`, `iron`, `diamond`, `netherite` | Ingots / materials |
| `cobblestone`, `gravel`, `deepslate`, `obsidian`, `bedrock` | Blocks |
| `<material>_<item>`, e.g. `iron_sword`, `gold_helmet`, `netherite_boots` | Gear (4 materials × sword, pickaxe, axe, shovel, hoe, helmet, chestplate, leggings, boots) |

At startup the logs show how many were found and list the missing names. A missing emoji is simply not shown (blocks fall back to 🪨 🟫 ⬛ 🟪, gear to its material).

To use another emoji for a name, set it in `config.json`, e.g. `"emojis": {"emerald": "<:my_emerald:123456789012345678>"}` (send `\:emoji_name:` in Discord to get the code).

After editing `config.json`, run `/reload_config` (or restart the bot). Changing `database_path` or `guild_id` needs a restart.

### Backups

Every night at 04:00 (config timezone) the bot copies the database to a `backups/` folder next to it (`bot/db/backups/` with Docker) and keeps the last 7 copies. Change it with `"balance": {"backups": {"hour": 4, "keep": 7}}`. `/backup_now` makes an extra copy at any time.

To restore one: stop the bot, replace `economy.db` with the backup (and delete `economy.db-wal` / `economy.db-shm`), start the bot.

### Game balance

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

> ⚠️ `.env`, `config.json` and `economy.db` contain secrets or user data. They are ignored by git — never commit them.

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
├── progress.py              # achievements and weekly challenges
├── events.py                # drops and bosses
└── links.py                 # Discord <-> Minecraft links
cogs/                        # slash commands, one file per feature
utils/                       # config, checks, announcer, RCON, Mojang, UI helpers
tests/                       # unit tests
```

Generated at runtime (not versioned): `.env`, `config.json`, `economy.db`.
