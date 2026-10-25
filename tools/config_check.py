"""Build every /config screen with discord.py (never logged in) and save a few values for real."""
import sys

import _env
import asyncio, os, types, json
_env.workdir()
import discord
import bot as botmod
from game import settings
from utils import config_edit as ce
from cogs import admin_config as ac

problems = []
def check_embed(e, where):
    d = e.to_dict(); total = len(d.get("title", "")) + len(d.get("description", "") or "")
    if len(d.get("description", "") or "") > 4096: problems.append(f"{where}: description")
    for f in d.get("fields", []):
        total += len(f["name"]) + len(f["value"])
        if not f["value"] or len(f["value"]) > 1024: problems.append(f"{where}: field {f['name']}")
    if total > 6000: problems.append(f"{where}: total {total}")

def check_view(v, where):
    rows = {}
    for item in v.children:
        rows.setdefault(item.row, []).append(item)
        if isinstance(item, discord.ui.Select) and not isinstance(item, (discord.ui.ChannelSelect, discord.ui.RoleSelect)):
            if not 1 <= len(item.options) <= 25: problems.append(f"{where}: {len(item.options)} options")
            for o in item.options:
                if len(o.label) > 100 or (o.description and len(o.description) > 100): problems.append(f"{where}: option too long {o.label}")
    for row, items in rows.items():
        width = sum(5 if isinstance(i, discord.ui.Select) else 1 for i in items)
        if width > 5: problems.append(f"{where}: row {row} too wide ({width})")

def check_modal(m, where):
    if len(m.title) > 45: problems.append(f"{where}: modal title {m.title!r}")
    for c in m.children:
        if len(c.label) > 45: problems.append(f"{where}: input label {c.label!r}")
        if c.placeholder and len(c.placeholder) > 100: problems.append(f"{where}: placeholder")
        if c.default and c.max_length and len(c.default) > c.max_length: problems.append(f"{where}: default too long")

class User:
    id = 1; mention = "<@1>"
    def __str__(self): return "staff#0001"

async def main():
    b = botmod.Bot()
    await b.__aenter__()
    await b.db.open()
    await b.load_extension("cogs.admin_config")
    cog = b.get_cog("ConfigCog")
    screens = 0
    check_view(ac.ConfigView(cog, 1, ac.Screen()), "home"); check_embed(cog.home_embed(), "home")
    for cat in ce.CATEGORIES:
        n = len(ce.fields_in(cat)); pages = max(1, -(-n // 25))
        for p in range(pages):
            check_embed(cog.category_embed(cat, p), f"{cat} p{p}")
            check_view(ac.ConfigView(cog, 1, ac.Screen(category=cat, page=p)), f"{cat} p{p}"); screens += 1
    for f in ce.FIELDS:
        v = ac.ConfigView(cog, 1, ac.Screen(category=f.category, field=f.key))
        check_view(v, f.key); check_embed(cog.field_embed(f, "✅ note"), f.key); screens += 1
        if f.typed: check_modal(ac.ValueModal(v), f.key)
        if f.kind == "table":
            check_view(ac.ConfigView(cog, 1, ac.Screen(category=f.category, field=f.key, mode="add")), f.key + " add")
            for kind, _ in (ce.DROP_REWARDS if f.item == "drops" else ce.GOODS):
                check_modal(ac.LineModal(v, None, kind), f"{f.key} new {kind}")
            check_modal(ac.LineModal(v, 0), f"{f.key} line 0")
        if f.kind == "list":
            check_modal(ac.ListItemModal(v, 0), f.key); check_modal(ac.ListItemModal(v, None), f.key)
    print("screens checked:", screens)

    user = User()
    F = ce.FIELDS_BY_KEY
    print(await cog.save(user, F["mining.cooldown_seconds"], 20))
    print(await cog.save(user, F["gear.shield_wear_per_block"], 20))
    print(await cog.save(user, F["enchants.apply_cost.2"], 9))
    print(await cog.save(user, F["villager.buys.cobblestone"], 128))
    print(await cog.save(user, F["enchants.challenges_book"], False))
    print(await cog.save(user, F["tournament.opens_day"], 3))
    print(await cog.save_whole(user, F["seasons.rewards"], [300, 150, 75, 30], "added 30"))
    print(await cog.save_whole(user, F["moderation.warn_mutes"], {"3": "2h", "6": "perm"}, "rules"))
    table = list(settings.get()["drops"]["table"]) + [{"weight": 5, "title": "Test", "reward": ce.drop_reward("potions", 3)}]
    print(await cog.save_whole(user, F["drops.table"], table, "added Test"))
    try:
        await cog.save(user, F["tournament.closes_day"], 0)
    except Exception as e:
        print("refused as expected:", str(e).splitlines()[0])
    print(await cog.save(user, F["mining.cooldown_seconds"], None))
    cfg = json.load(open("config.json"))
    print(json.dumps(cfg.get("balance"), indent=None)[:600])
    s = settings.get()
    assert s["gear"]["shield_wear_per_block"] == 20 and s["enchants"]["apply_cost"][:3] == [2, 4, 9]
    assert s["villager"]["buys"]["cobblestone"] == 128 and s["seasons"]["rewards"] == [300, 150, 75, 30]
    assert s["moderation"]["warn_mutes"] == {"3": "2h", "6": "perm"} and s["mining"]["cooldown_seconds"] == 30
    check_embed(cog.field_embed(F["drops.table"]), "table after"); check_embed(cog.category_embed("villager"), "villager after")
    print("\nPROBLEMS:" if problems else "\nno problem", *problems[:30], sep="\n")
    if problems:
        sys.exit(1)

asyncio.run(main())
