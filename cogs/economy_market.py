from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    init_db,
    ensure_user,
    get_emeralds,
    add_emeralds,
    add_item,
)

from utils.config import load_emojis

EMOJI = load_emojis()

MARKET = {
    "sticks_pack": ("4 Sticks", "stick", "none", 4, 1),
    "gold_ingot": ("Gold Ingot", "ingot", "gold", 1, 5),
    "iron_ingot": ("Iron Ingot", "ingot", "iron", 1, 10),
    "diamond_ingot": ("Diamond Ingot", "ingot", "diamond", 1, 25),
    "netherite_ingot": ("Netherite Ingot", "ingot", "netherite", 1, 100),
}

class QuantityModal(discord.ui.Modal, title="Enter quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Example: 1", min_length=1, max_length=6)

    def __init__(self, parent_view: "MarketView", selection_key: str):
        super().__init__()
        self.parent_view = parent_view
        self.selection_key = selection_key

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(str(self.quantity.value).strip())
        except ValueError:
            return await interaction.response.send_message("❌ Quantity must be a number.", ephemeral=True)
        if qty <= 0:
            return await interaction.response.send_message("❌ Quantity must be > 0.", ephemeral=True)
        await self.parent_view.handle_purchase(interaction, self.selection_key, qty)

class MarketSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for key, (label, item, material, unit_size, price) in MARKET.items():
            if key == "sticks_pack":
                desc = f"{unit_size} {EMOJI['stick']} for {price} {EMOJI['emerald']}"
            else:
                desc = f"{price} {EMOJI['emerald']} each"
            options.append(discord.SelectOption(label=label, value=key, description=desc))
        super().__init__(placeholder="Choose an item to buy…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        view: MarketView = self.view  # type: ignore
        await interaction.response.send_modal(QuantityModal(view, self.values[0]))

class MarketView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(MarketSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This menu isn’t for you.", ephemeral=True)
            return False
        return True

    async def handle_purchase(self, interaction: discord.Interaction, key: str, units: int):
        ensure_user(interaction.user.id)
        label, item, material, unit_size, price_per_unit = MARKET[key]
        total_price = units * price_per_unit

        balance = get_emeralds(interaction.user.id)
        if balance < total_price:
            return await interaction.response.send_message(
                f"❌ Not enough emeralds.\nYou have **{balance} {EMOJI['emerald']}**, you need **{total_price} {EMOJI['emerald']}**.",
                ephemeral=True,
            )

        add_emeralds(interaction.user.id, -total_price)
        total_amount = units * unit_size
        add_item(interaction.user.id, item, material, total_amount)
        new_balance = get_emeralds(interaction.user.id)

        if key == "sticks_pack":
            item_text = f"**{total_amount} {EMOJI['stick']} sticks**"
        else:
            prefix = EMOJI.get(material, "")
            item_text = f"{prefix} **{total_amount} {material} {item}**" if prefix else f"**{total_amount} {material} {item}**"

        await interaction.response.send_message(
            f"✅ Purchase complete!\nBought {item_text} for **{total_price} {EMOJI['emerald']}**.\n"
            f"New balance: **{new_balance} {EMOJI['emerald']}**.",
            ephemeral=True,
        )

class EconomyMarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_db()

    @app_commands.command(name="market", description="Open the market and buy items with emeralds.")
    async def market(self, interaction: discord.Interaction):
        ensure_user(interaction.user.id)
        balance = get_emeralds(interaction.user.id)
        embed = discord.Embed(
            title="Market",
            description=(
                f"Your balance: **{balance} {EMOJI['emerald']}**\n\n"
                "Choose an item from the dropdown. You will then enter a quantity."
            ),
        )
        await interaction.response.send_message(embed=embed, view=MarketView(interaction.user.id), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyMarketCog(bot))
