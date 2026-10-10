from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game import settings
from utils import config_edit as ce

BASE = {
    "staff": {"role_id": 1},
    "minecraft": {"rcon_password": "secret", "public_ip_text": "play.example"},
    "roles": {"level_roles": {"10": 111}},
}


class ConfigEditTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_protected_settings_cannot_be_written(self):
        for path in (("minecraft", "rcon_password"), ("staff", "role_id"), ("database_path",)):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                ce.set_value(BASE, path, "x")

    def test_no_field_exposes_a_protected_setting(self):
        for field in ce.FIELDS:
            for protected in ce.PROTECTED:
                self.assertNotEqual(field.path[: len(protected)], protected)

    def test_set_value_creates_sections_without_touching_the_original(self):
        field = ce.FIELDS_BY_KEY["diamond_price"]
        new = ce.set_value(BASE, field.path, 40)
        self.assertEqual(new["balance"]["market"]["ingots"]["diamond"], 40)
        self.assertNotIn("balance", BASE)
        self.assertEqual(new["minecraft"]["rcon_password"], "secret")  # untouched

    def test_reset_removes_the_override(self):
        field = ce.FIELDS_BY_KEY["diamond_price"]
        cfg = ce.set_value(BASE, field.path, 40)
        cfg = ce.set_value(cfg, field.path, None)
        self.assertEqual(ce.current_value(cfg, field), 60)  # default

    def test_parse(self):
        price = ce.FIELDS_BY_KEY["diamond_price"]
        self.assertEqual(ce.parse(price, " 40 "), 40)
        self.assertIsNone(ce.parse(price, ""))  # back to default
        for bad in ("abc", "0", "4.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ce.parse(price, bad)
        chance = ce.FIELDS_BY_KEY["drop_chance"]
        self.assertEqual(ce.parse(chance, "0,05"), 0.05)
        with self.assertRaises(ValueError):
            ce.parse(chance, "2")
        text = ce.FIELDS_BY_KEY["mc_ip_text"]
        with self.assertRaises(ValueError):
            ce.parse(text, "  ")

    def test_level_roles(self):
        cfg = ce.set_level_role(BASE, 5, 555)
        cfg = ce.set_level_role(cfg, 10, 999)
        self.assertEqual(ce.level_roles(cfg), {5: 555, 10: 999})
        self.assertEqual(list(cfg["roles"]["level_roles"]), ["5", "10"])
        cfg = ce.set_level_role(cfg, 5, None)
        self.assertEqual(ce.level_roles(cfg), {10: 999})

    def test_write_config_keeps_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, folder = Path(tmp) / "config.json", Path(tmp) / "backups"
            path.write_text(json.dumps(BASE))
            copy = ce.write_config(path, ce.set_value(BASE, ("channels", "events"), 7), folder)
            self.assertEqual(json.loads(copy.read_text()), BASE)
            self.assertEqual(json.loads(path.read_text())["channels"]["events"], 7)

    def test_every_field_has_a_short_enough_label(self):
        # Discord limits modal titles to 45 characters.
        for field in ce.FIELDS:
            self.assertLessEqual(len(field.label), 45, field.label)



class PrepareChangeTests(unittest.TestCase):
    """/config: only the problems a change creates refuse it."""

    def setUp(self):
        settings.load()

    def test_an_old_key_never_blocks_a_change_and_is_removed(self):
        old = {**BASE, "balance": {"boss": {"ping_here": True, "hp": 2000}, "mining": {"cooldown_seconds": 15}}}
        change = ce.prepare_change(old, lambda cfg: ce.set_value(cfg, ("channels", "spam"), [5]))
        self.assertEqual(change.refused, [])
        self.assertEqual(len(change.cleaned), 1)
        self.assertIn("ping_here", change.cleaned[0])
        self.assertEqual(change.config["balance"], {"boss": {"hp": 2000}, "mining": {"cooldown_seconds": 15}})
        self.assertEqual(change.config["channels"]["spam"], [5])
        self.assertIn("ping_here", old["balance"]["boss"])  # the original isn't touched

    def test_a_bad_new_value_is_refused(self):
        old = {**BASE, "balance": {"boss": {"ping_here": True}}}
        change = ce.prepare_change(old, lambda cfg: ce.set_value(cfg, ("balance", "mining", "cooldown_seconds"), -3))
        self.assertEqual(len(change.refused), 1)
        self.assertIn("cooldown_seconds", change.refused[0])
        self.assertEqual(change.cleaned, [])

    def test_a_clean_file_stays_as_it_is(self):
        old = {**BASE, "balance": {"mining": {"cooldown_seconds": 15}}}
        change = ce.prepare_change(old, lambda cfg: ce.set_value(cfg, ("balance", "daily", "xp"), 30))
        self.assertEqual((change.refused, change.cleaned), ([], []))
        self.assertEqual(change.config["balance"], {"mining": {"cooldown_seconds": 15}, "daily": {"xp": 30}})


if __name__ == "__main__":
    unittest.main()
