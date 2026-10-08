from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path("config.json")


@lru_cache(maxsize=1)
def load_config() -> Dict[str, Any]:
    """config.json, read once. Restart the bot after editing it."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found at the project root.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def channel_id(name: str) -> int:
    """ID of a channel from the "channels" section (0 if not set)."""
    return int(load_config().get("channels", {}).get(name, 0) or 0)


def role_id(name: str) -> int:
    """ID of a role from the "roles" section (0 if not set)."""
    return int(load_config().get("roles", {}).get(name, 0) or 0)


def staff_role_id() -> int:
    return int(load_config().get("staff", {}).get("role_id", 0) or 0)
