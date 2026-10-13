from __future__ import annotations

import random
import unittest

from game import assets, enchants, events, exchange, gear, leaderboard, mining, players, progress, settings, shop
from game.errors import GameError
from game.notices import AllChallengesCompleted
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class EnchantTestCase(GameTestCase):
    async def piece(self, user_id: int, item: str, material: str = "iron", **ench: int) -> int:
        gear_id = await self.run_game(shop.create_gear, user_id, item, material)
        if ench:
            await self.run_game(enchants.set_enchants, gear_id, ench)
        return gear_id

    async def equipped(self, user_id: int) -> dict:
        return await self.run_game(gear.get_equipped, user_id)


class KeyTests(unittest.TestCase):
    def setUp(self):
        settings.load()

    def test_signature_round_trip(self):
        sig = enchants.signature({"unbreaking": 1, "sharpness": 2})
        self.assertEqual(sig, "sharpness2,unbreaking1")
        self.assertEqual(enchants.parse_signature(sig), {"sharpness": 2, "unbreaking": 1})
        for bad in ("sharpness4", "magic1", "sharpness1,sharpness2", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                enchants.parse_signature(bad)

    def test_asset_keys(self):
        self.assertEqual(assets.describe("book:sharpness:2", 3), "3 × Sharpness II book")
        self.assertEqual(assets.describe("lapis"), "lapis lazuli")
        self.assertEqual(
            assets.describe("gear:diamond:sword:sharpness2,unbreaking1"),
            "diamond sword (Sharpness II, Unbreaking I)",
        )
        for bad in ("book:sharpness:4", "book:magic:1", "gear:diamond:sword:nope"):
            with self.subTest(bad=bad), self.assertRaises(GameError):
                assets.parse(bad)
        # An enchanted piece is worth its books too.
        self.assertEqual(
            assets.unit_value("gear:iron:sword:sharpness1"), assets.unit_value("gear:iron:sword") + 50
        )

    def test_effect_texts(self):
        self.assertEqual(enchants.effect_text("efficiency", 3), "mining cooldown -6s")
        self.assertEqual(enchants.effect_text("unbreaking", 1), "25% chance to keep durability")


class ApplyTests(EnchantTestCase):
    async def test_apply_costs_a_book_and_lapis(self):
        sword = await self.piece(ALICE, "sword")
        await self.run_game(enchants.give_book, ALICE, "sharpness", 2)
        with self.assertRaisesRegex(GameError, "lapis"):
            await self.run_game(enchants.apply, ALICE, "sharpness:2", sword)
        await self.run_game(enchants.give_lapis, ALICE, 5)
        res = await self.run_game(enchants.apply, ALICE, "sharpness:2", sword)
        self.assertEqual((res["cost"], res["replaced"]), (4, 0))
        self.assertEqual(await self.run_game(enchants.lapis, ALICE), 1)
        self.assertEqual(await self.run_game(enchants.books, ALICE), [])
        self.assertEqual((await self.run_game(enchants.of_gear, [sword]))[sword], {"sharpness": 2})

    async def test_higher_level_replaces_lower(self):
        sword = await self.piece(ALICE, "sword", sharpness=1)
        await self.run_game(enchants.give_lapis, ALICE, 20)
        await self.run_game(enchants.give_book, ALICE, "sharpness", 1)
        with self.assertRaisesRegex(GameError, "already has"):
            await self.run_game(enchants.apply, ALICE, "sharpness:1", sword)
        await self.run_game(enchants.give_book, ALICE, "sharpness", 3)
        res = await self.run_game(enchants.apply, ALICE, "sharpness:3", sword)
        self.assertEqual(res["replaced"], 1)
        self.assertEqual((await self.run_game(enchants.of_gear, [sword]))[sword], {"sharpness": 3})

    async def test_wrong_piece_or_owner(self):
        boots = await self.piece(ALICE, "boots")
        await self.run_game(enchants.give_lapis, ALICE, 20)
        await self.run_game(enchants.give_book, ALICE, "sharpness", 1)
        with self.assertRaisesRegex(GameError, "can't go on"):
            await self.run_game(enchants.apply, ALICE, "sharpness:1", boots)
        bob_sword = await self.piece(BOB, "sword")
        with self.assertRaisesRegex(GameError, "don't own"):
            await self.run_game(enchants.apply, ALICE, "sharpness:1", bob_sword)
        with self.assertRaisesRegex(GameError, "don't have"):
            await self.run_game(enchants.apply, ALICE, "protection:1", boots)

    async def test_combine(self):
        await self.run_game(enchants.give_book, ALICE, "fortune", 2, 2)
        with self.assertRaisesRegex(GameError, "need an anvil"):
            await self.run_game(enchants.combine, ALICE, "fortune:2")
        await self.run_game(lambda ctx: ctx.execute("UPDATE users SET anvil=3 WHERE user_id=?;", (ALICE,)))
        res = await self.run_game(enchants.combine, ALICE, "fortune:2")
        self.assertEqual(res["level"], 3)
        self.assertEqual(await self.run_game(enchants.books, ALICE), [("fortune", 3, 1)])
        with self.assertRaisesRegex(GameError, "maximum"):
            await self.run_game(enchants.combine, ALICE, "fortune:3")
        with self.assertRaisesRegex(GameError, "need 2"):
            await self.run_game(enchants.combine, ALICE, "fortune:1")

    async def test_enchants_disappear_with_the_piece(self):
        sword = await self.piece(ALICE, "sword", sharpness=1)
        await self.run_game(lambda ctx: ctx.execute("DELETE FROM gear WHERE gear_id=?;", (sword,)))
        self.assertEqual(await self.run_game(enchants.of_gear, [sword]), {})


class EffectTests(EnchantTestCase):
    async def test_sharpness_and_protection(self):
        await self.piece(ALICE, "sword", sharpness=3)
        await self.piece(ALICE, "helmet", protection=2)
        await self.run_game(gear.equip_best, ALICE)
        eq = await self.equipped(ALICE)
        self.assertEqual(gear.attack_damage(eq), 10 + 3)  # iron sword maximum + Sharpness III
        self.assertEqual(gear.armor_points(eq), 2 + 2)

    async def test_unbreaking_saves_durability(self):
        sword = await self.piece(ALICE, "sword", unbreaking=3)
        await self.run_game(gear.equip, ALICE, sword)
        piece = (await self.equipped(ALICE))["sword"]
        await self.run_game(gear.wear, piece, 200)
        lost = piece["max_durability"] - piece["durability"]
        self.assertTrue(60 < lost < 140, lost)  # about half of 200

    async def test_efficiency_shortens_the_cooldown(self):
        await self.piece(ALICE, "pickaxe", efficiency=3)
        await self.run_game(gear.equip_best, ALICE)
        self.assertEqual((await self.run_game(mining.mine, ALICE))["cooldown"], 30 - 6)
        self.assertEqual(mining.cooldown_seconds(99, 6), 10)  # never below the minimum

    async def test_fortune_adds_blocks(self):
        await self.piece(ALICE, "pickaxe", fortune=3)
        await self.piece(BOB, "pickaxe")
        await self.run_game(gear.equip_best, ALICE)
        await self.run_game(gear.equip_best, BOB)
        self.db.rng = random.Random(9)
        lucky = await self.run_game(mining.mine, ALICE)
        self.db.rng = random.Random(9)
        plain = await self.run_game(mining.mine, BOB)
        # Fortune III: 3 more cobblestone, the mined block itself isn't multiplied.
        self.assertEqual((lucky["amount"], lucky["bonus"]), (plain["amount"], plain["bonus"] + 3))

    async def test_mining_finds_lapis(self):
        settings.load({"enchants": {"lapis_chance": 1}})
        res = await self.run_game(mining.mine, ALICE)
        self.assertIn(res["lapis"], (1, 2))
        self.assertEqual(await self.run_game(enchants.lapis, ALICE), res["lapis"])

    async def test_looting_and_book_on_bosses(self):
        await self.piece(ALICE, "sword", "netherite", looting=3)
        await self.run_game(gear.equip_best, ALICE)
        await self.run_game(events.spawn_boss, "Test", 1)
        res = await self.run_game(events.attack_boss, ALICE)
        reward = res["defeat"]["rewards"][0]
        self.assertEqual(reward["looting"], int(750 * 0.3))
        self.assertEqual(reward["reward"], 750 + int(750 * 0.3))
        self.assertTrue(reward["book"])
        self.assertEqual(len(await self.run_game(enchants.books, ALICE)), 1)

    async def test_drops_give_books_and_lapis(self):
        text = await self.run_game(events.claim_drop, ALICE, {"title": "x", "reward": {"book": True}})
        self.assertTrue(text.endswith(" book"))
        self.assertEqual(len(await self.run_game(enchants.books, ALICE)), 1)
        await self.run_game(events.claim_drop, ALICE, {"title": "x", "reward": {"lapis": 4}})
        self.assertEqual(await self.run_game(enchants.lapis, ALICE), 4)

    async def test_all_weekly_challenges_give_a_book(self):
        settings.load({"challenges": {"per_week": 1}})
        week = await self.run_game(lambda ctx: ctx.week_id)
        challenge = progress.challenges_of_week(week)[0]
        await self.run_game(players.bump_stat, ALICE, challenge.stat, challenge.target)
        self.assertTrue(any(isinstance(n, AllChallengesCompleted) for n in self.notices))
        self.assertEqual(len(await self.run_game(enchants.books, ALICE)), 1)

    async def test_lapis_and_books_count_in_the_fortune(self):
        await self.run_game(enchants.give_lapis, ALICE, 3)
        await self.run_game(enchants.give_book, ALICE, "looting", 1)
        self.assertEqual((await self.run_game(leaderboard.fortunes))[ALICE], 3 * 10 + 50)


class TradeTests(EnchantTestCase):
    async def test_enchanted_gear_keeps_its_enchants_in_a_trade(self):
        await self.piece(ALICE, "sword", "diamond")
        await self.piece(ALICE, "sword", "diamond", sharpness=2)
        owned = dict(await self.run_game(assets.owned, ALICE))
        self.assertEqual(owned["gear:diamond:sword"], 1)
        self.assertEqual(owned["gear:diamond:sword:sharpness2"], 1)

        await self.run_game(exchange.trade, ALICE, BOB, "gear:diamond:sword:sharpness2", 1, None, 0)
        bob = await self.run_game(shop.get_gear, BOB)
        self.assertEqual([g["enchants"] for g in bob], [{"sharpness": 2}])
        alice = await self.run_game(shop.get_gear, ALICE)
        self.assertEqual([g["enchants"] for g in alice], [{}])

    async def test_plain_key_never_takes_an_enchanted_piece(self):
        await self.piece(ALICE, "sword", "diamond", sharpness=2)
        with self.assertRaisesRegex(GameError, "doesn't have"):
            await self.run_game(exchange.trade, ALICE, BOB, "gear:diamond:sword", 1, None, 0)

    async def test_auction_keeps_enchants_and_durability(self):
        sword = await self.piece(ALICE, "sword", "iron", unbreaking=1)
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability=100 WHERE gear_id=?;", (sword,)))
        listing = await self.run_game(exchange.list_for_sale, ALICE, "gear:iron:sword:unbreaking1", 1, 50)
        await self.run_game(players.give_emeralds, BOB, 50)
        await self.run_game(exchange.buy, BOB, listing["auction_id"])
        bob = await self.run_game(shop.get_gear, BOB)
        self.assertEqual((bob[0]["durability"], bob[0]["enchants"]), (100, {"unbreaking": 1}))

    async def test_books_and_lapis_trade(self):
        await self.run_game(enchants.give_book, ALICE, "protection", 1, 2)
        await self.run_game(enchants.give_lapis, BOB, 6)
        await self.run_game(exchange.trade, ALICE, BOB, "book:protection:1", 2, "lapis", 6)
        self.assertEqual(await self.run_game(enchants.books, BOB), [("protection", 1, 2)])
        self.assertEqual(await self.run_game(enchants.lapis, ALICE), 6)
        with self.assertRaisesRegex(GameError, "doesn't have"):
            await self.run_game(exchange.trade, ALICE, BOB, "book:protection:1", 1, None, 0)


if __name__ == "__main__":
    unittest.main()


class MendingTests(EnchantTestCase):
    async def test_the_book(self):
        self.assertEqual(enchants.label("mending", 1), "Mending")
        self.assertNotIn("mending", enchants.RANDOM_BOOKS)  # never from drops, challenges or a normal boss book
        rng = random.Random(3)
        self.assertNotIn("mending", {enchants.random_book(rng)[0] for _ in range(300)})
        self.assertEqual(shop.item_value("book", "mending:1"), 600)  # the most valuable book
        await self.run_game(enchants.give_book, ALICE, "mending", 1, 2)
        await self.run_game(lambda ctx: ctx.execute("UPDATE users SET anvil=3 WHERE user_id=?;", (ALICE,)))
        with self.assertRaisesRegex(GameError, "only one level"):
            await self.run_game(enchants.combine, ALICE, "mending:1")
        with self.assertRaises(GameError):
            enchants.parse_book("mending:2")

    async def test_xp_repairs_the_gear_first(self):
        sword = await self.piece(ALICE, "sword", mending=1)
        await self.run_game(gear.equip, ALICE, sword)
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability=240 WHERE gear_id=?;", (sword,)))
        user = await self.run_game(players.add_xp, ALICE, 12)  # 5 XP repair the 10 missing, 7 XP are left
        self.assertEqual(((await self.equipped(ALICE))["sword"]["durability"], user["xp"]), (250, 7))
        self.assertEqual(await self.run_game(players.get_stat, ALICE, "durability_mended"), 10)
        user = await self.run_game(players.add_xp, ALICE, 5)  # nothing to repair: all the XP goes to the player
        self.assertEqual(user["xp"], 12)
        # Only equipped pieces, and never the staff's XP.
        await self.run_game(lambda ctx: ctx.execute("UPDATE gear SET durability=100 WHERE gear_id=?;", (sword,)))
        user = await self.run_game(players.add_xp, ALICE, 10, False)
        self.assertEqual(((await self.equipped(ALICE))["sword"]["durability"], user["xp"]), (100, 22))
        await self.run_game(gear.unequip, ALICE, "sword")
        self.assertEqual((await self.run_game(players.add_xp, ALICE, 3))["xp"], 25)

    async def test_the_villager_and_the_boss_give_it(self):
        from game import villager
        settings.load({"villager": {"exclusive_mending_chance": 1.0}, "enchants": {"boss_mending_chance": 1.0}})
        offer = await self.run_game(villager._exclusive_offer)
        self.assertEqual((offer["asset"], offer["price"]), ("book:mending:1", 600))
        await self.run_game(events.spawn_boss, "Test", 1000)
        await self.run_game(events.attack_boss, ALICE)
        await self.run_game(lambda ctx: ctx.execute("UPDATE bosses SET hp=1;"))
        self.advance(120)
        rewards = (await self.run_game(events.attack_boss, ALICE))["defeat"]["rewards"]
        self.assertEqual(rewards[0]["book"], "Mending")
        self.assertIn(("mending", 1, 1), await self.run_game(enchants.books, ALICE))
