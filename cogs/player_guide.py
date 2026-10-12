from __future__ import annotations

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from game import guide, settings, species
from game.errors import GameError
from game.notices import GuideProgress
from utils.checks import is_staff, staff_only
from utils.config import channel_id, role_id, staff_role_id
from utils.ui import ConfirmView, dm, em

log = logging.getLogger("guide")

CHANNEL_LIMIT = 490  # Discord allows 500 channels per server: keep some room for the staff
CATEGORY_LIMIT = 50  # channels per category (Discord's limit)
COLOR = discord.Color.green()
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class GuideLimit(GameError):
    """No room left for one more guide channel."""


# ---------------- what the guide says ----------------
def checklist_embed(state: dict) -> discord.Embed:
    done = sum(1 for _, ok in state["steps"] if ok)
    total = len(state["steps"])
    lines = [f"✅ ~~{step.text}~~" if ok else f"⬜ {step.text}" for step, ok in state["steps"]]
    bar = "🟩" * done + "⬛" * (total - done)
    if state["completed"]:
        end = f"🎉 **All done!** The reward ({em(state['reward'])}) is paid once, and it's yours."
    elif state["rewarded"]:
        end = "You already got the reward of the checklist."
    else:
        end = f"🎁 Do them all to get **{em(state['reward'])}**."
    text = "\n".join(lines) + f"\n\n{bar} **{done}/{total}**\n{end}"
    if state["channel_id"] and state["delete_at"]:
        text += f"\n\n🗑️ This channel will be deleted <t:{state['delete_at']}:R>. `/guide` shows this checklist anywhere."
    embed = discord.Embed(title="📋 Your first steps", description=text, color=COLOR)
    embed.set_footer(text="Each step is checked by itself as soon as you do it (steps done before count too).")
    return embed


