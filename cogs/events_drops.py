from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from game import events, settings
from utils.checks import staff_only
from utils.ui import BaseView


class DropView(BaseView):
    def __init__(self, cog: "DropsCog", drop: dict):
        super().__init__(timeout=settings.get()["drops"]["claim_seconds"])
        self.cog = cog
        self.drop = drop
        self.claimed_by: int | None = None

    def embed(self, text: str, color: discord.Color) -> discord.Embed:
        return discord.Embed(title=f"⛏️ {self.drop['title']} appeared!", description=text, color=color)

    @discord.ui.button(label="Mine it!", style=discord.ButtonStyle.success, emoji="⛏️")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed_by is not None:
            return await interaction.response.send_message(
                f"Too late! <@{self.claimed_by}> got there first.", ephemeral=True
            )
        self.claimed_by = interaction.user.id
        try:
            await self.cog.bot.db.run(events.claim_drop, interaction.user.id, self.drop)
        except Exception:
            self.claimed_by = None
            raise
        self.disable_all()
        self.stop()
        reward = events.describe_reward(self.drop["reward"])
        await interaction.response.edit_message(
            embed=self.embed(f"🎉 {interaction.user.mention} was the fastest and got **{reward}**!", discord.Color.green()),
            view=self,
        )

    async def on_timeout(self) -> None:
        if self.claimed_by is None and self.message is not None:
            self.disable_all()
            try:
                await self.message.edit(
                    embed=self.embed("The vein collapsed… nobody was fast enough.", discord.Color.dark_grey()),
                    view=self,
                )
            except discord.HTTPException:
                pass


class DropsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rng = random.Random()
        self.next_drop_at = 0.0

    async def spawn(self, channel: discord.abc.Messageable) -> None:
        drop = events.roll_drop(self.rng)
        view = DropView(self, drop)
        view.message = await channel.send(
            embed=view.embed(f"First to click gets it! ({int(view.timeout)}s)", discord.Color.blue()),
            view=view,
        )

    @commands.Cog.listener()
    async def on_blocky_mined(self, message: discord.Message, result: dict):
        """Every mining event has a small chance to make a drop appear."""
        d = settings.get()["drops"]
        now = time.monotonic()
        if now < self.next_drop_at or self.rng.random() >= d["chance"]:
            return
        self.next_drop_at = now + int(d["min_interval_seconds"])
        channel = self.bot.announcer.channel("events") or message.channel
        try:
            await self.spawn(channel)
        except discord.HTTPException:
            pass

    @app_commands.command(name="drop_spawn", description="STAFF: Make a drop appear in this channel.")
    @staff_only()
    async def drop_spawn(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Drop spawned.", ephemeral=True)
        await self.spawn(interaction.channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(DropsCog(bot))
