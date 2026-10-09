"""Shared Discord helpers: formatting, replies and error handling."""
from __future__ import annotations

import logging
from collections import defaultdict

import discord

from game.errors import GameError
from utils import emojis
from utils.config import load_config

log = logging.getLogger("ui")

# name -> emoji code. Filled from config.json now, then from the application
# emojis once the bot is logged in (see load_application_emojis).
EMOJI: defaultdict[str, str] = defaultdict(str, emojis.resolve(load_config().get("emojis") or {}, {}))


async def load_application_emojis(client: discord.Client) -> None:
    """Use the emojis uploaded to the bot (Developer Portal > Emojis), found by name."""
    try:
        app = {e.name: str(e) for e in await client.fetch_application_emojis()}
    except Exception:  # never prevent the bot from starting because of emojis
        log.warning("Could not fetch the application emojis, using config.json only", exc_info=True)
        app = {}
    resolved = emojis.resolve(load_config().get("emojis") or {}, app)
    EMOJI.clear()
    EMOJI.update(resolved)
    absent = emojis.missing(resolved)
    log.info("Emojis: %d found, %d missing", len(emojis.EXPECTED_NAMES) - len(absent), len(absent))
    if absent:
        log.info("Missing emojis (upload them with these names): %s", ", ".join(absent))


def em(amount: int) -> str:
    """'12 <:emerald:...>'"""
    return f"{amount:,} {EMOJI['emerald']}".strip()


def mat(material: str) -> str:
    """Emoji of a material ('' when not configured)."""
    return EMOJI.get(material, "")


def gear_icon(item: str, material: str) -> str:
    """Emoji of a piece of gear, or of its material when there is none."""
    return EMOJI.get(emojis.gear_key(item, material)) or mat(material)


def block_icon(block: str) -> str:
    return EMOJI.get(block) or emojis.BLOCK_FALLBACK[block]


def asset_icon(key: str) -> str:
    """Emoji for an asset key of game/assets.py ('' if none)."""
    parts = key.split(":")
    if parts[0] == "emeralds":
        return EMOJI.get("emerald", "")
    if parts[0] == "stick":
        return EMOJI.get("stick", "")
    if parts[0] == "block" and len(parts) == 2 and parts[1] in emojis.BLOCK_FALLBACK:
        return block_icon(parts[1])
    if parts[0] == "ingot" and len(parts) == 2:
        return mat(parts[1])
    if parts[0] == "gear" and len(parts) == 3:
        return gear_icon(parts[2], parts[1])
    return ""


def item_label(item: str, material: str, amount: int | None = None) -> str:
    if item == "stick":
        text = f"{EMOJI['stick']} stick" + ("s" if amount != 1 else "")
    else:
        text = f"{mat(material)} {material} {item}".strip()
    return f"{amount} × {text}" if amount is not None else text


def gear_label(g: dict, show_durability: bool = True) -> str:
    text = f"{gear_icon(g['item'], g['material'])} **{g['material']} {g['item']}**".strip()
    if show_durability:
        text += f" `{g['durability']}/{g['max_durability']}`"
    return text


def tag_prefix(tags: dict[int, str], user_id: int) -> str:
    """'`[ABC]` ' when the player is in a team, '' otherwise."""
    tag = tags.get(user_id)
    return f"`[{tag}]` " if tag else ""


def join_lines(lines: list[str], limit: int = 1024, empty: str = "—") -> str:
    """Join lines without cutting one in half (embed fields hold 1024 characters)."""
    out, size = [], 0
    for i, line in enumerate(lines):
        more = f"…and {len(lines) - i} more"
        if size + len(line) + 1 > limit - len(more) - 1:
            out.append(more)
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out) or empty


def progress_bar(current: int, total: int, width: int = 14) -> str:
    if total <= 0:
        return "█" * width
    filled = max(0, min(width, int(current / total * width)))
    return "█" * filled + "░" * (width - filled)


async def reply(interaction: discord.Interaction, content: str | None = None, *, ephemeral: bool = True, **kwargs) -> None:
    """Answer an interaction whether or not it was already answered/deferred."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)


async def report_error(interaction: discord.Interaction, error: Exception) -> None:
    if isinstance(error, GameError):
        message = f"❌ {error}"
    elif isinstance(error, discord.app_commands.CheckFailure):
        message = "❌ You don't have permission to use this command."
    elif isinstance(error, discord.app_commands.CommandOnCooldown):
        message = f"⏳ Slow down! Try again in **{error.retry_after:.0f}s**."
    elif isinstance(error, discord.Forbidden):
        log.error("Missing Discord permission", exc_info=error)
        message = (
            "❌ The bot is missing a Discord permission (a channel it can't see, or a role "
            "above its own). Ask an admin to check its permissions."
        )
    else:
        log.error("Unhandled interaction error", exc_info=error)
        message = "❌ Something went wrong. The error has been logged."
    try:
        await reply(interaction, message, ephemeral=True)
    except discord.HTTPException:
        pass


class BaseView(discord.ui.View):
    """View that reports GameError to the player and can be limited to some users."""

    def __init__(self, *, allowed_ids: set[int] | None = None, timeout: float | None = 180):
        super().__init__(timeout=timeout)
        self.allowed_ids = allowed_ids
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.allowed_ids is not None and interaction.user.id not in self.allowed_ids:
            await interaction.response.send_message("❌ This isn't for you.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        await report_error(interaction, error)

    def disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True

    async def on_timeout(self) -> None:
        self.disable_all()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
