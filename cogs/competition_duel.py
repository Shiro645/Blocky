from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from game import duel, settings
from game.errors import GameError
from utils.ui import BaseView, em, progress_bar


class DuelView(BaseView):
    def __init__(self, cog: "DuelCog", challenger: discord.Member, opponent: discord.Member, stake: int):
        timeout = settings.get()["duel"]["request_timeout_seconds"]
        super().__init__(allowed_ids={challenger.id, opponent.id}, timeout=timeout)
        self.cog = cog
        self.challenger, self.opponent, self.stake = challenger, opponent, stake
        self.done = False

    async def on_timeout(self) -> None:
        self.cog.pending.discard(self.challenger.id)
        await super().on_timeout()

    @discord.ui.button(label="Fight!", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            return await interaction.response.send_message("❌ Only the challenged player can accept.", ephemeral=True)
        if self.done:
            return await interaction.response.defer()
        self.done = True
        try:
            res = await self.cog.bot.db.run(duel.fight, self.challenger.id, self.opponent.id, self.stake)
        except GameError:
            self.done = False
            raise
        self.cog.finish(self.challenger.id, self.opponent.id)
        self.disable_all()
        self.stop()
        await interaction.response.edit_message(content=None, embed=self.cog.result_embed(self, res), view=self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return await interaction.response.defer()
        self.done = True
        self.cog.pending.discard(self.challenger.id)
        self.disable_all()
        self.stop()
        verb = "declined" if interaction.user.id == self.opponent.id else "cancelled"
        embed = discord.Embed(
            title="⚔️ Duel " + verb,
            description=f"{interaction.user.mention} {verb} the duel.",
            color=discord.Color.dark_grey(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=self)


class DuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldown_until: dict[int, float] = {}
        self.pending: set[int] = set()  # challengers with an open request

    def finish(self, *user_ids: int) -> None:
        cooldown = settings.get()["duel"]["cooldown_seconds"]
        for uid in user_ids:
            self.pending.discard(uid)
            self.cooldown_until[uid] = time.monotonic() + cooldown

    def check_cooldown(self, member: discord.abc.User) -> None:
        left = self.cooldown_until.get(member.id, 0) - time.monotonic()
        if left > 0:
            raise GameError(f"{member.mention} is still recovering from a duel. Try again in **{left:.0f}s**.")

    @app_commands.command(name="duel", description="Challenge a player: both bet the stake, the winner takes it all.")
    @app_commands.describe(member="Who you want to fight", stake="Emeralds each player bets")
    async def duel_cmd(self, interaction: discord.Interaction, member: discord.Member, stake: app_commands.Range[int, 1]):
        if member.bot or member.id == interaction.user.id:
            raise GameError("Pick another player.")
        if interaction.user.id in self.pending:
            raise GameError("You already have a duel request waiting.")
        self.check_cooldown(interaction.user)
        self.check_cooldown(member)

        def check(ctx):
            duel.check_stake(ctx, interaction.user.id, stake)
            duel.check_stake(ctx, member.id, stake)

        await self.bot.db.run(check)

        view = DuelView(self, interaction.user, member, stake)
        self.pending.add(interaction.user.id)
        embed = discord.Embed(
            title="⚔️ Duel challenge!",
            description=(
                f"{interaction.user.mention} challenges {member.mention}!\n"
                f"Stake: **{em(stake)}** each — the winner takes **{em(stake * 2)}**.\n\n"
                f"{member.mention}, do you accept? (expires in {int(view.timeout)}s)"
            ),
            color=discord.Color.red(),
        )
        await interaction.response.send_message(
            content=member.mention, embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        view.message = await interaction.original_response()

    def result_embed(self, view: DuelView, res: dict) -> discord.Embed:
        names = {view.challenger.id: view.challenger.display_name, view.opponent.id: view.opponent.display_name}
        max_hp = res["max_hp"]

        lines = []
        log = res["log"]
        shown = log if len(log) <= 8 else log[:3] + [None] + log[-4:]
        for entry in shown:
            if entry is None:
                lines.append("*…the fight goes on…*")
                continue
            attacker, dmg, crit, hp_left = entry
            hit = "💥 **CRIT** " if crit else ""
            lines.append(f"{hit}{names[attacker]} hits for **{dmg}** ({hp_left} HP left)")

        bars = []
        for uid in (view.challenger.id, view.opponent.id):
            s = res["stats"][uid]
            bars.append(
                f"**{names[uid]}** ⚔️ {s['attack']} · 🛡️ {s['reduction']:.0%}\n"
                f"`{progress_bar(int(res['hp'][uid]), int(max_hp), 12)}` {res['hp'][uid]}/{max_hp:g} HP"
            )

        embed = discord.Embed(
            title=f"🏆 {names[res['winner']]} wins the duel!",
            description="\n".join(bars) + "\n\n" + "\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Pot", value=f"<@{res['winner']}> takes **{em(res['stake'] * 2)}**", inline=False)
        if res["broken"]:
            embed.add_field(
                name="🔨 Broken",
                value="\n".join(f"<@{uid}>'s {name}" for uid, name in res["broken"]),
                inline=False,
            )
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(DuelCog(bot))
