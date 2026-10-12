from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from game import restrictions, settings
from game.db import Database
from utils.announcer import Announcer
from utils.config import balance_overrides, load_config, staff_role_id
from utils import staff_log, staff_visibility
from utils.checks import is_staff_command
from utils.ui import load_application_emojis, mark_handled, report_error, take_handled


# -------- LOAD ENV --------
load_dotenv()


# -------- LOGGING --------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


# -------- EXTENSIONS --------
EXTENSIONS = [
    "cogs.minecraft_whitelist",
    "cogs.minecraft_core",
    "cogs.minecraft_link",
    "cogs.economy_mining",
    "cogs.economy_market",
    "cogs.economy_craft",
    "cogs.economy_enchant",
    "cogs.economy_xp",
    "cogs.economy_daily",
    "cogs.economy_exchange",
    "cogs.economy_loans",
    "cogs.player_species",
    "cogs.player_profile",
    "cogs.player_guide",
    "cogs.info_wiki",
    "cogs.economy_auction",
    "cogs.staff_economy",
    "cogs.admin_tools",
    "cogs.admin_config",
    "cogs.staff_moderation",
    "cogs.staff_blocky",
    "cogs.staff_events",
    "cogs.competition_leaderboard",
    "cogs.competition_seasons",
    "cogs.competition_duel",
    "cogs.competition_teams",
    "cogs.events_progress",
    "cogs.events_drops",
    "cogs.events_boss",
    "cogs.events_tournament",
    "cogs.events_villager",
    "cogs.games_roulette",
    "cogs.games_blockdle",
    "cogs.games_quiz",
    "cogs.games_rob",
    "cogs.games_pve",
    "cogs.games_dummy",
    "cogs.help_command",
]


