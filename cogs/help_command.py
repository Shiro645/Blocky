from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_staff

SECTIONS: list[tuple[str, list[str]]] = [
    ("⛏️ Mining & Economy", [
        "Chat to mine blocks automatically (with a cooldown).",
        "`/inventory` → Your blocks, items and gear",
        "`/sell` → Sell all your blocks",
        "`/market` → Buy sticks and ingots",
        "`/daily` → Daily reward (keep your streak!)",
    ]),
    ("🛠️ Crafting & Equipment", [
        "`/craft <item> <material>` · `/craftlist` → Craft gear",
        "`/gear` → Your equipment and what it does",
        "`/equip` · `/equip_best` · `/unequip` → Manage your equipment",
    ]),
    ("⭐ XP & Talents", [
        "`/xp` → Level and XP",
        "`/talents` · `/talent_buy <branch> [points]` → Talent points",
    ]),
    ("🤝 Trading", [
        "`/pay <member> <amount>` → Send emeralds",
        "`/trade <member> <give> ...` → Propose a trade or a gift",
        "`/auction sell · browse · buy · cancel · mine` → Auction house",
    ]),
    ("🏆 Competition", [
        "`/leaderboard [board]` · `/profile [member]`",
        "`/season` → This week's season (top 3 rewarded)",
        "`/duel <member> <stake>` → Fight for emeralds",
        "`/challenges` · `/achievements [member]`",
        "`/boss` · `/attack` → Fight the server boss together",
    ]),
    ("🌍 Minecraft", [
        "`/server_status` · `/ip` · `/modpacks`",
        "`/link <username>` · `/link_status` → Link your account (whitelist)",
    ]),
]

STAFF_SECTION = ("🔐 Staff", [
    "`/add_whitelist` · `/remove_whitelist` · `/check_whitelist` · `/unlink`",
    "`/add_block` · `/add_emerald` · `/remove_emerald` · `/add_item` · `/add_gear` · `/remove_gear`",
    "`/xp_add` · `/xp_set` · `/level_set` · `/talent_add` · `/talent_reset` · `/sync_level_roles`",
    "`/boss_spawn` · `/drop_spawn`",
])


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands.")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Blocky commands", color=discord.Color.blurple())
        sections = SECTIONS + ([STAFF_SECTION] if is_staff(interaction.user) else [])
        for name, lines in sections:
            embed.add_field(name=name, value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
