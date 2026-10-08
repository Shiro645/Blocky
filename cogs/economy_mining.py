from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from game import mining, players, shop
from game.db import Ctx
from utils.ui import EMOJI, block_icon, em, gear_label, item_label, join_lines


def _inventory(ctx: Ctx, user_id: int) -> dict:
    return {
        "blocks": players.get_blocks(ctx, user_id),
        "items": players.get_items(ctx, user_id),
        "gear": shop.get_gear(ctx, user_id),
        "emeralds": players.get_emeralds(ctx, user_id),
    }


class EconomyMiningCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # user_id -> monotonic time when the user can mine again
        self._next_mine: dict[int, float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        user_id = message.author.id
        now = time.monotonic()
        if now < self._next_mine.get(user_id, 0.0):
            return
        # Reserve the slot before awaiting, so two quick messages can't both mine.
        self._next_mine[user_id] = now + 3600

        try:
            result = await self.bot.db.run(mining.mine, user_id)
        except Exception:
            self._next_mine.pop(user_id, None)
            raise
        self._next_mine[user_id] = now + result["cooldown"]
        self.bot.dispatch("blocky_mined", message, result)

    @app_commands.command(name="inventory", description="Show your blocks, emeralds, items and gear.")
    async def inventory(self, interaction: discord.Interaction):
        inv = await self.bot.db.run(_inventory, interaction.user.id)

        lines, total_value = [], 0
        for block, amount in inv["blocks"].items():
            value = players.block_value(block)
            total_value += amount * value
            lines.append(f"{block_icon(block)} **{block}**: {amount} ({em(value)} each)")

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Inventory",
            description="\n".join(lines),
            color=discord.Color.dark_green(),
        )
        embed.add_field(name=f"{EMOJI['emerald']} Emeralds".strip(), value=f"{inv['emeralds']:,}", inline=True)
        embed.add_field(name="Blocks sell value", value=em(total_value), inline=True)

        item_lines = [item_label(item, material, amount) for (item, material), amount in sorted(inv["items"].items())]
        embed.add_field(name="Items", value=join_lines(item_lines, empty="No items yet."), inline=False)

        gear_lines = [("🟢 " if g["equipped"] else "▫️ ") + gear_label(g) for g in inv["gear"]]
        embed.add_field(name="Gear (🟢 equipped)", value=join_lines(gear_lines, empty="No gear yet."), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sell", description="Sell all your blocks for emeralds.")
    async def sell(self, interaction: discord.Interaction):
        res = await self.bot.db.run(players.sell_all_blocks, interaction.user.id)

        lines = [
            f"{block_icon(b)} **{b}** ×{amt} → +{em(amt * players.block_value(b))}"
            for b, amt in res["sold"].items()
        ]
        embed = discord.Embed(title="Sale complete", description="\n".join(lines), color=discord.Color.green())
        gained = res["base"] + res["bonus"]
        if res["bonus"]:
            embed.add_field(name="Gained", value=f"{res['base']} + {res['bonus']} trader bonus = {em(gained)}")
        else:
            embed.add_field(name="Gained", value=em(gained))
        embed.add_field(name="New balance", value=em(res["balance"]))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyMiningCog(bot))
