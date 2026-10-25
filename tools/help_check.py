"""Load every cog in a bot that never logs in, then render every /help screen and check Discord's limits.

python3 tools/help_check.py [home] [page names…]   (home / page names: also print those screens)"""
import sys

import _env
import asyncio, os, types, json
WORK = _env.workdir()

import discord
from discord import app_commands
from discord.ext import commands
from game import settings
from game.db import Database
from utils.announcer import Announcer
from utils import manual

import importlib.util
spec = importlib.util.spec_from_file_location("botmod_ext", str(_env.ROOT / "bot.py"))
src = open(str(_env.ROOT / "bot.py")).read()
EXT = eval(src.split("EXTENSIONS = ", 1)[1].split("]", 1)[0] + "]")

problems = []
def check_embed(e: discord.Embed, where: str):
    d = e.to_dict()
    total = len(d.get("title", "")) + len(d.get("description", "")) + len(d.get("footer", {}).get("text", ""))
    if len(d.get("title", "")) > 256: problems.append(f"{where}: title too long")
    if len(d.get("description", "")) > 4096: problems.append(f"{where}: description too long")
    if len(d.get("fields", [])) > 25: problems.append(f"{where}: too many fields")
    for f in d.get("fields", []):
        total += len(f["name"]) + len(f["value"])
        if len(f["name"]) > 256 or len(f["value"]) > 1024 or not f["value"]: problems.append(f"{where}: field {f['name']} size {len(f['value'])}")
        if "…and" in f["value"]: problems.append(f"{where}: field {f['name']} was cut")
    if total > 6000: problems.append(f"{where}: embed total {total}")

def check_view(v: discord.ui.View, where: str):
    for item in v.children:
        if isinstance(item, discord.ui.Select):
            if not 1 <= len(item.options) <= 25: problems.append(f"{where}: {len(item.options)} options")
            for o in item.options:
                if len(o.label) > 100: problems.append(f"{where}: option label too long {o.label}")

async def main():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.__aenter__()
    settings.load()
    bot.db = Database(os.path.join(WORK, "sim.db")); await bot.db.open()
    bot.announcer = Announcer(bot)
    for ext in EXT:
        await bot.load_extension(ext)
    tree_names = sorted(c.qualified_name for c in bot.tree.walk_commands() if isinstance(c, app_commands.Command))
    page_names = sorted(p.name for p in manual.PAGES if not p.is_topic)
    print("tree:", len(tree_names), "pages:", len(page_names))
    if tree_names != page_names:
        problems.append(f"missing pages: {set(tree_names) - set(page_names)}; extra pages: {set(page_names) - set(tree_names)}")
    # Discord limits on the command payload itself.
    for c in bot.tree.get_commands():
        payload = c.to_dict(bot.tree)
        for sub in [payload] + [o for o in payload.get("options", []) if o.get("type") == 1]:
            if len(sub.get("description", "")) > 100: problems.append(f"/{sub['name']}: description > 100")
            for o in sub.get("options", []):
                if o.get("type") in (1, 2): continue
                if len(o.get("description", "")) > 100: problems.append(f"/{sub['name']} {o['name']}: option description > 100")
                if o.get("description") in ("…", ""): problems.append(f"/{sub['name']} {o['name']}: no option description")
    cog = bot.get_cog("HelpCog")
    for staff in (False, True):
        check_embed(cog.home_embed(staff), f"home staff={staff}")
        check_view(__import__("cogs.help_command", fromlist=["x"]).HelpView(cog, 1, staff), "home view")
    from cogs.help_command import HelpView
    for key in manual.CATEGORIES:
        check_embed(cog.category_embed(key), f"category {key}")
        check_view(HelpView(cog, 1, True, key), f"view {key}")
    for p in manual.PAGES:
        for staff in (False, True):
            if p.staff and not staff: continue
            check_embed(cog.page_embed(p, staff), f"page {p.name}")
        check_view(HelpView(cog, 1, True, p.category, p.name), f"view {p.name}")
    class FakeInteraction: user = object()
    choices = await cog.page_autocomplete(FakeInteraction(), "team")
    print("autocomplete 'team':", [c.name for c in choices][:4])
    if any(len(c.name) > 100 for c in choices): problems.append("autocomplete name > 100")
    staff_choices = await cog.page_autocomplete(FakeInteraction(), "")
    if any(manual.BY_NAME[c.value].staff for c in staff_choices): problems.append("staff page suggested to a player")
    if "home" in sys.argv:
        for e in (cog.home_embed(True), cog.category_embed("start"), cog.category_embed("staff_players")):
            d = e.to_dict(); print("\n=====", d["title"]); print(d.get("description", ""))
            for f in d.get("fields", []): print(f"--- {f['name']}\n{f['value']}")
    for name in [a for a in sys.argv[1:] if a != "home"]:
        e = cog.page_embed(manual.BY_NAME[name], True).to_dict()
        print("\n=====", e["title"]); print(e["description"])
        for f in e.get("fields", []): print(f"--- {f['name']}\n{f['value']}")
        print("(", e["footer"]["text"], ")")
    print("\nPROBLEMS:" if problems else "\nno problem", *problems, sep="\n")
    if problems:
        sys.exit(1)
    await bot.db.close() if hasattr(bot.db, "close") else None

asyncio.run(main())
