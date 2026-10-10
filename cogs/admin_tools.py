from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import backups, settings
from game.errors import GameError
from utils.checks import staff_only
from utils.config import balance_overrides, load_config, reload_config
from utils.mc_commands import DEFAULT_BLOCKED, blocked_by, clean_output
from utils.minecraft_rcon import RconError, rcon_command
from utils.ui import load_application_emojis

log = logging.getLogger("admin_tools")


def code_block(text: str) -> str:
    return "```\n" + text.replace("```", "'''") + "\n```"


class AdminToolsCog(commands.Cog):
    """Staff tools: database backups, config reload and Minecraft console."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.backup_loop.start()

    async def cog_unload(self) -> None:
        self.backup_loop.cancel()

    # ---------- backups ----------
    async def make_backup(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        await self.bot.db.backup_to(tmp)
        tmp.replace(target)  # a half-written copy never looks like a backup
        manual = target.name.startswith(backups.MANUAL_PREFIX)
        backups.prune(target.parent, int(settings.get()["backups"]["keep"]), manual=manual)
        log.info("Database backup written to %s", target)
        return target

    @tasks.loop(minutes=10)
    async def backup_loop(self):
        try:
            b = settings.get()["backups"]
            now = datetime.now(ZoneInfo(settings.get()["timezone"]))
            target = backups.due(backups.backup_dir(self.bot.db.path), now, int(b["hour"]))
            if target is not None:
                await self.make_backup(target)
        except Exception:  # an error must never stop the loop
            log.exception("Backup failed")

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="backup_now", description="STAFF: Save a copy of the database right now.")
    @staff_only()
    async def backup_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        now = datetime.now(ZoneInfo(settings.get()["timezone"]))
        folder = backups.backup_dir(self.bot.db.path)
        target = backups.manual_path(folder, now)
        await self.make_backup(target)
        nightly, manual = len(backups.existing(folder)), len(backups.existing(folder, manual=True))
        await interaction.followup.send(
            f"✅ Backup saved: `{target.name}` in `{folder.name}/` ({manual} manual and {nightly} nightly backup(s) kept).",
            ephemeral=True,
        )

    # ---------- config ----------
    @app_commands.command(name="reload_config", description="STAFF: Apply changes made to config.json without restarting.")
    @staff_only()
    async def reload_config_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old = load_config()
        try:
            cfg = reload_config()
        except (ValueError, OSError) as e:
            raise GameError(f"Config not reloaded, the current one is still active.\n{e}")
        # Like at startup: the valid values apply, the others are ignored (and listed).
        valid, problems = settings.clean(balance_overrides(cfg))
        settings.load(valid)
        await load_application_emojis(self.bot)

        notes = []
        if problems:
            ignored = "\n".join(f"- {p}" for p in problems[:10])
            notes.append(f"⚠️ Ignored in `balance` (the default values are used):\n{ignored}")
        for key in ("database_path", "guild_id"):
            if old.get(key) != cfg.get(key):
                notes.append(f"⚠️ `{key}` changed: restart the bot to apply it.")
        text = "✅ Config reloaded: channels, roles, emojis, prices and balance are up to date."
        await interaction.followup.send("\n".join([text, *notes]), ephemeral=True)

    # ---------- Minecraft console ----------
    def blocked_list(self) -> list[str]:
        custom = load_config().get("minecraft", {}).get("blocked_commands")
        return list(custom) if isinstance(custom, list) else list(DEFAULT_BLOCKED)

    async def log_console(self, user: discord.abc.User, command: str, result: str, color: discord.Color) -> None:
        embed = discord.Embed(title="🖥️ Minecraft console", color=color)
        embed.add_field(name="By", value=f"{user.mention} (`{user}`)", inline=False)
        embed.add_field(name="Command", value=code_block(command)[:1024], inline=False)
        embed.add_field(name="Result", value=code_block(result)[:1024], inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")

    @app_commands.command(name="mc", description="STAFF: Run a command on the Minecraft server console.")
    @app_commands.describe(command="Command without the slash, e.g. say Hello or give Steve diamond 3")
    @staff_only()
    async def mc(self, interaction: discord.Interaction, command: app_commands.Range[str, 1, 400]):
        rule = blocked_by(command, self.blocked_list())
        if rule:
            await self.log_console(interaction.user, command, f"Blocked (rule: {rule})", discord.Color.red())
            raise GameError(
                f"`{rule}` is blocked from Discord. Run it from the server console, "
                "or change minecraft.blocked_commands in config.json."
            )

        await interaction.response.defer(ephemeral=True)
        try:
            output = clean_output(await rcon_command(command.strip().lstrip("/")))
        except RconError as e:
            await self.log_console(interaction.user, command, f"Failed: {e}", discord.Color.orange())
            raise GameError(str(e))
        await self.log_console(interaction.user, command, output, discord.Color.blurple())
        await interaction.followup.send(f"`/{command.strip().lstrip('/')}`\n{code_block(output)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminToolsCog(bot))
