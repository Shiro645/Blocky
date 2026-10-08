from __future__ import annotations

import aiohttp


async def fetch_uuid(username: str) -> str | None:
    """UUID of a Minecraft Java account, or None if it doesn't exist."""
    url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            raw = (await resp.json())["id"]
            return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
