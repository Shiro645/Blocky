---
name: blocky-audit
description: How to audit the Blocky bot for incoherences, i.e. goals players can't reach, numbers that no longer fit the economy, texts that contradict the code, settings or stats that are never used. Use it whenever the owner asks to look for other problems "comme celle-ci", to check the project's coherence, or after a big rework.
---

# Blocky audit

Delegate the read-heavy sweep to one Explore agent (it keeps file dumps out of the main context). Give it the
recent changes and this checklist, and ask for a report grouped by severity with file:line and a one-line fix.

## Checklist
1. **Impossible goals**:
   - challenges (`game/progress.py` + settings `challenges`), biome challenges, guide steps, achievements, titles, frames, prestige conditions;
   - for a new player in the overworld, and with each optional game switched off.
2. **Economy fit**:
   - rewards, costs and odds against ingot prices and income per day;
   - repair vs craft cost, gear wear vs PvE rewards;
   - Beacon, villager, drops.
3. **Stale texts**:
   - /help, wiki, README, guide, `utils/config_edit.py` help, cog messages, settings comments;
   - all against the code (channels, routing, prices, durability, who gets what).
   - Skip `utils/updates.py`, which is history.
4. **Broken links**:
   - stats used but never bumped, challenge codes without a stat;
   - settings never read, config fields pointing to missing settings;
   - commands without a /help page or channel;
   - items without an emoji name.

Then present the findings to the owner in French: fix the texts directly, and ask (AskUserQuestion) for every decision about numbers or design. Use blocky-balance for numbers.
