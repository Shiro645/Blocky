from __future__ import annotations

import asyncio
import hashlib
import json
import logging

import discord
from discord.ext import commands, tasks

from game import botstate, settings
from utils import wiki
from utils.config import channel_id

log = logging.getLogger("wiki")

WIKI_KEY = "wiki"  # botstate: {"channel", "messages", "keys", "hashes"} of the posted wiki
COLOR = discord.Color.blurple()


# ---------------- what the wiki shows ----------------
def section_embeds(section: wiki.Section, s: dict) -> list[discord.Embed]:
    """The explanation, then the current numbers in fields (1,024 characters each)."""
    chunks: list[str] = []
    for line in wiki.numbers(section, s):
        line = line[:1024]
        if chunks and len(chunks[-1]) + len(line) + 1 <= 1024:
            chunks[-1] += "\n" + line
        else:
            chunks.append(line)
    embeds = [discord.Embed(title=section.title, description=section.text, color=COLOR)]
    for n, chunk in enumerate(chunks):
        name = "📊 Current numbers" if n == 0 else "📊 More numbers"
        if len(embeds[-1].fields) == 25 or len(embeds[-1]) + len(name) + len(chunk) > 5800:
            embeds.append(discord.Embed(color=COLOR))
        embeds[-1].add_field(name=name, value=chunk, inline=False)
    return embeds


