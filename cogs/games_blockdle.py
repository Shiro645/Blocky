from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from game import blockdle, settings
from utils.checks import check_game_channel
from utils.ui import em, join_lines

ICONS = {"tool": "⛏️", "hardness": "🪨", "resistance": "💥", "transparent": "👁️", "craftable": "🛠️", "version": "📅"}
SHORT = {"yes": "✅", "no": "❌", "higher": "⬆️", "lower": "⬇️"}
LEGEND = "✅ same · ❌ different · ⬆️ the block of the day is higher / newer · ⬇️ lower / older"
HOW_TO = (
    "Find the Minecraft block of the day (the same for everyone). Guess any block with `/blockdle guess`: "
    "the bot compares it with the block of the day on 6 properties and tells you, for each one, if it's the same, "
    "or if the block of the day is higher (⬆️) or lower (⬇️). Use the clues to narrow it down!"
)
HIGHER = {"hardness": "harder", "resistance": "more blast resistant", "version": "newer"}
LOWER = {"hardness": "softer", "resistance": "less blast resistant", "version": "older"}


def explain(key: str, block: blockdle.Block, result: str) -> str:
    """One answer in plain words, e.g. "⬆️ the block of the day is harder"."""
    if result == "yes":
        return "✅ same"
    if key == "tool":
        return "❌ another tool"
    if key in ("transparent", "craftable"):
        is_it = not getattr(block, key)  # the block of the day is the opposite
        word = "transparent" if key == "transparent" else "craftable"
        return f"❌ the block of the day {'is' if is_it else 'is not'} {word}"
    return f"{SHORT[result]} the block of the day is {(HIGHER if result == 'higher' else LOWER)[key]}"


def result_lines(block: blockdle.Block, cells: dict[str, str]) -> str:
    return "\n".join(
        f"{ICONS[key]} {label}: **{blockdle.value_text(block, key)}** → {explain(key, block, cells[key])}"
        for key, label in blockdle.COLUMNS
    )


def known_lines(guesses: list) -> list[str]:
    """What all the answers together say about the block of the day."""
    know = blockdle.knowledge(guesses)
    lines = []
    tool = know["tool"]
    if "exact" in tool:
        lines.append(f"{ICONS['tool']} Tool: **{blockdle.TOOL_NAMES.get(tool['exact'], tool['exact'])}** ✅")
    else:
        excluded = [blockdle.TOOL_NAMES.get(t, t) for t in tool["not"]]
        lines.append(f"{ICONS['tool']} Tool: " + (" · ".join(f"❌ {t}" for t in excluded) if excluded else "?"))
    for key, label in (("hardness", "Hardness"), ("resistance", "Blast resistance"), ("version", "Version")):
        k = know[key]
        if "exact" in k:
            lines.append(f"{ICONS[key]} {label}: **{blockdle.value_text(k['exact'], key)}** ✅")
            continue
        bits = []
        if k["above"] is not None:
            bits.append(f"{HIGHER[key]} than {blockdle.value_text(k['above'], key)}")
        if k["below"] is not None:
            bits.append(f"{LOWER[key]} than {blockdle.value_text(k['below'], key)}")
        lines.append(f"{ICONS[key]} {label}: {' and '.join(bits) if bits else '?'}")
    for key, label in (("transparent", "Transparent"), ("craftable", "Craftable")):
        if key in know:
            lines.append(f"{ICONS[key]} {label}: **{'Yes' if know[key]['exact'] else 'No'}** ✅")
    return lines


def history_line(n: int, block: blockdle.Block, cells: dict[str, str]) -> str:
    return f"`{n}.` {''.join(SHORT[cells[key]] for key, _ in blockdle.COLUMNS)} {block.name}"


class BlockdleCog(commands.Cog):
    """/blockdle: guess the Minecraft block of the day."""

    group = app_commands.Group(name="blockdle", description="Guess the Minecraft block of the day (like Wordle).")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def grid(self, state: dict, title: str) -> discord.Embed:
        guesses = state["guesses"]
        embed = discord.Embed(title=title, color=discord.Color.green() if state["found"] else discord.Color.blurple())
        if state["found"]:
            embed.description = (f"🎉 It was **{state['secret'].name}**! Found in **{state['tries']}** guess(es): "
                                 f"+{em(state['reward'])}")
        elif guesses:
            block, cells = guesses[-1]
            embed.description = f"**Your guess: {block.name}**\n{result_lines(block, cells)}"
        else:
            embed.description = HOW_TO
        if guesses and not state["found"]:
            left = blockdle.candidates(guesses)
            known = known_lines(guesses)
            if len(left) <= 6:
                known.append(f"🎯 **{len(left)}** block(s) still possible: " + ", ".join(b.name for b in left))
            else:
                known.append(f"🎯 **{len(left)}** blocks still possible")
            embed.add_field(name="📋 What you know so far", value=join_lines(known), inline=False)
        if guesses:
            header = "`  ` " + "".join(ICONS[key] for key, _ in blockdle.COLUMNS)
            lines = [history_line(i + 1, b, cells) for i, (b, cells) in enumerate(guesses)][-15:]
            embed.add_field(name="🕘 Your guesses", value=join_lines([header, *lines]), inline=False)
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
