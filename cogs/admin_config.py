from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, replace
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
PAGE_SIZE = 25  # options in a select menu
COLOR = discord.Color.blurple()


def show(field: ce.Field, value: Any) -> str:
    """A value for the embeds (channels and roles as mentions)."""
    if field.kind == "channel":
        return f"<#{value}>" if value else "*not set*"
    if field.kind == "channels":
        ids = value if isinstance(value, list) else []
        return ", ".join(f"<#{c}>" for c in ids) if ids else "*none*"
    if field.kind == "role":
        return f"<@&{value}>" if value else "*not set*"
    if value is None:
        return "*not set*"
    return ce.display(field, value)


def short(field: ce.Field, value: Any) -> str:
    """A value for select menus (they can't show mentions)."""
    if field.kind == "channels":
        return f"{len(value) if isinstance(value, list) else 0} channel(s)"
    if field.kind in ("channel", "role"):
        return "set" if value else "not set"
    return show(field, value).replace("*", "")


@dataclass(frozen=True)
class Screen:
    """Where the /config message is: a category page, a setting, maybe an editor mode."""

    category: str | None = None
    page: int = 0
    field: str | None = None  # a key of ce.FIELDS_BY_KEY
    mode: str | None = None  # "add": picking what a new table line gives
    role_page: int = 0  # page of the role list (level roles, role settings)


def role_list(guild: discord.Guild | None, assignable: bool) -> list[discord.Role]:
    """The server's roles for a menu, the highest first.

    Discord's own role menu only shows some of the roles, so the bot lists them itself.
    Bot and integration roles are left out, and for roles the bot gives (level and champion
    roles) the ones above the bot's own role too: it couldn't give them.
    """
    if guild is None:
        return []
    roles = [r for r in reversed(guild.roles) if not r.is_default() and not r.managed]
    top = guild.me.top_role if guild.me is not None else None
    if assignable and top is not None:
        roles = [r for r in roles if r < top]
    return roles


