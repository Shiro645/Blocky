"""Staff tools: /give and /take, which permission hides the staff commands, the staff log names."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from game import assets, enchants, players, settings, shop
from game.errors import GameError
from tests.helpers import GameTestCase
from tests.test_manual import slash_commands
from utils import staff_visibility

ALICE = 1


class GiveTakeTests(GameTestCase):
    def test_catalog_keys_are_valid(self):
        keys = assets.catalog()
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            assets.describe(key)  # raises for an invalid key
        for wanted in ("emeralds", "block:bedrock", "stick", "ingot:netherite", "lapis", "book:sharpness:3",
                       "potion:speed:2", "gear:diamond:sword"):
            self.assertIn(wanted, keys)

    async def test_give_anything(self):
        self.assertEqual(await self.run_game(assets.staff_give, ALICE, "emeralds", 500), 500)
        self.assertEqual(await self.run_game(assets.staff_give, ALICE, "potion:speed:2", 2), 2)
        self.assertEqual(await self.run_game(assets.staff_give, ALICE, "gear:diamond:sword:sharpness3", 1), 1)
        gear = await self.run_game(shop.get_gear, ALICE)
        self.assertEqual([g["enchants"] for g in gear], [{"sharpness": 3}])
        with self.assertRaisesRegex(GameError, "Unknown item"):
            await self.run_game(assets.staff_give, ALICE, "ingot:copper", 1)
        with self.assertRaisesRegex(GameError, "At most"):
            await self.run_game(assets.staff_give, ALICE, "gear:iron:axe", assets.MAX_STAFF_GEAR + 1)

    async def test_staff_gifts_dont_count_for_the_season(self):
        await self.run_game(assets.staff_give, ALICE, "emeralds", 500)
        stats = await self.run_game(players.get_stats, ALICE)
        self.assertEqual(stats.get("emeralds_earned", 0), 0)

    async def test_take_never_removes_more_than_owned(self):
        await self.run_game(assets.staff_give, ALICE, "ingot:iron", 5)
        self.assertEqual(await self.run_game(assets.staff_take, ALICE, "ingot:iron", 3), (3, 2))
        self.assertEqual(await self.run_game(assets.staff_take, ALICE, "ingot:iron", 99), (2, 0))
        with self.assertRaisesRegex(GameError, "has no"):
            await self.run_game(assets.staff_take, ALICE, "ingot:iron", 1)

    async def test_take_books_lapis_and_spare_gear_first(self):
        await self.run_game(enchants.give_book, ALICE, "fortune", 2, 2)
        await self.run_game(enchants.give_lapis, ALICE, 4)
        self.assertEqual(await self.run_game(assets.staff_take, ALICE, "book:fortune:2", 1), (1, 1))
        self.assertEqual(await self.run_game(assets.staff_take, ALICE, "lapis", 10), (4, 0))

        worn = await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET equipped=1 WHERE gear_id=?;", (worn,)))
        await self.run_game(shop.create_gear, ALICE, "sword", "iron")
        self.assertEqual(await self.run_game(assets.amount_of, ALICE, "gear:iron:sword"), 2)
        self.assertEqual(await self.run_game(assets.staff_take, ALICE, "gear:iron:sword", 1), (1, 1))
        left = await self.run_game(shop.get_gear, ALICE)
        self.assertEqual([g["gear_id"] for g in left], [worn])  # the equipped piece stays


class VisibilityTests(unittest.TestCase):
    def test_a_permission_of_the_staff_role_that_everyone_lacks(self):
        everyone = {"send_messages", "read_message_history"}
        self.assertEqual(staff_visibility.pick({"send_messages", "moderate_members", "kick_members"}, everyone), "moderate_members")
        self.assertEqual(staff_visibility.pick({"manage_messages"}, everyone), "manage_messages")
        self.assertEqual(staff_visibility.pick({"administrator"}, everyone), "administrator")

    def test_no_permission_fits(self):
        self.assertIsNone(staff_visibility.pick({"send_messages"}, {"send_messages"}))
        # @everyone can already manage messages: it wouldn't hide anything.
        self.assertIsNone(staff_visibility.pick({"manage_messages"}, {"manage_messages"}))

    def test_no_staff_role(self):
        self.assertEqual(staff_visibility.pick(None, set()), "manage_guild")


class StaffLogTests(unittest.TestCase):
    def test_staff_log_names_are_real_commands(self):
        tree = ast.parse((Path(__file__).resolve().parent.parent / "utils" / "staff_log.py").read_text(encoding="utf-8"))
        names = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and node.targets[0].id in ("SELF_LOGGED", "READ_ONLY"):
                names |= ast.literal_eval(node.value)
        commands = slash_commands()
        self.assertEqual(sorted(n for n in names if n not in commands), [])
        for name in names:
            self.assertTrue(commands[name].staff, name)


if __name__ == "__main__":
    unittest.main()
