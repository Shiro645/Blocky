# Blocky

Discord bot (discord.py + SQLite) for a Minecraft server. Runs in Docker on a UGREEN NAS
(`/volume1/docker/craftoria`, service `blocky`). After a merge, the owner runs `/bot_update`.

## Working with the owner
- Answer in French, short and clear, with tables for numbers. Code, comments, commits and the game's texts are
  in English.
- New feature or rework: ask first (AskUserQuestion), propose a plan with numbers, wait for "go" (skill
  blocky-feature). Balance: skill blocky-balance. Bug: explain the cause first (skill blocky-bugfix).
- Every change in the code follows skill blocky-rules (emojis, /config fields, /help, wiki, routing…).
  To find where something lives, use skill blocky-map before searching.
- Never show or repeat a secret (Discord token, RCON password, CurseForge key). The RCON password, the staff
  role and the database path are never visible or editable in /config; rcon_host/rcon_port have no field.
- Never touch or mention `/volume1/docker/discord-bots/Command-Block-Bot`: it doesn't exist anymore.

## Git and PRs
- Work on the branch the session gives; push with `git push -u origin <branch>`.
- After a PR is merged: check `origin/main` contains it, then `git merge --ff-only origin/main` and push.
  Never reset or force-push a branch whose PR is still open (it closes the PR).
- One PR per topic, title "x.y.z — …", body in French. No model name in commits or PRs.

## Checks
`python3 tools/check_all.py` before every push (tests, then /help, /config and the wiki against Discord's limits).

## Saving tokens
- Read only the files the task needs (blocky-map); prefer grep and line ranges over whole files.
- Delegate wide sweeps (audits, many text fixes) to a subagent so their reads stay out of the main context.
- The README has no balance numbers on purpose: /help and the wiki are generated from `game/settings.py`.

## Compacting the conversation
- When the conversation is summarized (automatically or with /compact), keep: the open PRs and their state,
  the decisions the owner made and the questions still waiting for them, the task in progress. Drop: file
  contents, test and check outputs, simulation logs (they can be read or run again).
- When the owner says a PR is merged and the conversation is already long, suggest in one line:
  `/compact garde l'état des PR ouvertes et les décisions en cours`.
