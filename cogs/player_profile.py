from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from game import leaderboard, players, profiles, settings, species
from game.errors import GameError
from utils import profile_card
from utils.ui import ConfirmView, em

log = logging.getLogger("profiles")


# ---------------- the card ----------------
async def avatar_bytes(member: discord.abc.User) -> bytes | None:
    try:
        return await member.display_avatar.with_size(128).read()
    except (discord.HTTPException, ValueError):
        return None


def card_data(member: discord.abc.User, p: dict, avatar: bytes | None, override: dict | None = None):
    """What the card shows, from leaderboard.profile() (and a change being previewed)."""
    u = p["user"]
    custom = {**p["custom"], **(override or {})}
    unlocked = [a for a, _ in p["achievements"]["unlocked"]]
    names = {a.code: a.name for a in unlocked}
    showcase = [names[c] for c in custom["showcase"] if c in names] or [a.name for a in unlocked[-3:]]
    team = p["team"]
    kind = u.get("species")
    return profile_card.CardData(
        name=member.display_name, level=u["level"], xp=u["xp"], xp_needed=players.xp_required_for_level(u["level"]),
        emeralds=u["emeralds"], accent=profiles.color_rgb(custom["color"]), tag=team["tag"] if team else None,
        title=profiles.title_label(custom["title"]), fortune_rank=p["fortune_rank"],
        species=species.SPECIES[kind].name if kind in species.SPECIES else None, bio=custom["bio"],
        showcase=showcase, frame=custom["frame"], avatar=avatar, banner=p.get("banner"),
        team_name=team["name"] if team else None, champion=p["is_champion"],
    )


async def card_file(member: discord.abc.User, p: dict, override: dict | None = None) -> discord.File | None:
    """The profile card as an attachment (None without Pillow, or if drawing failed)."""
    if not profile_card.AVAILABLE:
        return None
    try:
        data = card_data(member, p, await avatar_bytes(member), override)
        png = await asyncio.to_thread(profile_card.render_card, data)
    except Exception:
        log.exception("Could not draw the profile card")
        return None
    return discord.File(io.BytesIO(png), filename="profile.png")


def banner_file(banner: dict, name: str = "banner.png") -> discord.File | None:
    if not profile_card.AVAILABLE or not banner:
        return None
    return discord.File(io.BytesIO(profile_card.render_banner(banner)), filename=name)


