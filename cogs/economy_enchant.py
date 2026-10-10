from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from game import enchants, shop
from game.db import Ctx
from game.enchants import ENCHANTS, MAX_LEVEL, ROMAN
from utils.ui import book_icon, gear_label, join_lines, lapis_icon


def _overview(ctx: Ctx, user_id: int) -> dict:
    return {"lapis": enchants.lapis(ctx, user_id), "books": enchants.books(ctx, user_id)}


class EnchantCog(commands.Cog):
    enchant = app_commands.Group(name="enchant", description="Enchanted books: apply them to your gear with lapis lazuli.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- autocomplete ----------
    async def book_autocomplete(self, interaction: discord.Interaction, current: str):
        data = await self.bot.db.run(_overview, interaction.user.id)
        choices = []
        for name, level, amount in data["books"]:
            text = f"{enchants.label(name, level)} book ({amount})"
            if current.lower() in text.lower():
                choices.append(app_commands.Choice(name=text, value=enchants.book_material(name, level)))
        return choices[:25]

    async def piece_autocomplete(self, interaction: discord.Interaction, current: str):
        pieces = await self.bot.db.run(shop.get_gear, interaction.user.id)
        # Only the pieces the chosen book can go on.
        book = getattr(interaction.namespace, "book", None)
        allowed = None
        if book:
            try:
                allowed = ENCHANTS[enchants.parse_book(book)[0]].items
            except Exception:
                allowed = None
        choices = []
        for g in pieces:
            if allowed is not None and g["item"] not in allowed:
                continue
            text = f"{g['material']} {g['item']} ({g['durability']}/{g['max_durability']})"
            if g["enchants"]:
                text += f" — {enchants.labels(g['enchants'])}"
            if g["equipped"]:
                text += " — equipped"
            if current.lower() in text.lower():
                choices.append(app_commands.Choice(name=text[:100], value=g["gear_id"]))
        return choices[:25]

    # ---------- commands ----------
    @enchant.command(name="apply", description="Apply an enchanted book to a piece of gear (costs lapis lazuli).")
    @app_commands.describe(book="The book to use", piece="The piece of gear to enchant")
    @app_commands.autocomplete(book=book_autocomplete, piece=piece_autocomplete)
    async def apply(self, interaction: discord.Interaction, book: str, piece: int):
        res = await self.bot.db.run(enchants.apply, interaction.user.id, book, piece)
        text = f"✨ {gear_label(res['piece'])}\n**{enchants.label(res['name'], res['level'])}** applied for {lapis_icon()} {res['cost']} lapis."
        if res["replaced"]:
            text += f" It replaces {enchants.label(res['name'], res['replaced'])}."
        await interaction.response.send_message(text, ephemeral=True)

    @enchant.command(name="combine", description="Combine 2 identical books into 1 book of the next level.")
    @app_commands.describe(book="The book you have twice")
    @app_commands.autocomplete(book=book_autocomplete)
    async def combine(self, interaction: discord.Interaction, book: str):
        res = await self.bot.db.run(enchants.combine, interaction.user.id, book)
        await interaction.response.send_message(
            f"{book_icon()} 2 books combined into a **{enchants.label(res['name'], res['level'])}** book!", ephemeral=True
        )

    @enchant.command(name="info", description="Your books and lapis, and what each enchantment does.")
    async def info(self, interaction: discord.Interaction):
        data = await self.bot.db.run(_overview, interaction.user.id)
        costs = " / ".join(str(enchants.apply_cost(lvl)) for lvl in range(1, MAX_LEVEL + 1))
        embed = discord.Embed(
            title="✨ Enchanting",
            description=(
                f"{lapis_icon()} You have **{data['lapis']} lapis lazuli** (found while mining).\n"
                f"Applying a book costs **{costs} lapis** for level I / II / III and replaces a lower level. "
                "Two identical books combine into the next level with `/enchant combine`.\n"
                "Books come from drops, bosses (top damage), completing every weekly challenge, "
                "and other players (`/trade`, `/auction`)."
            ),
            color=discord.Color.purple(),
        )
        books = [f"{book_icon()} {enchants.label(n, lvl)} × {amount}" for n, lvl, amount in data["books"]]
        embed.add_field(name="Your books", value=join_lines(books, empty="No books yet."), inline=False)
        for e in ENCHANTS.values():
            effects = " · ".join(f"{ROMAN[lvl]}: {enchants.effect_text(e.key, lvl)}" for lvl in range(1, MAX_LEVEL + 1))
            on = "all gear" if len(e.items) > 5 else ", ".join(e.items)
            embed.add_field(name=f"{e.name} ({on})", value=effects[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EnchantCog(bot))
