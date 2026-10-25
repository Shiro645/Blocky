---
name: blocky-rules
description: The small rules to follow every time you add or change anything in the Blocky bot (a block, item, setting, command, stat, table, text, notice). Use it whenever you create or fix code in Blocky, even a small change. These are the details that were forgotten before (missing emojis, missing /config fields, docs out of date) and that the owner expects without being reminded.
---

# Blocky rules

Go through the lines that match the change. Each one exists because forgetting it broke something or confused players.

## New block, item or piece of gear
- Add its emoji name in `utils/emojis.py` (EXPECTED_NAMES, plus a fallback emoji when there is one). Add it to the emoji table in README.md. Tell the owner the exact name to upload in the Developer Portal: the bot finds emojis by name, so a missing one silently shows nothing or the fallback.
- New block: `game/catalog.py` (BLOCK_TYPES, dimension blocks), its value in `block_values`, `/inventory`, the Blockdle data if relevant, and the villager's `buys` if he should buy it.
- New tradeable thing: `game/assets.py` (parse, describe, value, catalog for staff /give and /take). Netherite stays untradeable.

## New setting
- In `game/settings.py` DEFAULTS, with a comment saying what it does and what the numbers mean.
- A field in `utils/config_edit.py` for every leaf, with a label of at most 45 characters and a help text. A test fails otherwise.
- Cross-check impossible combinations in `_cross_checks`. Keys ending in `chance` are capped at 1 automatically.
- A float default makes the field a float. Use `1.0`, not `1`, when decimals are allowed.
- Renamed or removed setting: add its path to `_RETIRED` so an old config.json doesn't warn.

## New command
- A /help page in `utils/manual.py`, and a mention in `utils/wiki.py`. Tests fail otherwise.
- Its channel in `utils/routing.py`: casino, portal, or commands (the default).
- Description at most 100 characters. Staff commands use `@staff_only()`.

## Database, state, stats
- A new column or table is a new migration at the end of `game/db.py`. Never edit an old one.
- A new users column: think about `game/reset.py` (which part resets it) and `game/prestige.py`.
- A new stat used by an achievement, challenge, title or guide step must really be bumped (`players.bump_stat`).
- A challenge or achievement that depends on an optional game: `progress.available()` / `achievement_open()`. Nothing may be impossible for a player in the overworld or with that game switched off.

## Texts and messages
- English in the game. Discord limits: field 1024, description 4096, embed 6000, button label 80, select option 100.
- Announcements go through a notice (game/notices.py) and `utils/announcer.py`, not from game/.
- A player-visible change gets an entry at the end of `utils/updates.py`, in short, simple sentences.
- Never write a number in a text by hand when it comes from a setting. Read the setting, so the text follows /config.

## Before pushing
- `python3 tools/check_all.py`.
- Tests keep the old numbers through `LEGACY_ECONOMY` (tests/helpers.py). New balance gets its own tests with `legacy_economy = False`.
