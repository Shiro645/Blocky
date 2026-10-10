from __future__ import annotations

import discord
from discord import AppCommandOptionType, app_commands
from discord.ext import commands

from game import settings
from utils import manual
from utils.checks import is_staff
from utils.ui import BaseView, join_lines

TYPE_NAMES = {
    AppCommandOptionType.string: "text",
    AppCommandOptionType.integer: "whole number",
    AppCommandOptionType.number: "number",
    AppCommandOptionType.boolean: "yes / no",
    AppCommandOptionType.user: "member",
    AppCommandOptionType.channel: "channel",
    AppCommandOptionType.role: "role",
    AppCommandOptionType.mentionable: "member or role",
    AppCommandOptionType.attachment: "file",
}
NO_DESCRIPTION = "…"  # what discord.py uses when a command or option has no description
COLOR = discord.Color.blurple()


def short(description: str) -> str:
    """'STAFF: Warn a member.' -> 'Warn a member.' (the staff categories already say it)."""
    return description.removeprefix("STAFF: ").strip()


def option_line(p: app_commands.Parameter) -> str:
    """'`stake` · whole number, at least 1 · required — Emeralds each player bets'"""
    kind = TYPE_NAMES.get(p.type, "value")
    lo, hi = p.min_value, p.max_value
    if p.choices:
        kind = "a choice"
    elif p.autocomplete:
        kind = "pick a suggestion"
    elif p.type is AppCommandOptionType.string:
        if hi is not None:
            kind += f", up to {hi} characters"
    elif lo is not None and hi is not None:
        kind += f", {lo:,}–{hi:,}"
    elif lo is not None:
        kind += f", at least {lo:,}"
    elif hi is not None:
        kind += f", at most {hi:,}"
    if p.required:
        state = "required"
    else:
        state = "optional"
        default = next((c.name for c in p.choices if c.value == p.default), p.default)
        if default not in (None, "") and default is not discord.utils.MISSING:
            state += f", default: {default}"
    line = f"`{p.display_name}` · {kind} · {state}"
    if p.description and p.description != NO_DESCRIPTION:
        line += f" — {p.description}"
    if p.choices:
        names = ", ".join(c.name for c in p.choices[:12])
        line += f"\n  ↳ {names}{'…' if len(p.choices) > 12 else ''}"
    return line


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- command tree ----------
    def tree_command(self, name: str) -> app_commands.Command | None:
        """The slash command of a page ('team create' -> the create subcommand of /team)."""
        first, _, rest = name.partition(" ")
        cmd = self.bot.tree.get_command(first)
        if rest and isinstance(cmd, app_commands.Group):
            cmd = cmd.get_command(rest)
        return cmd if isinstance(cmd, app_commands.Command) else None

    def summary(self, page: manual.Page) -> str:
        """One line about a page, for menus and suggestions."""
        cmd = self.tree_command(page.name)
        if cmd is not None and cmd.description and cmd.description != NO_DESCRIPTION:
            return short(cmd.description)
        return page.text.split("\n")[0].split(". ")[0].replace("**", "").rstrip(".") + "."

    # ---------- embeds ----------
    def home_embed(self, staff: bool) -> discord.Embed:
        embed = discord.Embed(
            title="📖 Blocky manual",
            description=(
                "Pick a category below, then a command to read its page: what it does, its options, "
                "its current numbers, examples and related commands.\n"
                "Shortcut: `/help command:<name>`, e.g. `/help command:duel`.\n\n"
                "💬 **Chat in the server to mine blocks**: see `/help command:mining`."
            ),
            color=COLOR,
        )
        for key in manual.categories(staff):
            names = [p.heading if p.is_topic else f"`/{p.name}`" for p in manual.in_category(key)]
            embed.add_field(name=manual.CATEGORIES[key][0], value=join_lines([" · ".join(names)]), inline=False)
        return embed

    def category_embed(self, category: str) -> discord.Embed:
        label, staff_only = manual.CATEGORIES[category]
        lines = [
            (f"**{p.heading}**" if p.is_topic else f"`/{p.name}`") + f" — {self.summary(p)}"
            for p in manual.in_category(category)
        ]
        if staff_only:
            lines.append("\n*Staff commands. Each use is written in the staff log channel.*")
        embed = discord.Embed(title=label, description="\n".join(lines)[:4096], color=COLOR)
        embed.set_footer(text="Pick a command below to open its page.")
        return embed

    def page_embed(self, page: manual.Page, staff: bool) -> discord.Embed:
        embed = discord.Embed(title=page.heading, description=page.text, color=COLOR)
        cmd = self.tree_command(page.name)
        if cmd is not None:
            options = [option_line(p) for p in cmd.parameters]
            embed.add_field(name="⚙️ Options", value=join_lines(options, empty="No options."), inline=False)
        values = page.current_values(settings.get())
        if values:
            embed.add_field(name="📊 Current values", value=join_lines(values), inline=False)
        if page.examples:
            examples = []
            for example in page.examples:
                command, _, note = example.partition(" → ")
                examples.append(f"`{command}`" + (f" → {note}" if note else ""))
            embed.add_field(name="💡 Examples", value=join_lines(examples), inline=False)
        related = [manual.BY_NAME[name] for name in page.related]
        related = [p.heading if p.is_topic else f"`/{p.name}`" for p in related if staff or not p.staff]
        if related:
            embed.add_field(name="🔗 See also", value=" · ".join(related), inline=False)
        embed.set_footer(text=f"{manual.CATEGORIES[page.category][0]} · numbers follow the server settings")
        return embed

    # ---------- command ----------
    async def page_autocomplete(self, interaction: discord.Interaction, current: str):
        staff = is_staff(interaction.user)
        return [
            app_commands.Choice(name=f"{p.heading} — {self.summary(p)}"[:100], value=p.name)
            for p in manual.search(current, staff)
        ]

    @app_commands.command(name="help", description="The manual: every command, how it works and its current numbers.")
    @app_commands.describe(command="A command to read its page directly (start typing)")
    @app_commands.autocomplete(command=page_autocomplete)
    async def help(self, interaction: discord.Interaction, command: str | None = None):
        staff = is_staff(interaction.user)
        if command:
            page = manual.find(command, staff)
            if page is None:
                await interaction.response.send_message(
                    f"❌ No page for `{command[:50]}`. Pick a command from the suggestions, or use `/help` alone.",
                    ephemeral=True,
                )
                return
            embed, view = self.page_embed(page, staff), HelpView(self, interaction.user.id, staff, page.category, page.name)
        else:
            embed, view = self.home_embed(staff), HelpView(self, interaction.user.id, staff)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


