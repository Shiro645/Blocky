---
name: blocky-balance
description: How to rebalance numbers in the Blocky bot (prices, rewards, odds, damage, HP, durability, costs) with simulations and a before/after table the owner validates. Use it whenever the owner says something is too strong, too weak, too expensive, not worth it or unprofitable, or asks to change values or to check that something is balanced.
---

# Blocky balance

The owner decides the numbers. Your job is to show the consequences clearly.

1. **Read the current values** from `game/settings.py`, and the code that uses them. Don't trust old texts.
2. **Pick a yardstick** the owner understands:
   - emeralds per mining reward (about 5.2 in the overworld, ×1.25 / 1.5 / 1.75 / 2 in later dimensions);
   - about 100 mining rewards a day for an active player;
   - win rates by gear (none / gold / iron / diamond / netherite);
   - the cost in days of play.
3. **Simulate.** Use a short script in the scratchpad that calls the real engine (`game/pve.fight_wave`, `duel.simulate`, `gate.Fight.auto_play`, `mining.roll_blocks`…) with `settings.load(overrides)`. Use a few thousand runs and a fixed seed.
4. **Propose** a French table (current → proposed → effect), and say which ones are judgment calls.
5. **Apply after "go".** Edit the defaults and their comments, keeping the calibration in the comment ("calibrated so that…").
   - Tests that relied on old numbers: add the old values to `LEGACY_ECONOMY` rather than rewriting the tests.
   - Add a test of the new defaults.
   - Update texts that state numbers by hand (README, wiki, help). Most help numbers already come from the settings.
6. **Remind** the owner that values changed by hand in /config override the new defaults.
