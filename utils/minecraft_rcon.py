from __future__ import annotations

import asyncio

from mcrcon import MCRcon

from utils.config import load_config


def _rcon_command_sync(command: str) -> str:
    mc = load_config()["minecraft"]
    with MCRcon(mc["rcon_host"], mc["rcon_password"], port=int(mc["rcon_port"])) as mcr:
        return mcr.command(command)


async def rcon_command(command: str) -> str:
    """Send a command to the Minecraft server without blocking the bot."""
    return await asyncio.to_thread(_rcon_command_sync, command)
