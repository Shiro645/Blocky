from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import players, shop
from utils.ui import EMOJI, BaseView, em, item_label, mat, report_error


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
        why = " + ".join(w for w, on in ((f"🏷️ prices {-res['sale']:+.0%} (Market Sale, biome)", round(res["sale"], 4)),
                                         ("🧑‍🌾 Villager price", res["villager"])) if on)
        saved = res["saved"]
        await interaction.response.send_message(
            f"✅ Bought **{item_label(offer['item'], offer['material'], res['amount'])}** for **{em(res['price'])}**"
            + (f" ({why}: {'-' if saved > 0 else '+'}{em(abs(saved))})" if saved else "") + ".\n"
            f"New balance: **{em(res['balance'])}**.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


def price_note(discount: float, when: str) -> str:
    """The market's prices are lower (a Market Sale, the biome) or higher (the biome) than usual."""
    if round(discount, 4) > 0:
        return f"🏷️ Everything is **{discount:.0%}** cheaper {when} (Market Sale, biome of the week)!\n\n"
    if round(discount, 4) < 0:
        return f"📈 Everything is **{-discount:.0%}** dearer {when} (biome of the week: `/biome`).\n\n"
    return ""


def market_options(discount: float = 0.0) -> list[discord.SelectOption]:
    """The market's items, for a menu (/market and the market channel). `discount`: a Market Sale."""
    options = []
    for key, offer in shop.market_offers().items():
        price = shop.sale_price(offer["price"], discount)
        if offer["item"] == "stick":
            desc = f"{offer['unit_size']} sticks for {price} emeralds"
        else:
            desc = f"{price} emeralds each"
        if round(discount, 4):
            desc += f" ({-discount:+.0%})"
        icon = EMOJI.get("stick") if offer["item"] == "stick" else mat(offer["material"])
        options.append(discord.SelectOption(label=offer["label"], value=key, description=desc, emoji=icon or None))
    return options


class MarketSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, discount: float = 0.0):
        self.bot = bot
        super().__init__(placeholder="Choose an item to buy…", options=market_options(discount))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(QuantityModal(self.bot, self.values[0]))


class EconomyMarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="market", description="Open the market and buy items with emeralds.")
    async def market(self, interaction: discord.Interaction):
        def load(ctx, user_id):
            return players.get_emeralds(ctx, user_id), shop.market_discount(ctx)

        balance, discount = await self.bot.db.run(load, interaction.user.id)
        sale = price_note(discount, "right now")
        embed = discord.Embed(
            title="Market",
            description=(
                f"{sale}Your balance: **{em(balance)}**\n\n"
                "Choose an item from the dropdown. You will then enter a quantity."
            ),
            color=discord.Color.gold(),
        )
        view = BaseView(allowed_ids={interaction.user.id}, timeout=120)
        view.add_item(MarketSelect(self.bot, discount))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyMarketCog(bot))
