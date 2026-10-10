from __future__ import annotations

import unittest

from game import settings


class SettingsValidationTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(settings.problems({}), [])
        self.assertEqual(settings.problems(settings.DEFAULTS), [])

    def test_typos_and_wrong_types(self):
        problems = settings.problems({
            "mining": {"cooldown": 20, "cooldown_seconds": "fast"},
            "daily": {"base_reward": 12.5},
            "enchants": {"apply_cost": [1, 2]},
            "challenges": {"per_week": -1},
        })
        text = "\n".join(problems)
        self.assertIn("mining.cooldown` doesn't exist", text)
        self.assertIn("cooldown_seconds` must be a number", text)
        self.assertIn("base_reward` must be a whole number", text)
        self.assertIn("apply_cost` must have 3 values", text)
        self.assertIn("per_week` can't be negative", text)

    def test_not_a_number_and_chances(self):
        self.assertTrue(settings.problems({"drops": {"chance": float("nan")}}))
        self.assertTrue(settings.problems({"drops": {"chance": 1.5}}))
        self.assertEqual(settings.problems({"drops": {"chance": 0.5}}), [])

    def test_timezone(self):
        self.assertTrue(settings.problems({"timezone": "Paris"}))
        self.assertEqual(settings.problems({"timezone": "America/Montreal"}), [])

    def test_cross_checks(self):
        self.assertTrue(settings.problems({"tournament": {"closes_day": 3}}))  # closes before it opens
        self.assertTrue(settings.problems({"tournament": {"min_players": 40}}))  # above the maximum
        self.assertTrue(settings.problems({"tournament": {"prize_split": [80, 30, 10]}}))
        self.assertTrue(settings.problems({"villager": {"leave_hour": 18}}))
        self.assertTrue(settings.problems({"villager": {"buys": {"dirt": 10}}}))
        self.assertTrue(settings.problems({"moderation": {"warn_mutes": {"3": "soon"}}}))
        self.assertTrue(settings.problems({"drops": {"table": [{"weight": 1, "title": "x", "reward": {"cake": 1}}]}}))

    def test_free_lists_and_dicts(self):
        self.assertEqual(settings.problems({"seasons": {"rewards": [500, 300, 150, 75, 30]}}), [])
        self.assertEqual(settings.problems({"moderation": {"warn_mutes": {"2": "30m", "4": "perm"}}}), [])

    def test_clean_keeps_the_valid_part(self):
        valid, problems = settings.clean({"timezone": "Paris", "daily": {"base_reward": 50}, "mining": {"nope": 1}})
        self.assertEqual(valid, {"daily": {"base_reward": 50}, "mining": {}})
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