# ---------------- /customize ----------------
class ProfileCog(commands.Cog):
    """/customize: the bio, color, frame, title and showcase of your profile card."""

    group = app_commands.Group(name="customize", description="Customize your profile card: bio, color, frame, title, showcase.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def change(self, interaction: discord.Interaction, override: dict, label: str, cost: int, apply) -> None:
        """Show the card with the change (only you see it). A purchase is confirmed first."""
        member = interaction.user
        p = await self.bot.db.run(leaderboard.profile, member.id)
        file = await card_file(member, p, override)
        files = [file] if file else []
        if not cost:
            await self.bot.db.run(apply)
            await interaction.response.send_message(f"✅ {label}", files=files, ephemeral=True)
            return

        async def do(i: discord.Interaction) -> None:
            await self.bot.db.run(apply)
            await i.response.edit_message(content=f"✅ {label} (-{em(cost)})", view=None)

        await interaction.response.send_message(
            f"{label}: buy it for {em(cost)}? (preview below)", files=files,
            view=ConfirmView(member.id, f"Buy ({cost:,})", do), ephemeral=True,
        )

    # ---------- suggestions ----------
    async def color_autocomplete(self, interaction: discord.Interaction, current: str):
        def load(ctx):
            owned = {r["key"] for r in ctx.all("SELECT key FROM profile_unlocks WHERE user_id=? AND kind='color';",
                                               (interaction.user.id,))}
            return owned
        owned = await self.bot.db.run(load)
        price = int(settings.get()["profiles"]["color_price"])
        out = [app_commands.Choice(name="Default (free)", value="default")]
        for key, (name, _) in profiles.DYES.items():
            out.append(app_commands.Choice(name=f"{name} — {'owned' if key in owned else f'{price:,} emeralds'}", value=key))
        return [c for c in out if current.lower() in c.name.lower()][:25]

    async def frame_autocomplete(self, interaction: discord.Interaction, current: str):
        states = await self.bot.db.run(profiles.frames_of, interaction.user.id)
        prices = settings.get()["profiles"]["frame_prices"]
        out = [app_commands.Choice(name="No frame", value="none")]
        for key, frame in profiles.FRAMES.items():
            state = states[key]
            what = ("owned" if state == "owned" else f"{int(prices[key]):,} emeralds" if state == "price"
                    else f"earned: {frame.how}")
            out.append(app_commands.Choice(name=f"{frame.name} — {what}"[:100], value=key))
        return [c for c in out if current.lower() in c.name.lower()][:25]

    async def title_autocomplete(self, interaction: discord.Interaction, current: str):
        mine = await self.bot.db.run(profiles.titles_of, interaction.user.id)
        out = [app_commands.Choice(name="No title", value="none")]
        out += [app_commands.Choice(name=label[:100], value=value[:100]) for value, label in mine]
        return [c for c in out if current.lower() in c.name.lower()][:25]

    async def badge_autocomplete(self, interaction: discord.Interaction, current: str):
        p = await self.bot.db.run(leaderboard.profile, interaction.user.id)
        out = [app_commands.Choice(name=a.name, value=a.code) for a, _ in p["achievements"]["unlocked"]]
        return [c for c in out if current.lower() in c.name.lower()][:25]

    # ---------- commands ----------
    @group.command(name="bio", description="Your bio, shown on your profile card (leave empty to remove it).")
    @app_commands.describe(text="A few words about you")
    async def bio(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 300] | None = None):
        clean = " ".join((text or "").split()) or None
        if clean and len(clean) > int(settings.get()["profiles"]["bio_max"]):
            raise GameError(f"Your bio can be **{settings.get()['profiles']['bio_max']}** characters at most.")
        await self.change(interaction, {"bio": clean}, "Bio updated." if clean else "Bio removed.", 0,
                          lambda ctx: profiles.set_bio(ctx, interaction.user.id, clean))

    @group.command(name="color", description="The color of your profile card (each color is bought once).")
    @app_commands.describe(color="A dye color")
    @app_commands.autocomplete(color=color_autocomplete)
    async def color(self, interaction: discord.Interaction, color: str):
        cost = await self.bot.db.run(profiles.color_cost, interaction.user.id, color)
        name = "Default" if color == "default" else profiles.DYES[color][0]
        await self.change(interaction, {"color": color}, f"Color: **{name}**", cost,
                          lambda ctx: profiles.set_color(ctx, interaction.user.id, color))

    @group.command(name="hex", description="Any color by its code, e.g. #ff8800 (unlocked once for every code).")
    @app_commands.describe(code="A color code like #ff8800")
    async def hex_color(self, interaction: discord.Interaction, code: app_commands.Range[str, 6, 7]):
        cost = await self.bot.db.run(profiles.color_cost, interaction.user.id, code.strip().lower())
        await self.change(interaction, {"color": code.strip().lower()}, f"Color: **{code}**", cost,
                          lambda ctx: profiles.set_color(ctx, interaction.user.id, code))

    @group.command(name="frame", description="The patterned frame of your profile card.")
    @app_commands.describe(frame="Bought frames, and frames earned by playing")
    @app_commands.autocomplete(frame=frame_autocomplete)
    async def frame(self, interaction: discord.Interaction, frame: str):
        cost = await self.bot.db.run(profiles.frame_cost, interaction.user.id, frame)
        name = "No frame" if frame == "none" else profiles.FRAMES[frame].name
        await self.change(interaction, {"frame": None if frame == "none" else frame}, f"Frame: **{name}**", cost,
                          lambda ctx: profiles.set_frame(ctx, interaction.user.id, frame))

    @group.command(name="title", description="The title under your name (earned by playing, or given by the staff).")
    @app_commands.describe(title="One of your titles")
    @app_commands.autocomplete(title=title_autocomplete)
    async def title(self, interaction: discord.Interaction, title: str):
        if title != "none":
            mine = dict(await self.bot.db.run(profiles.titles_of, interaction.user.id))
            if title not in mine:
                t = profiles.TITLES.get(title)
                raise GameError(f"You haven't earned **{t.name}** yet: {t.how}." if t else "Unknown title.")
        await self.change(interaction, {"title": None if title == "none" else title},
                          "Title removed." if title == "none" else f"Title: **{profiles.title_label(title)}**", 0,
                          lambda ctx: profiles.set_title(ctx, interaction.user.id, title))

    @group.command(name="showcase", description="Up to 3 achievements shown first on your card (none = the latest).")
    @app_commands.describe(badge1="An achievement", badge2="Another one", badge3="And a third")
    @app_commands.autocomplete(badge1=badge_autocomplete, badge2=badge_autocomplete, badge3=badge_autocomplete)
    async def showcase(self, interaction: discord.Interaction, badge1: str | None = None,
                       badge2: str | None = None, badge3: str | None = None):
        codes = [c for c in (badge1, badge2, badge3) if c]
        await self.bot.db.run(profiles.set_showcase, interaction.user.id, codes)  # checks them
        await self.change(interaction, {"showcase": codes}, "Showcase updated." if codes else "Showcase reset.", 0,
                          lambda ctx: None)

    @group.command(name="list", description="Your colors, frames and titles, and how to get the others.")
    async def list_cmd(self, interaction: discord.Interaction):
        def load(ctx):
            uid = interaction.user.id
            colors = {r["key"] for r in ctx.all("SELECT key FROM profile_unlocks WHERE user_id=? AND kind='color';", (uid,))}
            hexed = bool(ctx.one("SELECT 1 FROM profile_unlocks WHERE user_id=? AND kind='hex';", (uid,)))
            return colors, hexed, profiles.frames_of(ctx, uid), dict(profiles.titles_of(ctx, uid))

        colors, hexed, frames, titles = await self.bot.db.run(load)
        c = settings.get()["profiles"]
        embed = discord.Embed(title="🎨 Your profile customization", color=discord.Color.blurple())
        owned_colors = [profiles.DYES[k][0] for k in profiles.DYES if k in colors]
        embed.add_field(
            name="Colors",
            value=(", ".join(owned_colors) or "Only the default") + f"\nOthers: {em(c['color_price'])} each · any #hex: "
                  + ("**unlocked**" if hexed else em(c["hex_price"])),
            inline=False,
        )
        lines = []
        for key, frame in profiles.FRAMES.items():
            state = frames[key]
            what = ("✅ owned" if state == "owned" else em(c["frame_prices"][key]) if state == "price"
                    else f"🔒 {frame.how}")
            lines.append(f"**{frame.name}** — {what}")
        embed.add_field(name="Frames", value="\n".join(lines), inline=False)
        earned = [t for t in profiles.TITLES.values() if t.key in titles]
        locked = [t for t in profiles.TITLES.values() if t.key not in titles]
        customs = [label for value, label in titles.items() if value.startswith("custom:")]
        text = ", ".join(t.name for t in earned) or "None yet"
        if customs:
            text += "\nFrom the staff: " + ", ".join(customs)
        embed.add_field(name="Titles earned", value=text[:1024], inline=False)
        embed.add_field(name="Titles to earn", value="\n".join(f"🔒 **{t.name}** — {t.how}" for t in locked)[:1024] or "All of them!",
                        inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
