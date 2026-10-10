from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game import settings
from game.catalog import BLOCK_TYPES
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
        field = ce.FIELDS_BY_KEY["market.ingots.diamond"]
        new = ce.set_value(BASE, field.path, 40)
        self.assertEqual(new["balance"]["market"]["ingots"]["diamond"], 40)
        self.assertNotIn("balance", BASE)
        self.assertEqual(new["minecraft"]["rcon_password"], "secret")  # untouched

    def test_reset_removes_the_override(self):
        field = ce.FIELDS_BY_KEY["market.ingots.diamond"]
        cfg = ce.set_value(BASE, field.path, 40)
        cfg = ce.set_value(cfg, field.path, None)
        self.assertEqual(ce.current_value(cfg, field), 60)  # default

    def test_parse(self):
        price = ce.FIELDS_BY_KEY["market.ingots.diamond"]
        self.assertEqual(ce.parse(price, " 40 "), 40)
        self.assertIsNone(ce.parse(price, ""))  # back to default
        for bad in ("abc", "0", "4.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ce.parse(price, bad)
        chance = ce.FIELDS_BY_KEY["drops.chance"]  # a percentage
        self.assertEqual(ce.parse(chance, "5"), 0.05)
        self.assertEqual(ce.parse(chance, "2,5 %"), 0.025)
        with self.assertRaises(ValueError):
            ce.parse(chance, "150")
        zone = ce.FIELDS_BY_KEY["timezone"]
        self.assertEqual(ce.parse(zone, "America/New_York"), "America/New_York")
        with self.assertRaises(ValueError):
            ce.parse(zone, "Mars/Olympus")
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



class RegistryTests(unittest.TestCase):
    """Every game setting can be changed from /config."""

    FREE_LENGTH = {("seasons", "rewards"), ("teams", "season_rewards"), ("boss", "names"), ("drops", "table"),
                   ("villager", "goods")}

    def setUp(self):
        settings.load()

    def leaves(self, data, path=()):
        for key, value in data.items():
            here = path + (key,)
            if isinstance(value, dict) and not settings.is_free_dict(here):
                yield from self.leaves(value, here)
            elif here == ("villager", "buys"):
                yield from (here + (b,) for b in BLOCK_TYPES)
            elif isinstance(value, list) and here not in self.FREE_LENGTH:
                yield from (here + (i,) for i in range(len(value)))
            else:
                yield here

    def test_every_setting_has_a_field(self):
        wanted = set(self.leaves(settings.DEFAULTS))
        fields = {f.path[1:] for f in ce.FIELDS if f.is_balance}
        self.assertEqual(sorted(wanted - fields, key=str), [], "settings missing from utils/config_edit.py")
        self.assertEqual(sorted(fields - wanted, key=str), [], "fields for settings that don't exist")
        self.assertEqual(len(ce.FIELDS), len(ce.FIELDS_BY_KEY))

    def test_fields_are_well_formed(self):
        for field in ce.FIELDS:
            with self.subTest(field=field.key):
                self.assertIn(field.category, ce.CATEGORIES)
                self.assertLessEqual(len(field.help), 300)
                if field.is_balance:
                    self.assertEqual(ce.current_value({}, field), ce.default_value(field))
                if field.kind == "choice":
                    self.assertIn(ce.default_value(field), [v for _, v in field.choices])
        self.assertEqual(len(ce.CATEGORIES), len(set(ce.CATEGORIES.values())))
        self.assertLessEqual(len(ce.CATEGORIES), 25)  # one select menu

    def test_a_value_inside_a_list(self):
        cost = ce.FIELDS_BY_KEY["enchants.apply_cost.1"]
        cfg = ce.set_field(BASE, cost, 6)
        self.assertEqual(cfg["balance"]["enchants"]["apply_cost"], [2, 6, 8])
        self.assertTrue(ce.is_modified(cfg, cost))
        cfg = ce.set_field(cfg, cost, None)  # back to the default: the override goes away
        self.assertNotIn("balance", cfg)

    def test_a_value_inside_a_free_dict(self):
        cobble = ce.FIELDS_BY_KEY["villager.buys.cobblestone"]
        gravel = ce.FIELDS_BY_KEY["villager.buys.gravel"]
        self.assertEqual(ce.current_value(BASE, cobble), 0)
        cfg = ce.set_field(ce.set_field(BASE, cobble, 100), gravel, 0)
        self.assertEqual(cfg["balance"]["villager"]["buys"], {"deepslate": 48, "obsidian": 24, "bedrock": 16, "cobblestone": 100})
        self.assertEqual(settings.merged(cfg["balance"])["villager"]["buys"], cfg["balance"]["villager"]["buys"])

    def test_setting_the_default_value_removes_the_override(self):
        price = ce.FIELDS_BY_KEY["market.ingots.diamond"]
        self.assertEqual(ce.set_field(BASE, price, 60), BASE)

    def test_editors(self):
        for kind, _ in ce.DROP_REWARDS:
            amount = 1 if kind == "book" else 4
            self.assertEqual(ce.drop_kind(ce.drop_reward(kind, amount)), (kind, amount))
        self.assertEqual(ce.mute_rule(" 4 ", "2H"), ("4", "2h"))
        with self.assertRaises(ValueError):
            ce.mute_rule("4", "soon")
        names = ce.FIELDS_BY_KEY["boss.names"]
        self.assertEqual(ce.parse_item(names, " Herobrine "), "Herobrine")
        table = ce.FIELDS_BY_KEY["drops.table"]
        self.assertEqual(ce.set_whole(BASE, table, settings.DEFAULTS["drops"]["table"]), BASE)
        self.assertEqual(ce.display(ce.FIELDS_BY_KEY["moderation.warn_mutes"], {"10": "1d", "3": "1h"}), "3 → 1h · 10 → 1d")
        self.assertEqual(ce.display(ce.FIELDS_BY_KEY["duel.dodge_chance"], 0.125), "12.5%")


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
