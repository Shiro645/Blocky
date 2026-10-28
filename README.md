# 🧱 Blocky

A modular Discord bot built for a modded Minecraft server community.

It connects to the Minecraft server through **RCON** to manage the whitelist, shows the server status, and runs a Minecraft-themed economy and competition system directly in Discord.

> **The numbers live in the game.** Prices, rewards, odds and timers come from `game/settings.py` (overridable in `config.json` or from Discord with `/config`). Players read them, always up to date, in **`/help`** (one page per command) and in the **wiki channel**. This README doesn't repeat them.

---

## 🚀 Features

- **Mining by chatting** in the mining channel, in the dimension you are in: Overworld → Nether → End → Deep Dark → Shimmer (`/portal`, `/dimensions`), with ores that add up from one dimension to the next.
- **Economy**: `/sell`, `/market`, `/daily` with a streak, `/pay`, `/trade`, the auction house (`/auction`, with a market channel board), loans (`/loan`).
- **Gear**: `/craft` tools, weapons, armor and the shield; the anvil and `/repair`; netherite from the Nether.
- **Enchanting**: books (I–VII), `/enchant apply` / `combine`, the enchanting table (`/enchant table`, with curses); combat enchantments (Fire Aspect, Thorns, Sweeping Edge).
- **Progress**: XP and talents, achievements, daily and weekly challenges, species, prestige, profile cards (`/profile`, `/customize`), titles and frames.
- **Fights**: duels with potions and shields, the training dummy, the weekend tournament, the PVE dungeon (`/dungeon`), night monsters (`/time`, `/sleep`, `/wake`), gate bosses (`/boss`) that open the next dimension, the server's Beacon.
- **Teams**: teams and team seasons, team spaces, team chests with bonuses and defenses, the weekly gang war and turn-based raids, bounties.
- **Games**: the casino (Lucky Block, the wheel, blackjack, mines), Blockdle, the Minecraft quiz, robberies (`/rob`).
- **Events**: random drops, the wandering villager, timed events (Gambling Frenzy, Mining Rush…), the biome of the week, weekly seasons.
- **Server**: Minecraft status, account linking and whitelist through RCON, a private guide channel for new players, an updates channel, a wiki channel.
- **Staff**: `/config` (almost every setting from Discord), `/give` / `/take`, `/reset`, moderation (warn, mute, kick, ban, clear, lock), `/blocky ban`, backups, `/bot_update`. Every staff action is logged in the staff channel.

### 🗂️ Where commands work
Each player command works in its own channel, set in `/config` → Channels:
- 🎰 the **casino** (`channels.casino`): the games of chance;
- 🌀 the **portal** (`channels.portal`): `/dungeon`, `/boss`, `/portal`, `/dimensions`;
- 💬 the **commands** channel (`channels.commands`): everything else (`/rob` too; the robbery the bot posts goes to `channels.robberies`).

Staff commands, `/help` and the guide channels work everywhere. A channel that isn't set lets its commands work anywhere. Typed in the wrong place, a command answers where it goes.

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
| `channels.robberies` | Robberies channel: every robbery is posted there with its *Stop the thief!* button (0 = where `/rob` is used; `/rob` itself is typed in the commands channel) |
| `channels.market` | Market channel: the bot keeps two messages there, always up to date: the market (fixed prices) then every auction listing, each with a menu to buy |
| `channels.casino` | Casino channels: `/luckyblock`, `/wheel`, `/blackjack` and `/mines` only work there (empty = anywhere). The old `channels.games` is moved here at the first start |
| `channels.portal` | Portal channels: `/dungeon`, `/boss`, `/portal` and `/dimensions` only work there (empty = anywhere) |
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
| `roles.event_ping` | Role pinged when a timed event starts, the wandering villager arrives or a tournament opens (0 = no ping). Nobody else is pinged. |
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
| `anvil`, `enchanting_table` | The anvil and the enchanting table (fallbacks 🔨 and 🪄) |
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

Every setting has its own field in `/config`, with its help text: that's the place to read what each one does.

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

# 🧪 Tests and checks

The game logic (`game/`) doesn't depend on Discord and is covered by unit tests. Before every push, run:

```bash
python3 tools/check_all.py
```

It runs the tests, then renders every `/help` screen, every `/config` screen and the wiki against Discord's limits (see `tools/README.md`). The tests also check that every slash command has a `/help` page and a wiki mention, and that every setting has a `/config` field.

---

# 🏗️ Project Structure

```
bot.py            # entry point: database, announcer, cogs, the channel of each command
game/             # game rules, no Discord code (settings.py: every number; db.py: SQLite + migrations)
cogs/             # slash commands, one file per feature
utils/            # config, /config fields, /help manual, wiki, updates, emojis, routing, RCON, UI helpers
tools/            # checks run before a push
tests/            # unit tests
updater/          # the updater container: git pull + rebuild, asked by /bot_update
CLAUDE.md, .claude/skills/   # how the project is worked on with Claude Code
```
