"""2.4.0: asleep, a player only looks things up; /wake gets them up early."""
from __future__ import annotations

import re
from datetime import date

from game import daily, night, players
from game.errors import GameError
from tests.helpers import GameTestCase
from tests.test_routing import ROOT

ALICE = 1
HOUR = 3600


def qualified_commands() -> set[str]:
    """Every command name, "group sub" for the subcommands."""
    names = set()
    for path in (ROOT / "cogs").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        groups = dict(re.findall(r'(\w+)\s*=\s*app_commands\.Group\(name="([a-z_]+)"', text))
        names |= set(re.findall(r'@app_commands\.command\(name="([a-z_]+)"', text))
        for var, sub in re.findall(r'@(\w+)\.command\(name="([a-z_]+)"', text):
            if var in groups:
                names.add(f"{groups[var]} {sub}")
    return names


class SleepOkTests(GameTestCase):
    def test_every_allowed_command_exists(self):
        names = qualified_commands()
        for name in night.SLEEP_OK:
            self.assertIn(name, names)

    def test_the_shops_stay_closed(self):
        for name in ("market", "villager", "auction browse", "daily", "rob", "pve start", "sell"):
            self.assertNotIn(name, night.SLEEP_OK)


class WakeTests(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.set_level, ALICE, 10)

    async def test_asleep_until_dawn(self):
        self.assertIsNone(await self.run_game(night.asleep_until, ALICE))
        self.advance(11 * HOUR)  # 23:00
        self.assertIsNone(await self.run_game(night.asleep_until, ALICE))
        await self.run_game(night.sleep, ALICE)
        dawn = await self.run_game(night.asleep_until, ALICE)
        self.assertEqual(dawn, await self.run_game(night.next_change))
        self.advance(8 * HOUR)  # 07:00: morning
        self.assertIsNone(await self.run_game(night.asleep_until, ALICE))

    async def test_wake_undoes_the_night(self):
        with self.assertRaisesRegex(GameError, "not asleep"):
            await self.run_game(night.wake, ALICE)
        self.advance(11 * HOUR)
        await self.run_game(night.sleep, ALICE)  # the night of the 7th
        self.advance(24 * HOUR)
        await self.run_game(night.sleep, ALICE)  # the night of the 8th
        await self.run_game(night.wake, ALICE)
        self.assertIsNone(await self.run_game(night.asleep_until, ALICE))
        user = await self.run_game(players.get_user, ALICE)
        self.assertEqual(user["last_sleep"], date(2026, 10, 7).isoformat())  # the night before is kept
        self.assertEqual(await self.run_game(night.nights_awake, user, date(2026, 10, 9)), 1)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "nights_slept"), 1)
        with self.assertRaisesRegex(GameError, "got up this night"):
            await self.run_game(night.sleep, ALICE)
        self.assertTrue((await self.run_game(night.status, ALICE))["woke"])
        self.advance(10 * HOUR)  # 09:00 the next day
        self.assertFalse((await self.run_game(daily.claim, ALICE))["rested"])
        self.advance(14 * HOUR)  # the next night: back to bed
        await self.run_game(night.sleep, ALICE)

