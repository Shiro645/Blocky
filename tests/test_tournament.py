from __future__ import annotations

import unittest

from game import gear, players, seasons, settings, shop, tournament
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

HOUR = 3600
# START is Wednesday 12:00: Friday 18:00, Saturday 21:00 and Sunday 18:00 are:
FRIDAY_18 = 2 * DAY + 6 * HOUR
SATURDAY_21 = 3 * DAY + 9 * HOUR
SUNDAY_18 = 4 * DAY + 6 * HOUR


class TournamentTestCase(GameTestCase):
    def go_to(self, offset: float) -> None:
        """Move the clock to START + offset."""
        self.now = self.start + offset

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.start = self.now

    async def tick(self) -> list[dict]:
        return await self.run_game(tournament.tick)

    async def register(self, *user_ids: int) -> None:
        for uid in user_ids:
            await self.run_game(players.give_emeralds, uid, 100)
            await self.run_game(tournament.join, uid)

    async def play_all(self) -> list[dict]:
        """Run the clock until the tournament is over. Returns every event."""
        events = []
        for _ in range(48):
            self.advance(HOUR)
            events += await self.tick()
            if events and events[-1].get("final"):
                break
        return events


class ScheduleTests(TournamentTestCase):
    async def test_schedule_of_the_week(self):
        sch = await self.run_game(tournament.schedule)
        self.assertEqual(sch["opens"], int(self.start + FRIDAY_18))
        self.assertEqual(sch["closes"], int(self.start + SATURDAY_21))
        self.assertEqual(sch["starts"], int(self.start + SUNDAY_18))

    async def test_registrations_open_on_friday_once(self):
        self.assertEqual(await self.tick(), [])
        with self.assertRaisesRegex(GameError, "not open"):
            await self.run_game(tournament.join, 1)
        self.go_to(FRIDAY_18)
        events = await self.tick()
        self.assertEqual([e["type"] for e in events], ["opened"])
        self.assertEqual(await self.tick(), [])

    def test_round_names(self):
        self.assertEqual(tournament.round_name(5, 5), "Final")
        self.assertEqual(tournament.round_name(4, 5), "Semi-finals")
        self.assertEqual(tournament.round_name(3, 5), "Quarter-finals")
        self.assertEqual(tournament.round_name(1, 5), "Round 1")


