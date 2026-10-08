from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


from utils.config import load_emojis

EMOJI = load_emojis()


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands.")
    async def help(self, interaction: discord.Interaction):

        embed = discord.Embed(
            title="Server Commands",
            description="Here are all available commands:",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Mining & Inventory",
            value=(
                "`/inventory` → Show your blocks, items and gear\n"
                "`/sell` → Sell all your blocks\n"
                "`/market` → Open the market\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="Crafting",
            value=(
                "`/craft <item> <material>` → Craft gear\n"
                "`/craftlist` → Show all recipes\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="XP & Talents",
            value=(
                "`/xp` → Show your level and XP\n"
                "`/talents` → Show talent branches\n"
                "`/talent_buy <branch> <points>` → Spend talent points\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="Minecraft",
            value=(
                "`/server_status` → Server status\n"
                "`/ip` → How to join\n"
                "`/modpacks` → Modpack info\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="Staff Commands",
            value=(
                "`/add_whitelist` · `/remove_whitelist` · `/check_whitelist`\n"
                "`/add_block` · `/add_emerald` · `/add_item` · `/add_gear`\n"
                "`/xp_add` · `/xp_set` · `/level_set` · `/talent_add` · `/talent_reset`\n"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
