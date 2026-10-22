from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import deque

import discord
from discord.ext import commands, tasks

from game import botstate, quiz, settings
from utils.config import channel_id
from utils.ui import BaseView, em

log = logging.getLogger("quiz")
LETTERS = ("A", "B", "C", "D")
OPEN_KEY = "open_quizzes"  # bot_state: the questions still open, closed at the next start if the bot restarts


def _open(ctx, change=None) -> list[dict]:
    """The open questions [{channel, message, answer}] (`change`: a function returning the new list)."""
    items = json.loads(botstate.get(ctx, OPEN_KEY) or "[]")
    if change is not None:
        items = change(items)
        botstate.put(ctx, OPEN_KEY, json.dumps(items) if items else None)
    return items


class QuizView(BaseView):
    """A question: the first player to click the right answer wins. One try per player."""

    def __init__(self, cog: "QuizCog", index: int, options: list[str], right: int):
        seconds = int(settings.get()["games"]["quiz_seconds"])
        # A view's own timeout starts again at every click: the question ends at a fixed time instead.
        super().__init__(timeout=None)
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds
        self.ends_at = int(time.time()) + seconds  # shown as a countdown
        self.cog, self.index, self.options, self.right = cog, index, options, right
        self.tried: set[int] = set()
        self.winner: discord.abc.User | None = None
        for i, text in enumerate(options):
            self.add_item(AnswerButton(i, text))

    def embed(self) -> discord.Embed:
        question = quiz.QUESTIONS[self.index][0]
        embed = discord.Embed(title="❓ Minecraft quiz", description=f"**{question}**", color=discord.Color.gold())
        embed.description += "\n\n" + "\n".join(f"**{LETTERS[i]}.** {text}" for i, text in enumerate(self.options))
        if self.winner is None and not self.is_finished():
            embed.description += f"\n\n⏳ Ends <t:{self.ends_at}:R> ({self.seconds} s to answer)"
        return embed

    async def closed(self) -> None:
        """The question is over: it's no longer to close at the next start."""
        if self.message is not None:
            mid = self.message.id
            await self.cog.bot.db.run(_open, lambda items: [i for i in items if i["message"] != mid])

    def reveal(self) -> None:
        for item in self.children:
            if isinstance(item, AnswerButton):
                item.disabled = True
                if item.index == self.right:
                    item.style = discord.ButtonStyle.success

    def start_clock(self) -> None:
        asyncio.create_task(self._ring())

    async def _ring(self) -> None:
        await asyncio.sleep(self.seconds)
        if self.winner is None and not self.is_finished():
            self.stop()
            await self.on_timeout()

    async def on_timeout(self) -> None:
        if self.winner is not None:
            return
        await self.closed()
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
        if view.winner is None and time.monotonic() >= view.deadline:
            await interaction.response.send_message("⌛ Time's up for this question!", ephemeral=True)
            return
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
        await view.closed()
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
    """A Minecraft question in the events channel every X minutes (and /event quiz)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rng = random.Random()
        self.recent: deque[int] = deque()  # questions asked lately, not asked again soon (games.quiz_no_repeat)
        self.next_at = 0.0

    async def cog_load(self) -> None:
        self.quiz_loop.start()

    async def cog_unload(self) -> None:
        self.quiz_loop.cancel()

    async def post(self, channel: discord.abc.Messageable) -> None:
        keep = int(settings.get()["games"]["quiz_no_repeat"])
        index = quiz.pick(self.rng, list(self.recent)[-keep:] if keep > 0 else [])
        self.recent.append(index)
        while len(self.recent) > max(keep, 0):
            self.recent.popleft()
        options, right = quiz.answers(self.rng, index)
        view = QuizView(self, index, options, right)
        view.message = await channel.send(embed=view.embed(), view=view)
        entry = {"channel": view.message.channel.id, "message": view.message.id, "answer": options[right]}
        await self.bot.db.run(_open, lambda items: items + [entry])
        view.start_clock()

    async def close_left_open(self) -> None:
        """Questions posted before a restart lost their buttons: close them with their answer."""
        for item in await self.bot.db.run(_open, lambda items: []):
            channel = self.bot.get_channel(item["channel"])
            if not isinstance(channel, discord.abc.Messageable):
                continue
            try:
                message = await channel.fetch_message(item["message"])
                embed = message.embeds[0] if message.embeds else discord.Embed(title="❓ Minecraft quiz")
                embed.color = discord.Color.dark_grey()
                embed.description = (embed.description or "").split("\n\n⏳")[0]
                embed.add_field(name="⌛ Closed", value=f"The bot restarted. The answer was **{item['answer']}**.")
                await message.edit(embed=embed, view=None)
            except discord.HTTPException:
                log.warning("Could not close an old quiz question", exc_info=True)

    def schedule(self) -> None:
        g = settings.get()["games"]
        minutes, jitter = float(g["quiz_every_minutes"]), float(g["quiz_every_jitter"])
        self.next_at = time.monotonic() + minutes * 60 * self.rng.uniform(1 - jitter, 1 + jitter) if minutes > 0 else 0.0

    @tasks.loop(minutes=1)
    async def quiz_loop(self):
        try:
            # Without an events channel no quiz comes by itself: the quiz challenge isn't drawn then.
            quiz.auto_channel = isinstance(self.bot.get_channel(channel_id("events") or 0), discord.abc.Messageable)
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
            channel = self.bot.get_channel(channel_id("events") or 0)  # the events channel
            if isinstance(channel, discord.abc.Messageable):
                await self.post(channel)
        except Exception:  # an error must never stop the loop
            log.exception("Quiz loop failed")

    @quiz_loop.before_loop
    async def before_quiz_loop(self):
        await self.bot.wait_until_ready()
        await self.close_left_open()


async def setup(bot: commands.Bot):
    await bot.add_cog(QuizCog(bot))
