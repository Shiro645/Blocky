"""2.2.1: the new ingot prices, the ingot rewind, and the tools that pay for themselves."""
from __future__ import annotations

from game import daily, exchange, mines, players, rewind_ingots, settings, shop, villager
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB = 1, 2


class RewindIngotsTests(GameTestCase):
    legacy_economy = False

    async def test_paid_back_at_the_old_prices(self):
        await self.run_game(players.add_item, ALICE, "ingot", "gold", 4)
        await self.run_game(players.add_item, ALICE, "ingot", "diamond", 2)
        await self.run_game(players.add_item, ALICE, "ingot", "netherite", 1)
        await self.run_game(players.add_item, ALICE, "scrap", "none", 3)
        await self.run_game(shop.create_gear, ALICE, "sword", "iron")  # gear isn't touched
        await self.run_game(players.add_item, BOB, "ingot", "iron", 5)
        await self.run_game(players.add_item, BOB, "lapis", "none", 4)
        await self.run_game(exchange.list_for_sale, BOB, "ingot:iron", 5, 9000)
        await self.run_game(exchange.list_for_sale, BOB, "lapis", 4, 50)  # stays listed

        plan = await self.run_game(rewind_ingots.plan)
        self.assertEqual(plan[ALICE], {"ingots": 7, "scraps": 3, "listings": 0,
                                       "emeralds": 4 * 5 + 2 * 60 + 300 + 3 * 70})
        self.assertEqual(plan[BOB], {"ingots": 0, "scraps": 0, "listings": 1, "emeralds": 5 * 10})

        await self.run_game(rewind_ingots.apply)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), plan[ALICE]["emeralds"])
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), plan[BOB]["emeralds"])
        for material in ("gold", "diamond", "netherite"):
            self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", material), 0)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "scrap", "none"), 0)
        self.assertEqual(len(await self.run_game(shop.get_gear, ALICE)), 1)
        left = await self.run_game(exchange.listings_of, BOB)
        self.assertEqual([r["asset"] for r in left], ["lapis"])
        with self.assertRaisesRegex(GameError, "already done"):  # once only
            await self.run_game(rewind_ingots.plan)

    async def test_the_villager_sells_his_ingots_at_the_new_price(self):
        visit = await self.run_game(villager.arrive)

        def old_offer(ctx):
            ctx.execute("UPDATE villager_offers SET kind='sell', asset='ingot:iron', amount=8, price=56, value=80 "
                        "WHERE visit_id=? AND slot=0;", (visit["visit_id"],))

        await self.run_game(old_offer)
        await self.run_game(players.add_item, ALICE, "ingot", "gold", 1)  # someone to refund
        await self.run_game(rewind_ingots.apply)
        offer = await self.run_game(lambda ctx: dict(ctx.one(
            "SELECT * FROM villager_offers WHERE visit_id=? AND slot=0;", (visit["visit_id"],))))
        self.assertEqual(offer["value"], 8 * 1000)
        self.assertEqual(offer["price"], villager.priced("ingot:iron", 8)["price"])


class NewEconomyTests(GameTestCase):
    legacy_economy = False

    def test_the_new_defaults(self):
        s = settings.get()
        self.assertEqual(s["market"]["ingots"], {"gold": 300, "iron": 1000, "diamond": 5000, "netherite": 20000})
        self.assertEqual(s["gear"]["durability"], {"gold": 300, "iron": 1000, "diamond": 3000, "netherite": 5000})
        self.assertEqual(s["gear"]["pickaxe_extra_blocks_per_tier"], 3)
        self.assertEqual(s["daily"]["weekly_bonus_item"], "iron")
        self.assertFalse(settings.problems({}))

    def test_ingot_drops_are_rare_and_single(self):
        table = settings.get()["drops"]["table"]
        total = sum(d["weight"] for d in table)
        for d in table:
            if "ingot" in d["reward"]:
                self.assertEqual(d["reward"]["amount"], 1)
        ingots = sum(d["weight"] for d in table if "ingot" in d["reward"])
        self.assertLess(ingots / total, 0.05)  # was about 29% before 2.2.1

    def test_tools_pay_for_themselves(self):
        """A pickaxe's extra cobblestone over its life is worth more than its craft, from iron on."""
        g = settings.get()["gear"]
        for tier, material in enumerate(("iron", "diamond", "netherite"), start=2):  # gold breaks even
            gain = g["pickaxe_extra_blocks_per_tier"] * tier * players.block_value("cobblestone") * g["durability"][material]
            self.assertGreater(gain, shop.craft_cost("pickaxe", material), material)

    async def test_the_daily_bonus_is_iron(self):
        settings.load({"daily": {"bonus_every_days": 2}})
        for _ in range(2):
            await self.run_game(daily.claim, ALICE)
            self.advance(DAY)
        self.assertEqual(await self.run_game(players.item_amount, ALICE, "ingot", "iron"), 1)


class GamblingBalanceTests(GameTestCase):
    async def test_a_finished_game_shows_the_balance(self):
        await self.run_game(players.give_emeralds, ALICE, 500)
        game = await self.run_game(mines.start, ALICE, 100, 3)
        self.assertEqual(game["balance"], 400)
