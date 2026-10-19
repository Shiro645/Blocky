from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from game import assets, backups, cooldowns, dimensions, players, profiles, reset, rewind, settings, species
from game.catalog import DIMENSIONS
from game.errors import GameError
from utils.autocomplete import owned_asset_choices
from utils.checks import staff_only
from utils.ui import BaseView, ConfirmView, asset_icon, dm, em, report_error

log = logging.getLogger("staff_economy")

Amount = app_commands.Range[int, 1, 1_000_000]
Reason = app_commands.Range[str, 1, 300]


def what(key: str, amount: int) -> str:
    """'💎 **3 × diamond ingot**'"""
    return f"{asset_icon(key)} **{assets.describe(key, amount)}**".strip()


class StaffEconomyCog(commands.Cog):
    """Staff: give and take anything, change a member's XP, level and talents. Members get a DM."""

    player = app_commands.Group(name="player", description="STAFF: Change a member's XP, level, talents, species and dimension.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- helpers ----------
    async def answer(
        self, interaction: discord.Interaction, text: str, member: discord.abc.User, news: str,
        reason: str | None = None, *, edit: bool = False,
    ) -> None:
        """Answer the staff member first (Discord gives 3 seconds), then DM the member the `news`."""
        if edit:
            await interaction.response.edit_message(content=text, view=None)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        server = f"**{interaction.guild.name}** · " if interaction.guild else ""
        if not await dm(member, f"{server}{news}." + (f"\nReason: {reason}" if reason else "")):
            await interaction.edit_original_response(content=text + "\n*(Couldn't DM them: their DMs are closed.)*")

    async def log(self, title: str, member: discord.abc.User, staff: discord.abc.User, details: str, reason: str | None) -> None:
        embed = discord.Embed(title=title, description=details, color=discord.Color.blurple())
        embed.add_field(name="Member", value=f"{member.mention} (`{member}`)", inline=True)
        embed.add_field(name="By", value=f"{staff.mention} (`{staff}`)", inline=True)
        embed.add_field(name="Reason", value=reason or "—", inline=False)
        await self.bot.announcer.send(embed=embed, channel="staff_log")

    # ---------- autocomplete ----------
    async def give_autocomplete(self, interaction: discord.Interaction, current: str):
        text = current.strip().lower()
        choices = []
        try:  # a full key typed by hand, e.g. an enchanted piece "gear:diamond:sword:sharpness3"
            assets.parse(text)
            choices.append(app_commands.Choice(name=assets.describe(text)[:100], value=text))
        except GameError:
            pass
        for key in assets.catalog():
            name = assets.describe(key)
            if key != text and (text in name.lower() or text in key):
                choices.append(app_commands.Choice(name=name, value=key))
        return choices[:25]

    async def take_autocomplete(self, interaction: discord.Interaction, current: str):
        member = getattr(interaction.namespace, "member", None)
        if member is None:  # pick the member first: the suggestions are what they own
            return []
        return await owned_asset_choices(self.bot, member.id, current)

    # ---------- give / take ----------
    @app_commands.command(name="give", description="STAFF: Give anything to a member (emeralds, blocks, items, books, potions, gear).")
    @app_commands.describe(
        member="Who gets it",
        item="What to give (start typing; for an enchanted piece type e.g. gear:diamond:sword:sharpness3)",
        amount="How many (gear: 50 at most)",
        reason="Why (sent to the member and logged)",
    )
    @app_commands.autocomplete(item=give_autocomplete)
    @staff_only()
    async def give(
        self, interaction: discord.Interaction, member: discord.Member, item: str,
        amount: Amount = 1, reason: Reason | None = None,
    ):
        key = item.strip().lower()
        assets.parse(key)  # a readable error for an unknown item
        total = await self.bot.db.run(assets.staff_give, member.id, key, amount)
        await self.answer(
            interaction, f"✅ Gave {what(key, amount)} to {member.mention} (they have **{total:,}** now).",
            member, f"🎁 The staff gave you {what(key, amount)}", reason,
        )
        await self.log("🎁 Staff gift", member, interaction.user, f"Gave {what(key, amount)} (now {total:,})", reason)

    @app_commands.command(name="take", description="STAFF: Remove anything a member owns (asks for confirmation).")
    @app_commands.describe(
        member="Whose inventory",
        item="What to remove (the suggestions are what they own)",
        amount="How many (never more than they have)",
        reason="Why (sent to the member and logged)",
    )
    @app_commands.autocomplete(item=take_autocomplete)
    @staff_only()
    async def take(
        self, interaction: discord.Interaction, member: discord.Member, item: str,
        amount: Amount = 1, reason: Reason | None = None,
    ):
        key = item.strip().lower()
        have = await self.bot.db.run(assets.amount_of, member.id, key)
        if have <= 0:
            raise GameError(f"{member.mention} has no **{assets.describe(key)}**.")
        count = min(amount, have)
        extra = f" You asked for {amount:,}, they only have {have:,}." if amount > have else ""

        async def do(confirm: discord.Interaction) -> None:
            removed, left = await self.bot.db.run(assets.staff_take, member.id, key, count)
            await self.answer(
                confirm, f"✅ Removed {what(key, removed)} from {member.mention} (**{left:,}** left).",
                member, f"📦 The staff removed {what(key, removed)} from your inventory", reason, edit=True,
            )
            await self.log("📦 Staff removal", member, interaction.user, f"Removed {what(key, removed)} ({left:,} left)", reason)

        await interaction.response.send_message(
            f"Remove {what(key, count)} from {member.mention}? They have **{have:,}**.{extra}",
            view=ConfirmView(interaction.user.id, "Remove", do), ephemeral=True,
        )

    # ---------- /player ----------
    @player.command(name="xp_add", description="STAFF: Give XP to a member (levels and talent points follow).")
    @app_commands.describe(member="Who gets the XP", amount="How much XP")
    @staff_only()
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member, amount: Amount):
        p = await self.bot.db.run(players.add_xp, member.id, amount, False)  # the staff's XP never mends gear
        await self.answer(
            interaction, f"✅ {member.mention} is now level **{p['level']}** ({p['xp']} XP).",
            member, f"✨ The staff gave you **{amount:,} XP** (you're level **{p['level']}**)",
        )

    @player.command(name="xp_set", description="STAFF: Set a member's XP inside their current level.")
    @app_commands.describe(member="Whose XP to set", xp="XP inside the current level")
    @staff_only()
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member, xp: app_commands.Range[int, 0]):
        p = await self.bot.db.run(players.set_xp, member.id, xp)
        await self.answer(
            interaction, f"✅ {member.mention} is now level **{p['level']}** ({p['xp']} XP).",
            member, f"✨ The staff set your XP to **{p['xp']:,}** (level **{p['level']}**)",
        )

    @player.command(name="level", description="STAFF: Set a member's level (unspent talent points are recomputed).")
    @app_commands.describe(member="Whose level to set", level="The new level")
    @staff_only()
    async def level(self, interaction: discord.Interaction, member: discord.Member, level: app_commands.Range[int, 1, 10_000]):
        p = await self.bot.db.run(players.set_level, member.id, level)
        await self.answer(
            interaction,
            f"✅ {member.mention} is now level **{p['level']}** with **{p['talent_points']}** unspent talent point(s).",
            member, f"⭐ The staff set your level to **{p['level']}**",
        )
        await self.bot.announcer.sync_level_role(member.id, p["level"])

    @player.command(name="talents_add", description="STAFF: Add talent points (a negative number removes some).")
    @app_commands.describe(member="Who gets the points", points="Points to add (negative to remove some)")
    @staff_only()
    async def talents_add(self, interaction: discord.Interaction, member: discord.Member, points: app_commands.Range[int, -1000, 1000]):
        if points == 0:
            raise GameError("0 points: nothing to change.")
        p = await self.bot.db.run(players.add_talent_points, member.id, points)
        change = f"gave you **{points}**" if points > 0 else f"removed **{-points}** of your"
        await self.answer(
            interaction, f"✅ {member.mention} has **{p['talent_points']}** unspent talent point(s).",
            member, f"🌟 The staff {change} talent point(s) (unspent: **{p['talent_points']}**)",
        )

    @player.command(name="talents_reset", description="STAFF: Reset a member's talents (every spent point is refunded).")
    @app_commands.describe(member="Whose talents to reset")
    @staff_only()
    async def talents_reset(self, interaction: discord.Interaction, member: discord.Member):
        p = await self.bot.db.run(players.reset_talents, member.id)
        await self.answer(
            interaction, f"✅ {member.mention}'s talents were reset. Unspent points: **{p['talent_points']}**.",
            member, f"🌟 The staff reset your talents: you have **{p['talent_points']}** points to spend again with /talent_buy",
        )

    @player.command(name="species", description="STAFF: Set a member's species (free, no waiting).")
    @app_commands.describe(member="Whose species to set", kind="The species (None = no species)")
    @app_commands.rename(kind="species")
    @app_commands.choices(kind=[
        *[app_commands.Choice(name=f"{s.emoji} {s.name}", value=s.key) for s in species.SPECIES.values()],
        app_commands.Choice(name="None", value="none"),
    ])
    @staff_only()
    async def set_species(self, interaction: discord.Interaction, member: discord.Member, kind: str):
        key = None if kind == "none" else kind
        res = await self.bot.db.run(species.staff_set, member.id, key)
        await self.answer(
            interaction, f"✅ {member.mention}: {species.label(res['before'])} → **{species.label(key)}**.",
            member, f"🧬 The staff set your species to **{species.label(key)}**",
        )
        cog = self.bot.get_cog("SpeciesCog")
        if cog is not None:
            await cog.sync_roles(member.id)  # type: ignore[attr-defined]

    @player.command(name="dimension", description="STAFF: Set the furthest dimension a member reached (the ones before it too).")
    @app_commands.describe(member="Whose dimensions to set", dimension="Their furthest dimension (Overworld = locks the others)")
    @app_commands.choices(dimension=[app_commands.Choice(name=dimensions.label(d), value=d) for d in DIMENSIONS])
    @staff_only()
    async def set_dimension(self, interaction: discord.Interaction, member: discord.Member, dimension: str):
        res = await self.bot.db.run(dimensions.set_highest, member.id, dimension)
        opened = ", ".join(dimensions.label(d) for d in res["unlocked"])
        await self.answer(
            interaction, f"✅ {member.mention}: {dimensions.label(res['before'])} → **{dimensions.label(dimension)}** "
                         f"(unlocked: {opened}).",
            member, f"🌍 The staff set your dimensions: you can now mine in {opened}",
        )
        cog = self.bot.get_cog("DimensionsCog")
        if cog is not None:
            await cog.sync_roles(member.id)  # type: ignore[attr-defined]

    @player.command(name="title", description="STAFF: Give a member a custom title (shown on their profile card).")
    @app_commands.describe(member="Who gets the title", title="The title (40 characters at most)")
    @staff_only()
    async def give_title(self, interaction: discord.Interaction, member: discord.Member, title: app_commands.Range[str, 1, 40]):
        text = await self.bot.db.run(profiles.give_title, member.id, title)
        await self.answer(interaction, f"✅ {member.mention} now wears the title **{text}**.",
                          member, f"🎖️ The staff gave you the title **{text}** (change it with /customize title)")

    @player.command(name="profile_reset", description="STAFF: Remove a member's bio and/or title (and their custom titles).")
    @app_commands.describe(member="Whose profile", part="What to remove", reason="Why (sent to the member)")
    @app_commands.choices(part=[
        app_commands.Choice(name="Bio", value="bio"),
        app_commands.Choice(name="Title (and custom titles)", value="title"),
        app_commands.Choice(name="Both", value="all"),
    ])
    @staff_only()
    async def profile_reset(self, interaction: discord.Interaction, member: discord.Member, part: str,
                            reason: app_commands.Range[str, 1, 400] | None = None):
        await self.bot.db.run(profiles.reset, member.id, part)
        what = {"bio": "bio", "title": "title", "all": "bio and title"}[part]
        await self.answer(interaction, f"✅ {member.mention}'s {what} was removed.", member,
                          f"🧹 The staff removed your profile {what}", reason)

    @player.command(name="cooldowns", description="STAFF: Reset a member's waiting times (rob, dungeon, daily…).")
    @app_commands.describe(member="Whose waiting times", timer="Which one (empty = all of them)",
                           reason="Why (sent to the member)")
    @app_commands.choices(timer=[app_commands.Choice(name=label, value=key) for key, label in cooldowns.TIMERS.items()])
    @staff_only()
    async def reset_cooldowns(self, interaction: discord.Interaction, member: discord.Member, timer: str | None = None,
                              reason: app_commands.Range[str, 1, 300] | None = None):
        if member.bot:
            raise GameError("Bots don't play.")
        timers = [timer] if timer else list(cooldowns.TIMERS)
        done = await self.bot.db.run(cooldowns.reset, member.id, timers)
        self.clear_in_memory(member.id, done)
        if not done:
            raise GameError(f"{member.mention} had nothing to wait for there.")
        names = ", ".join(cooldowns.TIMERS[t] for t in done)
        await self.answer(interaction, f"⏱️ {member.mention}'s waiting times were reset: **{names}**.", member,
                          f"⏱️ The staff reset your waiting times: **{names}**. You can play again right away", reason)
        await self.log("⏱️ Waiting times reset", member, interaction.user, names, reason)

    def clear_in_memory(self, user_id: int, timers: list[str]) -> None:
        """The short waits the cogs keep in memory."""
        if "duel" in timers and (cog := self.bot.get_cog("DuelCog")) is not None:
            cog.cooldown_until.pop(user_id, None)  # type: ignore[attr-defined]
        if "games" in timers:
            for name in ("LuckyBlockCog", "RouletteCog", "BlackjackCog", "MinesCog"):
                if (cog := self.bot.get_cog(name)) is not None:
                    cog._next.pop(user_id, None)  # type: ignore[attr-defined]
        if "mining" in timers and (cog := self.bot.get_cog("EconomyMiningCog")) is not None:
            cog._next_mine.pop(user_id, None)  # type: ignore[attr-defined]
            cog._next_spam.pop(user_id, None)  # type: ignore[attr-defined]

    @player.command(name="sync_roles", description="STAFF: Give every member the level role matching their level.")
    @staff_only()
    async def sync_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        levels = await self.bot.db.run(lambda ctx: [(r["user_id"], r["level"]) for r in ctx.all("SELECT user_id, level FROM users;")])
        for user_id, level in levels:
            await self.bot.announcer.sync_level_role(user_id, level)
        await interaction.followup.send(f"✅ Level roles checked for **{len(levels)}** player(s).", ephemeral=True)


    # ---------- /reset ----------
    @app_commands.command(name="reset", description="STAFF: A fresh start: reset emeralds, gear, levels or stats of a player or of everyone.")
    @app_commands.describe(member="Only this player (leave empty for the whole server)")
    @staff_only()
    async def reset_cmd(self, interaction: discord.Interaction, member: discord.Member | None = None):
        view = ResetView(self, interaction.user.id, member)
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    async def backup_first(self, what: str):
        """A backup of the database before something that can't be undone. Raises if it fails."""
        tools = self.bot.get_cog("AdminToolsCog")
        if tools is None:
            raise GameError(f"Backups aren't available right now: nothing was {what}.")
        now = datetime.now(ZoneInfo(settings.get()["timezone"]))
        target = backups.manual_path(backups.backup_dir(self.bot.db.path), now)
        try:
            await tools.make_backup(target)  # type: ignore[attr-defined]
        except Exception:
            log.exception("Backup before %s failed", what)
            raise GameError(f"The backup failed, so nothing was {what}. Check the bot logs.")
        return target

    async def do_reset(self, interaction: discord.Interaction, member: discord.Member | None, parts: list[str]) -> discord.Embed:
        """Back up the database, then reset. Nothing is reset if the backup fails."""
        target = await self.backup_first("reset")
        user_id = member.id if member else None

        def run(ctx):
            return reset.apply(ctx, parts, user_id), reset.affected_users(ctx, user_id)

        result, user_ids = await self.bot.db.run(run)
        who = member.mention if member else "**the whole server**"
        what = "\n".join(f"• {reset.PARTS[p]}" for p in parts)

        def summary() -> discord.Embed:
            embed = discord.Embed(title="♻️ Reset done", color=discord.Color.dark_red(),
                                  description=f"Reset for {who} ({result['players']} player(s)):\n{what}")
            embed.add_field(name="Backup made just before", value=f"`{target.name}` (restore it to undo)", inline=False)
            if "levels" in parts:
                embed.add_field(name="Level roles", value="Being removed in the background.", inline=False)
            return embed

        if "levels" in parts:
            # Level roles follow the level: everyone is level 1 again.
            asyncio.create_task(self.sync_roles_of(user_ids))
        dims = self.bot.get_cog("DimensionsCog")
        if "progress" in parts and dims is not None:  # back to the overworld: the dimension roles go
            asyncio.create_task(dims.sync_roles(user_id))  # type: ignore[attr-defined]
        seasons_cog = self.bot.get_cog("SeasonsCog")
        if "progress" in parts and member is None and seasons_cog is not None:
            # The past seasons are gone: nobody is champion anymore.
            await seasons_cog.move_champion_role(None)  # type: ignore[attr-defined]
        log_embed = summary()
        log_embed.add_field(name="By", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=False)
        await self.bot.announcer.send(embed=log_embed, channel="staff_log")
        embed = summary()
        log.warning("%s reset %s for %s", interaction.user, ", ".join(parts), member or "the whole server")
        return embed

    # ---------- /rewind_gear ----------
    @app_commands.command(name="rewind_gear", description="STAFF: Take back every piece of gear and netherite ingot and pay them back in full.")
    @staff_only()
    async def rewind_gear(self, interaction: discord.Interaction):
        plan = await self.bot.db.run(rewind.plan)
        total = rewind.summary(plan)
        if not total["players"]:
            raise GameError("Nobody has gear or netherite ingots: nothing to rewind.")
        text = (
            "♻️ **Rewind the gear of the whole server?**\n"
            f"Every piece of gear (weapons, armor, tools, shields, worn or not) and every netherite ingot is taken back "
            f"and paid back in full (recipe + books), auction listings of them too:\n"
            f"• **{total['players']}** player(s) · **{total['pieces']}** piece(s) · **{total['ingots']}** netherite "
            f"ingot(s) · **{total['listings']}** listing(s)\n"
            f"• **{em(total['emeralds'])}** paid back in all\n"
            "A backup is made first. Each player gets a DM with their refund."
        )

        async def sure(i: discord.Interaction) -> None:
            await i.response.edit_message(
                content=text + "\n\n⚠️ **Last check**: this can only be undone by restoring the backup.",
                view=ConfirmView(interaction.user.id, "Yes, rewind everything", go))

        async def go(i: discord.Interaction) -> None:
            await i.response.edit_message(content="♻️ Backing up, then rewinding…", view=None)
            try:
                target = await self.backup_first("rewound")
            except GameError as error:
                await i.edit_original_response(content=f"❌ {error}")
                return
            done = await self.bot.db.run(rewind.apply)
            result = rewind.summary(done)
            summary = (f"**{result['players']}** player(s) · **{result['pieces']}** piece(s) · **{result['ingots']}** "
                       f"netherite ingot(s) · **{result['listings']}** listing(s) · **{em(result['emeralds'])}** paid back.")
            await i.edit_original_response(content=f"✅ Gear rewound. {summary}\nBackup: `{target.name}`.")
            embed = discord.Embed(title="♻️ Gear rewound", description=summary, color=discord.Color.dark_red())
            embed.add_field(name="Backup made just before", value=f"`{target.name}` (restore it to undo)", inline=False)
            embed.add_field(name="By", value=f"{interaction.user.mention} (`{interaction.user}`)", inline=False)
            await self.bot.announcer.send(embed=embed, channel="staff_log")
            log.warning("%s rewound the gear: %s", interaction.user, result)
            asyncio.create_task(self.dm_refunds(done))

        await interaction.response.send_message(text, view=ConfirmView(interaction.user.id, "Rewind", sure),
                                                ephemeral=True)

    async def dm_refunds(self, refunds: dict[int, dict]) -> None:
        """Tell each player what the rewind took and paid back (in the background: DMs are slow)."""
        for uid, e in refunds.items():
            try:
                user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                parts = []
                if e["pieces"]:
                    parts.append(f"{e['pieces']} piece(s) of gear")
                if e["ingots"]:
                    parts.append(f"{e['ingots']} netherite ingot(s)")
                if e["listings"]:
                    parts.append(f"{e['listings']} auction listing(s)")
                await dm(user, f"♻️ **New season, new gear!** Your {', '.join(parts)} were taken back and paid back "
                               f"in full: **+{em(e['emeralds'])}**. Craft your new gear with `/craft`; netherite is "
                               "now found in the Nether (`/dimensions`).")
            except Exception:  # one closed DM must not stop the others
                log.warning("Could not DM the rewind refund to %s", uid, exc_info=True)
            await asyncio.sleep(1)

    async def sync_roles_of(self, user_ids: list[int]) -> None:
        try:
            for user_id in user_ids:
                await self.bot.announcer.sync_level_role(user_id, 1)
        except Exception:  # a background task: log instead of losing the error
            log.exception("Updating the level roles after /reset failed")


