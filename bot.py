from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from game import restrictions, settings, shop
from game.db import Database
from utils.announcer import Announcer
from utils.config import CONFIG_PATH, balance_overrides, load_config, read_config_file, reload_config, staff_role_id
from utils import config_edit, routing, staff_log, staff_visibility
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
    "cogs.player_dimensions",
    "cogs.player_profile",
    "cogs.player_guide",
    "cogs.info_wiki",
    "cogs.info_updates",
    "cogs.admin_update",
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
    "cogs.events_tournament",
    "cogs.events_villager",
    "cogs.events_live",
    "cogs.games_roulette",
    "cogs.games_luckyblock",
    "cogs.games_blackjack",
    "cogs.games_mines",
    "cogs.games_blockdle",
    "cogs.games_quiz",
    "cogs.games_rob",
    "cogs.games_pve",
    "cogs.games_boss",
    "cogs.player_beacon",
    "cogs.competition_war",
    "cogs.competition_bounty",
    "cogs.events_biomes",
    "cogs.player_prestige",
    "cogs.events_night",
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


def migrate_config() -> None:
    """config.json from before 2.2.4: the "games" channels become the casino (a copy is kept first)."""
    try:
        new = routing.migrate(read_config_file())
        if new is None:
            return
        from game import backups

        config_edit.write_config(CONFIG_PATH, new, backups.backup_dir(new.get("database_path", "economy.db")))
        reload_config()
        log.info("config.json: the game channels are now the casino channels")
    except Exception:
        log.exception("Could not move the game channels to the casino channels")


class Bot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=build_intents(),
            # Safe default: never ping @everyone/@here or roles unless a message asks for it explicitly.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            # Commands only in servers (never in DMs), and only when the bot is added to a server
            # (not to a user's account): see also in_main_guild, Blocky only plays in its own server.
            allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
            allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
        )
        migrate_config()
        cfg = load_config()
        valid, problems = settings.clean(balance_overrides(cfg))
        for problem in problems:
            log.warning("config.json balance ignored: %s", problem.replace("`", ""))
        settings.load(valid)
        self.db = Database(cfg.get("database_path", "economy.db"))
        self.announcer = Announcer(self)
        self.db.notice_handler = self.announcer.handle
        self.blocked: dict[int, dict] = {}  # players blocked from Blocky (/blocky ban), see block_of
        self.staff_visibility_problem: str | None = None  # told in the staff channel once connected
        # Read once: the commands are synced to this server at startup, so a /reload can't move the bot
        # (it would refuse every command where they are) until the next restart.
        self.guild_id = int(cfg.get("guild_id", 0) or 0)

    @property
    def main_guild(self) -> discord.Guild | None:
        return self.get_guild(self.guild_id) if self.guild_id else (self.guilds[0] if self.guilds else None)

    async def setup_hook(self) -> None:
        await self.db.open()
        # Gear made before a durability change gets the new maximum (same share of durability left).
        resized = await self.db.run(shop.sync_max_durability)
        if resized:
            log.info("Gear durability: %d piece(s) adapted to the current maximums", resized)
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
        guild_id = self.guild_id
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

    def in_main_guild(self, guild_id: int | None) -> bool:
        """Blocky only plays in its own server: not in DMs, not in another server it was added to."""
        guild = self.main_guild
        return guild is not None and guild_id == guild.id

    async def tell_elsewhere(self, interaction: discord.Interaction) -> None:
        guild = self.main_guild
        where = f" on **{guild.name}**" if guild is not None else " on its own server"
        try:
            await interaction.response.send_message(f"🧱 Blocky only works{where}.", ephemeral=True)
        except discord.HTTPException:
            pass

    async def not_blocked(self, interaction: discord.Interaction) -> bool:
        """Every slash command (and its suggestions) first checks it's used in Blocky's server, by a player
        who isn't blocked."""
        if not self.in_main_guild(interaction.guild_id):
            if interaction.type is not discord.InteractionType.autocomplete:
                await self.tell_elsewhere(interaction)
            return False
        block = self.block_of(interaction.user.id)
        if block is not None:
            if interaction.type is not discord.InteractionType.autocomplete:
                await self.tell_blocked(interaction, block)
            return False
        return await self.in_its_place(interaction)

    async def in_its_place(self, interaction: discord.Interaction) -> bool:
        """Each player command works in its channel (utils/routing.py); elsewhere the player is told where."""
        command = interaction.command
        if command is None or not isinstance(command, (app_commands.Command, app_commands.Group)):
            return True
        root = command.root_parent or command
        channel = interaction.channel
        if channel is None or channel.id in getattr(self, "guide_channels", {}):
            return True  # a player's guide channel: try everything there
        place = routing.place_of(root.name, staff=is_staff_command(root))
        if routing.allowed(place, channel.id, getattr(channel, "parent_id", None)):
            return True
        if interaction.type is not discord.InteractionType.autocomplete:
            try:
                await interaction.response.send_message(routing.refusal(root.name, place), ephemeral=True)
            except discord.HTTPException:
                pass
        return False

    def gate_components(self) -> None:
        """Buttons, menus and forms check they're used in Blocky's server, by a player who isn't blocked,
        before reaching any view."""
        store = self._connection._view_store
        dispatch_view, dispatch_modal = store.dispatch_view, store.dispatch_modal

        def stopped(interaction: discord.Interaction) -> bool:
            if not self.in_main_guild(interaction.guild_id):
                mark_handled(interaction)
                asyncio.create_task(self.tell_elsewhere(interaction))
                return True
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
        role = guild.get_role(role_id) if role_id else None
        if role_id and role is None:
            log.warning("Staff role %s not found: only the administrators are staff", role_id)
        if role is not None:
            staff = {name for name, allowed in role.permissions if allowed}
        # Every other role a player could have (other bots' roles and admin roles don't matter).
        others = [{name for name, allowed in r.permissions if allowed} for r in guild.roles
                  if r.id != role_id and not r.managed and not r.permissions.administrator]
        permission, fits = staff_visibility.pick(staff, others)
        if not fits:
            self.staff_visibility_problem = (
                "⚠️ **Staff commands**: no permission belongs to the staff role only, so they are hidden behind "
                "*Administrator* (staff members who aren't admins don't see them). Give the staff role a permission "
                "no other role has (e.g. *Timeout Members*), or allow the staff role in Server Settings → "
                "Integrations → Blocky."
            )
            log.warning(self.staff_visibility_problem.replace("*", ""))
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
        if self.staff_visibility_problem:
            await self.announcer.send(self.staff_visibility_problem, channel="staff_log")
            self.staff_visibility_problem = None

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
