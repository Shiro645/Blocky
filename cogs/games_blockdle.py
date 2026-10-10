from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from game import blockdle, settings
from utils.checks import check_game_channel
from utils.ui import em, join_lines

CELLS = {"yes": "🟩", "no": "🟥", "higher": "🔼", "lower": "🔽"}
LEGEND = "🟩 same · 🟥 different · 🔼 the block of the day is higher / newer · 🔽 lower / older"
HEADER = "Tool · Hardness · Blast resistance · Transparent · Craftable · Version"


def guess_line(block: blockdle.Block, cells: dict[str, str]) -> str:
    parts = [f"{CELLS[cells[key]]} {blockdle.value_text(block, key)}" for key, _ in blockdle.COLUMNS]
    return f"**{block.name}**\n" + " · ".join(parts)


class BlockdleCog(commands.Cog):
    """/blockdle: guess the Minecraft block of the day."""

    group = app_commands.Group(name="blockdle", description="Guess the Minecraft block of the day (like Wordle).")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def grid(self, state: dict, title: str) -> discord.Embed:
        lines = [guess_line(b, cells) for b, cells in state["guesses"]]
        shown = lines[-15:]
        if len(lines) > len(shown):
            shown.insert(0, f"*…{len(lines) - len(shown)} earlier guesses*")
        embed = discord.Embed(title=title, color=discord.Color.green() if state["found"] else discord.Color.blurple())
        embed.description = (f"*{HEADER}*\n\n" + "\n".join(shown))[:4000] if lines else (
            "Guess a block with `/blockdle guess`. After each guess you see how it compares with the block of "
            "the day: same tool? harder? more blast resistant? transparent? craftable? newer?"
        )
        if state["found"]:
            embed.add_field(name="Found!", value=f"**{state['secret'].name}** in **{state['tries']}** guess(es): "
                                                 f"+{em(state['reward'])}", inline=False)
        embed.add_field(name="Found today", value=f"{state['winners']} player(s)", inline=True)
        embed.add_field(name="Next block", value=f"<t:{self.next_day(state['day'])}:R>", inline=True)
        embed.set_footer(text=LEGEND)
        return embed

    @staticmethod
    def next_day(day: str) -> int:
        """Timestamp of the next midnight (server time): a new block."""
        tz = ZoneInfo(settings.get()["timezone"])
        midnight = datetime.combine(datetime.fromisoformat(day).date() + timedelta(days=1), dtime(), tzinfo=tz)
        return int(midnight.timestamp())

    async def block_autocomplete(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=b.name, value=b.id) for b in blockdle.search(current)]

    @group.command(name="guess", description="Guess the block of the day.")
    @app_commands.describe(block="A Minecraft block (start typing)")
    @app_commands.autocomplete(block=block_autocomplete)
    async def guess(self, interaction: discord.Interaction, block: str):
        check_game_channel(interaction)
        state = await self.bot.db.run(blockdle.guess, interaction.user.id, block)
        title = "🧩 Blockdle — found!" if state["found"] else f"🧩 Blockdle — guess {state['tries']}"
        # Private: the others mustn't see the clues.
        await interaction.response.send_message(embed=self.grid(state, title), ephemeral=True)
        if state["found"] and interaction.channel is not None:
            try:
                await interaction.channel.send(
                    f"🧩 {interaction.user.mention} found today's Blockdle in **{state['tries']}** guess(es)! "
                    f"(+{em(state['reward'])})",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                pass

    @group.command(name="today", description="Your guesses of the day so far.")
    async def today(self, interaction: discord.Interaction):
        state = await self.bot.db.run(blockdle.state, interaction.user.id)
        await interaction.response.send_message(embed=self.grid(state, "🧩 Blockdle — today"), ephemeral=True)

    @group.command(name="top", description="Who found today's block, with the fewest guesses.")
    async def top(self, interaction: discord.Interaction):
        def run(ctx):
            return blockdle.winners(ctx), blockdle.yesterday(ctx)

        rows, before = await self.bot.db.run(run)
        lines = [f"**{i + 1}.** <@{r['user_id']}> · {r['tries']} guess(es)" for i, r in enumerate(rows)]
        embed = discord.Embed(title="🧩 Blockdle — today's best", description=join_lines(lines, 4000, "Nobody yet. Be the first!"),
                              color=discord.Color.blurple())
        if before:
            embed.set_footer(text=f"Yesterday's block: {before.name}")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(BlockdleCog(bot))
