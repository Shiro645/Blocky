from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import players, shop
from utils.ui import BaseView, em, item_label, report_error


class QuantityModal(discord.ui.Modal, title="Enter quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Example: 1", min_length=1, max_length=6)

    def __init__(self, bot: commands.Bot, key: str):
        super().__init__()
        self.bot = bot
        self.key = key

    async def on_submit(self, interaction: discord.Interaction):
        try:
            units = int(str(self.quantity.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Quantity must be a number.", ephemeral=True)

        res = await self.bot.db.run(shop.buy, interaction.user.id, self.key, units)
        offer = res["offer"]
        await interaction.response.send_message(
            f"✅ Bought **{item_label(offer['item'], offer['material'], res['amount'])}** for **{em(res['price'])}**.\n"
            f"New balance: **{em(res['balance'])}**.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class MarketSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        options = []
        for key, offer in shop.market_offers().items():
            if offer["item"] == "stick":
                desc = f"{offer['unit_size']} sticks for {offer['price']} emeralds"
            else:
                desc = f"{offer['price']} emeralds each"
            options.append(discord.SelectOption(label=offer["label"], value=key, description=desc))
        super().__init__(placeholder="Choose an item to buy…", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(QuantityModal(self.bot, self.values[0]))


class EconomyMarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="market", description="Open the market and buy items with emeralds.")
    async def market(self, interaction: discord.Interaction):
        balance = await self.bot.db.run(players.get_emeralds, interaction.user.id)
        embed = discord.Embed(
            title="Market",
            description=(
                f"Your balance: **{em(balance)}**\n\n"
                "Choose an item from the dropdown. You will then enter a quantity."
            ),
            color=discord.Color.gold(),
        )
        view = BaseView(allowed_ids={interaction.user.id}, timeout=120)
        view.add_item(MarketSelect(self.bot))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyMarketCog(bot))
