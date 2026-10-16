from __future__ import annotations

import asyncio
import json
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from game import botstate
from game.errors import GameError
from utils import selfupdate
from utils.checks import staff_only
from utils.config import channel_id
from utils.ui import ConfirmView

log = logging.getLogger("update")

PENDING_KEY = "update_pending"  # botstate: {"id", "channel_id", "user_id", "at"} of the running update
ALERTED_KEY = "update_alerted"  # botstate: the GitHub version the staff were last told about
UPDATE_MINUTES = 20  # longest wait for an update (pull + build)


def commit_lines(commits: list[str], limit: int = 15) -> str:
    lines = [f"`{c[:7]}` {c[8:]}"[:150] for c in commits[:limit]]
    if len(commits) > limit:
        lines.append(f"… and {len(commits) - limit} more")
    return "\n".join(lines)


def result_embed(res: dict, user_id: int | None) -> discord.Embed:
    by = f"\nAsked by <@{user_id}>." if user_id else ""
    if res.get("ok"):
        embed = discord.Embed(title="✅ Blocky updated", color=discord.Color.green(),
                              description=f"`{res.get('before')}` → `{res.get('after')}`{by}")
        if res.get("commits"):
            embed.add_field(name="What changed", value=commit_lines(res["commits"])[:1024], inline=False)
        return embed
    step = {"pull": "git pull", "build": "the rebuild"}.get(res.get("step"), res.get("step") or "the update")
    error = str(res.get("error") or "unknown error")[-900:]
    embed = discord.Embed(title="❌ Update failed", color=discord.Color.red(),
                          description=f"During {step}. The bot kept running the old version.{by}")
    embed.add_field(name="Error", value=f"```\n{error}\n```"[:1024], inline=False)
    return embed


class UpdateCog(commands.Cog):
    """/bot_update: pull Blocky from GitHub and restart it, through the updater container."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.waiting = False

    async def pending(self) -> dict | None:
        raw = await self.bot.db.run(botstate.get, PENDING_KEY)
        return json.loads(raw) if raw else None

    async def follow(self, pending: dict, timeout: float) -> None:
        """Wait for the result of an update and post it (once)."""
        if self.waiting:
            return
        self.waiting = True
        try:
            res = await selfupdate.wait_result(pending["id"], timeout)
            current = await self.pending()
            if current is None or current["id"] != pending["id"]:
                return  # already posted
            await self.bot.db.run(botstate.put, PENDING_KEY, None)
            if res is None:
                res = {"ok": False, "step": "update", "error": "No answer from the updater (is it running?)."}
            selfupdate.forget(pending["id"])
            channel = self.bot.get_channel(channel_id("staff_log") or pending.get("channel_id") or 0)
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send(embed=result_embed(res, pending.get("user_id")),
                                       allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    log.warning("Could not post the update result")
            log.info("Update %s: %s", pending["id"], "ok" if res.get("ok") else res.get("error"))
        finally:
            self.waiting = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        pending = await self.pending()
        if pending is not None:  # the bot was just restarted by the update: post its result
            asyncio.create_task(self.follow(pending, 10 * 60))

    @app_commands.command(name="bot_update", description="STAFF: Update Blocky from GitHub (shows what's new, then restarts).")
    @staff_only()
    async def update_cmd(self, interaction: discord.Interaction):
        if not selfupdate.updater_alive():
            raise GameError("The updater isn't running, so Blocky can't update itself. See the README: "
                            "*Updating from Discord*.")
        pending = await self.pending()
        if pending is not None and time.time() - pending.get("at", 0) < UPDATE_MINUTES * 60:
            raise GameError("An update is already running.")
        await interaction.response.defer(ephemeral=True, thinking=True)
        rid = selfupdate.request("check")
        res = await selfupdate.wait_result(rid, 90)
        selfupdate.forget(rid)
        if res is None:
            raise GameError("The updater didn't answer. Check its logs (`docker logs blocky-updater`).")
        if not res.get("ok"):
            raise GameError(f"Couldn't check for updates: {str(res.get('error'))[-500:]}")
        if not res["behind"]:
            await interaction.followup.send(f"✅ Blocky is up to date (`{res['head']}`).", ephemeral=True)
            return
        embed = discord.Embed(title=f"🔄 {res['behind']} new change(s) on GitHub", color=discord.Color.blurple(),
                              description=commit_lines(res["commits"]) or "(merges only)")
        embed.add_field(name="Version", value=f"`{res['head']}` → `{res['remote']}`", inline=False)
        warnings = []
        if res.get("branch") not in (None, "main"):
            warnings.append(f"The Blocky folder is on the branch `{res['branch']}`, not `main`.")
        if res.get("ahead"):
            warnings.append(f"The Blocky folder has {res['ahead']} commit(s) GitHub doesn't have: the pull will fail.")
        if res.get("dirty"):
            warnings.append("Files changed by hand in the Blocky folder (the pull fails if GitHub changed them too): "
                            + ", ".join(f"`{f}`" for f in res["dirty"]))
        if warnings:
            embed.add_field(name="⚠️ Before you update", value="\n".join(warnings)[:1024], inline=False)
        embed.set_footer(text="Updating pulls these changes, rebuilds the bot and restarts it (a few minutes).")

        async def go(i: discord.Interaction) -> None:
            if not selfupdate.updater_alive():
                await i.response.edit_message(content="❌ The updater stopped answering.", embed=None, view=None)
                return
            uid = selfupdate.request("update")
            pending = {"id": uid, "channel_id": i.channel_id, "user_id": i.user.id, "at": int(time.time())}
            await self.bot.db.run(botstate.put, PENDING_KEY, json.dumps(pending))
            await i.response.edit_message(
                content="⏳ Updating: pulling and rebuilding. The bot restarts in a few minutes, and the result is "
                        "posted in the staff channel.", embed=None, view=None)
            asyncio.create_task(self.follow(pending, UPDATE_MINUTES * 60))

        await interaction.followup.send(embed=embed, view=ConfirmView(interaction.user.id, "Update and restart", go),
                                        ephemeral=True)


    # ---------- the nightly check ----------
    @commands.Cog.listener()
    async def on_blocky_nightly_backup(self) -> None:
        """Right after the nightly backup: if GitHub has a new version, tell the staff (once per version)."""
        try:
            await self.alert_if_behind()
        except Exception:  # never break the backup loop
            log.exception("Nightly update check failed")

    async def alert_if_behind(self) -> bool:
        if not selfupdate.updater_alive():
            return False  # no updater: /bot_update can't run anyway
        rid = selfupdate.request("check")
        res = await selfupdate.wait_result(rid, 90)
        selfupdate.forget(rid)
        if not res or not res.get("ok") or not res.get("behind"):
            return False
        if await self.bot.db.run(botstate.get, ALERTED_KEY) == res["remote"]:
            return False  # already told about this version
        channel = self.bot.get_channel(channel_id("staff_log") or 0)
        if not isinstance(channel, discord.abc.Messageable):
            return False
        embed = discord.Embed(title=f"🔄 Blocky can be updated: {res['behind']} new change(s) on GitHub",
                              description=commit_lines(res["commits"]) or "(merges only)", color=discord.Color.blurple())
        embed.add_field(name="Version", value=f"`{res['head']}` → `{res['remote']}`", inline=False)
        embed.set_footer(text="Use /bot_update to install them: the bot rebuilds and restarts (a few minutes).")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await self.bot.db.run(botstate.put, ALERTED_KEY, res["remote"])
        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(UpdateCog(bot))
