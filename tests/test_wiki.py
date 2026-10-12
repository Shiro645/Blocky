"""The wiki: every player command explained, no staff command, and parts that fit in Discord messages."""
from __future__ import annotations

import unittest

from game import settings
from tests.test_manual import slash_commands
from utils import manual, wiki


class WikiTests(unittest.TestCase):
    def setUp(self) -> None:
        settings.load(None)

    def tearDown(self) -> None:
        settings.load(None)

    def text(self) -> str:
        return "\n".join(section.text for section in wiki.SECTIONS)

    def test_every_player_command_is_explained(self):
        text = self.text()

        def mentioned(name: str) -> bool:
            top, _, sub = name.partition(" ")
            return f"/{top}" in text and (not sub or sub in text)

        missing = [name for name, cmd in slash_commands().items() if not cmd.staff and not mentioned(name)]
        self.assertEqual(missing, [], "player commands the wiki doesn't talk about")

    def test_no_staff_command(self):
        text = self.text()
        staff = [name for name, cmd in slash_commands().items() if cmd.staff and f"`/{name}" in text]
        self.assertEqual(staff, [])

    def test_the_parts_fit_in_discord(self):
        for overrides in (None, {"games": {"quiz_every_minutes": 0}, "boss": {"auto_spawn_hours": 48},
                                 "teams": {"log_score": False}, "guide": {"delete_after_days": 0}}):
            settings.load(overrides)
            for section in wiki.SECTIONS:
                for name in section.pages:
                    self.assertIn(name, manual.BY_NAME, section.key)
                lines = wiki.numbers(section, settings.get())
                self.assertLessEqual(len(section.text), 4096, section.key)
                self.assertTrue(all(len(line) <= 1024 for line in lines), section.key)
                self.assertEqual(len(lines), len(set(lines)), section.key)
                self.assertLessEqual(len(section.title) + len(section.text) + sum(len(x) + 1 for x in lines), 5800,
                                     section.key)
        self.assertEqual(len({s.key for s in wiki.SECTIONS}), len(wiki.SECTIONS))
