---
name: blocky-map
description: Architecture map of the Blocky Discord bot repo, i.e. which file does what. Use it before reading code whenever you need to find where a feature, command, setting, table or text lives in Blocky, so you open the right file directly instead of searching the whole repo.
---

# Blocky map

Read the line for the feature, open that file, and stop there. Every number lives in `game/settings.py`.
Numbers shown to players come from it through `utils/manual.py` (/help) and `utils/wiki.py`.

## Layers
- `game/`: the rules, with no Discord import. A function takes a `Ctx` first and is run through
  `await bot.db.run(fn, …)`. Each call is one transaction. The `Ctx` gives `ctx.now`, `ctx.rng`, `ctx.today`,
  `ctx.week_id`, `ctx.one/all/execute` and `ctx.notices`.
- `cogs/`: slash commands, views and buttons. Buttons are `DynamicItem`s with `blocky:<feature>:…` ids, so
  they survive restarts. Loops are `tasks.loop`.
- `utils/`: Discord helpers, docs and config editing.
- `bot.py`: startup, the EXTENSIONS list (every cog), the central command check (bans, then
  `utils/routing.py`), and the config migration.
- `tests/`: unittest, no discord. `tools/`: the checks (`python3 tools/check_all.py`).

## Where things are
| Topic | Rules | Commands / views |
|---|---|---|
| Settings and validation | game/settings.py (DEFAULTS, `_cross_checks`, `_RETIRED`) | cogs/admin_config.py + utils/config_edit.py (fields) |
| DB schema | game/db.py MIGRATIONS (append only) | |
| Players, stats, XP | game/players.py | cogs/economy_xp.py |
| Mining, dimensions, ores, /portal | game/mining.py, game/dimensions.py | cogs/economy_mining.py, cogs/player_dimensions.py |
| Market, crafting, repair | game/shop.py, game/anvil.py, game/gear.py | cogs/economy_market.py, cogs/economy_craft.py |
| Enchants, enchanting table | game/enchants.py, game/enchanting_table.py | cogs/economy_enchant.py |
| Trading, auction | game/exchange.py, game/assets.py | cogs/economy_exchange.py, cogs/economy_auction.py |
| Daily, loans | game/daily.py, game/loans.py | cogs/economy_daily.py, cogs/economy_loans.py |
| Duels, dummy, tournament | game/duel.py, game/dummy.py, game/tournament.py | cogs/competition_duel.py, games_dummy.py, events_tournament.py |
| Dungeon, night | game/pve.py, game/night.py | cogs/games_pve.py, cogs/events_night.py |
| Gate bosses, Beacon | game/gate.py, game/beacon.py | cogs/games_boss.py, cogs/player_beacon.py |
| Teams, war, raids | game/teams.py, game/war.py, game/raid_fight.py | cogs/competition_teams.py, competition_war.py |
| Games of chance | game/gambling.py, luckyblock.py, roulette.py, blackjack.py, mines.py | cogs/games_*.py |
| Quiz, Blockdle, rob, bounty | game/quiz.py, blockdle.py, robbery.py, bounty.py | cogs/games_quiz.py, games_blockdle.py, games_rob.py, competition_bounty.py |
| Achievements, challenges | game/progress.py | cogs/events_progress.py |
| Seasons, leaderboard | game/seasons.py, game/leaderboard.py | cogs/competition_seasons.py, competition_leaderboard.py |
| Species, prestige, profile | game/species.py, prestige.py, profiles.py | cogs/player_species.py, player_prestige.py, player_profile.py (utils/profile_card.py) |
| Biomes, live events, drops, villager | game/biomes.py, live_events.py, events.py, villager.py | cogs/events_biomes.py, events_live.py, events_drops.py, events_villager.py |
| Guide | game/guide.py | cogs/player_guide.py |
| Staff | game/reset.py, rewind*.py, cooldowns.py, restrictions.py, moderation.py | cogs/staff_*.py, admin_*.py |
| Minecraft link, RCON | game/links.py | cogs/minecraft_*.py, utils/minecraft_rcon.py |

## Docs and texts
- utils/manual.py: one /help Page per command. Its numbers are functions of the settings.
- utils/wiki.py: wiki sections, with every player command mentioned.
- utils/updates.py: the update announcements, append only.
- utils/emojis.py: the emoji names the bot expects. utils/announcer.py: the `on_<Notice>` messages for the notices in game/notices.py.
- README.md: kept short (setup and an overview); no balance numbers.