# ---------------- menus ----------------
class HelpView(BaseView):
    def __init__(self, cog: HelpCog, user_id: int, staff: bool, category: str | None = None, page: str | None = None):
        super().__init__(allowed_ids={user_id}, timeout=600)
        self.cog, self.user_id, self.staff = cog, user_id, staff
        self.add_item(CategorySelect(category, staff))
        if category:
            self.add_item(PageSelect(category, page))
            self.add_item(HomeButton())

    async def show(self, interaction: discord.Interaction, embed: discord.Embed, category: str | None, page: str | None = None):
        """Replace the message with another screen of the manual."""
        view = HelpView(self.cog, self.user_id, self.staff, category, page)
        view.message = self.message
        self.stop()  # the old menu must not come back when it times out
        await interaction.response.edit_message(embed=embed, view=view)


class CategorySelect(discord.ui.Select):
    view: HelpView

    def __init__(self, current: str | None, staff: bool):
        options = [
            discord.SelectOption(label=manual.CATEGORIES[key][0], value=key, default=key == current)
            for key in manual.categories(staff)
        ]
        super().__init__(placeholder="Choose a category…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await self.view.show(interaction, self.view.cog.category_embed(category), category)


class PageSelect(discord.ui.Select):
    view: HelpView

    def __init__(self, category: str, current: str | None):
        options = [
            discord.SelectOption(label=p.heading[:100], value=p.name, default=p.name == current)
            for p in manual.in_category(category)
        ][:25]
        super().__init__(placeholder="Open a command's page…", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        page = manual.BY_NAME[self.values[0]]
        await self.view.show(interaction, self.view.cog.page_embed(page, self.view.staff), page.category, page.name)


class HomeButton(discord.ui.Button):
    view: HelpView

    def __init__(self):
        super().__init__(label="All categories", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        await self.view.show(interaction, self.view.cog.home_embed(self.view.staff), None)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
