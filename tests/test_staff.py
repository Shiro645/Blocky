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
    EVERYONE = {"send_messages", "read_message_history"}

    def test_a_permission_only_the_staff_role_has(self):
        pick = staff_visibility.pick
        self.assertEqual(pick({"send_messages", "moderate_members", "kick_members"}, [self.EVERYONE]),
                         ("moderate_members", True))
        self.assertEqual(pick({"manage_messages"}, [self.EVERYONE]), ("manage_messages", True))
        # A players' role (e.g. "Helper") that can time out members: that permission would show the commands to them.
        helper = {"send_messages", "moderate_members"}
        self.assertEqual(pick({"moderate_members", "kick_members"}, [self.EVERYONE, helper]), ("kick_members", True))

    def test_nothing_fits_hides_behind_administrator(self):
        self.assertEqual(staff_visibility.pick({"send_messages"}, [self.EVERYONE]), ("administrator", False))
        # Another role can already do everything the staff role can.
        self.assertEqual(staff_visibility.pick({"manage_messages"}, [self.EVERYONE, {"manage_messages"}]),
                         ("administrator", False))

    def test_no_staff_role(self):
        self.assertEqual(staff_visibility.pick(None, [self.EVERYONE]), ("administrator", True))


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


class ResetRewardTests(GameTestCase):
    async def test_a_progress_reset_doesnt_pay_achievements_again(self):
        from game import profiles, progress, reset
        await self.run_game(players.set_level, ALICE, 50)
        await self.run_game(progress.check_achievements, ALICE)
        await self.run_game(players.bump_stat, ALICE, "seasons_won")
        await self.run_game(profiles.set_title, ALICE, "season_champion")
        rich = await self.run_game(players.get_emeralds, ALICE)
        self.assertGreater(rich, 0)
        await self.run_game(reset.apply, {"progress"}, ALICE)
        self.assertIsNone((await self.run_game(profiles.get, ALICE))["title"])  # not earned anymore
        await self.run_game(players.bump_stat, ALICE, "blocks_mined")  # re-unlocks the level achievements
        self.assertIn("level_10", await self.run_game(progress.unlocked_codes, ALICE))
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), rich)  # but pays nothing
        await self.run_game(reset.apply, {"progress", "wealth"}, ALICE)
        await self.run_game(players.bump_stat, ALICE, "blocks_mined")
        self.assertGreater(await self.run_game(players.get_emeralds, ALICE), 0)  # a real fresh start pays again


class CooldownResetTests(GameTestCase):
    async def test_waiting_times_are_reset(self):
        from game import cooldowns, daily, dummy, pve, robbery, species
        alice, bob = 1, 2
        for uid in (alice, bob):
            await self.run_game(players.give_emeralds, uid, 1000)
            await self.run_game(players.set_level, uid, 20)
        # A robbery: the thief waits, the victim is protected.
        rob = await self.run_game(robbery.start, alice, bob, "discreet")
        self.advance(3601)
        await self.run_game(robbery.finish_due)
        with self.assertRaisesRegex(GameError, "rob again"):
            await self.run_game(robbery.start, alice, bob, "discreet")
        self.assertEqual(await self.run_game(cooldowns.reset, alice, ["rob"]), ["rob"])
        with self.assertRaisesRegex(GameError, "protected"):  # the victim is still protected
            await self.run_game(robbery.start, alice, bob, "discreet")
        await self.run_game(cooldowns.reset, bob, ["rob_protection"])
        await self.run_game(robbery.start, alice, bob, "discreet")
        self.assertIsNotNone(rob)

        # The daily: today's claim is undone, the streak doesn't grow twice.
        first = await self.run_game(daily.claim, alice)
        await self.run_game(cooldowns.reset, alice, ["daily"])
        again = await self.run_game(daily.claim, alice)
        self.assertEqual((again["streak"], again["emeralds"]), (first["streak"], first["emeralds"]))
        self.assertEqual(await self.run_game(cooldowns.reset, alice, ["daily", "dummy"]), ["daily"])

        # Species, dummy, dungeon.
        await self.run_game(species.choose, alice, "miner")
        await self.run_game(players.give_emeralds, alice, 5000)
        with self.assertRaises(GameError):
            await self.run_game(species.choose, alice, "dwarf")
        await self.run_game(cooldowns.reset, alice, ["species"])
        await self.run_game(species.choose, alice, "dwarf")
        await self.run_game(dummy.hit_series, alice)
        with self.assertRaises(GameError):
            await self.run_game(dummy.hit_series, alice)
        await self.run_game(cooldowns.reset, alice, ["dummy"])
        await self.run_game(dummy.hit_series, alice)
        run = await self.run_game(pve.create, alice, "easy")
        await self.run_game(pve.start, run["run_id"], alice)
        await self.run_game(pve.leave, run["run_id"], alice)
        self.assertGreater(await self.run_game(pve.ready_at, alice), self.now)
        await self.run_game(cooldowns.reset, alice, ["dungeon"])
        self.assertEqual(await self.run_game(pve.ready_at, alice), 0)
