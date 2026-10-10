from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import discord
from discord import app_commands
from discord.ext import commands

from game import backups, settings
from game.errors import GameError
from utils import config_edit as ce
from utils.checks import staff_only
from utils.config import CONFIG_PATH, balance_overrides, load_config, read_config_file, reload_config
from utils.ui import BaseView, report_error

log = logging.getLogger("admin_config")

TEXT_CHANNELS = [discord.ChannelType.text, discord.ChannelType.news]


def show(field: ce.Field, value: Any) -> str:
    if field.kind == "channel":
        return f"<#{value}>" if value else "*not set*"
    if field.kind == "channels":
        ids = value if isinstance(value, list) else []
        return ", ".join(f"<#{c}>" for c in ids) if ids else "*none*"
    if field.kind == "role":
        return f"<@&{value}>" if value else "*not set*"
    if value is None:
        return "*not set*"
    if field.kind == "text":
        text = str(value)
        return text if len(text) <= 80 else text[:79] + "…"
    return f"{value:g}" if isinstance(value, float) else str(value)


class ConfigCog(commands.Cog):
    """/config: guided menus to change config.json from Discord (staff)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def apply(self, user: discord.abc.User, label: str, before: str, after: str, mutate: Callable[[dict], dict]) -> str:
        """Change config.json, apply it right away, log it. Returns the confirmation text."""
        async with self.lock:
            try:
                change = ce.prepare_change(read_config_file(), mutate)
                if change.refused:
                    raise GameError("Not changed, this value isn't allowed:\n" + "\n".join(f"- {p}" for p in change.refused[:10]))
                ce.write_config(CONFIG_PATH, change.config, backups.backup_dir(self.bot.db.path))
                cfg = reload_config()
            except PermissionError as e:
                raise GameError(str(e))
            except ValueError as e:
                raise GameError(f"config.json is invalid, nothing was changed.\n{e}")
            except OSError as e:
                raise GameError(f"Could not write config.json ({e}). Is it mounted read-only?")
            settings.load(settings.clean(balance_overrides(cfg))[0])

        embed = discord.Embed(title="⚙️ Config changed", color=discord.Color.blurple())
        embed.add_field(name="Setting", value=label, inline=False)
        embed.add_field(name="Before", value=before, inline=True)
        embed.add_field(name="After", value=after, inline=True)
        embed.add_field(name="By", value=f"{user.mention} (`{user}`)", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")
        log.info("%s changed %s: %s -> %s", user, label, before, after)
        text = f"✅ **{label}**: {before} → {after}"
        if change.cleaned:
            removed = "\n".join(f"- {p}" for p in change.cleaned[:10])
            text += f"\n🧹 Also removed from config.json (the bot didn't use them):\n{removed}"
            log.info("Removed from config.json: %s", "; ".join(change.cleaned))
        return text

    async def set_field(self, interaction: discord.Interaction, field: ce.Field, value: Any) -> str:
        """Set a field (None = clear it, or back to the default for balance settings)."""
        before = show(field, ce.current_value(load_config(), field))
        if value is None and field.is_balance:
            after = show(field, ce.current_value({}, field)) + " *(default)*"
        else:
            after = show(field, value)
        return await self.apply(
            interaction.user, field.label, before, after,
            lambda cfg: ce.set_value(cfg, field.path, value),
        )

    def category_embed(self, category: str) -> discord.Embed:
        cfg = load_config()
        embed = discord.Embed(title=f"⚙️ Config — {ce.CATEGORIES[category]}", color=discord.Color.blurple())
        if category == "level_roles":
            roles = ce.level_roles(cfg)
            embed.description = "\n".join(f"Level **{lvl}** → <@&{rid}>" for lvl, rid in roles.items()) or "No level role yet."
        else:
            embed.description = "\n".join(f"**{f.label}**: {show(f, ce.current_value(cfg, f))}" for f in ce.fields_in(category))
        embed.set_footer(text="Pick a setting below to change it.")
        return embed

    @app_commands.command(name="config", description="STAFF: Change the bot settings (channels, roles, prices, gameplay…).")
    @staff_only()
    async def config_cmd(self, interaction: discord.Interaction):
        view = MenuView(self, interaction.user.id)
        embed = discord.Embed(
            title="⚙️ Bot configuration",
            description="Choose a category. Changes apply immediately, the previous config.json is saved "
                        "in the backups folder and every change is logged in the staff channel.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------------- menus ----------------
class MenuView(BaseView):
    def __init__(self, cog: ConfigCog, user_id: int, category: str | None = None):
        super().__init__(allowed_ids={user_id}, timeout=600)
        self.cog, self.user_id = cog, user_id
        self.add_item(CategorySelect(cog, user_id, category))
        if category == "level_roles":
            self.add_item(AddLevelRoleButton(cog))
            if ce.level_roles(load_config()):
                self.add_item(RemoveLevelRoleSelect(cog))
        elif category:
            self.add_item(FieldSelect(cog, category))


class CategorySelect(discord.ui.Select):
    def __init__(self, cog: ConfigCog, user_id: int, current: str | None):
        self.cog, self.user_id = cog, user_id
        options = [
            discord.SelectOption(label=label, value=key, default=key == current)
            for key, label in ce.CATEGORIES.items()
        ]
        super().__init__(placeholder="Choose a category…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await interaction.response.edit_message(
            embed=self.cog.category_embed(category), view=MenuView(self.cog, self.user_id, category)
        )


class FieldSelect(discord.ui.Select):
    def __init__(self, cog: ConfigCog, category: str):
        self.cog = cog
        cfg = load_config()
        options = [
            discord.SelectOption(label=f.label[:100], value=f.key, description=self.describe(f, ce.current_value(cfg, f)))
            for f in ce.fields_in(category)
        ]
        super().__init__(placeholder="Choose a setting to change…", options=options, row=1)

    @staticmethod
    def describe(field: ce.Field, value: Any) -> str:
        # Select descriptions can't render mentions: just say whether it is set.
        if field.kind == "channels":
            count = len(value) if isinstance(value, list) else 0
            return f"Now: {count} channel(s)"
        if field.kind in ("channel", "role"):
            return "Now: set" if value else "Now: not set"
        return f"Now: {show(field, value)}".replace("*", "")[:100]

    async def callback(self, interaction: discord.Interaction):
        field = ce.FIELDS_BY_KEY[self.values[0]]
        if field.kind in ("channel", "channels"):
            view = PickerView(self.cog, field, interaction.user.id)
            view.add_item(ChannelPicker(self.cog, field))
            await interaction.response.send_message(f"Choose the **{field.label}**:", view=view, ephemeral=True)
        elif field.kind == "role":
            view = PickerView(self.cog, field, interaction.user.id)
            view.add_item(RolePicker(self.cog, field))
            await interaction.response.send_message(f"Choose the **{field.label}**:", view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(ValueModal(self.cog, field))


class PickerView(BaseView):
    """Holds a channel/role picker and a button to clear the setting."""

    def __init__(self, cog: ConfigCog, field: ce.Field, user_id: int):
        super().__init__(allowed_ids={user_id}, timeout=300)
        self.cog, self.field = cog, field

    @discord.ui.button(label="Clear (not set)", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        text = await self.cog.set_field(interaction, self.field, None)
        await interaction.response.edit_message(content=text, view=None)


class ChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, cog: ConfigCog, field: ce.Field):
        self.cog, self.field = cog, field
        many = field.kind == "channels"
        super().__init__(
            channel_types=TEXT_CHANNELS, placeholder="Choose channels…" if many else "Choose a channel…",
            min_values=1, max_values=25 if many else 1, row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.field.kind == "channels":
            value: Any = [c.id for c in self.values]
        else:
            value = self.values[0].id
        text = await self.cog.set_field(interaction, self.field, value)
        await interaction.response.edit_message(content=text, view=None)


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, cog: ConfigCog, field: ce.Field):
        self.cog, self.field = cog, field
        super().__init__(placeholder="Choose a role…", row=0)

    async def callback(self, interaction: discord.Interaction):
        text = await self.cog.set_field(interaction, self.field, self.values[0].id)
        await interaction.response.edit_message(content=text, view=None)


class ValueModal(discord.ui.Modal):
    def __init__(self, cog: ConfigCog, field: ce.Field):
        super().__init__(title=field.label[:45])
        self.cog, self.field = cog, field
        current = ce.current_value(load_config(), field)
        hint = "Leave empty to go back to the default" if field.is_balance else ""
        self.value = discord.ui.TextInput(
            label="New value"[:45],
            default="" if current is None else (f"{current:g}" if isinstance(current, float) else str(current)),
            placeholder=hint or None,
            required=not field.is_balance,
            style=discord.TextStyle.paragraph if field.kind == "text" else discord.TextStyle.short,
            max_length=1000 if field.kind == "text" else 20,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = ce.parse(self.field, str(self.value.value))
        except ValueError as e:
            raise GameError(str(e))
        text = await self.cog.set_field(interaction, self.field, value)
        await interaction.response.send_message(text, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


# ---------------- level roles ----------------
class AddLevelRoleButton(discord.ui.Button):
    def __init__(self, cog: ConfigCog):
        self.cog = cog
        super().__init__(label="Add / replace a level role", style=discord.ButtonStyle.success, emoji="➕", row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelModal(self.cog))


class LevelModal(discord.ui.Modal, title="Level role"):
    level = discord.ui.TextInput(label="Level at which the role is given", placeholder="e.g. 10", max_length=5)

    def __init__(self, cog: ConfigCog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(str(self.level.value).strip())
        except ValueError:
            raise GameError("The level must be a whole number.")
        if level < 1:
            raise GameError("The level must be at least 1.")
        view = BaseView(allowed_ids={interaction.user.id}, timeout=300)
        view.add_item(LevelRolePicker(self.cog, level))
        await interaction.response.send_message(f"Choose the role given at level **{level}**:", view=view, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class LevelRolePicker(discord.ui.RoleSelect):
    def __init__(self, cog: ConfigCog, level: int):
        self.cog, self.level = cog, level
        super().__init__(placeholder="Choose a role…")

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        before = ce.level_roles(load_config()).get(self.level)
        text = await self.cog.apply(
            interaction.user, f"Level {self.level} role",
            f"<@&{before}>" if before else "*none*", role.mention,
            lambda cfg: ce.set_level_role(cfg, self.level, role.id),
        )
        await interaction.response.edit_message(
            content=text + "\nRun `/player sync_roles` to update members who already passed this level.", view=None
        )


class RemoveLevelRoleSelect(discord.ui.Select):
    def __init__(self, cog: ConfigCog):
        self.cog = cog
        options = [
            discord.SelectOption(label=f"Remove the level {lvl} role", value=str(lvl))
            for lvl in ce.level_roles(load_config())
        ][:25]
        super().__init__(placeholder="Remove a level role…", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        level = int(self.values[0])
        before = ce.level_roles(load_config()).get(level)
        text = await self.cog.apply(
            interaction.user, f"Level {level} role", f"<@&{before}>" if before else "*none*", "*removed*",
            lambda cfg: ce.set_level_role(cfg, level, None),
        )
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCog(bot))
