from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from game import settings
from game.biomes import BIOMES
from game.db import Database

# The economy before the 2.2.1 prices (ingots 60-100× dearer, tools rebalanced): most tests were written with
# these numbers and check the game's logic, not its prices. Tests of the new prices set legacy_economy = False.
LEGACY_ECONOMY = {
    "market": {"ingots": {"gold": 5, "iron": 10, "diamond": 60, "netherite": 300}},
    "gear": {"durability": {"gold": 60, "iron": 250, "diamond": 800, "netherite": 1500},
             "pickaxe_extra_blocks_per_tier": 1},
    "daily": {"weekly_bonus_item": "diamond", "base_reward": 30, "streak_bonus_per_day": 10},
    # The rewards and costs before the 2.2.5 rescale.
    "repair": {"anvil_iron": 22},
    "seasons": {"rewards": [300, 150, 75]},
    "tournament": {"house_bonus": 200},
    "games": {"quiz_reward": 50},
    "biomes": {"challenge_reward": 250},
    "beacon": {"level_ingots": [81, 225, 441, 729], "contributor_value": 200},
    "pve": {"wave_rewards": [5, 8, 12, 18, 27]},
}
_NEW_ACHIEVEMENT_REWARDS = {"iron_set": 100, "diamond_set": 300, "netherite_set": 1000, "handyman_10": 100,
                            "beacon_builder": 500}
LEGACY_ECONOMY["achievements"] = {
    code: {"reward": _NEW_ACHIEVEMENT_REWARDS.get(code, int(a["reward"]) // 5)}
    for code, a in settings.DEFAULTS["achievements"].items() if "reward" in a
}
LEGACY_ECONOMY["achievements"]["beacon_builder"]["goal"] = 5000
LEGACY_ECONOMY["achievements"]["bedrock_100"]["goal"] = 100
LEGACY_ECONOMY["challenges"] = {"goals": {"find_bedrock": {"target": 5, "reward": 150}}}
LEGACY_ECONOMY["biomes"]["challenges"] = {"badlands": 6}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# Wednesday 2026-10-07 12:00 Paris time.
START = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
DAY = 86400


class GameTestCase(unittest.IsolatedAsyncioTestCase):
    """Fresh database, default settings, fixed clock and seeded randomness."""

    overrides: dict | None = None
    biomes_on = False  # no biome of the week: its bonuses would change the numbers the tests check
    legacy_economy = True

    async def asyncSetUp(self) -> None:
        if not self.biomes_on and "biomes" not in (self.overrides or {}):
            off = {"biomes": {"enabled": {k: False for k in BIOMES}}}
            base = _merge(LEGACY_ECONOMY, off) if self.legacy_economy else off
        else:
            base = LEGACY_ECONOMY if self.legacy_economy else {}
        overrides = _merge(base, self.overrides or {})
        settings.load(overrides)
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.now = START
        self.db.clock = lambda: self.now
        self.db.rng = random.Random(1234)
        self.notices: list = []

        async def handler(notices):
            self.notices.extend(notices)

        self.db.notice_handler = handler
        await self.db.open()

    async def asyncTearDown(self) -> None:
        await self.db.drain()
        await self.db.close()
        self._tmp.cleanup()

    async def run_game(self, fn, *args, **kwargs):
        result = await self.db.run(fn, *args, **kwargs)
        await self.db.drain()
        return result

    def advance(self, seconds: float) -> None:
        self.now += seconds
