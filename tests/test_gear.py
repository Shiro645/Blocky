from __future__ import annotations

import unittest

from game import gear, mining, players, shop
from game.errors import GameError
from game.notices import GearBroken
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class EquipTests(GameTestCase):
    async def test_craft_auto_equips_only_into_empty_slot(self):
        await self.run_game(players.add_item, ALICE, "ingot", "iron", 4)
        await self.run_game(players.add_item, ALICE, "stick", "none", 2)
        first = await self.run_game(shop.craft, ALICE, "sword", "iron")
        second = await self.run_game(shop.craft, ALICE, "sword", "iron")
        self.assertTrue(first["equipped"])
        self.assertFalse(second["equipped"])

    async def test_one_piece_per_slot(self):
        a = await self.run_game(shop.create_gear, ALICE, "helmet", "iron")
        b = await self.run_game(shop.create_gear, ALICE, "helmet", "diamond")
        await self.run_game(gear.equip, ALICE, a)
        await self.run_game(gear.equip, ALICE, b)
        equipped = await self.run_game(gear.get_equipped, ALICE)
        self.assertEqual(equipped["helmet"]["gear_id"], b)

    async def test_cannot_equip_someone_elses_gear(self):
        gid = await self.run_game(shop.create_gear, BOB, "sword", "gold")
        with self.assertRaises(GameError):
            await self.run_game(gear.equip, ALICE, gid)

    async def test_equip_best_picks_highest_tier(self):
        await self.run_game(shop.create_gear, ALICE, "boots", "gold")
        best = await self.run_game(shop.create_gear, ALICE, "boots", "netherite")
        await self.run_game(gear.equip_best, ALICE)
        equipped = await self.run_game(gear.get_equipped, ALICE)
        self.assertEqual(equipped["boots"]["gear_id"], best)

    async def test_unequip(self):
        gid = await self.run_game(shop.create_gear, ALICE, "axe", "iron")
        await self.run_game(gear.equip, ALICE, gid)
        await self.run_game(gear.unequip, ALICE, "axe")
        self.assertEqual(await self.run_game(gear.get_equipped, ALICE), {})
        with self.assertRaises(GameError):
            await self.run_game(gear.unequip, ALICE, "axe")


class CombatStatTests(unittest.TestCase):
    def setUp(self):
        from game import settings

        settings.load()

    def test_attack_and_armor(self):
        self.assertEqual(gear.attack_damage({}), 1)
        full_iron = {s: {"material": "iron"} for s in ("helmet", "chestplate", "leggings", "boots")}
        full_iron["sword"] = {"material": "diamond"}
        self.assertEqual(gear.attack_damage(full_iron), 7)
        self.assertEqual(gear.armor_points(full_iron), 15)
        self.assertAlmostEqual(gear.damage_reduction(full_iron), 0.45)

    def test_reduction_is_capped(self):
        from game import settings

        settings.load({"gear": {"damage_reduction_per_armor_point": 1}})
        self.assertEqual(gear.damage_reduction({"helmet": {"material": "gold"}}), 0.8)


class MiningWithToolsTests(GameTestCase):
    overrides = {"gear": {"durability": {"gold": 2}}}

    async def test_pickaxe_adds_blocks_and_wears_out(self):
        gid = await self.run_game(shop.create_gear, ALICE, "pickaxe", "gold")
        await self.run_game(gear.equip, ALICE, gid)

        res = await self.run_game(mining.mine, ALICE)
        self.assertGreaterEqual(res["amount"], 2)  # at least 1 rolled + 1 from a gold pickaxe
        self.assertEqual(res["broken"], [])

        res = await self.run_game(mining.mine, ALICE)
        self.assertEqual(res["broken"], ["gold pickaxe"])
        self.assertEqual(await self.run_game(shop.get_gear, ALICE), [])
        self.assertIn(GearBroken(ALICE, "pickaxe", "gold"), self.notices)
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "gear_broken"), 1)

    async def test_hoe_boosts_xp(self):
        gid = await self.run_game(shop.create_gear, ALICE, "hoe", "iron")
        await self.run_game(gear.equip, ALICE, gid)
        res = await self.run_game(mining.mine, ALICE)
        self.assertGreaterEqual(res["xp"], round(5 * 1.2))

    def test_upgrade_block(self):
        self.assertEqual(mining.upgrade_block("cobblestone"), "gravel")
        self.assertEqual(mining.upgrade_block("deepslate"), "obsidian")
        self.assertEqual(mining.upgrade_block("obsidian"), "bedrock")
        self.assertEqual(mining.upgrade_block("bedrock"), "bedrock")


if __name__ == "__main__":
    unittest.main()
