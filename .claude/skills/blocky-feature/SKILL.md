---
name: blocky-feature
description: The full workflow to add or rework a feature in the Blocky Discord bot, from the owner's idea to a merged-ready PR. Use it whenever the owner asks for something new or a change in how the game works (a new command, mechanic, item, event, rework), even if they describe it casually in French.
---

# Blocky feature

The owner writes in French, often in one quick message. They want to decide the design, then not re-explain anything.

1. **Understand.** Read only the files that matter (use blocky-map). Find what already exists that the idea touches.
2. **Ask.** Use AskUserQuestion: at most 4 questions per round, 2–4 options each, with the recommended one first. Ask only what changes the design. Pick obvious defaults yourself and say so.
3. **Plan with numbers.** In French, short. Give the mechanics, a before → after table when values change, the formulas, and the impact (income per day, win rates). Run a quick simulation for balance (blocky-balance). Wait for "go".
4. **Build.** Follow blocky-rules: settings, /config field, /help, wiki, routing, emojis, migration, notice, update entry.
5. **Test.** Write unit tests in `tests/` for the rules, and run `python3 tools/check_all.py`.
6. **Ship.** Commit in English, without model names, ending with the trailer the session gives. Push the session branch, then open a PR in French titled "x.y.z — …". Describe it with sections (Pourquoi / changements / tests / après le merge) and tables for numbers.
7. **Report.** Give the PR link and a short French summary of what changed for players. Say what the owner must do after the merge (`/bot_update`, a channel to set in /config, an emoji to upload).

If the previous PR on the branch is merged, `git merge --ff-only origin/main` first. Never reset a branch whose PR is still open.
