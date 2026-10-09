from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from game import backups, players
from tests.helpers import GameTestCase
from utils import config
from utils.mc_commands import DEFAULT_BLOCKED, blocked_by, clean_output, normalize


class BackupTests(GameTestCase):
    async def test_backup_is_a_working_copy(self):
        await self.run_game(players.give_emeralds, 1, 42)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "copy.db"
            await self.db.backup_to(dest)
            conn = sqlite3.connect(dest)
            try:
                emeralds = conn.execute("SELECT emeralds FROM users WHERE user_id=1;").fetchone()[0]
            finally:
                conn.close()
        self.assertEqual(emeralds, 42)


class BackupScheduleTests(unittest.TestCase):
    def test_due_once_per_day_after_the_hour(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertIsNone(backups.due(folder, datetime(2026, 10, 9, 3, 59), hour=4))
            target = backups.due(folder, datetime(2026, 10, 9, 4, 0), hour=4)
            self.assertEqual(target.name, "economy-2026-10-09.db")
            target.write_bytes(b"x")
            self.assertIsNone(backups.due(folder, datetime(2026, 10, 9, 23, 0), hour=4))

    def test_prune_keeps_the_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for day in range(1, 11):
                backups.backup_path(folder, date(2026, 10, day)).write_bytes(b"x")
            (folder / "notes.txt").write_text("not a backup")
            removed = backups.prune(folder, keep=7)
            self.assertEqual(len(removed), 3)
            names = [p.name for p in backups.existing(folder)]
            self.assertEqual(names[0], "economy-2026-10-04.db")
            self.assertEqual(len(names), 7)
            self.assertTrue((folder / "notes.txt").exists())


class ConsoleRulesTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("  /Minecraft:Whitelist   OFF "), "whitelist off")

    def test_blocked_commands(self):
        for cmd in ("stop", "/stop", "op Steve", "whitelist off", "minecraft:deop Steve", "kill @e[type=cow]"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(blocked_by(cmd, DEFAULT_BLOCKED))

    def test_allowed_commands(self):
        for cmd in ("say hello", "give Steve diamond 3", "whitelist add Steve", "list", "stopwatch", "kill Steve"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(blocked_by(cmd, DEFAULT_BLOCKED))

    def test_clean_output(self):
        self.assertEqual(clean_output("§aThere are §c2§r players"), "There are 2 players")
        self.assertEqual(clean_output(""), "(no output)")
        self.assertEqual(len(clean_output("x" * 5000)), 1500)


class ConfigReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_path = config.CONFIG_PATH
        config.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        config.load_config.cache_clear()

    def tearDown(self):
        config.CONFIG_PATH = self.original_path
        config.load_config.cache_clear()
        self.tmp.cleanup()

    def write(self, text: str) -> None:
        config.CONFIG_PATH.write_text(text, encoding="utf-8")

    def test_reload_applies_changes(self):
        self.write(json.dumps({"channels": {"events": 1}}))
        self.assertEqual(config.channel_id("events"), 1)
        self.write(json.dumps({"channels": {"events": 2}}))
        self.assertEqual(config.channel_id("events"), 1)  # cached until reload
        config.reload_config()
        self.assertEqual(config.channel_id("events"), 2)

    def test_invalid_file_keeps_current_config(self):
        self.write(json.dumps({"channels": {"events": 1}}))
        config.load_config()
        self.write('{"channels": {"events": 2},}')
        with self.assertRaisesRegex(ValueError, "line 1"):
            config.reload_config()
        self.assertEqual(config.channel_id("events"), 1)

    def test_balance_overrides_keep_legacy_cooldown(self):
        self.assertEqual(
            config.balance_overrides({"economy": {"cooldown_seconds": 12}}),
            {"mining": {"cooldown_seconds": 12}},
        )
        self.assertEqual(
            config.balance_overrides({"economy": {"cooldown_seconds": 12}, "balance": {"mining": {"cooldown_seconds": 5}}}),
            {"mining": {"cooldown_seconds": 5}},
        )


if __name__ == "__main__":
    unittest.main()
