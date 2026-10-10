from __future__ import annotations

import asyncio

import aiohttp

from game.errors import GameError


async def fetch_uuid(username: str) -> str | None:
    """UUID of a Minecraft Java account, or None if it doesn't exist.

    Raises GameError when Mojang can't answer (down, rate limited, network error):
    that must not be reported as "this account doesn't exist".
    """
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status in (204, 404):
                    return None
                if resp.status != 200:
                    raise GameError(f"The Mojang API is unavailable right now (HTTP {resp.status}). Try again in a few minutes.")
                raw = (await resp.json())["id"]
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise GameError("Couldn't reach the Mojang API. Try again in a few minutes.")
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