class ConfigCog(commands.Cog):
    """/config: guided menus to change config.json from Discord (staff)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    # ---------- saving ----------
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

        embed = discord.Embed(title="⚙️ Config changed", color=COLOR)
        embed.add_field(name="Setting", value=label, inline=False)
        embed.add_field(name="Before", value=before[:1024], inline=True)
        embed.add_field(name="After", value=after[:1024], inline=True)
        embed.add_field(name="By", value=f"{user.mention} (`{user}`)", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")
        log.info("%s changed %s: %s -> %s", user, label, before, after)
        text = f"✅ **{label}**: {before} → {after}"
        if change.cleaned:
            removed = "\n".join(f"- {p}" for p in change.cleaned[:10])
            text += f"\n🧹 Also removed from config.json (the bot didn't use them):\n{removed}"
            log.info("Removed from config.json: %s", "; ".join(change.cleaned))
        return text

    async def save(self, user: discord.abc.User, field: ce.Field, value: Any) -> str:
        """Set a field (None = clear it, or back to the default for a game setting)."""
        before = show(field, ce.current_value(load_config(), field))
        if value is None and field.is_balance:
            after = show(field, ce.default_value(field)) + " *(default)*"
        else:
            after = show(field, value)
        return await self.apply(user, field.label, before, after, lambda cfg: ce.set_field(cfg, field, value))

    async def save_whole(self, user: discord.abc.User, field: ce.Field, value: Any, what: str) -> str:
        """Replace a list, the automatic mutes or a table (`what` says what changed)."""
        before = show(field, ce.current_value(load_config(), field))
        return await self.apply(user, field.label, before, what, lambda cfg: ce.set_whole(cfg, field, value))

    # ---------- embeds ----------
    def home_embed(self) -> discord.Embed:
        return discord.Embed(
            title="⚙️ Bot configuration",
            description=(
                "Choose a category, then a setting: you'll see what it does, its value and its default.\n"
                "Changes apply immediately, the previous config.json is saved in the backups folder and "
                "every change is logged in the staff channel."
            ),
            color=COLOR,
        )

    def category_embed(self, category: str, page: int = 0) -> discord.Embed:
        cfg = load_config()
        embed = discord.Embed(title=f"⚙️ {ce.CATEGORIES[category]}", color=COLOR)
        if category == "level_roles":
            roles = ce.level_roles(cfg)
            embed.description = "\n".join(f"Level **{lvl}** → <@&{rid}>" for lvl, rid in roles.items()) or "No level role yet."
            embed.add_field(
                name="Add or change one",
                value="Pick the role in the menu below, then type the level. Members keep the highest role reached.\n"
                      "Roles above the bot's own role aren't listed (it couldn't give them): move the bot's role "
                      "higher in Server Settings → Roles.",
                inline=False,
            )
            return embed
        used = ce.used_settings(cfg)
        fields = ce.fields_in(category)
        pages = max(1, -(-len(fields) // PAGE_SIZE))
        lines = []
        for f in fields[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
            mark = "✏️ " if ce.is_modified(cfg, f, used) else ""
            lines.append(f"{mark}**{f.label}**: {show(f, ce.current_value(cfg, f, used))}")
        embed.description = "\n".join(lines)[:4096]
        footer = "Pick a setting below. ✏️ = changed from the default."
        embed.set_footer(text=footer + (f" · Page {page + 1}/{pages}" if pages > 1 else ""))
        return embed

    def field_embed(self, field: ce.Field, note: str | None = None) -> discord.Embed:
        cfg = load_config()
        value = ce.current_value(cfg, field)
        embed = discord.Embed(title=f"⚙️ {field.label}", description=field.help or None, color=COLOR)
        if note:
            embed.description = f"{note}\n\n{field.help}" if field.help else note
        embed.add_field(name="Now", value=self.value_text(field, value)[:1024], inline=True)
        if field.is_balance:
            embed.add_field(name="Default", value=self.value_text(field, ce.default_value(field))[:1024], inline=True)
        limits = self.limits(field)
        if limits:
            embed.add_field(name="Allowed", value=limits, inline=True)
        embed.set_footer(text=ce.CATEGORIES[field.category])
        return embed

    def value_text(self, field: ce.Field, value: Any) -> str:
        """Lists and tables line by line in the setting's card."""
        if field.kind == "list":
            return "\n".join(f"{i + 1}. {v:,}" if isinstance(v, int) else f"{i + 1}. {v}" for i, v in enumerate(value)) or "*none*"
        if field.kind == "map":
            rules = sorted(value.items(), key=lambda kv: int(kv[0]))
            return "\n".join(f"{n} warnings → {d}" for n, d in rules) or "*none*"
        if field.kind == "table" and field.item == "drops":
            total = sum(float(r["weight"]) for r in value) or 1
            return "\n".join(
                f"{i + 1}. {r['title']} · {ce.reward_label(r['reward'])} · {float(r['weight']) / total:.0%}"
                for i, r in enumerate(value)
            ) or "*none*"
        if field.kind == "table":
            return "\n".join(f"{i + 1}. {ce.good_label(g)}" for i, g in enumerate(value)) or "*none*"
        return show(field, value)

    @staticmethod
    def limits(field: ce.Field) -> str:
        if field.kind == "percent":
            return f"{ce.percent(field.min or 0)} to {ce.percent(field.max)}" if field.max is not None else ""
        if field.kind in ("int", "float") and field.min is not None:
            top = f"{field.max:,g}" if field.max is not None else "∞"
            return f"{field.min:,g} to {top}" + (" (whole number)" if field.kind == "int" else "")
        return ""

    # ---------- command ----------
    @app_commands.command(name="config", description="STAFF: Change the bot settings (channels, roles, prices, gameplay…).")
    @staff_only()
    async def config_cmd(self, interaction: discord.Interaction):
        view = ConfigView(self, interaction.user.id, Screen(), interaction.guild)
        await interaction.response.send_message(embed=self.home_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


# ---------------- the menu ----------------
class ConfigView(BaseView):
    """The whole /config message: it is rebuilt for every screen."""

    def __init__(self, cog: ConfigCog, user_id: int, screen: Screen, guild: discord.Guild | None = None):
        super().__init__(allowed_ids={user_id}, timeout=600)
        self.cog, self.user_id, self.screen, self.guild = cog, user_id, screen, guild
        self.add_item(CategorySelect(screen.category))
        field = ce.FIELDS_BY_KEY.get(screen.field) if screen.field else None
        if field is not None:
            self.field_controls(field)
        elif screen.category == "level_roles":
            self.role_controls(assignable=True)
            if ce.level_roles(load_config()):
                self.add_item(RemoveLevelRoleSelect())
        elif screen.category:
            fields = ce.fields_in(screen.category)
            self.add_item(FieldSelect(fields[screen.page * PAGE_SIZE:(screen.page + 1) * PAGE_SIZE]))
            if len(fields) > PAGE_SIZE:
                self.add_item(PageButton(-1, disabled=screen.page == 0))
                self.add_item(PageButton(+1, disabled=(screen.page + 1) * PAGE_SIZE >= len(fields)))

    def field_controls(self, field: ce.Field) -> None:
        cfg = load_config()
        value = ce.current_value(cfg, field)
        modified = ce.is_modified(cfg, field)
        if field.kind in ("channel", "channels"):
            self.add_item(ChannelPicker(field))
            self.add_item(ClearButton(disabled=not value))
        elif field.kind == "role":
            self.role_controls(assignable=field.item == "assign")
            self.add_item(ClearButton(disabled=not value))
        elif field.typed:
            self.add_item(ChangeButton())
        elif field.kind == "bool":
            self.add_item(ToggleButton(bool(value)))
        elif field.kind == "choice":
            self.add_item(ChoiceSelect(field, value))
        elif field.kind == "list":
            if value:
                self.add_item(ItemSelect([(f"{i + 1}. {v}", str(i)) for i, v in enumerate(value)], "Change an entry…"))
            self.add_item(AddButton(disabled=len(value) >= field.max_items))
            self.add_item(RemoveLastButton(disabled=not value or (field.item == "text" and len(value) <= 1)))
        elif field.kind == "map":
            if value:
                rules = sorted(value.items(), key=lambda kv: int(kv[0]))
                self.add_item(ItemSelect([(f"Remove: {n} warnings → {d}", n) for n, d in rules], "Remove a rule…"))
            self.add_item(AddButton(label="Add / replace a rule", disabled=len(value) >= field.max_items))
        elif field.kind == "table":
            self.table_controls(field, value)
        if field.is_balance and field.kind not in ("channel", "channels", "role"):
            self.add_item(ResetButton(disabled=not modified))
        self.add_item(BackButton())

    def role_controls(self, assignable: bool) -> None:
        """A page of the server's roles (row 1) and the page buttons (row 2)."""
        roles = role_list(self.guild, assignable)
        pages = max(1, -(-len(roles) // PAGE_SIZE))
        page = min(self.screen.role_page, pages - 1)
        if roles:
            self.add_item(RoleChoiceSelect(roles[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page, pages))
        if pages > 1:
            self.add_item(RolePageButton(-1, disabled=page == 0))
            self.add_item(RolePageButton(+1, disabled=page >= pages - 1))

    def table_controls(self, field: ce.Field, rows: list) -> None:
        if self.screen.mode == "add":
            choices = ce.DROP_REWARDS if field.item == "drops" else ce.GOODS
            self.add_item(NewLineSelect(field, choices))
            return
        labels = [r["title"] for r in rows] if field.item == "drops" else [ce.good_label(g) for g in rows]
        if rows:
            self.add_item(ItemSelect([(f"Change: {i + 1}. {t}", str(i)) for i, t in enumerate(labels)], "Change a line…"))
            if len(rows) > 1:
                self.add_item(DeleteLineSelect([(f"Delete: {i + 1}. {t}", str(i)) for i, t in enumerate(labels)]))
        self.add_item(AddButton(label="Add a line", disabled=len(rows) >= field.max_items))

    @property
    def field(self) -> ce.Field:
        return ce.FIELDS_BY_KEY[self.screen.field]

    async def show(self, interaction: discord.Interaction, screen: Screen, note: str | None = None) -> None:
        """Replace the message with another screen."""
        view = ConfigView(self.cog, self.user_id, screen, self.guild)
        view.message = self.message
        self.stop()  # the old menu must not come back when it times out
        if screen.field:
            embed = self.cog.field_embed(ce.FIELDS_BY_KEY[screen.field], note)
        elif screen.category:
            embed = self.cog.category_embed(screen.category, screen.page)
            if note:
                embed.description = f"{note}\n\n{embed.description or ''}"[:4096]
        else:
            embed = self.cog.home_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def saved(self, interaction: discord.Interaction, note: str) -> None:
        """After a change: show the setting again with what changed."""
        await self.show(interaction, replace(self.screen, mode=None), note)


# ---------- navigation ----------
class CategorySelect(discord.ui.Select):
    view: ConfigView

    def __init__(self, current: str | None):
        options = [
            discord.SelectOption(label=label, value=key, default=key == current)
            for key, label in ce.CATEGORIES.items()
        ]
        super().__init__(placeholder="Choose a category…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.show(interaction, Screen(category=self.values[0]))


class FieldSelect(discord.ui.Select):
    view: ConfigView

    def __init__(self, fields: list[ce.Field]):
        cfg = load_config()
        used = ce.used_settings(cfg)
        options = []
        for f in fields:
            value = ce.current_value(cfg, f, used)
            text = f"Now: {short(f, value)}"
            if ce.is_modified(cfg, f, used):
                text = f"✏️ {text} · default {short(f, ce.default_value(f))}"
            options.append(discord.SelectOption(label=f.label[:100], value=f.key, description=text[:100]))
        super().__init__(placeholder="Choose a setting…", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        screen = self.view.screen
        await self.view.show(interaction, replace(screen, field=self.values[0]))


class PageButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, step: int, disabled: bool):
        super().__init__(label="Previous" if step < 0 else "Next", emoji="◀️" if step < 0 else "▶️",
                         style=discord.ButtonStyle.secondary, row=2, disabled=disabled)
        self.step = step

    async def callback(self, interaction: discord.Interaction):
        screen = self.view.screen
        await self.view.show(interaction, replace(screen, page=max(0, screen.page + self.step)))


class BackButton(discord.ui.Button):
    view: ConfigView

    def __init__(self):
        super().__init__(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        screen = self.view.screen
        if screen.mode:
            await self.view.show(interaction, replace(screen, mode=None))
        else:
            await self.view.show(interaction, replace(screen, field=None))


class ResetButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, disabled: bool):
        super().__init__(label="Reset to default", emoji="🔄", style=discord.ButtonStyle.danger, row=4, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        field = self.view.field
        if field.kind in ("list", "map", "table"):
            note = await self.view.cog.save_whole(interaction.user, field, ce.default_value(field), "*default*")
        else:
            note = await self.view.cog.save(interaction.user, field, None)
        await self.view.saved(interaction, note)


# ---------- simple values ----------
class ChangeButton(discord.ui.Button):
    view: ConfigView

    def __init__(self):
        super().__init__(label="Change", emoji="✏️", style=discord.ButtonStyle.primary, row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ValueModal(self.view))


class ValueModal(discord.ui.Modal):
    def __init__(self, view: ConfigView):
        field = view.field
        super().__init__(title=field.label[:45])
        self.menu = view
        current = ce.current_value(load_config(), field)
        hint = f"Empty = default ({ce.as_text(field, ce.default_value(field))})" if field.is_balance else ""
        unit = " (%)" if field.kind == "percent" else ""
        self.value = discord.ui.TextInput(
            label=f"New value{unit}"[:45],
            default=ce.as_text(field, current),
            placeholder=hint[:100] or None,
            required=not field.is_balance,
            style=discord.TextStyle.paragraph if field.kind == "text" else discord.TextStyle.short,
            max_length=1000 if field.kind == "text" else 64,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        field = self.menu.field
        try:
            value = ce.parse(field, str(self.value.value))
        except ValueError as e:
            raise GameError(str(e))
        note = await self.menu.cog.save(interaction.user, field, value)
        await self.menu.saved(interaction, note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class ToggleButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, on: bool):
        super().__init__(label="Turn off" if on else "Turn on", emoji="🔴" if on else "🟢",
                         style=discord.ButtonStyle.primary, row=4)
        self.on = on

    async def callback(self, interaction: discord.Interaction):
        note = await self.view.cog.save(interaction.user, self.view.field, not self.on)
        await self.view.saved(interaction, note)


class ChoiceSelect(discord.ui.Select):
    view: ConfigView

    def __init__(self, field: ce.Field, current: Any):
        options = [
            discord.SelectOption(label=label, value=str(i), default=value == current)
            for i, (label, value) in enumerate(field.choices)
        ]
        super().__init__(placeholder="Choose…", options=options, row=1)
        self.choices = field.choices

    async def callback(self, interaction: discord.Interaction):
        value = self.choices[int(self.values[0])][1]
        note = await self.view.cog.save(interaction.user, self.view.field, value)
        await self.view.saved(interaction, note)


class ChannelPicker(discord.ui.ChannelSelect):
    view: ConfigView

    def __init__(self, field: ce.Field):
        many = field.kind == "channels"
        super().__init__(
            channel_types=TEXT_CHANNELS, placeholder="Choose channels…" if many else "Choose a channel…",
            min_values=1, max_values=25 if many else 1, row=1,
        )
        self.many = many

    async def callback(self, interaction: discord.Interaction):
        value: Any = [c.id for c in self.values] if self.many else self.values[0].id
        note = await self.view.cog.save(interaction.user, self.view.field, value)
        await self.view.saved(interaction, note)


class RoleChoiceSelect(discord.ui.Select):
    """A page of the server's roles: for a role setting, or a new level role."""

    view: ConfigView

    def __init__(self, roles: list[discord.Role], page: int, pages: int):
        levels = {rid: lvl for lvl, rid in ce.level_roles(load_config()).items()}
        options = []
        for role in roles:
            note = f"Now given at level {levels[role.id]}" if role.id in levels else None
            options.append(discord.SelectOption(label=role.name[:100] or str(role.id), value=str(role.id), description=note))
        where = f" (page {page + 1}/{pages})" if pages > 1 else ""
        super().__init__(placeholder=f"Choose a role…{where}", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        if self.view.screen.field:
            note = await self.view.cog.save(interaction.user, self.view.field, role_id)
            await self.view.saved(interaction, note)
        else:  # a level role: ask the level
            await interaction.response.send_modal(LevelModal(self.view, role_id))


class RolePageButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, step: int, disabled: bool):
        super().__init__(label="More roles" if step > 0 else "Previous roles", emoji="▶️" if step > 0 else "◀️",
                         style=discord.ButtonStyle.secondary, row=2, disabled=disabled)
        self.step = step

    async def callback(self, interaction: discord.Interaction):
        screen = self.view.screen
        await self.view.show(interaction, replace(screen, role_page=max(0, screen.role_page + self.step)))


class ClearButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, disabled: bool):
        super().__init__(label="Clear (not set)", emoji="🧹", style=discord.ButtonStyle.secondary, row=4, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        note = await self.view.cog.save(interaction.user, self.view.field, None)
        await self.view.saved(interaction, note)


# ---------- lists, automatic mutes and tables ----------
class ItemSelect(discord.ui.Select):
    """Pick an entry: change it (list, table) or remove it (automatic mutes)."""

    view: ConfigView

    def __init__(self, entries: list[tuple[str, str]], placeholder: str):
        options = [discord.SelectOption(label=label[:100], value=value) for label, value in entries[:25]]
        super().__init__(placeholder=placeholder, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        field = self.view.field
        choice = self.values[0]
        if field.kind == "map":
            rules = dict(ce.current_value(load_config(), field))
            removed = rules.pop(choice, None)
            note = await self.view.cog.save_whole(interaction.user, field, rules, f"removed {choice} warnings → {removed}")
            await self.view.saved(interaction, note)
        elif field.kind == "list":
            await interaction.response.send_modal(ListItemModal(self.view, int(choice)))
        else:
            await interaction.response.send_modal(LineModal(self.view, int(choice)))


class AddButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, label: str = "Add", disabled: bool = False):
        super().__init__(label=label, emoji="➕", style=discord.ButtonStyle.success, row=3, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        field = self.view.field
        if field.kind == "list":
            await interaction.response.send_modal(ListItemModal(self.view, None))
        elif field.kind == "map":
            await interaction.response.send_modal(MuteRuleModal(self.view))
        else:  # a table: first pick what the new line gives
            await self.view.show(interaction, replace(self.view.screen, mode="add"))


class RemoveLastButton(discord.ui.Button):
    view: ConfigView

    def __init__(self, disabled: bool):
        super().__init__(label="Remove the last one", emoji="➖", style=discord.ButtonStyle.secondary, row=3, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        field = self.view.field
        values = list(ce.current_value(load_config(), field))
        if not values:
            raise GameError("The list is already empty.")
        removed = values.pop()
        note = await self.view.cog.save_whole(interaction.user, field, values, f"removed {removed}")
        await self.view.saved(interaction, note)


class ListItemModal(discord.ui.Modal):
    """Change an entry of a list (index) or add one (None)."""

    def __init__(self, view: ConfigView, index: int | None):
        field = view.field
        super().__init__(title=field.label[:45])
        self.menu, self.index = view, index
        values = ce.current_value(load_config(), field)
        current = "" if index is None or index >= len(values) else str(values[index])
        label = "New entry" if index is None else f"Entry {index + 1}"
        self.value = discord.ui.TextInput(label=label, default=current, max_length=64)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        field = self.menu.field
        try:
            item = ce.parse_item(field, str(self.value.value))
        except ValueError as e:
            raise GameError(str(e))
        values = list(ce.current_value(load_config(), field))
        if self.index is None:
            if len(values) >= field.max_items:
                raise GameError(f"At most {field.max_items} entries.")
            values.append(item)
            what = f"added {item}"
        else:
            if self.index >= len(values):
                raise GameError("This entry doesn't exist anymore.")
            what = f"entry {self.index + 1}: {values[self.index]} → {item}"
            values[self.index] = item
        note = await self.menu.cog.save_whole(interaction.user, field, values, what)
        await self.menu.saved(interaction, note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class MuteRuleModal(discord.ui.Modal, title="Automatic mute"):
    count = discord.ui.TextInput(label="Number of active warnings", placeholder="e.g. 3", max_length=3)
    duration = discord.ui.TextInput(label="Mute duration", placeholder="e.g. 30m, 2h, 1d, 1w or perm", max_length=12)

    def __init__(self, view: ConfigView):
        super().__init__()
        self.menu = view

    async def on_submit(self, interaction: discord.Interaction):
        field = self.menu.field
        try:
            count, duration = ce.mute_rule(str(self.count.value), str(self.duration.value))
        except ValueError as e:
            raise GameError(str(e))
        rules = dict(ce.current_value(load_config(), field))
        if count not in rules and len(rules) >= field.max_items:
            raise GameError(f"At most {field.max_items} rules.")
        rules[count] = duration
        note = await self.menu.cog.save_whole(interaction.user, field, rules, f"{count} warnings → {duration}")
        await self.menu.saved(interaction, note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class NewLineSelect(discord.ui.Select):
    """What a new line of the drop table / the villager's goods gives."""

    view: ConfigView

    def __init__(self, field: ce.Field, choices: tuple[tuple[str, str], ...]):
        options = [discord.SelectOption(label=label, value=key) for key, label in choices]
        what = "What does the new drop give?" if field.item == "drops" else "What does he sell?"
        super().__init__(placeholder=what, options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LineModal(self.view, None, self.values[0]))


class LineModal(discord.ui.Modal):
    """A line of the drop table (title, weight, amount) or of the villager's goods (amount)."""

    def __init__(self, view: ConfigView, index: int | None, kind: str | None = None):
        field = view.field
        super().__init__(title=("New line: " if index is None else f"Line {index + 1}: ") + field.label[:30])
        self.menu, self.index = view, index
        rows = ce.current_value(load_config(), field)
        row = rows[index] if index is not None and index < len(rows) else None
        self.drops = field.item == "drops"
        if self.drops:
            current_kind, amount = ce.drop_kind(row["reward"]) if row else (kind, 1)
            self.kind = current_kind
            self.title_input = discord.ui.TextInput(label="Title", default=row["title"] if row else "", max_length=80)
            self.weight = discord.ui.TextInput(label="Weight (chance = weight ÷ total)",
                                               default=f"{row['weight']:g}" if row else "10", max_length=8)
            self.add_item(self.title_input)
            self.add_item(self.weight)
        else:
            self.kind = row["asset"] if row else kind
            amount = int(row["amount"]) if row else 1
        self.amount = None
        if self.kind != "book" or not self.drops:
            self.amount = discord.ui.TextInput(label="Amount", default=str(amount), max_length=8)
            self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        field = self.menu.field
        try:
            amount = int(str(self.amount.value).strip()) if self.amount is not None else 1
            if amount < 1:
                raise ValueError
        except ValueError:
            raise GameError("The amount must be a whole number of 1 or more.")
        if self.drops:
            title = str(self.title_input.value).strip()
            try:
                weight = float(str(self.weight.value).strip().replace(",", "."))
            except ValueError:
                raise GameError("The weight must be a number.")
            if not title or weight < 0:
                raise GameError("A drop needs a title and a weight of 0 or more.")
            line = {"weight": int(weight) if weight.is_integer() else weight, "title": title,
                    "reward": ce.drop_reward(self.kind, amount)}
            label = f"“{title}” ({ce.reward_label(line['reward'])})"
        else:
            line = {"asset": self.kind, "amount": amount}
            label = ce.good_label(line)
        rows = copy.deepcopy(ce.current_value(load_config(), field))
        if self.index is None:
            if len(rows) >= field.max_items:
                raise GameError(f"At most {field.max_items} lines.")
            rows.append(line)
            what = f"added {label}"
        else:
            if self.index >= len(rows):
                raise GameError("This line doesn't exist anymore.")
            rows[self.index] = line
            what = f"line {self.index + 1} is now {label}"
        note = await self.menu.cog.save_whole(interaction.user, field, rows, what)
        await self.menu.saved(interaction, note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class DeleteLineSelect(discord.ui.Select):
    view: ConfigView

    def __init__(self, entries: list[tuple[str, str]]):
        options = [discord.SelectOption(label=label[:100], value=value) for label, value in entries[:25]]
        super().__init__(placeholder="Delete a line…", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        field = self.view.field
        rows = copy.deepcopy(ce.current_value(load_config(), field))
        index = int(self.values[0])
        if len(rows) <= 1 or index >= len(rows):
            raise GameError("The table needs at least one line.")
        removed = rows.pop(index)
        label = removed["title"] if field.item == "drops" else ce.good_label(removed)
        note = await self.view.cog.save_whole(interaction.user, field, rows, f"deleted {label}")
        await self.view.saved(interaction, note)


# ---------- level roles ----------
class LevelModal(discord.ui.Modal, title="Level role"):
    level = discord.ui.TextInput(label="Level at which the role is given", placeholder="e.g. 10", max_length=5)

    def __init__(self, view: ConfigView, role_id: int):
        super().__init__()
        self.menu, self.role_id = view, role_id
        current = {rid: lvl for lvl, rid in ce.level_roles(load_config()).items()}.get(role_id)
        if current is not None:
            self.level.default = str(current)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(str(self.level.value).strip())
        except ValueError:
            raise GameError("The level must be a whole number.")
        if level < 1:
            raise GameError("The level must be at least 1.")
        roles = ce.level_roles(load_config())
        before = roles.get(level)
        role_id = self.role_id

        def change(cfg: dict) -> dict:
            # A role is given at one level only: moving it frees its old level.
            for lvl, rid in ce.level_roles(cfg).items():
                if rid == role_id and lvl != level:
                    cfg = ce.set_level_role(cfg, lvl, None)
            return ce.set_level_role(cfg, level, role_id)

        note = await self.menu.cog.apply(
            interaction.user, f"Level {level} role", f"<@&{before}>" if before else "*none*", f"<@&{role_id}>", change,
        )
        note += "\nRun `/player sync_roles` to update the members who already passed this level."
        await self.menu.show(interaction, self.menu.screen, note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


class RemoveLevelRoleSelect(discord.ui.Select):
    view: ConfigView

    def __init__(self):
        options = [
            discord.SelectOption(label=f"Remove the level {lvl} role", value=str(lvl))
            for lvl in ce.level_roles(load_config())
        ][:25]
        super().__init__(placeholder="Remove a level role…", options=options, row=3)

    async def callback(self, interaction: discord.Interaction):
        level = int(self.values[0])
        before = ce.level_roles(load_config()).get(level)
        note = await self.view.cog.apply(
            interaction.user, f"Level {level} role", f"<@&{before}>" if before else "*none*", "*removed*",
            lambda cfg: ce.set_level_role(cfg, level, None),
        )
        await self.view.show(interaction, self.view.screen, note)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCog(bot))
