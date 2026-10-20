"""Bounties (2.0.5): placing, adding up, claiming (duel, robbery, raid), expiring and the rules."""
from __future__ import annotations

import random

from game import bounty, duel, players, reset, robbery, teams, war
from game.errors import GameError
from game.notices import BountyClaimed, BountyExpired, BountyPlaced
from tests.helpers import DAY, GameTestCase

A1, A2, A3, B1, B2, C1, C2 = 1, 2, 3, 11, 12, 21, 22
HOUR = 3600


class BountyTestCase(GameTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for uid in (A1, A2, A3, B1, B2, C1, C2):
            await self.run_game(players.give_emeralds, uid, 10_000)
            await self.run_game(players.set_level, uid, 10)

    async def team(self, leader: int, name: str, tag: str, *others: int) -> int:
        t = await self.run_game(teams.create, leader, name, tag)
        for uid in others:
            await self.run_game(teams.invite, leader, uid)
            await self.run_game(teams.accept, uid, t["team_id"])
        return t["team_id"]

    async def emeralds(self, uid: int) -> int:
        return await self.run_game(players.get_emeralds, uid)


class PlaceTests(BountyTestCase):
    async def test_bounties_add_up_and_stay_anonymous(self):
        before = await self.emeralds(A1)
        await self.run_game(bounty.place, A1, C1, 500)
        res = await self.run_game(bounty.place, A2, C1, 1000)
        self.assertEqual(res["total"], 1500)
        self.assertEqual(await self.emeralds(A1), before - 500)
        board = await self.run_game(bounty.board)
        self.assertEqual(board, [{"target_id": C1, "total": 1500, "n": 2, "next_expiry": int(self.now + 7 * DAY)}])
        self.assertEqual([type(x) for x in self.notices if "Bounty" in type(x).__name__], [BountyPlaced, BountyPlaced])

    async def test_rules(self):
        with self.assertRaisesRegex(GameError, "tiers"):
            await self.run_game(bounty.place, A1, C1, 300)
        with self.assertRaisesRegex(GameError, "own head"):
            await self.run_game(bounty.place, A1, A1, 250)
        await self.run_game(players.set_level, C2, 9)
        with self.assertRaisesRegex(GameError, "below level"):
            await self.run_game(bounty.place, A1, C2, 250)
        with self.assertRaisesRegex(GameError, "level"):
            await self.run_game(bounty.place, C2, A1, 250)
        await self.team(A1, "Alpha", "AAA", A2)
        with self.assertRaisesRegex(GameError, "teammate"):
            await self.run_game(bounty.place, A1, A2, 250)


class ClaimTests(BountyTestCase):
    async def test_a_duel_claims_everything(self):
        await self.run_game(bounty.place, A1, C1, 500)
        await self.run_game(bounty.place, A2, C1, 250)
        rng = random.Random(3)

        def play(ctx):
            res = duel.start(ctx, B1, C1, 10, rng)
            res["fight"].auto_play(rng)
            return duel.finish(ctx, res["duel_id"], res["fight"])

        out = await self.run_game(play)
        if out["winner"] == B1:
            self.assertEqual(out["bounty"], {"hunter_id": B1, "target_id": C1, "amount": 750, "via": "duel"})
            self.assertEqual(await self.run_game(bounty.on_head, C1), 0)
            self.assertIn(BountyClaimed(B1, C1, 750, "duel"), self.notices)
            self.assertEqual(await self.run_game(players.get_stat, B1, "bounty_winnings"), 750)
        else:  # the target won: the bounty stays
            self.assertIsNone(out["bounty"])
            self.assertEqual(await self.run_game(bounty.on_head, C1), 750)

    async def test_claim_then_protection(self):
        await self.run_game(bounty.place, A1, C1, 1000)
        before = await self.emeralds(B1)
        got = await self.run_game(bounty.claim, B1, C1, "duel")
        self.assertEqual(got["amount"], 1000)
        self.assertEqual(await self.emeralds(B1), before + 1000)
        self.assertIsNone(await self.run_game(bounty.claim, B2, C1, "duel"))  # nothing left
        with self.assertRaisesRegex(GameError, "just lost a bounty"):
            await self.run_game(bounty.place, A1, C1, 250)
        self.advance(25 * HOUR)
        await self.run_game(bounty.place, A1, C1, 250)

    async def test_teammates_never_claim(self):
        await self.team(C1, "Charlie", "CCC", C2)
        await self.run_game(bounty.place, A1, C1, 500)
        self.assertIsNone(await self.run_game(bounty.claim, C2, C1, "duel"))
        self.assertIsNone(await self.run_game(bounty.claim, C1, C1, "duel"))
        self.assertEqual(await self.run_game(bounty.on_head, C1), 500)

    async def test_a_robbery_claims(self):
        await self.run_game(bounty.place, A1, C1, 2500)
        await self.run_game(robbery.start, B1, C1, "discreet")
        self.advance(61 * 60)
        done = (await self.run_game(robbery.finish_due))[0]
        self.assertEqual(done["bounty"]["amount"], 2500)
        self.assertEqual(done["bounty"]["hunter_id"], B1)

    async def test_the_blow_that_downs_claims_in_a_raid(self):
        await self.team(A1, "Alpha", "AAA", A2, A3)
        await self.team(B1, "Bravo", "BBB", B2)
        await self.run_game(bounty.place, C1, B1, 1000)
        raid = await self.run_game(war.start_raid, A1, "BBB")
        await self.run_game(war.join_raid, raid["raid_id"], A2)
        await self.run_game(war.join_raid, raid["raid_id"], A3)
        await self.run_game(war.launch_raid, raid["raid_id"], A1)
        await self.run_game(war.join_raid, raid["raid_id"], B1)
        raid = await self.run_game(war.resolve_raid, raid["raid_id"])
        self.assertEqual(raid["status"], "fighting")
        raid = await self.run_game(war.play_out, raid["raid_id"])
        self.assertEqual(raid["status"], "won")  # three against one: the defender falls
        [claim] = raid["bounties"]
        self.assertEqual((claim["target_id"], claim["amount"], claim["via"]), (B1, 1000, "raid"))
        self.assertIn(claim["hunter_id"], (A1, A2, A3))

    def test_fight_remembers_who_downed_whom(self):
        from game.raid_fight import Fighter, RaidFight

        a = Fighter(1, "attack", 30, 30, 0, 20)
        d = Fighter(2, "defend", 1, 1, 0, 20)
        fight = RaidFight([a, d])
        fight.auto_play(random.Random(1))
        self.assertEqual((fight.result, d.downed_by, a.downed_by), ("attack", 1, None))


class ExpiryTests(BountyTestCase):
    async def test_unclaimed_goes_back_minus_the_tax(self):
        before = await self.emeralds(A1)
        await self.run_game(bounty.place, A1, C1, 1000)
        self.advance(3 * DAY)
        await self.run_game(bounty.place, A2, C1, 500)
        self.advance(4 * DAY)
        out = await self.run_game(bounty.expire)
        self.assertEqual([(b["payer_id"], b["refund"]) for b in out], [(A1, 900)])
        self.assertEqual(await self.emeralds(A1), before - 100)
        self.assertEqual(await self.run_game(bounty.on_head, C1), 500)
        self.assertIn(BountyExpired(A1, C1, 1000, 900), self.notices)
        self.assertEqual(await self.run_game(bounty.expire), [])

    async def test_a_wealth_reset_drops_them(self):
        await self.run_game(bounty.place, A1, C1, 1000)
        await self.run_game(bounty.place, A2, C2, 500)
        await self.run_game(reset.apply, {"wealth"}, A1)
        self.assertEqual(await self.run_game(bounty.on_head, C1), 0)
        self.assertEqual(await self.run_game(bounty.on_head, C2), 500)
        await self.run_game(reset.apply, {"wealth"})
        self.assertEqual(await self.run_game(bounty.board), [])