def guide_pages() -> list[discord.Embed]:
    s = settings.get()
    values = s["block_values"]
    daily = s["daily"]
    sp = s["species"]
    kinds = "\n".join(f"{k.emoji} **{k.name}** — {species.describe(k.key)}" for k in species.SPECIES.values())
    easy = s["pve"]["difficulties"]["easy"]["entry"]
    t, v = s["tournament"], s["villager"]
    pages = [
        ("⛏️ 1. Mining and emeralds", (
            "**Chat to mine.** Every message you write in the server mines **1 to 6 blocks**: cobblestone, gravel, "
            f"deepslate, sometimes obsidian and, rarely, bedrock. It works once every **{s['mining']['cooldown_seconds']} s** "
            "(spam channels give almost nothing). You can chat right here too.\n\n"
            "`/inventory` — your blocks, emeralds, items and gear.\n"
            f"`/sell` — sells all your blocks: cobblestone {values['cobblestone']}, gravel {values['gravel']}, "
            f"deepslate {values['deepslate']}, obsidian {values['obsidian']}, bedrock {values['bedrock']} emeralds each.\n"
            f"`/daily` — {em(daily['base_reward'])} and XP once a day. Come back every day: the streak adds a bonus "
            f"(up to {daily['streak_cap_days']} days) and every 7th day gives a {daily['weekly_bonus_item']} ingot.\n"
            "`/market` — buy sticks and ingots to craft with.\n\n"
            "**XP and levels.** Playing gives XP. Level-ups are announced, and every 5 levels gives a talent point "
            "to spend in `/talents` (better blocks, better prices, more bedrock, shorter cooldown)."
        )),
        ("🛠️ 2. Gear", (
            "`/craft <item> <material>` makes tools, swords and armor in gold, iron, diamond or netherite "
            "(`/craftlist` shows the recipes). New gear is equipped if the slot is empty; `/gear`, `/equip`, "
            "`/equip_best`.\n"
            "• **Pickaxe, shovel, axe, hoe**: more blocks, sticks or XP when you mine.\n"
            "• **Sword**: more damage. **Armor**: less damage taken.\n"
            "• **Shield** (6 iron): in a duel, **Attack + block** blocks the opponent's next attack, twice per duel.\n"
            "Gear wears out when used: `/repair` it before it breaks.\n\n"
            "**Enchanting.** Mining sometimes finds lapis, and enchanted books drop from events and bosses: "
            "`/enchant apply` puts a book on a piece (Efficiency, Fortune, Unbreaking, Sharpness, Looting, "
            "Protection), `/enchant combine` merges two books into a stronger one."
        )),
        ("🧬 3. Species and profile", (
            "Pick a **species** with `/species choose` for a small bonus. Your first choice is free; changing later "
            f"costs {em(sp['change_cost'])}, once every {sp['change_days']:g} days.\n{kinds}\n\n"
            "`/profile` shows your **profile card**: level, emeralds, fortune rank, species, team and achievements. "
            "Make it yours with `/customize`: a bio, a color, a frame, a title earned by playing and the achievements "
            "you want to show. `/customize list` shows what you can unlock."
        )),
        ("⚔️ 4. Fighting", (
            "**Training dummy.** `/dummy hit` tests your damage (with a leaderboard: `/dummy top`) and `/dummy duel` "
            "is a training duel: free potions, nothing to lose. The best way to learn.\n"
            f"**Duels.** `/duel <member> <stake>`: both bet the same emeralds (at least {s['duel']['min_stake']}) and "
            "the winner takes it all. On your turn: drink a potion if you want, then **Attack** (or **Attack + block** "
            "with a shield). Potions (`/potions`): Strength, Speed, Healing, Harming.\n"
            f"**Dungeon.** `/pve start <difficulty>`: 5 waves of monsters, alone or with up to 3 friends, from "
            f"{em(easy)} to enter. Health isn't restored between waves: leave with your loot in time, or lose it.\n"
            "**Bosses.** Sometimes a boss appears: everyone attacks it (`/attack` or the button) and the rewards are "
            "shared by damage dealt.\n"
            f"**Weekend tournament.** Register from {DAYS[int(t['opens_day'])]} {int(t['opens_hour'])}:00 "
            f"(`/tournament join`, {em(t['entry_fee'])}); the fights are played on {DAYS[int(t['start_day'])]} with "
            "your gear, and the winners share the pot."
        )),
        ("🌍 5. Playing with others", (
            "**Trading.** `/pay` sends emeralds, `/trade` swaps items safely, `/auction sell` lists an item for "
            "everyone and `/loan` lends or borrows with interest.\n"
            f"**Teams.** `/team create` (up to {s['teams']['max_members']} players): a tag next to your name, more XP "
            "when your teammates mine, a banner on your profile and a weekly team season with rewards.\n"
            "**Seasons.** Every week (Monday to Sunday) the players who create the most value win emeralds and the "
            "champion role: `/season`. Also `/leaderboard`, `/challenges` (3 weekly goals) and `/achievements`.\n"
            f"**Events.** Drops (the first to click wins), the wandering villager every day from "
            f"{int(v['arrive_hour'])}:00 to {int(v['leave_hour'])}:00 (`/villager`), bosses.\n"
            "**Mini-games.** `/roulette`, `/blockdle` (guess the block of the day), the Minecraft quiz and `/rob` "
            "(risky!).\n"
            "**Minecraft.** `/ip` to join the server, `/link` to link your Minecraft account."
        )),
        ("📖 6. Need more info?", (
            "`/help` opens the **manual**: pick a category, then a command. Every page explains what the command does, "
            "each option, the **current numbers** (prices, rewards, cooldowns) and gives examples.\n"
            "`/help command:<name>` opens a page directly, e.g. `/help command:duel` or `/help command:mining`.\n"
            "When you type `/`, Discord lists every command with a short description, and each option says what to "
            "put in it.\n\n"
            "`/guide` shows your checklist anywhere. A question? Ask the staff. Have fun! 🧱"
        )),
    ]
    return [discord.Embed(title=title, description=text, color=COLOR) for title, text in pages]


