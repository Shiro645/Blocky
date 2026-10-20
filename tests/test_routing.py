"""2.2.4: every player command has its channel (utils/routing.py)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from utils import routing

ROOT = Path(__file__).resolve().parent.parent


def root_commands() -> set[str]:
    names = set()
    for path in (ROOT / "cogs").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'app_commands\.command\(name="([a-z_]+)"', text))
        names |= set(re.findall(r'app_commands\.Group\(name="([a-z_]+)"', text))
    return names


class RoutingTests(unittest.TestCase):
    def test_places(self):
        self.assertEqual(routing.place_of("blackjack"), "casino")
        self.assertEqual(routing.place_of("boss"), "portal")
        self.assertEqual(routing.place_of("portal"), "portal")
        self.assertEqual(routing.place_of("rob"), "robberies")
        self.assertEqual(routing.place_of("blockdle"), "commands")
        self.assertEqual(routing.place_of("inventory"), "commands")
        self.assertIsNone(routing.place_of("help"))
        self.assertIsNone(routing.place_of("config", staff=True))

    def test_every_routed_command_exists(self):
        names = root_commands()
        for place, (_, _, commands) in routing.PLACES.items():
            for command in commands:
                self.assertIn(command, names, place)

    def test_a_place_not_set_works_anywhere(self):
        with mock.patch.object(routing, "channel_ids", return_value=set()):
            self.assertTrue(routing.allowed("casino", 5))
        with mock.patch.object(routing, "channel_ids", return_value={10}):
            self.assertTrue(routing.allowed("casino", 10))
            self.assertTrue(routing.allowed("casino", 99, parent_id=10))  # a thread of the casino
            self.assertFalse(routing.allowed("casino", 11))
            self.assertIn("<#10>", routing.refusal("wheel", "casino"))
        self.assertTrue(routing.allowed(None, 11))
        with mock.patch.object(routing, "channel_id", return_value=7):
            self.assertTrue(routing.allowed("robberies", 7))
            self.assertFalse(routing.allowed("robberies", 8))

    def test_the_game_channels_become_the_casino(self):
        self.assertIsNone(routing.migrate({"channels": {"mining": [1]}}))
        new = routing.migrate({"guild_id": 3, "channels": {"games": [5, 6], "mining": [1]}})
        self.assertEqual(new, {"guild_id": 3, "channels": {"casino": [5, 6], "mining": [1]}})
        kept = routing.migrate({"channels": {"games": [5], "casino": [9]}})
        self.assertEqual(kept["channels"], {"casino": [9]})


if __name__ == "__main__":
    unittest.main()
