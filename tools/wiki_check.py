"""Render every wiki message and check Discord's limits (--long-emojis: as if every emoji were custom)."""
import sys

import _env

_env.workdir()
import types; from collections import defaultdict
from utils import ui
long = "<:emoji_name_xx:123456789012345678>"
if "--long-emojis" in sys.argv:  # custom emojis take ~40 characters each
    ui.EMOJI.default_factory = lambda: long
    for k in list(ui.EMOJI): ui.EMOJI[k] = long
from game import settings; settings.load(None)
from cogs import info_wiki
problems = []
parts = info_wiki.body(settings.get())
for key, embeds in parts:
    tot = sum(len(e) for e in embeds)
    if len(embeds) > 10 or tot > 6000: problems.append((key, "message", len(embeds), tot))
    for e in embeds:
        d = e.to_dict()
        if len(d.get("title", "")) > 256 or len(d.get("description", "")) > 4096: problems.append((key, "title/desc"))
        if len(d.get("fields", [])) > 25: problems.append((key, "fields"))
        for f in d.get("fields", []):
            if not f["value"] or len(f["value"]) > 1024 or len(f["name"]) > 256: problems.append((key, f["name"], len(f["value"])))
print(len(parts), "messages;", "problems:", problems or "none")
print([(k, sum(len(e) for e in em)) for k, em in parts])
if problems:
    sys.exit(1)