class ResetView(BaseView):
    """/reset: pick what to reset, then confirm by typing RESET."""

    def __init__(self, cog: StaffEconomyCog, user_id: int, member: discord.Member | None):
        super().__init__(allowed_ids={user_id}, timeout=300)
        self.cog, self.member = cog, member
        self.parts = list(reset.PARTS)
        self.add_item(PartsSelect(self.parts))
        self.add_item(ResetButton())

    def embed(self) -> discord.Embed:
        who = self.member.mention if self.member else "**every player of the server**"
        lines = [f"{'☑️' if key in self.parts else '⬜'} {label}" for key, label in reset.PARTS.items()]
        embed = discord.Embed(
            title="♻️ Reset",
            description=f"For {who}:\n" + "\n".join(lines) + "\n\nPick what to reset in the menu, then press **Reset…** "
                        "and type `RESET` to confirm. A backup of the database is made just before.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Never touched", value="Minecraft links, moderation, teams, settings, bosses, tournaments, "
                                                    "villager, Blockdle.", inline=False)
        return embed


class PartsSelect(discord.ui.Select):
    view: ResetView

    def __init__(self, selected: list[str]):
        options = [discord.SelectOption(label=label, value=key, default=key in selected) for key, label in reset.PARTS.items()]
        super().__init__(placeholder="What to reset…", options=options, min_values=1, max_values=len(options), row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.parts = [key for key in reset.PARTS if key in self.values]
        for option in self.options:
            option.default = option.value in self.view.parts
        await interaction.response.edit_message(embed=self.view.embed(), view=self.view)


class ResetButton(discord.ui.Button):
    view: ResetView

    def __init__(self):
        super().__init__(label="Reset…", emoji="♻️", style=discord.ButtonStyle.danger, row=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ResetModal(self.view))


class ResetModal(discord.ui.Modal, title="Confirm the reset"):
    confirm = discord.ui.TextInput(label="Type RESET to confirm", placeholder="RESET", max_length=10)

    def __init__(self, view: ResetView):
        super().__init__()
        self.menu = view

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.confirm.value).strip() != "RESET":
            raise GameError("Not confirmed (type RESET in capitals): nothing was reset.")
        await interaction.response.defer()
        embed = await self.menu.cog.do_reset(interaction, self.menu.member, self.menu.parts)
        self.menu.stop()
        await interaction.edit_original_response(embed=embed, view=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffEconomyCog(bot))
