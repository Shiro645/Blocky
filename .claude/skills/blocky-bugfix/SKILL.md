---
name: blocky-bugfix
description: How to handle a bug the owner or players report in the Blocky bot (an error message, a button that does nothing, something impossible, a wrong number). Use it whenever the owner describes something broken, strange or "ça marche pas", including pasted logs or Discord error texts.
---

# Blocky bugfix

1. **Find the exact message** in the code (grep the quoted text). Read the paths that raise it.
2. **Find the real cause**, not the first plausible one. The owner knows what players saw: if they correct your guess, believe them and look again. Common causes in this bot:
   - Discord's 3-second interaction limit on a slow NAS (defer first, then edit; fall back to editing the message through the channel);
   - a stale message whose buttons carry an old state;
   - a channel config that silently refuses (routing, mining channel);
   - a setting at an unusual value;
   - an old config.json key.
3. **Explain in French**: what players see, why, and the fix you propose. Wait for the go unless the owner already said to fix it.
4. **Fix with a test** that reproduces the bug (mock what's random, e.g. `mock.patch.object(pve, "fight_wave", …)`). Run `python3 tools/check_all.py`.
5. **Ship** a small PR (blocky-feature, step 6) and give the link with a two-line summary.