def bundles(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """As few messages as possible: 10 embeds and 6,000 characters at most per message."""
    out: list[list[discord.Embed]] = []
    size = 0
    for embed in embeds:
        n = len(embed)
        if not out or len(out[-1]) == 10 or size + n > 6000:
            out.append([])
            size = 0
        out[-1].append(embed)
        size += n
    return out


# ---------------- the close button ----------------
class CloseGuideButton(discord.ui.DynamicItem[discord.ui.Button], template=r"blocky:guide:close:(?P<user_id>\d+)"):
    """Deletes a finished guide channel now (the player or the staff). Survives restarts."""

    def __init__(self, user_id: int) -> None:
        super().__init__(discord.ui.Button(label="Delete this channel now", emoji="🗑️",
                                           style=discord.ButtonStyle.secondary, custom_id=f"blocky:guide:close:{user_id}"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        return cls(int(match["user_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id and not is_staff(interaction.user):
            await interaction.response.send_message("❌ This isn't your guide.", ephemeral=True)
            return
        cog = interaction.client.get_cog("GuideCog")  # type: ignore[union-attr]
        await interaction.response.send_message("🗑️ Deleting this channel…")
        if cog is not None and interaction.guild is not None:
            await cog.close_for(interaction.guild, self.user_id)  # type: ignore[attr-defined]


# ---------------- the cog ----------------
class GuideCog(commands.Cog):
    """The guide: a private channel for every new player, with a checklist of first steps."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lock = asyncio.Lock()  # one channel created at a time (counting the categories)
        self.sending = False  # /guide_resend for everyone is running

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(CloseGuideButton)
        self.bot.guide_channels = await self.bot.db.run(guide.channels)  # type: ignore[attr-defined]
        self.cleanup_loop.start()

    async def cog_unload(self) -> None:
        self.cleanup_loop.cancel()
        self.bot.remove_dynamic_items(CloseGuideButton)

    @property
    def cache(self) -> dict[int, int]:
        return self.bot.guide_channels  # type: ignore[attr-defined]

    # ---------- channels ----------
    @staticmethod
    def base_category(guild: discord.Guild) -> discord.CategoryChannel | None:
        found = guild.get_channel(channel_id("guide_category"))
        return found if isinstance(found, discord.CategoryChannel) else None

    @staticmethod
    def player_role(guild: discord.Guild) -> discord.Role | None:
        """The Blocky player role (roles.blocky_player): only its members get a guide channel."""
        rid = role_id("blocky_player")
        return guild.get_role(rid) if rid else None

    @staticmethod
    def overflow(guild: discord.Guild, base: discord.CategoryChannel) -> list[tuple[int, discord.CategoryChannel]]:
        """The extra categories made when the first one is full: "<name> 2", "<name> 3"…"""
        pattern = re.compile(rf"^{re.escape(base.name)} (\d+)$")
        found = [(int(m[1]), c) for c in guild.categories if c.id != base.id and (m := pattern.match(c.name))]
        return sorted(found, key=lambda pair: pair[0])

    async def free_category(self, guild: discord.Guild, base: discord.CategoryChannel) -> discord.CategoryChannel:
        if len(guild.channels) >= CHANNEL_LIMIT:
            raise GuideLimit("The server is close to Discord's limit of 500 channels: no room for a guide channel.")
        extra = self.overflow(guild, base)
        for category in [base] + [c for _, c in extra]:
            if len(category.channels) < CATEGORY_LIMIT:
                return category
        if len(guild.channels) + 2 > CHANNEL_LIMIT:
            raise GuideLimit("The server is close to Discord's limit of 500 channels: no room for a guide channel.")
        number = (extra[-1][0] if extra else 1) + 1
        return await guild.create_category(f"{base.name} {number}", overwrites=base.overwrites,
                                           reason="Blocky: the guide category is full")

    @staticmethod
    def overwrites(guild: discord.Guild, member: discord.Member) -> dict:
        player = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                             use_application_commands=True, add_reactions=True)
        out: dict = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: player,
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                                  attach_files=True, read_message_history=True),
        }
        staff = guild.get_role(staff_role_id())
        if staff is not None:
            out[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        return out

    async def delete_channel(self, guild: discord.Guild, cid: int) -> None:
        self.cache.pop(cid, None)
        channel = guild.get_channel(cid)
        if channel is None:
            return
        category = channel.category
        try:
            await channel.delete(reason="Blocky: guide channel closed")
        except discord.NotFound:
            pass
        except discord.HTTPException:
            log.warning("Could not delete the guide channel %s (check Manage Channels)", cid)
            return
        base = self.base_category(guild)
        left = [c for c in category.channels if c.id != cid] if category is not None else []
        if category is not None and base is not None and category.id != base.id and not left \
                and any(c.id == category.id for _, c in self.overflow(guild, base)):
            try:
                await category.delete(reason="Blocky: extra guide category is empty")
            except discord.HTTPException:
                pass

    async def close_for(self, guild: discord.Guild, user_id: int) -> None:
        cid = await self.bot.db.run(guide.closed, user_id)
        if cid:
            await self.delete_channel(guild, cid)

    async def open_for(self, member: discord.Member) -> discord.TextChannel | None:
        """A new guide channel for this player (their old one is replaced). None without a guide category."""
        guild = member.guild
        base = self.base_category(guild)
        if base is None:
            await self.bot.db.run(guide.opened, member.id, None, None)  # the checklist works with /guide
            return None
        async with self.lock:
            await self.close_for(guild, member.id)
            category = await self.free_category(guild, base)
            name = "guide-" + (re.sub(r"[^a-z0-9_-]", "", member.name.lower())[:80] or str(member.id))
            try:
                channel = await guild.create_text_channel(
                    name, category=category, overwrites=self.overwrites(guild, member),
                    topic=f"{member.display_name}'s Blocky guide: first steps and how the game works.",
                    reason=f"Blocky: guide for {member}",
                )
            except discord.HTTPException as exc:
                log.warning("Could not create a guide channel for %s: %s", member, exc)
                raise GameError("I couldn't create the guide channel: I need the *Manage Channels* and *Manage Roles* "
                                "permissions.") from exc
            self.cache[channel.id] = member.id
        state = await self.bot.db.run(guide.overview, member.id)
        first = None
        try:
            first = await channel.send(
                f"👋 Welcome to **{guild.name}**, {member.mention}! This private channel is your **Blocky guide**: "
                "only you and the staff see it. Start with the checklist, then read on.",
                embed=checklist_embed(state), allowed_mentions=discord.AllowedMentions(users=[member]),
            )
            for embeds in bundles(guide_pages()):
                await channel.send(embeds=embeds)
        except discord.HTTPException as exc:
            log.warning("Could not post the guide in %s: %s", channel.id, exc)
        # Recorded even if posting failed, so the channel is still cleaned up.
        state = await self.bot.db.run(guide.opened, member.id, channel.id, first.id if first else None)
        if first is not None:
            try:
                await first.edit(embed=checklist_embed(state))
            except discord.HTTPException:
                pass
        return channel

    # ---------- the checklist, live ----------
    @commands.Cog.listener()
    async def on_guide_progress(self, notice: GuideProgress) -> None:
        guild = getattr(self.bot, "main_guild", None)
        channel = guild.get_channel(notice.channel_id) if guild is not None and notice.channel_id else None
        if not isinstance(channel, discord.TextChannel):
            if notice.completed and notice.reward:
                user = self.bot.get_user(notice.user_id)
                if user is not None:
                    await dm(user, f"🎉 You finished the Blocky checklist: **+{em(notice.reward)}**!")
            return
        state = await self.bot.db.run(guide.overview, notice.user_id)
        try:
            if notice.message_id:
                await channel.get_partial_message(notice.message_id).edit(embed=checklist_embed(state))
            steps = [guide.STEPS_BY_KEY[k].text for k in notice.steps]
            lines = [f"✅ Step done: **{text}** ({notice.done}/{notice.total})" for text in steps]
            if not notice.completed:
                await channel.send("\n".join(lines))
                return
            lines.append("🎉 **Checklist done!**" + (f" You get **{em(notice.reward)}**." if notice.reward else ""))
            if state["delete_at"]:
                lines.append(f"This channel will be deleted <t:{state['delete_at']}:R>; scroll up to read the guide "
                             "again until then, and `/help` is always there.")
            view = discord.ui.View(timeout=None)
            view.add_item(CloseGuideButton(notice.user_id))
            await channel.send("\n".join(lines), view=view)
        except discord.HTTPException:
            log.warning("Could not update the guide channel %s", channel.id)

    # ---------- members and channels ----------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        role = self.guide_role_of(member)
        if role is not None and role in member.roles:
            await self.welcome(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Getting the Blocky player role (e.g. from a question in Channels & Roles) opens the guide;
        losing it closes the guide channel (the checklist progress is kept)."""
        role = self.guide_role_of(after)
        if role is None or (role in before.roles) == (role in after.roles):
            return
        if role in after.roles:
            state = await self.bot.db.run(guide.overview, after.id)
            if not (state["channel_id"] and after.guild.get_channel(state["channel_id"])):
                await self.welcome(after)
        else:
            await self.close_for(after.guild, after.id)

    def guide_role_of(self, member: discord.Member) -> discord.Role | None:
        """The Blocky player role, when this member is a player of the main server and guides are on."""
        guild = getattr(self.bot, "main_guild", None)
        if member.bot or guild is None or member.guild.id != guild.id or self.base_category(guild) is None:
            return None
        return self.player_role(guild)

    async def welcome(self, member: discord.Member) -> None:
        try:
            await self.open_for(member)
        except GameError as exc:
            log.warning("No guide channel for %s: %s", member, exc)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        guild = getattr(self.bot, "main_guild", None)
        if guild is not None and member.guild.id == guild.id:
            await self.close_for(guild, member.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if channel.id in self.cache:
            self.cache.pop(channel.id, None)
            await self.bot.db.run(guide.channel_deleted, channel.id)

    @tasks.loop(minutes=10)
    async def cleanup_loop(self) -> None:
        guild = getattr(self.bot, "main_guild", None)
        if guild is None:
            return
        for row in await self.bot.db.run(guide.due):
            await self.close_for(guild, row["user_id"])

    @cleanup_loop.before_loop
    async def before_cleanup(self) -> None:
        await self.bot.wait_until_ready()

    # ---------- commands ----------
    @app_commands.command(name="guide", description="Your checklist of first steps, and your guide channel.")
    async def guide_cmd(self, interaction: discord.Interaction):
        member = interaction.user
        role = self.player_role(interaction.guild) if interaction.guild is not None else None
        if role is not None and isinstance(member, discord.Member) and role not in member.roles:
            await interaction.response.send_message(
                f"📘 The guide is for Blocky players. Answer the question in <id:customize> to get the **{role.name}** "
                "role: your guide channel opens right away.", ephemeral=True,
            )
            return
        state = await self.bot.db.run(guide.overview, member.id)
        channel = interaction.guild.get_channel(state["channel_id"]) if interaction.guild and state["channel_id"] else None
        if channel is None and isinstance(member, discord.Member) and interaction.guild is not None:
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                channel = await self.open_for(member)
            except GuideLimit:
                channel = None
                await self.bot.db.run(guide.opened, member.id, None, None)
            state = await self.bot.db.run(guide.overview, member.id)
            if channel is not None:
                await interaction.followup.send(f"📘 Your guide channel is ready: {channel.mention}",
                                                embed=checklist_embed(state), ephemeral=True)
                return
            # No guide channel (no guide category, or no room): the guide comes here.
            for n, embeds in enumerate(bundles([checklist_embed(state)] + guide_pages())):
                await interaction.followup.send("📘 Your Blocky guide:" if n == 0 else None, embeds=embeds, ephemeral=True)
            return
        text = f"📘 Your guide channel: {channel.mention}" if channel else "📘 Your checklist:"
        await interaction.response.send_message(text, embed=checklist_embed(state), ephemeral=True)

    @app_commands.command(name="guide_resend", description="STAFF: Send the guide again, to a member or to every Blocky player.")
    @app_commands.describe(member="Who gets a new guide channel (empty = every member with the Blocky player role)")
    @staff_only()
    async def guide_resend(self, interaction: discord.Interaction, member: discord.Member | None = None):
        guild = interaction.guild
        if guild is None:
            raise GameError("Use this in the server.")
        if self.base_category(guild) is None:
            raise GameError("Set the guide category first: `/config` → Channels → Guide category.")
        if member is not None:
            if member.bot:
                raise GameError("Bots don't play.")
            await interaction.response.defer(ephemeral=True, thinking=True)
            channel = await self.open_for(member)
            await interaction.followup.send(f"📘 New guide for {member.mention}: {channel.mention if channel else '—'}",
                                            ephemeral=True)
            return
        if self.sending:
            raise GameError("The guide is already being sent to everyone.")
        role = self.player_role(guild)
        if role is None:
            raise GameError("Set the Blocky player role first: `/config` → Roles → Blocky player role. Only the members "
                            "with it get the guide.")
        members = sorted((m for m in role.members if not m.bot), key=lambda m: m.joined_at or discord.utils.utcnow(),
                         reverse=True)
        if not members:
            raise GameError(f"Nobody has the **{role.name}** role yet.")
        room = max(0, CHANNEL_LIMIT - len(guild.channels) + len(self.cache))

        async def go(i: discord.Interaction) -> None:
            if self.sending:
                await i.response.edit_message(content="The guide is already being sent to everyone.", view=None)
                return
            await i.response.edit_message(content=f"⏳ Sending the guide to **{len(members)}** members…", view=None)
            self.sending = True
            asyncio.create_task(self.resend_all(i, members))

        note = (f" Discord allows 500 channels: about **{room}** guide channels fit, the newest members first."
                if room < len(members) else "")
        await interaction.response.send_message(
            f"Send the guide again to the **{len(members)}** members with the **{role.name}** role? Each one gets a new "
            "private channel (their old one is "
            f"replaced). Steps already done stay checked, and the reward is only paid once.{note}",
            view=ConfirmView(interaction.user.id, f"Send to {len(members)}", go), ephemeral=True,
        )

    async def resend_all(self, interaction: discord.Interaction, members: list[discord.Member]) -> None:
        sent = failed = no_room = 0
        try:
            for index, member in enumerate(members, start=1):
                try:
                    await self.open_for(member)
                    sent += 1
                except GuideLimit:
                    no_room += 1  # the next ones may still replace the channel they have
                except (GameError, discord.HTTPException) as exc:
                    failed += 1
                    log.warning("Guide for %s: %s", member, exc)
                if index % 10 == 0:
                    try:
                        await interaction.edit_original_response(content=f"⏳ Guide sent to {index}/{len(members)}…")
                    except discord.HTTPException:
                        pass
        finally:
            self.sending = False
        report = f"📘 Guide sent to **{sent}** member(s)."
        if failed:
            report += f" {failed} failed (see the logs)."
        if no_room:
            report += f" {no_room} didn't get one: the server is close to Discord's limit of 500 channels."
        try:
            await interaction.edit_original_response(content=report)
        except discord.HTTPException:
            pass
        await self.bot.announcer.send(embed=discord.Embed(title="📘 Guide sent to everyone", description=report,  # type: ignore[attr-defined]
                                                          color=COLOR), channel="staff_log")


async def setup(bot: commands.Bot):
    await bot.add_cog(GuideCog(bot))
