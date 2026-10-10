from __future__ import annotations

import logging
import random
import time
from collections import deque

import discord
from discord.ext import commands, tasks

from game import quiz, settings
from utils.config import channel_ids
from utils.ui import BaseView, em

log = logging.getLogger("quiz")
LETTERS = ("A", "B", "C", "D")


class QuizView(BaseView):
    """A question: the first player to click the right answer wins. One try per player."""

    def __init__(self, cog: "QuizCog", index: int, options: list[str], right: int):
        super().__init__(timeout=int(settings.get()["games"]["quiz_seconds"]))
        self.cog, self.index, self.options, self.right = cog, index, options, right
        self.tried: set[int] = set()
        self.winner: discord.abc.User | None = None
        for i, text in enumerate(options):
            self.add_item(AnswerButton(i, text))

    def embed(self) -> discord.Embed:
        question = quiz.QUESTIONS[self.index][0]
        embed = discord.Embed(title="❓ Minecraft quiz", description=f"**{question}**", color=discord.Color.gold())
        embed.description += "\n\n" + "\n".join(f"**{LETTERS[i]}.** {text}" for i, text in enumerate(self.options))
        return embed

    def reveal(self) -> None:
        for item in self.children:
            if isinstance(item, AnswerButton):
                item.disabled = True
                if item.index == self.right:
                    item.style = discord.ButtonStyle.success

    async def on_timeout(self) -> None:
        if self.winner is not None:
            return
        self.reveal()
        embed = self.embed()
        embed.color = discord.Color.dark_grey()
        embed.add_field(name="⌛ Time's up!", value=f"The answer was **{self.options[self.right]}**.")
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


class AnswerButton(discord.ui.Button):
    view: QuizView

    def __init__(self, index: int, text: str):
        super().__init__(label=f"{LETTERS[index]}. {text}"[:80], style=discord.ButtonStyle.secondary, row=index // 2)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if view.winner is not None:
            await interaction.response.send_message(f"Too late, {view.winner.mention} already won this one.", ephemeral=True)
            return
        if interaction.user.id in view.tried:
            await interaction.response.send_message("You already answered this question.", ephemeral=True)
            return
        view.tried.add(interaction.user.id)
        if self.index != view.right:
            await interaction.response.send_message("❌ Wrong answer! Others can still try.", ephemeral=True)
            return
        view.winner = interaction.user
        view.stop()
        prize = await view.cog.bot.db.run(quiz.reward, interaction.user.id)
        view.reveal()
        embed = view.embed()
        embed.color = discord.Color.green()
        embed.add_field(
            name="✅ Right answer!",
            value=f"{interaction.user.mention} answered **{view.options[view.right]}** first: "
                  f"+{em(prize['emeralds'])} and +{prize['xp']} XP.",
        )
        await interaction.response.edit_message(embed=embed, view=view)


class QuizCog(commands.Cog):
    """A Minecraft question in a games channel every X minutes (and /event quiz)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rng = random.Random()
        self.recent: deque[int] = deque(maxlen=40)  # questions asked lately, not asked again soon
        self.next_at = 0.0

    async def cog_load(self) -> None:
        self.quiz_loop.start()

    async def cog_unload(self) -> None:
        self.quiz_loop.cancel()

    async def post(self, channel: discord.abc.Messageable) -> None:
        index = quiz.pick(self.rng, list(self.recent))
        self.recent.append(index)
        options, right = quiz.answers(self.rng, index)
        view = QuizView(self, index, options, right)
        view.message = await channel.send(embed=view.embed(), view=view)

    def schedule(self) -> None:
        minutes = float(settings.get()["games"]["quiz_every_minutes"])
        self.next_at = time.monotonic() + minutes * 60 * self.rng.uniform(0.75, 1.25) if minutes > 0 else 0.0

    @tasks.loop(minutes=1)
    async def quiz_loop(self):
        try:
            minutes = float(settings.get()["games"]["quiz_every_minutes"])
            if minutes <= 0:
                self.next_at = 0.0
                return
            if not self.next_at:
                self.schedule()
                return
            if time.monotonic() < self.next_at:
                return
            self.schedule()
            channels = [self.bot.get_channel(c) for c in sorted(channel_ids("games"))]
            channels = [c for c in channels if isinstance(c, discord.abc.Messageable)]
            if channels:
                await self.post(self.rng.choice(channels))
        except Exception:  # an error must never stop the loop
            log.exception("Quiz loop failed")

    @quiz_loop.before_loop
    async def before_quiz_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(QuizCog(bot))