def messages_of(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """A message holds 10 embeds and 6,000 characters at most."""
    out: list[list[discord.Embed]] = []
    size = 0
    for embed in embeds:
        if not out or len(out[-1]) == 10 or size + len(embed) > 6000:
            out.append([])
            size = 0
        out[-1].append(embed)
        size += len(embed)
    return out


def body(s: dict) -> list[tuple[str, list[discord.Embed]]]:
    """(section key, embeds) for every message of the wiki, contents excluded."""
    return [(section.key, embeds) for section in wiki.SECTIONS for embeds in messages_of(section_embeds(section, s))]


def links(channel: discord.TextChannel, keys: list[str], ids: list[int]) -> list[str]:
    """A link to the first message of each section (ids of the body messages, in order)."""
    first: dict[str, int] = {}
    for key, mid in zip(keys, ids):
        first.setdefault(key, mid)
    base = f"https://discord.com/channels/{channel.guild.id}/{channel.id}"
    return [f"[{wiki.BY_KEY[key].title}]({base}/{mid})" for key, mid in first.items()]


def contents_embed(lines: list[str]) -> discord.Embed:
    return discord.Embed(
        title="📚 Blocky wiki",
        description="Everything about Blocky, explained in detail. Click a part to jump to it:\n\n" + "\n".join(lines)
                    + "\n\nThe numbers follow the server's settings and are updated here automatically. "
                      "For one command (options, examples): `/help`.",
        color=COLOR,
    )


def bottom_embed(lines: list[str], top: str) -> discord.Embed:
    return discord.Embed(title="📚 Contents", description="\n".join(lines) + f"\n\n⬆️ [Back to the top]({top})",
                         color=COLOR)


def digest(embeds: list[discord.Embed]) -> str:
    return hashlib.sha1(json.dumps([e.to_dict() for e in embeds], sort_keys=True).encode()).hexdigest()


# ---------------- the cog ----------------
class WikiCog(commands.Cog):
    """Keeps the wiki (every feature in detail) in the wiki channel, up to date with the settings."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self._warned = False

    async def cog_load(self) -> None:
        self.wiki_loop.start()

    async def cog_unload(self) -> None:
        self.wiki_loop.cancel()

    async def load_state(self) -> dict | None:
        raw = await self.bot.db.run(botstate.get, WIKI_KEY)
        return json.loads(raw) if raw else None

    async def save_partial(self, cid: int, ids: list[int], old: dict | None) -> None:
        """While a new wiki is being posted: remember its messages (to delete them if it fails) and the old ones."""
        partial = {"channel": cid, "messages": ids, "keys": [], "hashes": [],
                   "old": (old or {}).get("old") or ({"channel": old["channel"], "messages": old["messages"]}
                                                     if old and old.get("messages") else None)}
        await self.bot.db.run(botstate.put, WIKI_KEY, json.dumps(partial))

    async def warn_staff(self, text: str) -> None:
        if self._warned:
            return  # once until it works again
        self._warned = True
        await self.bot.announcer.send(text, channel="staff_log")

    async def delete_old(self, state: dict | None) -> None:
        """Best effort: the messages of a wiki that was replaced (and of an older one a failed repost left)."""
        if not state:
            return
        for part in (state, state.get("old") or {}):
            channel = self.bot.get_channel(part.get("channel") or 0)
            if not isinstance(channel, discord.TextChannel):
                continue
            for mid in part.get("messages", []):
                try:
                    await channel.get_partial_message(mid).delete()
                except discord.HTTPException:
                    pass

    async def ensure(self, check: bool = False) -> None:
        """Post the wiki, or edit the messages whose content changed.

        `check`: first make sure the posted wiki still exists (a deleted message = post it again)."""
        async with self.lock:
            await self._ensure(check)

    async def _ensure(self, check: bool, again: bool = True) -> None:
        state = await self.load_state()
        cid = channel_id("wiki")
        if not cid:
            if state:
                await self.delete_old(state)
                await self.bot.db.run(botstate.put, WIKI_KEY, None)
            return
        channel = self.bot.get_channel(cid)
        if not isinstance(channel, discord.TextChannel):
            log.warning("The wiki channel %s is not a text channel the bot can see", cid)
            return
        parts = body(settings.get())
        keys = [key for key, _ in parts]
        n = len(parts) + 2  # contents, the sections, the contents again at the bottom
        same = bool(state and state["channel"] == cid and state.get("keys") == keys and len(state["messages"]) == n)
        if same and check:
            try:  # the top and the bottom: a /clear of the newest messages takes the bottom first
                await channel.fetch_message(state["messages"][0])
                await channel.fetch_message(state["messages"][-1])
            except discord.NotFound:
                same = False
            except discord.HTTPException:
                return  # Discord is having trouble: try again later
        try:
            if same:
                ids, hashes = list(state["messages"]), list(state["hashes"])
            else:
                # The new wiki is posted first and the old one deleted only once it's all there: a failure on the
                # way never leaves the channel empty. What was posted is saved as it goes, to be cleaned up.
                placeholder = discord.Embed(title="📚 Blocky wiki", description="…", color=COLOR)
                ids, hashes = [], []
                for embeds in [[placeholder], *[e for _, e in parts], [placeholder]]:
                    ids.append((await channel.send(embeds=embeds)).id)
                    hashes.append("" if embeds[0] is placeholder else digest(embeds))
                    await self.save_partial(cid, ids, state)
                if state:
                    await self.delete_old(state)
            lines = links(channel, keys, ids[1:-1])
            top = f"https://discord.com/channels/{channel.guild.id}/{channel.id}/{ids[0]}"
            wanted = [[contents_embed(lines)], *[embeds for _, embeds in parts], [bottom_embed(lines, top)]]
            for i, embeds in enumerate(wanted):
                h = digest(embeds)
                if h != hashes[i]:
                    await channel.get_partial_message(ids[i]).edit(embeds=embeds)
                    hashes[i] = h
        except discord.NotFound:
            # A wiki message was deleted: post it all again (once); what's left of the old one is deleted after.
            await self.bot.db.run(botstate.put, WIKI_KEY, json.dumps({
                "channel": (state or {}).get("channel", cid), "messages": (state or {}).get("messages", []),
                "keys": [], "hashes": []}))
            if again:
                await self._ensure(False, again=False)
            return
        except discord.HTTPException as exc:
            log.warning("Could not update the wiki: %s (check Send Messages and Embed Links)", exc)
            await self.warn_staff(f"⚠️ I couldn't update the wiki in <#{cid}>: {exc}. Check that I can **Send "
                                  "Messages** and **Embed Links** there; I'll try again within the hour.")
            return
        await self.bot.db.run(botstate.put, WIKI_KEY, json.dumps({"channel": cid, "messages": ids, "keys": keys,
                                                                  "hashes": hashes}))
        self._warned = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.ensure(check=True)

    @commands.Cog.listener()
    async def on_blocky_config_changed(self, key: str, before) -> None:
        await self.ensure()  # numbers or the wiki channel may have changed

    @commands.Cog.listener()
    async def on_blocky_config_reloaded(self) -> None:
        await self.ensure()

    @tasks.loop(hours=1)
    async def wiki_loop(self) -> None:
        try:
            await self.ensure(check=True)
        except Exception:  # an error must never stop the loop (the wiki would never be fixed again)
            log.exception("Wiki loop failed")

    @wiki_loop.before_loop
    async def before_wiki(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(WikiCog(bot))