def build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.members = True
    intents.reactions = False
    intents.message_content = False
    return intents


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=build_intents(),
            # Safe default: never ping @everyone/@here or roles unless a message asks for it explicitly.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        cfg = load_config()
        valid, problems = settings.clean(balance_overrides(cfg))
        for problem in problems:
            log.warning("config.json balance ignored: %s", problem.replace("`", ""))
        settings.load(valid)
        self.db = Database(cfg.get("database_path", "economy.db"))
        self.announcer = Announcer(self)
        self.db.notice_handler = self.announcer.handle
        self.blocked: dict[int, dict] = {}  # players blocked from Blocky (/blocky ban), see block_of

    @property
    def main_guild(self) -> discord.Guild | None:
        guild_id = int(load_config().get("guild_id", 0) or 0)
        return self.get_guild(guild_id) if guild_id else (self.guilds[0] if self.guilds else None)

    async def setup_hook(self) -> None:
        await self.db.open()
        self.blocked = await self.db.run(restrictions.active)
        self.tree.interaction_check = self.not_blocked  # type: ignore[method-assign]
        self.gate_components()

        self.tree.on_error = self.on_app_command_error
        await load_application_emojis(self)

        # Load cogs
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:
                log.exception("Failed to load extension: %s", ext)

        # Sync slash commands
        guild_id = int(load_config().get("guild_id", 0) or 0)
        if guild_id:
            await self.hide_staff_commands(guild_id)
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands (guild sync)", len(synced))
            await self.remove_global_commands()
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def remove_global_commands(self) -> None:
        """Commands synced globally by a start without guild_id would show twice in the server: remove them.

        Only on Discord's side: the tree keeps its global commands (the guild copies and /help use them).
        """
        try:
            old = await self.tree.fetch_commands()
            if old:
                await self.http.bulk_upsert_global_commands(self.application_id, payload=[])
                log.info("Removed %d old global commands (they showed twice in the server)", len(old))
        except discord.HTTPException:
            log.warning("Could not remove the old global commands: some commands may show twice", exc_info=True)

    # -------- players blocked from Blocky (/blocky ban) --------
    def block_of(self, user_id: int) -> dict | None:
        """The player's block if they are blocked right now (a finished block is forgotten)."""
        block = self.blocked.get(user_id)
        if block is not None and block["until"] is not None and block["until"] <= time.time():
            self.blocked.pop(user_id, None)
            return None
        return block

    async def tell_blocked(self, interaction: discord.Interaction, block: dict) -> None:
        if block["until"] is None:
            until = "until the staff lifts it"
        else:
            until = f"until <t:{block['until']}:f> (<t:{block['until']}:R>)"
        text = f"⛔ You can't use Blocky {until}." + (f"\nReason: {block['reason']}" if block["reason"] else "")
        try:
            await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass

    async def not_blocked(self, interaction: discord.Interaction) -> bool:
        """Every slash command (and its suggestions) first checks the player isn't blocked."""
        block = self.block_of(interaction.user.id)
        if block is None:
            return True
        if interaction.type is not discord.InteractionType.autocomplete:
            await self.tell_blocked(interaction, block)
        return False

    def gate_components(self) -> None:
        """Buttons, menus and forms check the player isn't blocked before reaching any view."""
        store = self._connection._view_store
        dispatch_view, dispatch_modal = store.dispatch_view, store.dispatch_modal

        def stopped(interaction: discord.Interaction) -> bool:
            block = self.block_of(interaction.user.id)
            if block is None:
                return False
            mark_handled(interaction)  # so the expired-button answer stays quiet
            asyncio.create_task(self.tell_blocked(interaction, block))
            return True

        def view(component_type, custom_id, interaction):
            if not stopped(interaction):
                dispatch_view(component_type, custom_id, interaction)

        def modal(custom_id, interaction, components, resolved):
            if not stopped(interaction):
                dispatch_modal(custom_id, interaction, components, resolved)

        store.dispatch_view, store.dispatch_modal = view, modal  # type: ignore[method-assign]

    async def hide_staff_commands(self, guild_id: int) -> None:
        """Only members with a permission of the staff role see the staff commands (utils/staff_visibility.py)."""
        try:
            guild = await self.fetch_guild(guild_id)
        except discord.HTTPException:
            log.warning("Could not read the server roles: the staff commands stay visible to everyone")
            return
        staff = None
        role_id = staff_role_id()
        if role_id:
            role = guild.get_role(role_id)
            if role is None:
                log.warning("Staff role %s not found: the staff commands stay visible to everyone", role_id)
                return
            staff = {name for name, allowed in role.permissions if allowed}
        everyone = {name for name, allowed in guild.default_role.permissions if allowed}
        permission = staff_visibility.pick(staff, everyone)
        if permission is None:
            log.warning(
                "The staff role has no moderation permission (e.g. Timeout Members): "
                "the staff commands stay visible to everyone"
            )
            return
        hidden = [c for c in self.tree.get_commands() if is_staff_command(c)]
        for command in hidden:
            command.default_permissions = discord.Permissions(**{permission: True})
        log.info("%d staff commands are only shown to members with the %s permission", len(hidden), permission)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original  # type: ignore[assignment]
        await report_error(interaction, error)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """A button or menu that nothing handles any more (it expired, or the bot restarted since):
        say so instead of Discord's "This interaction failed"."""
        if interaction.type is not discord.InteractionType.component:
            return
        await asyncio.sleep(1)  # live views answer first (they mark the click as handled)
        handled = take_handled(interaction)
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        if handled or custom_id.startswith("blocky:") or interaction.response.is_done():
            return  # "blocky:..." buttons are persistent: they always have a handler
        try:
            await interaction.response.send_message(
                "⌛ These buttons don't work anymore (they expired, or the bot restarted). Use the command again.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass

    async def on_app_command_completion(self, interaction: discord.Interaction, command) -> None:
        """Log every staff command that doesn't log itself (economy, events, whitelist...)."""
        name = command.qualified_name
        if is_staff_command(command) and staff_log.wanted(name):
            await self.announcer.send(embed=staff_log.embed_for(interaction, name), channel="staff_log")

    async def on_ready(self) -> None:
        log.info("Connected as %s (%s)", self.user, self.user.id)

    async def close(self) -> None:
        await super().close()
        await self.db.close()


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN missing from .env")

    bot = Bot()
    bot.run(token)


if __name__ == "__main__":
    main()
