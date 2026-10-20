"""2.2.3: one mining channel, /portal, ores that add up from one dimension to the next."""
from __future__ import annotations

from game import dimensions, enchants, gear, mining, players, settings, shop
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class PortalTests(GameTestCase):
    async def test_unlocking_takes_you_there_and_the_portal_back(self):
        await self.run_game(players.ensure_user, ALICE)
        self.assertEqual(await self.run_game(dimensions.current, ALICE), "overworld")
        await self.run_game(dimensions.unlock, ALICE, "end")
        self.assertEqual(await self.run_game(dimensions.current, ALICE), "end")
        res = await self.run_game(dimensions.travel, ALICE, "nether")
        self.assertEqual((res["before"], res["after"]), ("end", "nether"))
        self.assertEqual((await self.run_game(mining.mine, ALICE))["dimension"], "nether")
        with self.assertRaisesRegex(GameError, "haven't unlocked"):
            await self.run_game(dimensions.travel, ALICE, "shimmer")
        with self.assertRaisesRegex(GameError, "already"):
            await self.run_game(dimensions.travel, ALICE, "nether")
        await self.run_game(dimensions.unlock, ALICE, "deep_dark")  # a new one: you go through
        self.assertEqual(await self.run_game(dimensions.current, ALICE), "deep_dark")

    async def test_the_staff_lowering_a_dimension_moves_you_back(self):
        await self.run_game(dimensions.unlock, ALICE, "shimmer")
        await self.run_game(dimensions.set_highest, ALICE, "nether")
        self.assertEqual(await self.run_game(dimensions.current, ALICE), "nether")
        self.assertEqual(await self.run_game(dimensions.all_current), {ALICE: 1})


class OreTests(GameTestCase):
    def test_ores_add_up(self):
        self.assertEqual(dimensions.ores("overworld"), [])
        self.assertEqual(dimensions.ores("nether"), ["gold"])
        self.assertEqual(dimensions.ores("deep_dark"), ["gold", "iron", "diamond"])
        self.assertEqual(dimensions.ores("shimmer"), ["gold", "iron", "diamond", "emerald"])

    async def test_every_ore_with_fortune(self):
        settings.load({"dimensions": {"ore_chances": {"gold": 1, "iron": 1, "diamond": 1, "emerald": 1},
                                      "ore_fortune_chance": [1, 1, 1, 1, 1, 1, 1]}})
        await self.run_game(dimensions.unlock, ALICE, "shimmer")
        before = await self.run_game(players.get_emeralds, ALICE)
        res = await self.run_game(mining.mine, ALICE)
        self.assertEqual(res["ores"], {"gold": 1, "iron": 1, "diamond": 1, "emerald": 1})
        for ore in ("gold", "iron", "diamond"):
            self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", ore), 1)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE) - before, 1000)

        pick = await self.run_game(shop.create_gear, ALICE, "pickaxe", "iron")
        await self.run_game(enchants.set_enchants, pick, {"fortune": 1})
        await self.run_game(gear.equip, ALICE, pick)
        res = await self.run_game(mining.mine, ALICE)
        self.assertEqual(res["ores"], {"gold": 2, "iron": 2, "diamond": 2, "emerald": 2})

    async def test_no_ore_in_the_overworld(self):
        settings.load({"dimensions": {"ore_chances": {"gold": 1, "iron": 1, "diamond": 1, "emerald": 1}}})
        self.assertEqual((await self.run_game(mining.mine, BOB))["ores"], {})
