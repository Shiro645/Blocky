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

    async def test_unequip_everything(self):
        self.assertEqual(await self.run_game(gear.unequip_all, ALICE), [])
        for item in ("sword", "helmet", "boots"):
            gid = await self.run_game(shop.create_gear, ALICE, item, "iron")
            await self.run_game(gear.equip, ALICE, gid)
        done = await self.run_game(gear.unequip_all, ALICE)
        self.assertEqual(sorted(g["item"] for g in done), ["boots", "helmet", "sword"])
        self.assertEqual(await self.run_game(gear.get_equipped, ALICE), {})

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
    async def kit(self, items) -> dict[str, int]:
        ids = {}
        for item in items:
            ids[item] = await self.run_game(shop.create_gear, ALICE, item, "iron")
            await self.run_game(gear.equip, ALICE, ids[item])
        return ids

    async def end_run(self, attacks: int, hits: int) -> None:
        from game import pve

        hero = await self.run_game(pve.make_hero, ALICE)
        hero.attacks, hero.hits_taken = attacks, hits
        await self.run_game(pve._end_member, {"run_id": 0}, {"user_id": ALICE, "hero": hero}, "cleared")

    async def test_the_dungeon_wears_one_armor_piece_per_hit(self):
        from game.catalog import ARMOR

        ids = await self.kit(("sword",) + ARMOR)
        await self.end_run(10, 40)
        pieces = await self.run_game(gear.get_pieces, ids)
        self.assertEqual(pieces["sword"]["durability"], 250 - 10)  # the sword: 1 per attack, like in duels
        lost = [pieces[slot]["max_durability"] - pieces[slot]["durability"] for slot in ARMOR]
        self.assertEqual(sum(lost), 40)  # 40 hits = 40 durability over the whole armor
        self.assertTrue(all(n < 40 for n in lost), lost)  # spread over the pieces

    async def test_an_empty_slot_takes_its_hits(self):
        ids = await self.kit(("chestplate",))
        await self.end_run(0, 40)
        piece = (await self.run_game(gear.get_pieces, ids))["chestplate"]
        lost = piece["max_durability"] - piece["durability"]
        self.assertTrue(0 < lost < 25, lost)  # about a quarter, not all 40


class ArmorDurabilityTests(GameTestCase):
    def test_each_piece_its_share(self):
        self.assertEqual([shop.max_durability("iron", s) for s in ("helmet", "chestplate", "leggings", "boots")],
                         [172, 250, 234, 203])
        self.assertEqual(shop.max_durability("netherite", "chestplate"), 1500)
        self.assertEqual(shop.max_durability("iron", "sword"), 250)  # tools: all of it
        self.assertEqual(shop.max_durability("gold", "boots"), 49)

    async def test_old_pieces_are_adapted_keeping_their_share(self):
        from game import exchange

        boots = await self.run_game(shop.create_gear, ALICE, "boots", "iron")
        shield = await self.run_game(shop.create_gear, ALICE, "shield", "iron")
        sword = await self.run_game(shop.create_gear, ALICE, "sword", "iron")

        def made_before(ctx):  # as crafted before the update: every piece 250
            ctx.execute("UPDATE gear SET max_durability=250, durability=200 WHERE gear_id=?;", (boots,))
            ctx.execute("UPDATE gear SET durability=0 WHERE gear_id=?;", (shield,))

        await self.run_game(made_before)
        listed = await self.run_game(shop.create_gear, BOB, "chestplate", "iron")
        await self.run_game(players.give_emeralds, BOB, 100)
        await self.run_game(exchange.list_for_sale, BOB, "gear:iron:chestplate", 1, 50)
        await self.run_game(lambda ctx: ctx.execute("UPDATE auctions SET max_durability=999, durability=999;"))
        self.assertEqual(await self.run_game(shop.sync_max_durability), 2)
        pieces = await self.run_game(gear.get_pieces, {"boots": boots, "shield": shield, "sword": sword})
        self.assertEqual((pieces["boots"]["durability"], pieces["boots"]["max_durability"]), (162, 203))  # 80%
        self.assertEqual(pieces["shield"]["durability"], 0)  # a worn-out shield stays worn out
        self.assertEqual(pieces["sword"]["max_durability"], 250)
        row = await self.run_game(lambda ctx: dict(ctx.one("SELECT durability, max_durability FROM auctions;")))
        self.assertEqual(row, {"durability": 250, "max_durability": 250})
        self.assertEqual(await self.run_game(shop.sync_max_durability), 0)  # nothing left to do
        del listed

    async def test_a_piece_given_back_never_goes_above_its_maximum(self):
        from game import assets

        await self.run_game(assets.give, ALICE, "gear:iron:boots", 1, 250)
        piece = (await self.run_game(shop.get_gear, ALICE))[0]
        self.assertEqual((piece["durability"], piece["max_durability"]), (203, 203))


class SellGearTests(GameTestCase):
    async def test_price_is_a_share_of_the_value_times_the_durability_left(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        offer = await self.run_game(shop.gear_offer, ALICE, piece)
        self.assertEqual((offer["value"], offer["price"]), (120, 96))  # 2 diamonds + 1 stick, × 80%
        await self.run_game(_wear, gid, piece["max_durability"] // 2)
        piece = await self.run_game(shop.owned_piece, ALICE, gid)
        self.assertEqual((await self.run_game(shop.gear_offer, ALICE, piece))["price"], 48)

    async def test_books_count_and_go_with_the_piece(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        await self.run_game(enchants.set_enchants, gid, {"sharpness": 2})
        await self.run_game(gear.equip, ALICE, gid)
        res = await self.run_game(shop.sell_gear, ALICE, gid)
        self.assertEqual(res["price"], 216)  # (120.25 + 150) × 80%
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 216)
        self.assertEqual(await self.run_game(shop.get_gear, ALICE), [])
        self.assertNotIn("sword", await self.run_game(gear.get_equipped, ALICE))
        self.assertEqual(await self.run_game(enchants.of_gear, [gid]), {})

    async def test_a_curse_adds_nothing_and_never_hides_the_list(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        await self.run_game(enchants.set_enchants, gid, {"sharpness": 2, "vanishing": 1})
        await self.run_game(shop.create_gear, ALICE, "pickaxe", "iron")
        offers = await self.run_game(shop.gear_offers, ALICE)  # a cursed piece broke the whole list
        self.assertEqual(len(offers), 2)
        sword = next(offer for piece, offer in offers if piece["gear_id"] == gid)
        self.assertEqual(sword["price"], 216)  # the same as without the curse
        self.assertEqual((await self.run_game(shop.sell_gear, ALICE, gid))["price"], 216)

    async def test_villagers_get_their_bonus(self):
        await self.run_game(species.choose, ALICE, "villager")
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "diamond")
        res = await self.run_game(shop.sell_gear, ALICE, gid)
        self.assertEqual((res["base"], res["bonus"], res["price"]), (96, 5, 101))

    async def test_netherite_is_never_sold(self):
        gid = await self.run_game(shop.create_gear, ALICE, "sword", "netherite")
        with self.assertRaisesRegex(GameError, "can't be sold"):
            await self.run_game(shop.sell_gear, ALICE, gid)
        self.assertEqual(await self.run_game(shop.gear_offers, ALICE), [])

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
