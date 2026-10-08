from __future__ import annotations

import unittest

from utils import emojis

EMERALD = "<:emerald:123456789012345678>"
EMERALD_CFG = "<:my_emerald:999999999999999999>"


class EmojiTests(unittest.TestCase):
    def test_expected_names(self):
        self.assertEqual(len(emojis.EXPECTED_NAMES), 48)
        self.assertIn("gold_sword", emojis.EXPECTED_NAMES)
        self.assertIn("netherite_boots", emojis.EXPECTED_NAMES)
        self.assertIn("obsidian", emojis.EXPECTED_NAMES)

    def test_placeholders_are_ignored(self):
        for code in ("", "  ", "<:emerald:EMOJI_ID>", "<:x:12>", None):
            self.assertFalse(emojis.is_usable(code))
        self.assertTrue(emojis.is_usable(EMERALD))
        self.assertTrue(emojis.is_usable("<a:orb:123456789012345678>"))
        self.assertTrue(emojis.is_usable("💎"))

    def test_config_overrides_application_emojis(self):
        resolved = emojis.resolve(
            {"emerald": EMERALD_CFG, "stick": "<:stick:EMOJI_ID>"},
            {"emerald": EMERALD, "stick": "<:stick:123456789012345678>", "iron_sword": "<:iron_sword:123456789012345678>"},
        )
        self.assertEqual(resolved["emerald"], EMERALD_CFG)
        self.assertEqual(resolved["stick"], "<:stick:123456789012345678>")  # placeholder in config ignored
        self.assertEqual(resolved["iron_sword"], "<:iron_sword:123456789012345678>")

    def test_missing(self):
        absent = emojis.missing({"emerald": EMERALD})
        self.assertNotIn("emerald", absent)
        self.assertEqual(len(absent), 47)


if __name__ == "__main__":
    unittest.main()
