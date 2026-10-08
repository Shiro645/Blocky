from __future__ import annotations

import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.config import load_config


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
    "cogs.economy_phase1",
    "cogs.economy_admin",
    "cogs.economy_market",
    "cogs.economy_craft",
    "cogs.economy_craftlist",
    "cogs.economy_xp",
    "cogs.economy_admin_xp",
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

    async def setup_hook(self) -> None:
        # Charger les cogs
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:
                log.exception("Failed to load extension: %s", ext)

        # Sync slash commands
        cfg = load_config()
        guild_id = int(cfg.get("guild_id", 0) or 0)

        if guild_id:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands (guild sync)", len(synced))
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def on_ready(self) -> None:
        log.info("Connected as %s (%s)", self.user, self.user.id)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant dans .env")

    bot = Bot()
    bot.run(token)


if __name__ == "__main__":
    main()
