from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import beacon, settings
from utils.ui import em, join_lines, mat

log = logging.getLogger("beacon")

MATERIAL_CHOICES = [app_commands.Choice(name=m, value=m) for m in beacon.ORDER]
EFFECT_TEXT = {
    "haste": "mining cooldown -{}",
    "xp": "mining XP +{}",
    "sell": "/sell of blocks +{}",
    "strength": "damage +{} (dungeon, gate bosses)",
    "resistance": "damage taken -{} (dungeon, gate bosses)",
}


def pct(value: float) -> str:
    return f"{value * 100:g}%"


def beacon_embed(st: dict, user_value: int = 0) -> discord.Embed:
    c = settings.get()["beacon"]
    if not st["lit"]:
        return discord.Embed(
            title="🔆 The Beacon (not lit)",
            description="The server's Beacon needs a **Nether Star**: the first group to beat the 🖤 **Wither** "
                        "(`/boss fight`) lights it for everyone. Then everyone can build it with ingots, and its "
                        "effects help the whole server.",
            color=discord.Color.dark_grey(),
        )
    lines = []
    for level in range(1, beacon.LEVELS + 1):
        material = st["levels"][level]
        effects = " · ".join(EFFECT_TEXT[name].format(pct(float(c[name]) * float(c["multipliers"][material])))
                             for name in beacon.EFFECTS[level]) if material else "not built yet"
        icon = mat(material) if material else "⬛"
        lines.append(f"{icon} **Level {level}** ({material or '—'}): {effects}")
    embed = discord.Embed(title=f"🔆 The Beacon · step {st['step']}/{beacon.STEPS}", description="\n".join(lines),
                          color=discord.Color.gold())
    if st["next"]:
        material, level = st["next"]
        need = st["next_cost"]
        bar = "█" * round(12 * st["progress"] / need) + "░" * (12 - round(12 * st["progress"] / need))
        embed.add_field(name="Building now",
                        value=f"{mat(material)} **Level {level} in {material}**: `{bar}` {st['progress']}/{need} ingots",
                        inline=False)
    else:
        embed.add_field(name="Building now", value="✨ The Beacon is complete: all in netherite!", inline=False)
    if st["upkeep_due"]:
        done = "✅" if st["upkeep_paid"] >= st["upkeep_due"] else "⏳"
        embed.add_field(name="This week's upkeep",
                        value=f"{done} {st['upkeep_paid']}/{st['upkeep_due']} {st['upkeep_material']} ingots "
                              "(not given by Monday: the last step is undone)", inline=False)
    top = [f"<@{r['user_id']}> — {em(r['value'])}" for r in st["top_week"]]
    embed.add_field(name="Builders this week", value=join_lines(top, empty="Nobody yet."), inline=True)
    need = int(c["contributor_value"])
    if need:
        mine = (f"✅ +{pct(float(c['contributor_xp']))} mining XP and +{pct(float(c['contributor_sell']))} /sell "
                "this week" if user_value >= need else f"{em(user_value)}/{em(need)} for the contributor bonus")
        embed.add_field(name="You this week", value=mine, inline=True)
    embed.set_footer(text="Give whole blocks (multiples of 9 ingots) with /beacon give. Gold first, then each level "
                          "again in iron, diamond and netherite.")
    return embed


class BeaconCog(commands.Cog):
    """/beacon: the server's Beacon, built by everyone."""

    group = app_commands.Group(name="beacon", description="The server's Beacon: everyone builds it, everyone gets its effects.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.beacon_loop.start()

    async def cog_unload(self) -> None:
        self.beacon_loop.cancel()

    @group.command(name="info", description="The Beacon: its levels, its effects, what it needs now and its builders.")
    async def info(self, interaction: discord.Interaction):
        def load(ctx):
            return beacon.status(ctx), beacon.week_value(ctx, interaction.user.id)

        st, mine = await self.bot.db.run(load)
        await interaction.response.send_message(embed=beacon_embed(st, mine), ephemeral=True)

    @group.command(name="give", description="Give ingots to the Beacon (whole blocks: multiples of 9).")
    @app_commands.describe(material="The ingots the Beacon needs now", ingots="How many (9, 18, 27…)")
    @app_commands.choices(material=MATERIAL_CHOICES)
    async def give(self, interaction: discord.Interaction, material: str,
                   ingots: app_commands.Range[int, 9, 100_000]):
        res = await self.bot.db.run(beacon.give, interaction.user.id, material, ingots)
        parts = [f"🔆 {interaction.user.mention} gave {mat(material)} **{ingots} {material} ingots** to the Beacon "
                 f"({em(res['value'])})."]
        if res["upkeep"]:
            parts.append(f"{res['upkeep']} went to this week's upkeep.")
        for m, level in res["built"]:
            parts.append(f"✨ **Level {level} is now built in {m}!** Its effects are stronger for everyone.")
        await interaction.response.send_message(" ".join(parts[:2]) + ("\n" + "\n".join(parts[2:]) if parts[2:] else ""),
                                                allowed_mentions=discord.AllowedMentions.none())
        for m, level in res["built"]:
            await self.bot.announcer.send(f"🔆 The Beacon's **level {level} is now built in {m}** "
                                          f"(step {res['status']['step']}/{beacon.STEPS})! Thanks to everyone who "
                                          "gave. `/beacon info`")

    async def announce_lit(self, user_id: int | None) -> None:
        who = f"<@{user_id}>'s group" if user_id else "The staff"
        await self.bot.announcer.send(f"🌟 {who} brought back a **Nether Star** from the Wither: **the Beacon is lit!** "
                                      "Build it together with `/beacon give` (gold first): its effects help everyone.")

    async def staff_set(self, interaction: discord.Interaction, lit: bool, step: int | None) -> None:
        def run(ctx):
            was = beacon.is_lit(ctx)
            return was, beacon.staff_set(ctx, lit, step)

        was, st = await self.bot.db.run(run)
        await interaction.response.send_message(
            f"✅ Beacon: {'lit' if st['lit'] else 'not lit'}, step **{st['step']}/{beacon.STEPS}**.", ephemeral=True)
        if lit and not was:
            await self.announce_lit(None)

    @tasks.loop(minutes=10)
    async def beacon_loop(self):
        try:
            res = await self.bot.db.run(beacon.weekly)
            if res and res["undone"]:
                m, level = res["undone"]
                await self.bot.announcer.send(
                    f"🔆 The Beacon's upkeep wasn't given last week ({res['missing']} {res['material']} ingots "
                    f"missing): **level {level} in {m} crumbled**. `/beacon info`")
        except Exception:  # an error must never stop the loop
            log.exception("Beacon loop failed")

    @beacon_loop.before_loop
    async def before_beacon_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BeaconCog(bot))
