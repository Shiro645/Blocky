"""Posts game notices in the announcements channel and keeps level roles in sync."""
from __future__ import annotations

import logging
from typing import Any

import discord

from game import notices as n
from utils.config import channel_id, load_config
from utils.ui import dm, em, gear_icon

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
            f"🎯 <@{notice.user_id}> completed a {'daily' if notice.daily else 'weekly'} challenge: **{notice.text}** "
            f"(+{notice.reward} emeralds)"
        )

    async def on_AllChallengesCompleted(self, notice: n.AllChallengesCompleted) -> None:
        await self.send(
            f"📕 <@{notice.user_id}> completed every weekly challenge and found a **{notice.book}** book!"
        )

    async def on_GearBroken(self, notice: n.GearBroken) -> None:
        icon = gear_icon(notice.item, notice.material)
        await self.send(f"🔨 <@{notice.user_id}>'s {icon} **{notice.material} {notice.item}** broke! Time to craft a new one.")

    async def on_GuideProgress(self, notice: n.GuideProgress) -> None:
        # The guide cog updates the player's checklist (cogs/player_guide.py).
        self.bot.dispatch("guide_progress", notice)

    async def on_LoanRepaid(self, notice: n.LoanRepaid) -> None:
        """Private messages: the lender got everything back; a late borrower is free again."""
        guild = getattr(self.bot, "main_guild", None)
        where = f" on **{guild.name}**" if guild else ""
        lender, borrower = self.bot.get_user(notice.lender_id), self.bot.get_user(notice.borrower_id)
        if lender is not None:
            name = borrower.display_name if borrower else "A player"
            await dm(lender, f"✅ {name} repaid their loan{where}: you got {em(notice.total)} back in total.")
        if notice.auto and borrower is not None:
            name = lender.display_name if lender else "your lender"
            await dm(borrower, f"✅ Your late loan to {name}{where} is fully paid (collected automatically). "
                               "You can use /pay, /trade, the auction and loans again.")

    async def on_PrestigeReached(self, notice: n.PrestigeReached) -> None:
        from game import prestige  # here: the game imports this module's notices

        await self.send(f"🌟 <@{notice.user_id}> reached **Prestige {prestige.roman(notice.prestige)}** "
                        f"{prestige.stars(notice.prestige)} and starts over, stronger for good! `/prestige`")
        self.bot.dispatch("blocky_prestige", notice.user_id)  # the roles (cogs/player_prestige.py)

    async def on_BountyPlaced(self, notice: n.BountyPlaced) -> None:
        """Public and anonymous; the target gets a private message; only the staff log names the payer."""
        more = f" (**{em(notice.total)}** on their head now)" if notice.total > notice.amount else ""
        await self.send(f"🎯 Someone put a bounty of **{em(notice.amount)}** on <@{notice.target_id}>'s head{more}! "
                        "Beat them in a duel, rob them or make them fall in a raid to claim it. `/bounty list`")
        await self.send(f"🎯 <@{notice.payer_id}> put a bounty of {em(notice.amount)} on <@{notice.target_id}>.",
                        channel="staff_log")
        target = self.bot.get_user(notice.target_id)
        if target is not None:
            guild = getattr(self.bot, "main_guild", None)
            where = f" on **{guild.name}**" if guild else ""
            await dm(target, f"🎯 Someone put a bounty of {em(notice.amount)} on your head{where} "
                             f"({em(notice.total)} in total). Whoever beats you in a duel, robs you or makes you fall "
                             f"in a raid takes it. It runs until <t:{notice.expires_at}:f>.")

    async def on_BountyClaimed(self, notice: n.BountyClaimed) -> None:
        from game.bounty import VIA  # here: the game imports this module's notices

        await self.send(f"🎯 <@{notice.hunter_id}> claimed the bounty on <@{notice.target_id}>'s head with "
                        f"{VIA.get(notice.via, notice.via)}: **{em(notice.amount)}**!")

    async def on_BountyExpired(self, notice: n.BountyExpired) -> None:
        payer = self.bot.get_user(notice.payer_id)
        if payer is not None:
            await dm(payer, f"🎯 Nobody claimed your bounty of {em(notice.amount)} on <@{notice.target_id}>: "
                            f"{em(notice.refund)} came back to you (after the tax).")

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
