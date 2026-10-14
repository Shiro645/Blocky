from __future__ import annotations

import unittest

from game import enchants, gear, mining, players, shop, species
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
        self.assertEqual(gear.attack_damage({}), 6)  # maximum damage without a sword
        full_iron = {s: {"material": "iron"} for s in ("helmet", "chestplate", "leggings", "boots")}
        full_iron["sword"] = {"material": "diamond"}
        self.assertEqual(gear.attack_damage(full_iron), 12)
        self.assertEqual(gear.armor_points(full_iron), 15)
        self.assertAlmostEqual(gear.damage_reduction(full_iron), 0.18)

    def test_reduction_is_capped(self):
        from game import settings

        settings.load({"gear": {"damage_reduction_per_armor_point": 1}})
        self.assertEqual(gear.damage_reduction({"helmet": {"material": "gold"}}), 0.35)


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


def _wear(ctx, gear_id: int, durability: int) -> None:
    ctx.execute("UPDATE gear SET durability=? WHERE gear_id=?;", (durability, gear_id))


class ArmorWearTests(GameTestCase):
    async def test_one_durability_every_n_hits(self):
        self.assertEqual(await self.run_game(gear.armor_wear, 7), 7)  # duels: every hit
        self.assertEqual(await self.run_game(gear.armor_wear, 0, 2), 0)
        self.assertEqual(await self.run_game(gear.armor_wear, 2, 2), 1)
        self.assertEqual(await self.run_game(gear.armor_wear, 40, 2), 20)
        self.assertEqual(await self.run_game(gear.armor_wear, 8, 4), 2)
        odd = [await self.run_game(gear.armor_wear, 3, 2) for _ in range(200)]
        self.assertEqual(set(odd), {1, 2})  # the rest is a 50% chance of one more
        self.assertTrue(70 < odd.count(2) < 130)

    async def test_the_dungeon_wears_armor_slower_than_duels(self):
        from game import pve

        ids = {}
        for item in ("sword", "chestplate"):
            ids[item] = await self.run_game(shop.create_gear, ALICE, item, "iron")
            await self.run_game(gear.equip, ALICE, ids[item])
        hero = await self.run_game(pve.make_hero, ALICE)
        hero.attacks, hero.hits_taken = 10, 20
        await self.run_game(pve._end_member, {"run_id": 0}, {"user_id": ALICE, "hero": hero}, "cleared")
        pieces = await self.run_game(gear.get_pieces, ids)
        self.assertEqual(pieces["sword"]["durability"], 250 - 10)
        self.assertEqual(pieces["chestplate"]["durability"], 250 - 10)  # 20 hits, 1 every 2


class SellGearTests(GameTestCase):
    async def test_price_is_a_share_of_the_value_times_the_durability_left(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        offer = await self.run_game(shop.gear_offer, ALICE, piece)
        self.assertEqual((offer["value"], offer["price"]), (600, 480))  # 2 netherite + 1 stick, × 80%
        await self.run_game(_wear, gid, piece["max_durability"] // 2)
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        self.assertEqual((await self.run_game(shop.gear_offer, ALICE, piece))["price"], 240)

    async def test_books_count_and_go_with_the_piece(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")
        await self.run_game(enchants.set_enchants, gid, {"sharpness": 2})
        await self.run_game(gear.equip, ALICE, gid)
        res = await self.run_game(shop.sell_gear, ALICE, gid)
        self.assertEqual(res["price"], 600)  # (600.25 + 150) × 80%
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 600)
        self.assertEqual(await self.run_game(shop.get_gear, ALICE), [])
        self.assertNotIn("sword", await self.run_game(gear.get_equipped, ALICE))
        self.assertEqual(await self.run_game(enchants.of_gear, [gid]), {})

    async def test_villagers_get_their_bonus(self):
        await self.run_game(species.choose, ALICE, "villager")
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")
        res = await self.run_game(shop.sell_gear, ALICE, gid)
        self.assertEqual((res["base"], res["bonus"], res["price"]), (480, 24, 504))

    async def test_refused_when_not_owned_or_the_price_changed(self):
        gid = await self.run_game(shop.create_gear, BOB, "sword", "iron")
        with self.assertRaises(GameError):
            await self.run_game(shop.sell_gear, ALICE, gid)
        with self.assertRaisesRegex(GameError, "price changed"):
            await self.run_game(shop.sell_gear, BOB, gid, 999)
        self.assertEqual(len(await self.run_game(shop.get_gear, BOB)), 1)
        await self.run_game(shop.sell_gear, BOB, gid, 16)  # 20.25 × 80%
        with self.assertRaises(GameError):
            await self.run_game(shop.sell_gear, BOB, gid)  # already sold


if __name__ == "__main__":
    unittest.main()
