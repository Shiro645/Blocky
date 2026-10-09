from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from game import settings
from game.db import Database
from utils.announcer import Announcer
from utils.config import balance_overrides, load_config
from utils.ui import load_application_emojis, report_error


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
    "cogs.economy_xp",
    "cogs.economy_daily",
    "cogs.economy_exchange",
    "cogs.economy_auction",
    "cogs.economy_admin",
    "cogs.admin_tools",
    "cogs.competition_leaderboard",
    "cogs.competition_seasons",
    "cogs.competition_duel",
    "cogs.events_progress",
    "cogs.events_drops",
    "cogs.events_boss",
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
        )
        cfg = load_config()
        settings.load(balance_overrides(cfg))
        self.db = Database(cfg.get("database_path", "economy.db"))
        self.announcer = Announcer(self)
        self.db.notice_handler = self.announcer.handle

    @property
    def main_guild(self) -> discord.Guild | None:
        guild_id = int(load_config().get("guild_id", 0) or 0)
        return self.get_guild(guild_id) if guild_id else (self.guilds[0] if self.guilds else None)

    async def setup_hook(self) -> None:
        await self.db.open()

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
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands (guild sync)", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandInvokeError):
            error = error.original  # type: ignore[assignment]
        await report_error(interaction, error)

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
