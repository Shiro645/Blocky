from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from collections import defaultdict

CONFIG_PATH = Path("config.json")

def load_emojis() -> Dict[str, str]:
    """Emojis du config.json. Une clé manquante renvoie "" au lieu de planter."""
    return defaultdict(str, load_config().get("emojis", {}))

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json introuvable à la racine du projet.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
