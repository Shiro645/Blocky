"""Shared Discord helpers: formatting, replies and error handling."""
from __future__ import annotations

import logging

import discord

from game.errors import GameError
from utils.config import load_emojis

log = logging.getLogger("ui")

EMOJI = load_emojis()

BLOCK_ICONS = {"cobblestone": "🪨", "gravel": "🟫", "deepslate": "⬛", "bedrock": "🟪"}


def em(amount: int) -> str:
    """'12 <:emerald:...>'"""
    return f"{amount:,} {EMOJI['emerald']}".strip()


def mat(material: str) -> str:
    """Emoji of a material ('' when not configured)."""
    return EMOJI.get(material, "")


def item_label(item: str, material: str, amount: int | None = None) -> str:
    if item == "stick":
        text = f"{EMOJI['stick']} stick" + ("s" if amount != 1 else "")
    else:
        text = f"{mat(material)} {material} {item}".strip()
    return f"{amount} × {text}" if amount is not None else text


def gear_label(g: dict, show_durability: bool = True) -> str:
    text = f"{mat(g['material'])} **{g['material']} {g['item']}**".strip()
    if show_durability:
        text += f" `{g['durability']}/{g['max_durability']}`"
    return text


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
