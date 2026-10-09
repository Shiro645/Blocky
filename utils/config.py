from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path("config.json")


def read_config_file() -> Dict[str, Any]:
    """Read and parse config.json, with a readable error if it is invalid."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json not found at the project root.")
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).") from e
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object ({ ... }).")
    return data


@lru_cache(maxsize=1)
def load_config() -> Dict[str, Any]:
    """config.json, read once (see reload_config)."""
    return read_config_file()


def reload_config() -> Dict[str, Any]:
    """Re-read config.json. If it is invalid, raise and keep the current config."""
    read_config_file()  # validate first: on error the current config stays
    load_config.cache_clear()
    return load_config()


def balance_overrides(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The "balance" section, plus the old economy.cooldown_seconds key."""
    balance = dict(cfg.get("balance") or {})
    legacy_cooldown = cfg.get("economy", {}).get("cooldown_seconds")
    if legacy_cooldown is not None and "cooldown_seconds" not in balance.get("mining", {}):
        balance["mining"] = {**balance.get("mining", {}), "cooldown_seconds": legacy_cooldown}
    return balance


def channel_id(name: str) -> int:
    """ID of a channel from the "channels" section (0 if not set)."""
    return int(load_config().get("channels", {}).get(name, 0) or 0)


def role_id(name: str) -> int:
    """ID of a role from the "roles" section (0 if not set)."""
    return int(load_config().get("roles", {}).get(name, 0) or 0)


def staff_role_id() -> int:
    return int(load_config().get("staff", {}).get("role_id", 0) or 0)
