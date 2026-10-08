from __future__ import annotations

import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from game import settings
from game.db import Database

# Wednesday 2026-10-07 12:00 Paris time.
START = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp()
DAY = 86400


class GameTestCase(unittest.IsolatedAsyncioTestCase):
    """Fresh database, default settings, fixed clock and seeded randomness."""

    overrides: dict | None = None

    async def asyncSetUp(self) -> None:
        settings.load(self.overrides)
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
