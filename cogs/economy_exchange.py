from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import assets, exchange
from game.errors import GameError
from utils.autocomplete import owned_asset_choices
from utils.ui import BaseView, em

TRADE_TIMEOUT = 300


class TradeView(BaseView):
    def __init__(self, bot: commands.Bot, a: discord.abc.User, b: discord.abc.User, give: str, give_amount: int, get: str | None, get_amount: int):
        super().__init__(allowed_ids={a.id, b.id}, timeout=TRADE_TIMEOUT)
        self.bot = bot
        self.a, self.b = a, b
        self.give, self.give_amount = give, give_amount
        self.get, self.get_amount = get, get_amount
        self.done = False

    def describe(self) -> str:
        text = f"{self.a.mention} offers **{assets.describe(self.give, self.give_amount)}**"
        if self.get:
            text += f"\nin exchange for **{assets.describe(self.get, self.get_amount)}** from {self.b.mention}"
        else:
            text += f"\nas a gift to {self.b.mention}"
        return text

    async def _finish(self, interaction: discord.Interaction, status: str, color: discord.Color) -> None:
        self.done = True
        self.disable_all()
        self.stop()
        embed = discord.Embed(title="🤝 Trade", description=f"{self.describe()}\n\n{status}", color=color)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.b.id:
            return await interaction.response.send_message("❌ Only the other player can accept.", ephemeral=True)
        if self.done:
            return await interaction.response.defer()
        self.done = True
        try:
            await self.bot.db.run(
                exchange.trade, self.a.id, self.b.id, self.give, self.give_amount, self.get, self.get_amount
            )
        except GameError:
            self.done = False
            raise
        await self._finish(interaction, "✅ **Trade completed!**", discord.Color.green())

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return await interaction.response.defer()
        who = "declined" if interaction.user.id == self.b.id else "cancelled"
        await self._finish(interaction, f"✖️ Trade {who} by {interaction.user.mention}.", discord.Color.red())


class ExchangeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pay", description="Send emeralds to another player.")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1]):
        if member.bot:
            raise GameError("Bots don't need emeralds.")
        res = await self.bot.db.run(exchange.pay, interaction.user.id, member.id, amount)
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} sent **{em(amount)}** to {member.mention}.",
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        await interaction.followup.send(f"Your new balance: **{em(res['balance'])}**.", ephemeral=True)

    async def give_autocomplete(self, interaction: discord.Interaction, current: str):
        return await owned_asset_choices(self.bot, interaction.user.id, current)

    async def get_autocomplete(self, interaction: discord.Interaction, current: str):
        member = getattr(interaction.namespace, "member", None)
        if member is None:
            return []
        return await owned_asset_choices(self.bot, member.id, current)

    @app_commands.command(name="trade", description="Propose a trade (or a gift) to another player.")
    @app_commands.describe(
        member="Who you want to trade with",
        give="What you give",
        give_amount="How many you give",
        get="What you want in return (leave empty for a gift)",
        get_amount="How many you want",
    )
    @app_commands.autocomplete(give=give_autocomplete, get=get_autocomplete)
    async def trade(
        self, interaction: discord.Interaction, member: discord.Member, give: str,
        give_amount: app_commands.Range[int, 1] = 1, get: str | None = None,
        get_amount: app_commands.Range[int, 1] = 1,
    ):
        if member.bot or member.id == interaction.user.id:
            raise GameError("Pick another player.")

        def check(ctx):
            exchange.check_owns(ctx, interaction.user.id, give, give_amount)
            if get:
                exchange.check_owns(ctx, member.id, get, get_amount)

        await self.bot.db.run(check)
        view = TradeView(self.bot, interaction.user, member, give, give_amount, get, get_amount if get else 0)
        embed = discord.Embed(
            title="🤝 Trade proposal",
            description=f"{view.describe()}\n\n{member.mention}, do you accept? (expires in {TRADE_TIMEOUT // 60} min)",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(
            content=member.mention, embed=embed, view=view,
            allowed_mentions=discord.AllowedMentions(users=[member]),
        )
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(ExchangeCog(bot))