class RegistrationTests(TournamentTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.go_to(FRIDAY_18)
        await self.tick()

    async def test_join_pays_the_fee_and_grows_the_pot(self):
        await self.register(1, 2)
        self.assertEqual(await self.run_game(players.get_emeralds, 1), 50)
        t = await self.run_game(tournament.active)
        self.assertEqual(t["pot"], 2 * 50 + 200)
        with self.assertRaisesRegex(GameError, "already registered"):
            await self.run_game(tournament.join, 1)

    async def test_join_needs_the_fee(self):
        with self.assertRaisesRegex(GameError, "Not enough emeralds"):
            await self.run_game(tournament.join, 1)

    async def test_leave_is_refunded(self):
        await self.register(1)
        res = await self.run_game(tournament.leave, 1)
        self.assertEqual(res["refund"], 50)
        self.assertEqual(await self.run_game(players.get_emeralds, 1), 100)
        self.assertEqual((await self.run_game(tournament.active))["pot"], 200)

    async def test_max_players(self):
        settings.load({"tournament": {"max_players": 2}})
        await self.register(1, 2)
        with self.assertRaisesRegex(GameError, "full"):
            await self.register(3)

    async def test_too_few_players_cancels_and_refunds(self):
        await self.register(1, 2, 3)
        self.go_to(SATURDAY_21)
        events = await self.tick()
        self.assertEqual(events[0]["type"], "cancelled")
        for uid in (1, 2, 3):
            self.assertEqual(await self.run_game(players.get_emeralds, uid), 100)
        self.assertIsNone(await self.run_game(tournament.active))
        # Not reopened the same week.
        self.assertEqual(await self.tick(), [])


class BracketTests(TournamentTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.go_to(FRIDAY_18)
        await self.tick()

    async def test_draw_with_byes(self):
        await self.register(1, 2, 3, 4, 5)
        self.go_to(SATURDAY_21)
        drawn = (await self.tick())[0]
        self.assertEqual(drawn["type"], "drawn")
        t = drawn["tournament"]
        self.assertEqual((t["status"], t["rounds"], t["next_round_at"]), ("running", 3, int(self.start + SUNDAY_18)))
        first = drawn["matches"]
        self.assertEqual(len(first), 4)
        self.assertEqual(sum(m["player2"] is None for m in first), 3)  # 8 slots, 5 players
        seen = [p for m in first for p in (m["player1"], m["player2"]) if p]
        self.assertEqual(sorted(seen), [1, 2, 3, 4, 5])
        with self.assertRaisesRegex(GameError, "drawn"):
            await self.run_game(tournament.leave, 1)
        with self.assertRaisesRegex(GameError, "closed"):
            await self.run_game(tournament.join, 6)

    async def test_full_tournament(self):
        ids = [1, 2, 3, 4, 5, 6]
        await self.register(*ids)
        for uid in ids:  # gear must not wear out
            await self.run_game(shop.create_gear, uid, "sword", "iron")
            await self.run_game(gear.equip_best, uid)
        self.go_to(SATURDAY_21)
        await self.tick()

        self.go_to(SUNDAY_18 - 60)
        self.assertEqual(await self.tick(), [])
        self.go_to(SUNDAY_18)
        r1 = (await self.tick())[0]
        self.assertEqual((r1["round"], r1["next_round_at"]), (1, int(self.start + SUNDAY_18 + HOUR)))
        self.assertEqual(await self.tick(), [])  # next round in an hour

        events = [r1] + await self.play_all()
        self.assertEqual([e["round"] for e in events], [1, 2, 3])
        final = events[-1]["final"]
        pot = 6 * 50 + 200
        self.assertEqual(final["pot"], pot)
        payout = dict(final["payout"])
        self.assertEqual(sum(payout.values()), pot)
        self.assertEqual(payout[final["runner_up"]], pot * 25 // 100)
        self.assertEqual(len(final["semis"]), 2)
        for uid in final["semis"]:
            self.assertEqual(payout[uid], pot * 15 // 100 // 2)

        t = await self.run_game(tournament.latest)
        self.assertEqual((t["status"], t["winner_id"]), ("finished", final["winner"]))
        self.assertIsNone(await self.run_game(tournament.active))
        self.assertEqual(await self.run_game(players.get_stat, final["winner"], "tournaments_won"), 1)
        for uid in ids:
            sword = (await self.run_game(gear.get_equipped, uid))["sword"]
            self.assertEqual(sword["durability"], sword["max_durability"])

    async def test_only_the_server_bonus_counts_for_the_season(self):
        await self.register(1, 2, 3, 4)
        self.go_to(SATURDAY_21)
        await self.tick()
        self.go_to(SUNDAY_18 - HOUR)
        final = (await self.play_all())[-1]["final"]
        pot = 4 * 50 + 200
        overview = await self.run_game(seasons.overview, final["winner"])
        winner_prize = dict(final["payout"])[final["winner"]]
        self.assertEqual(overview["score"], winner_prize * 200 // pot)

    async def test_two_players_final_only(self):
        settings.load({"tournament": {"min_players": 2}})
        await self.register(1, 2)
        self.go_to(SATURDAY_21)
        await self.tick()
        self.go_to(SUNDAY_18 - HOUR)
        final = (await self.play_all())[-1]["final"]
        # No semi-finalists: their 15% goes to the winner.
        self.assertEqual(dict(final["payout"]), {final["winner"]: 225, final["runner_up"]: 75})


class StaffTests(TournamentTestCase):
    async def test_staff_runs_a_tournament_any_day(self):
        # Wednesday: before the usual registrations.
        t = await self.run_game(tournament.staff_open)
        self.assertEqual(t["closes_at"], int(self.start + SATURDAY_21))
        await self.register(1, 2, 3, 4)
        drawn = await self.run_game(tournament.staff_round)
        self.assertEqual(drawn["type"], "drawn")
        r1 = await self.run_game(tournament.staff_round)
        self.assertEqual(r1["round"], 1)
        final = await self.run_game(tournament.staff_round)
        self.assertIn("final", final)
        with self.assertRaisesRegex(GameError, "no tournament"):
            await self.run_game(tournament.staff_round)

    async def test_staff_open_after_the_window_waits_for_staff(self):
        self.go_to(SUNDAY_18 + HOUR)
        t = await self.run_game(tournament.staff_open)
        self.assertIsNone(t["closes_at"])
        await self.register(1, 2, 3, 4)
        self.advance(DAY)
        self.assertEqual(await self.tick(), [])  # still open

    async def test_staff_cancel_refunds(self):
        await self.run_game(tournament.staff_open)
        await self.register(1, 2, 3, 4)
        await self.run_game(tournament.staff_round)  # draw
        res = await self.run_game(tournament.staff_cancel)
        self.assertEqual(len(res["refunded"]), 4)
        self.assertEqual(await self.run_game(players.get_emeralds, 1), 100)

    async def test_only_one_tournament_at_a_time(self):
        await self.run_game(tournament.staff_open)
        with self.assertRaisesRegex(GameError, "already"):
            await self.run_game(tournament.staff_open)


if __name__ == "__main__":
    unittest.main()
