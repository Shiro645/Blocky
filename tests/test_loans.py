"""Loans between players, the late penalty and collection, and the top senders board."""
from __future__ import annotations

from game import exchange, leaderboard, loans, players, reset, settings
from game.errors import GameError
from game.notices import LoanRepaid
from tests.helpers import DAY, GameTestCase

LENDER, BORROWER, OTHER = 1, 2, 3
MINUTE = 60


class LoanTestCase(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.run_game(players.give_emeralds, LENDER, 2000)

    async def emeralds(self, uid):
        return await self.run_game(players.get_emeralds, uid)

    async def lend(self, amount=1000, interest=10, days=3, lender=LENDER, borrower=BORROWER):
        o = await self.run_game(loans.propose, lender, lender, borrower, amount, interest, days)
        return (await self.run_game(loans.accept, o["offer_id"], borrower))["loan"]


class OfferTests(LoanTestCase):
    async def test_an_offer_accepted_moves_the_emeralds(self):
        o = await self.run_game(loans.propose, LENDER, LENDER, BORROWER, 1000, 10, 3)
        self.assertEqual((o["due"], o["answerer_id"]), (1100, BORROWER))
        with self.assertRaisesRegex(GameError, "isn't for you"):
            await self.run_game(loans.accept, o["offer_id"], LENDER)
        res = await self.run_game(loans.accept, o["offer_id"], BORROWER)
        loan = res["loan"]
        self.assertEqual((loan["due"], loan["due_at"] - loan["started_at"], loan["status"]), (1100, 3 * DAY, "active"))
        self.assertEqual((await self.emeralds(LENDER), await self.emeralds(BORROWER)), (1000, 1000))
        with self.assertRaisesRegex(GameError, "already answered"):
            await self.run_game(loans.accept, o["offer_id"], BORROWER)
        self.assertEqual(await self.run_game(players.get_stat, LENDER, "emeralds_lent"), 1000)
        self.assertEqual(await self.run_game(players.get_stat, BORROWER, "emeralds_earned"), 0)  # not for the seasons

    async def test_a_borrower_can_ask(self):
        o = await self.run_game(loans.propose, BORROWER, LENDER, BORROWER, 500, 5, 2)
        self.assertEqual(o["answerer_id"], LENDER)
        await self.run_game(loans.decline, o["offer_id"], LENDER)
        with self.assertRaisesRegex(GameError, "already answered"):
            await self.run_game(loans.accept, o["offer_id"], LENDER)
        self.assertEqual(await self.emeralds(BORROWER), 0)

    async def test_the_terms_are_checked(self):
        for amount, interest, days, error in (
            (10, 10, 3, "Loans go from"), (6000, 10, 3, "Loans go from"),
            (1000, 25, 3, "interest goes from"), (1000, 10, 8, "lasts from"),
        ):
            with self.subTest(amount=amount, interest=interest, days=days):
                with self.assertRaisesRegex(GameError, error):
                    await self.run_game(loans.propose, LENDER, LENDER, BORROWER, amount, interest, days)
        with self.assertRaisesRegex(GameError, "doesn't have"):
            await self.run_game(loans.propose, LENDER, LENDER, BORROWER, 3000, 10, 3)
        with self.assertRaisesRegex(GameError, "yourself"):
            await self.run_game(loans.propose, LENDER, LENDER, LENDER, 100, 10, 3)

    async def test_offers_expire_and_are_checked_again(self):
        o = await self.run_game(loans.propose, LENDER, LENDER, BORROWER, 1000, 10, 3)
        await self.run_game(players.spend_emeralds, LENDER, 1500)  # spent in the meantime
        with self.assertRaisesRegex(GameError, "doesn't have"):
            await self.run_game(loans.accept, o["offer_id"], BORROWER)
        self.advance(15 * MINUTE)
        with self.assertRaisesRegex(GameError, "expired"):
            await self.run_game(loans.accept, o["offer_id"], BORROWER)

    async def test_one_debt_at_a_time(self):
        await self.lend(500)
        with self.assertRaisesRegex(GameError, "already has a loan"):
            await self.run_game(loans.propose, LENDER, LENDER, BORROWER, 100, 0, 1)
        await self.run_game(players.give_emeralds, OTHER, 1000)
        with self.assertRaisesRegex(GameError, "already has a loan"):
            await self.run_game(loans.propose, OTHER, OTHER, BORROWER, 100, 0, 1)

    async def test_a_lender_has_a_limit(self):
        settings.load({"loans": {"max_loans_out": 2}})
        await self.lend(100, borrower=BORROWER)
        await self.lend(100, borrower=OTHER)
        with self.assertRaisesRegex(GameError, "loans running"):
            await self.run_game(loans.propose, LENDER, LENDER, 4, 100, 0, 1)


class RepayTests(LoanTestCase):
    async def test_repay_bit_by_bit(self):
        loan = await self.lend(1000, 10)
        await self.run_game(players.give_emeralds, BORROWER, 500)
        res = await self.run_game(loans.repay, BORROWER, 300)
        self.assertEqual((res["paid"], loans.left(res["loan"])), (300, 800))
        res = await self.run_game(loans.repay, BORROWER)  # all that's left
        self.assertEqual((res["paid"], res["loan"]["status"]), (800, "repaid"))
        self.assertEqual(await self.emeralds(LENDER), 1000 + 1100)
        self.assertEqual(await self.emeralds(BORROWER), 1500 - 1100)
        self.assertIn(LoanRepaid(loan["loan_id"], LENDER, BORROWER, 1100, False), self.notices)
        with self.assertRaisesRegex(GameError, "don't owe"):
            await self.run_game(loans.repay, BORROWER)

    async def test_repay_all_needs_enough(self):
        await self.lend(1000, 10)
        with self.assertRaisesRegex(GameError, "amount:1000"):
            await self.run_game(loans.repay, BORROWER)
        with self.assertRaisesRegex(GameError, "Not enough"):
            await self.run_game(loans.repay, BORROWER, 1050)
        await self.run_game(players.give_emeralds, BORROWER, 500)
        res = await self.run_game(loans.repay, BORROWER, 5000)  # never more than what's owed
        self.assertEqual((res["paid"], await self.emeralds(BORROWER)), (1100, 400))

    async def test_forgive(self):
        await self.lend(1000, 10)
        with self.assertRaisesRegex(GameError, "doesn't owe you"):
            await self.run_game(loans.forgive, OTHER, BORROWER)
        res = await self.run_game(loans.forgive, LENDER, BORROWER)
        self.assertEqual((res["status"], res["forgiven"]), ("forgiven", 1100))
        self.assertIsNone(await self.run_game(loans.debt_of, BORROWER))


class LateTests(LoanTestCase):
    async def test_late_penalty_collection_and_garnish(self):
        loan = await self.lend(1000, 10, days=1)
        await self.run_game(players.spend_emeralds, BORROWER, 800)  # 200 left
        self.assertEqual(await self.run_game(loans.tick), [])
        self.advance(DAY)
        events = await self.run_game(loans.tick)
        # 1100 + 10% penalty = 1210; the 200 he has are taken at once.
        self.assertEqual([(e["penalty"], e["taken"], e["left"]) for e in events], [(110, 200, 1010)])
        self.assertEqual((await self.emeralds(BORROWER), await self.emeralds(LENDER)), (0, 1200))
        self.assertTrue(await self.run_game(loans.is_late, BORROWER))

        # Half of everything he receives goes to the lender, earned or not.
        await self.run_game(players.earn_emeralds, BORROWER, 100)
        await self.run_game(players.give_emeralds, BORROWER, 1)  # 0.5 rounds down
        self.assertEqual((await self.emeralds(BORROWER), await self.emeralds(LENDER)), (51, 1250))
        self.assertEqual(await self.run_game(players.get_stat, BORROWER, "emeralds_earned"), 100)

        # No moving wealth away meanwhile.
        for fn, args in ((exchange.pay, (BORROWER, OTHER, 10)),
                         (exchange.trade, (BORROWER, OTHER, "emeralds", 10, None, 1)),
                         (exchange.list_for_sale, (BORROWER, "lapis", 1, 10)),
                         (loans.propose, (BORROWER, BORROWER, OTHER, 100, 0, 1)),
                         (loans.propose, (OTHER, OTHER, BORROWER, 100, 0, 1))):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(GameError):
                    await self.run_game(fn, *args)

        # A big gain pays the rest: never more than what's left.
        await self.run_game(players.give_emeralds, BORROWER, 5000)
        self.assertEqual(await self.emeralds(LENDER), 1250 + 960)
        self.assertEqual(await self.emeralds(BORROWER), 51 + 5000 - 960)
        self.assertIsNone(await self.run_game(loans.debt_of, BORROWER))
        self.assertIn(LoanRepaid(loan["loan_id"], LENDER, BORROWER, 1210, True), self.notices)
        await self.run_game(exchange.pay, BORROWER, OTHER, 10)  # free again

    async def test_a_borrower_who_has_it_all_pays_at_the_deadline(self):
        await self.lend(1000, 10, days=1)
        await self.run_game(players.give_emeralds, BORROWER, 1000)
        self.advance(DAY)
        events = await self.run_game(loans.tick)
        self.assertEqual((events[0]["taken"], events[0]["left"], events[0]["loan"]["status"]), (1210, 0, "repaid"))
        self.assertEqual(await self.emeralds(BORROWER), 2000 - 1210)

    async def test_garnish_pays_the_lender_directly(self):
        # The lender is late too: what the garnish pays him isn't garnished again (no chain).
        await self.lend(1000, 0, days=1)
        await self.run_game(players.give_emeralds, OTHER, 5000)
        await self.lend(500, 0, days=1, lender=OTHER, borrower=LENDER)
        await self.run_game(players.spend_emeralds, BORROWER, 1000)
        await self.run_game(players.spend_emeralds, LENDER, 1500)
        self.advance(DAY)
        await self.run_game(loans.tick)
        await self.run_game(players.give_emeralds, BORROWER, 100)
        self.assertEqual(await self.emeralds(LENDER), 50)
        self.assertEqual(await self.emeralds(OTHER), 4500)


class BoardAndResetTests(LoanTestCase):
    async def test_top_senders_counts_pay_and_loans(self):
        await self.run_game(exchange.pay, LENDER, OTHER, 100)
        await self.lend(500)
        await self.run_game(players.give_emeralds, OTHER, 1000)
        await self.run_game(exchange.pay, OTHER, LENDER, 50)
        await self.run_game(loans.repay, BORROWER, 100)  # repayments don't count
        rows = await self.run_game(leaderboard.ranking, "sent")
        self.assertEqual(rows, [(LENDER, 600), (OTHER, 50)])

    async def test_reset_cancels_the_loans(self):
        await self.lend(500)
        await self.run_game(reset.apply, {"wealth"}, BORROWER)
        self.assertIsNone(await self.run_game(loans.debt_of, BORROWER))
        await self.lend(500)
        await self.run_game(reset.apply, {"levels"})
        self.assertIsNotNone(await self.run_game(loans.debt_of, BORROWER))
        await self.run_game(reset.apply, {"wealth"})
        self.assertIsNone(await self.run_game(loans.debt_of, BORROWER))
