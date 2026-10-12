"""What's new: entries that fit in a Discord embed and are never posted twice."""
from __future__ import annotations

import re
import unittest

from tests.test_manual import slash_commands
from utils.updates import UPDATES


class UpdatesTests(unittest.TestCase):
    def test_keys_are_unique_and_dates_valid(self):
        keys = [u.key for u in UPDATES]
        self.assertEqual(len(keys), len(set(keys)), "an update key is used twice")
        for u in UPDATES:
            self.assertRegex(u.date, r"^\d{4}-\d{2}-\d{2}$", u.key)
        self.assertEqual([u.date for u in UPDATES], sorted(u.date for u in UPDATES), "add new entries at the end")

    def test_each_entry_fits_in_an_embed(self):
        for u in UPDATES:
            self.assertLessEqual(len(u.title) + 3, 256, u.key)
            self.assertLessEqual(len(u.text) + 100, 4096, u.key)  # room for the wiki link
            self.assertLessEqual(len(u.parts), 25, u.key)
            for name, value in u.parts:
                self.assertLessEqual(len(name), 256, u.key)
                self.assertLessEqual(len(value), 1024, u.key)
            total = len(u.title) + len(u.text) + 100 + sum(len(n) + len(v) for n, v in u.parts) + 40
            self.assertLessEqual(total, 6000, u.key)

    def test_only_player_commands(self):
        staff = {name for name, cmd in slash_commands().items() if cmd.staff}
        for u in UPDATES:
            text = u.text + " ".join(v for _, v in u.parts)
            mentioned = set(re.findall(r"`/([a-z_]+(?: [a-z_]+)?)", text))
            self.assertEqual(mentioned & staff, set(), u.key)
