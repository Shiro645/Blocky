from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import biomes, progress
from utils.ui import em, progress_bar

log = logging.getLogger("biomes")


def biome_embed(biome: biomes.Biome | None, ends: int, challenge: dict | None = None) -> discord.Embed:
    if biome is None:
        return discord.Embed(title="🗺️ Biome of the week", description="No biome this week.",
                             color=discord.Color.dark_grey())
    lines = [
        f"✅ **{biome.bonus_why}**: {biomes.describe(biome.bonus, True)}",
        f"⚠️ **{biome.malus_why}**: {biomes.describe(biome.malus, False)}",
    ]
    embed = discord.Embed(title=f"{biome.label} · biome of the week", description="\n".join(lines),
                          color=discord.Color.dark_green())
    if challenge:
        mark = "✅" if challenge["completed"] else "🎯"
        embed.add_field(name="The biome's challenge",
                        value=f"{mark} **{challenge['text']}** — reward {em(challenge['reward'])}\n"
                              f"`{progress_bar(challenge['progress'], challenge['target'], 12)}` "
                              f"{challenge['progress']:,}/{challenge['target']:,}", inline=False)
    embed.add_field(name="Next biome", value=f"<t:{ends}:R>", inline=False)
    embed.set_footer(text="One biome for the whole server, drawn every Monday (never the same twice in a row).")
    return embed


class BiomesCog(commands.Cog):
    """/biome: the biome of the week, announced every Monday."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.biome_loop.start()

    async def cog_unload(self) -> None:
        self.biome_loop.cancel()

    @app_commands.command(name="biome", description="The biome of the week: its bonus, its malus and its challenge.")
    async def biome(self, interaction: discord.Interaction):
        def load(ctx):
            return biomes.current(ctx), biomes.week_ends(ctx), progress.biome_progress(ctx, interaction.user.id)

        biome, ends, challenge = await self.bot.db.run(load)
        await interaction.response.send_message(embed=biome_embed(biome, ends, challenge), ephemeral=True)

    async def announce(self, biome: biomes.Biome, ends: int, forced: bool = False) -> None:
        challenge = await self.bot.db.run(lambda ctx: progress.biome_progress(ctx, 0))  # 0: nobody's progress
        head = "🗺️ **The staff changed the biome of the week!**" if forced else "🗺️ **A new week, a new biome!**"
        await self.bot.announcer.send(head, embed=biome_embed(biome, ends, challenge))

    async def staff_set(self, interaction: discord.Interaction, key: str) -> None:
        """/event biome (cogs/staff_events.py)."""
        def run(ctx):
            return biomes.force(ctx, key), biomes.week_ends(ctx)

        biome, ends = await self.bot.db.run(run)
        await interaction.response.send_message(f"✅ This week's biome is now **{biome.label}**.", ephemeral=True)
        await self.announce(biome, ends, forced=True)
        await self.bot.announcer.send(f"🔧 {interaction.user.mention} set the biome of the week to {biome.label}.",
                                      channel="staff_log")

    @tasks.loop(minutes=5)
    async def biome_loop(self):
        try:
            def run(ctx):
                return biomes.to_announce(ctx), biomes.week_ends(ctx)

            biome, ends = await self.bot.db.run(run)
            if biome is not None:
                await self.announce(biome, ends)
        except Exception:  # an error must never stop the loop
            log.exception("Biome loop failed")

    @biome_loop.before_loop
    async def before_biome_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BiomesCog(bot))
