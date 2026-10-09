from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import enchants, gear, shop
from game.catalog import GEAR_EFFECTS, GEAR_ITEMS, MATERIALS, RECIPES
from game.db import Ctx
from utils.ui import EMOJI, gear_icon, gear_label, join_lines, mat, progress_bar

ITEM_CHOICES = [app_commands.Choice(name=i, value=i) for i in GEAR_ITEMS]
MATERIAL_CHOICES = [app_commands.Choice(name=m, value=m) for m in MATERIALS]


class EconomyCraftCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="craft", description="Craft tools and armor using ingots and sticks.")
    @app_commands.choices(item=ITEM_CHOICES, material=MATERIAL_CHOICES)
    async def craft(self, interaction: discord.Interaction, item: str, material: str):
        res = await self.bot.db.run(shop.craft, interaction.user.id, item, material)

        cost = []
        if res["ingots"]:
            cost.append(f"{mat(material)} {res['ingots']} ingot(s)".strip())
        if res["sticks"]:
            cost.append(f"{EMOJI['stick']} {res['sticks']} stick(s)".strip())
        text = f"✅ Crafted {gear_icon(item, material)} **{material} {item}**! Cost: " + " + ".join(cost)
        if res["equipped"]:
            text += "\nIt was equipped automatically (the slot was empty)."
        else:
            text += f"\nUse `/equip` to wear it instead of your current {item}."
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="craftlist", description="Show all crafting recipes.")
    async def craftlist(self, interaction: discord.Interaction):
        lines = []
        for item, (ingots, sticks) in RECIPES.items():
            cost = []
            if ingots:
                cost.append(f"{ingots} ingot(s)")
            if sticks:
                cost.append(f"{EMOJI['stick']} {sticks} stick(s)".strip())
            lines.append(f"{gear_icon(item, 'iron')} **{item}** → " + " + ".join(cost))

        embed = discord.Embed(title="Crafting Recipes", description="\n".join(lines))
        embed.set_footer(text="Materials: " + ", ".join(MATERIALS))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- equipment ----------
    async def gear_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        pieces = await self.bot.db.run(shop.get_gear, interaction.user.id)
        current = current.lower()
        choices = []
        for g in pieces:
            name = f"{g['material']} {g['item']} ({g['durability']}/{g['max_durability']})"
            if g["enchants"]:
                name += f" — {enchants.labels(g['enchants'])}"
            if g["equipped"]:
                name += " — equipped"
            if current in name.lower():
                choices.append(app_commands.Choice(name=name[:100], value=g["gear_id"]))
        return choices[:25]

    @app_commands.command(name="equip", description="Equip a piece of gear (one per slot).")
    @app_commands.describe(piece="The piece to equip (start typing to search)")
    @app_commands.autocomplete(piece=gear_autocomplete)
    async def equip(self, interaction: discord.Interaction, piece: int):
        g = await self.bot.db.run(gear.equip, interaction.user.id, piece)
        await interaction.response.send_message(
            f"✅ Equipped {gear_label(g)} in the **{g['item']}** slot.", ephemeral=True
        )

    @app_commands.command(name="equip_best", description="Fill every empty slot with your best piece of gear.")
    async def equip_best(self, interaction: discord.Interaction):
        done = await self.bot.db.run(gear.equip_best, interaction.user.id)
        if not done:
            return await interaction.response.send_message("Nothing to equip: your slots are full or you have no spare gear.", ephemeral=True)
        await interaction.response.send_message(
            "✅ Equipped:\n" + "\n".join(f"- {gear_label(g)}" for g in done), ephemeral=True
        )

    @app_commands.command(name="unequip", description="Remove the piece of gear from a slot.")
    @app_commands.choices(slot=ITEM_CHOICES)
    async def unequip(self, interaction: discord.Interaction, slot: str):
        g = await self.bot.db.run(gear.unequip, interaction.user.id, slot)
        await interaction.response.send_message(f"✅ Unequipped {gear_label(g)}.", ephemeral=True)

    @app_commands.command(name="gear", description="Show your equipment and what each piece does.")
    async def gear_cmd(self, interaction: discord.Interaction):
        def load(ctx: Ctx, user_id: int):
            return gear.get_equipped(ctx, user_id), shop.get_gear(ctx, user_id)

        equipped, owned = await self.bot.db.run(load, interaction.user.id)
        lines = []
        for slot in GEAR_ITEMS:
            g = equipped.get(slot)
            if g:
                bar = progress_bar(g["durability"], g["max_durability"], width=8)
                lines.append(f"**{slot}**: {gear_label(g, show_durability=False)} `{bar}` {g['durability']}/{g['max_durability']}")
            else:
                lines.append(f"**{slot}**: — *({GEAR_EFFECTS[slot]})*")

        embed = discord.Embed(title=f"{interaction.user.display_name}'s equipment", description="\n".join(lines), color=discord.Color.dark_teal())
        embed.add_field(name="⚔️ Attack", value=str(gear.attack_damage(equipped)), inline=True)
        embed.add_field(name="🛡️ Damage reduction", value=f"{gear.damage_reduction(equipped):.0%}", inline=True)
        spare = [g for g in owned if not g["equipped"]]
        if spare:
            embed.add_field(name="Spare gear", value=join_lines([gear_label(g) for g in spare]), inline=False)
        embed.set_footer(text="Gear wears out when used and breaks at 0 durability.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCraftCog(bot))
