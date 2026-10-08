# 🧱 Blocky

A modular Discord bot built for a modded Minecraft server community.

It connects to the Minecraft server through **RCON** to manage the whitelist, shows the server status, and runs a fully integrated Minecraft-themed economy system directly in Discord.

---

## 🚀 Features

### 🌍 Minecraft Commands (@everyone)

- `/server_status` — Show server status (players & ping)
- `/ip` — Show join instructions
- `/modpacks` — Show modpack information
- `/help` — List the available commands

### 🔐 Staff Commands

Restricted to the staff role (or members with the *Manage Server* permission).

**Whitelist** (sent to the server via RCON):

- `/add_whitelist <username>` — Add a player to the whitelist
- `/remove_whitelist <username>` — Remove a player from the whitelist
- `/check_whitelist` — Show the current whitelist

**Economy administration:**

- `/add_block`
- `/add_emerald`
- `/add_item`
- `/add_gear`
- `/xp_add`
- `/xp_set`
- `/level_set`
- `/talent_add`
- `/talent_reset`

---

# 💎 Economy System

A Minecraft-inspired progression system integrated directly into Discord.

## 🪨 Passive Block Mining

Users receive **1–6 random blocks** when sending messages.

Block distribution:
- 6 → Cobblestone
- 4–5 → Cobblestone / Gravel
- 2–3 → Cobblestone / Gravel / Deepslate
- 1 → Cobblestone / Gravel / Deepslate / rare Bedrock

The cooldown is configurable in `config.json` (`economy.cooldown_seconds`).

## 💰 Selling Blocks

`/sell` — Sell all your blocks.

Block values:
- Cobblestone → 1 emerald
- Gravel → 3 emeralds
- Deepslate → 5 emeralds
- Bedrock → 10 emeralds

## 🛒 Market System

`/market`

Buy:
- 4 sticks → 1 emerald
- Gold ingot → 5 emeralds
- Iron ingot → 10 emeralds
- Diamond ingot → 25 emeralds
- Netherite ingot → 100 emeralds

Interactive dropdown + quantity modal.

## 🛠 Crafting

- `/craft <item> <material>` — Craft a piece of gear
- `/craftlist` — Show all recipes

Items: sword, pickaxe, axe, shovel, hoe, helmet, chestplate, leggings, boots

Materials: gold, iron, diamond, netherite

Recipes follow Minecraft crafting logic.

## 🎒 Inventory

`/inventory`

Displays:
- Blocks
- Emerald balance
- Items
- Gear
- Estimated sell value

## ⭐ XP & Talents

- `/xp` — Show your level and XP
- `/talents` — Show the talent branches
- `/talent_buy <branch> <points>` — Spend talent points

Users gain XP through activity.
Talent points are earned every 5 levels.

Talent branches:
- Miner
- Trader
- Lucky
- Efficiency

---

# ⚙️ Configuration

### Discord

1. Create an application and a bot on the [Discord Developer Portal](https://discord.com/developers/applications).
2. In the **Bot** tab, enable the **Server Members Intent**.
3. Invite the bot to your server with the `bot` and `applications.commands` scopes.

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
| `minecraft.server_host` / `server_port` | Minecraft server address used by `/server_status` |
| `minecraft.public_ip_text` | Text shown by `/ip` |
| `minecraft.modpack_text` | Text shown by `/modpacks` |
| `minecraft.rcon_host` / `rcon_port` / `rcon_password` | RCON connection to the Minecraft server |
| `economy.cooldown_seconds` | Cooldown between two block rewards |
| `emojis.<name>` | Custom emojis used in the bot's messages (`emerald`, `stick`, `gold`, `iron`, `diamond`, `netherite`, `xp`) |

To copy an ID in Discord, enable *Developer Mode* (Settings → Advanced), then right-click the server or role → *Copy ID*.

To get an emoji's code, send `\:emoji_name:` in any Discord channel and copy the result (e.g. `<:emerald:123456789012345678>`). The bot must be a member of the server that hosts the emojis. Restart the bot after changing them.

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
    ├── config.json
    └── economy.db      # create it first (see below)
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
      - ./bot/economy.db:/app/economy.db
    depends_on:
      - minecraft
    restart: unless-stopped
```

Create the database file before the first start (otherwise Docker creates a directory instead):

```bash
touch bot/economy.db
docker compose up -d --build
```

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

# 🏗️ Project Structure

```
bot.py                  # entry point, loads the cogs
database.py             # SQLite economy database
config.example.json     # config template
.env.example            # environment template
cogs/
├── minecraft_core.py       # /server_status, /ip, /modpacks
├── minecraft_whitelist.py  # whitelist commands (RCON)
├── economy_phase1.py       # passive mining, /sell, /inventory
├── economy_market.py       # /market
├── economy_craft.py        # /craft
├── economy_craftlist.py    # /craftlist
├── economy_xp.py           # /xp, /talents, /talent_buy
├── economy_admin.py        # economy staff commands
├── economy_admin_xp.py     # XP staff commands
└── help_command.py         # /help
utils/
├── config.py               # config loading
└── minecraft_rcon.py       # RCON helper
```

Generated at runtime (not versioned): `.env`, `config.json`, `economy.db`.