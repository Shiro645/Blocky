"""Posts game notices in the announcements channel and keeps level roles in sync."""
from __future__ import annotations

import logging
from typing import Any

import discord

from game import notices as n
from utils.config import channel_id, load_config

log = logging.getLogger("announcer")


def level_roles() -> list[tuple[int, int]]:
    """[(level, role_id)] sorted by level, from config roles.level_roles."""
    raw = load_config().get("roles", {}).get("level_roles", {}) or {}
    pairs = [(int(level), int(rid)) for level, rid in raw.items() if int(rid or 0)]
    return sorted(pairs)


def role_for_level(level: int) -> int | None:
    best = None
    for threshold, rid in level_roles():
        if level >= threshold:
            best = rid
    return best


class Announcer:
    def __init__(self, bot: discord.Client):
        self.bot = bot

    def channel(self, name: str = "announcements") -> discord.abc.Messageable | None:
        cid = channel_id(name)
        if not cid:
            return None
        ch = self.bot.get_channel(cid)
        return ch if isinstance(ch, discord.abc.Messageable) else None

    async def send(self, content: str | None = None, *, embed: discord.Embed | None = None, channel: str = "announcements") -> None:
        ch = self.channel(channel)
        if ch is None:
            return
        try:
            # Names are shown but nobody is pinged: announcements are frequent.
            await ch.send(content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Could not post in the %s channel", channel)

    async def handle(self, notices: list[Any]) -> None:
        for notice in notices:
            handler = getattr(self, f"on_{type(notice).__name__}", None)
            if handler is not None:
                await handler(notice)

    # ---------- handlers (one per notice type) ----------
    async def on_LevelUp(self, notice: n.LevelUp) -> None:
        text = f"🎉 <@{notice.user_id}> reached **level {notice.new_level}**!"
        if notice.talent_points_gained:
            text += f" (+{notice.talent_points_gained} talent point{'s' if notice.talent_points_gained > 1 else ''})"
        await self.send(text)
        await self.sync_level_role(notice.user_id, notice.new_level)

    async def on_AchievementUnlocked(self, notice: n.AchievementUnlocked) -> None:
        reward = f" (+{notice.reward} emeralds)" if notice.reward else ""
        await self.send(f"🏅 <@{notice.user_id}> unlocked the achievement **{notice.name}**!{reward}")

    async def on_ChallengeCompleted(self, notice: n.ChallengeCompleted) -> None:
        await self.send(
            f"🎯 <@{notice.user_id}> completed a weekly challenge: **{notice.text}** (+{notice.reward} emeralds)"
        )

    async def on_GearBroken(self, notice: n.GearBroken) -> None:
        await self.send(f"🔨 <@{notice.user_id}>'s **{notice.material} {notice.item}** broke! Time to craft a new one.")

    async def sync_level_role(self, user_id: int, level: int) -> None:
        """Give the highest level role reached and remove the other level roles."""
        pairs = level_roles()
        guild = getattr(self.bot, "main_guild", None)
        if not pairs or guild is None:
            return
        member = guild.get_member(user_id)
        if member is None:
            return
        target = role_for_level(level)
        all_ids = {rid for _, rid in pairs}
        to_remove = [r for r in member.roles if r.id in all_ids and r.id != target]
        to_add = guild.get_role(target) if target else None
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason="Blocky level role")
            if to_add is not None and to_add not in member.roles:
                await member.add_roles(to_add, reason="Blocky level role")
        except discord.HTTPException:
            log.exception("Could not update level roles of %s (check the bot's Manage Roles permission)", user_id)
