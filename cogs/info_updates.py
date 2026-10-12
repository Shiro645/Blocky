from __future__ import annotations

import asyncio
import json
import logging

import discord
from discord.ext import commands

from game import botstate
from utils.config import channel_id, role_id
from utils.updates import UPDATES, Update

log = logging.getLogger("updates")

POSTED_KEY = "updates_posted"  # botstate: JSON list of the update keys already posted


def update_embed(update: Update) -> discord.Embed:
    text = update.text
    if channel_id("wiki"):
        text += f"\n📚 Everything in detail: <#{channel_id('wiki')}>"
    embed = discord.Embed(title=f"🆕 {update.title}", description=text, color=discord.Color.green())
    for name, value in update.parts:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=f"Blocky update · {update.date}")
    return embed


class UpdatesCog(commands.Cog):
    """Announces each new Blocky feature once, in the updates channel (utils/updates.py)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def post_pending(self) -> None:
        async with self.lock:
            cid = channel_id("updates")
            channel = self.bot.get_channel(cid) if cid else None
            if not isinstance(channel, discord.abc.Messageable):
                return  # the entries wait until there is an updates channel
            posted = set(json.loads(await self.bot.db.run(botstate.get, POSTED_KEY) or "[]"))
            pending = [u for u in UPDATES if u.key not in posted]
            guild = getattr(channel, "guild", None)
            rid = role_id("updates_ping")
            role = guild.get_role(rid) if guild is not None and rid else None
            for n, update in enumerate(pending):
                ping = role.mention if role is not None and n == 0 else None  # one ping, even for several entries
                try:
                    await channel.send(
                        ping, embed=update_embed(update),
                        allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                                                                 roles=[role] if ping else False),
                    )
                except discord.HTTPException as exc:
                    log.warning("Could not post the update %s: %s", update.key, exc)
                    return
                posted.add(update.key)
                await self.bot.db.run(botstate.put, POSTED_KEY, json.dumps(sorted(posted)))

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.post_pending()

    @commands.Cog.listener()
    async def on_blocky_config_changed(self, key: str, before) -> None:
        if key == "ch_updates":
            await self.post_pending()

    @commands.Cog.listener()
    async def on_blocky_config_reloaded(self) -> None:
        await self.post_pending()


async def setup(bot: commands.Bot):
    await bot.add_cog(UpdatesCog(bot))
