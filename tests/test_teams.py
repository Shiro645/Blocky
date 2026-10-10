from __future__ import annotations

import unittest

from game import leaderboard, mining, players, seasons, settings, teams
from game.errors import GameError
from tests.helpers import DAY, GameTestCase

ALICE, BOB, CAROL, DAVE, EVE, FRANK = 1, 2, 3, 4, 5, 6


class TeamTestCase(GameTestCase):
    # Most tests are about the rules, not the costs: free teams, ranked from 1 member.
    overrides = {"teams": {"create_cost": 0, "min_members_ranked": 1}}

    async def make_team(self, leader=ALICE, name="Diamond Diggers", tag="DIG", *others):
        team = await self.run_game(teams.create, leader, name, tag)
        for uid in others:
            await self.run_game(teams.invite, leader, uid)
            await self.run_game(teams.accept, uid, team["team_id"])
        return team


class NameTests(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(teams.clean_name("  Les   Mineurs  "), "Les Mineurs")
        self.assertEqual(teams.clean_name("Équipe d'Or"), "Équipe d'Or")
        for bad in ("ab", "x" * 25, "**bold**", "<@123>", "_under", "a`b`c"):
            with self.subTest(bad=bad), self.assertRaises(GameError):
                teams.clean_name(bad)

    def test_clean_tag(self):
        self.assertEqual(teams.clean_tag("[abc]"), "ABC")
        self.assertEqual(teams.clean_tag("x1"), "X1")
        for bad in ("A", "ABCDE", "A B", "É"):
            with self.subTest(bad=bad), self.assertRaises(GameError):
                teams.clean_tag(bad)

    def test_split_reward(self):
        self.assertEqual(teams.split_reward(600, [(1, 300), (2, 100)]), {1: 450, 2: 150})
        # Leftovers go to the best contributors, nothing is lost.
        split = teams.split_reward(100, [(1, 1), (2, 1), (3, 1)])
        self.assertEqual(sum(split.values()), 100)
        self.assertEqual(split[1], 34)
        self.assertEqual(teams.split_reward(100, []), {})


class MembershipTests(TeamTestCase):
    async def test_create_and_unique_names(self):
        team = await self.make_team()
        self.assertEqual((team["name"], team["tag"], team["leader_id"]), ("Diamond Diggers", "DIG", ALICE))
        with self.assertRaisesRegex(GameError, "already in a team"):
            await self.run_game(teams.create, ALICE, "Other", "OTH")
        with self.assertRaisesRegex(GameError, "already exists"):
            await self.run_game(teams.create, BOB, "diamond diggers", "DD")
        with self.assertRaisesRegex(GameError, "already used"):
            await self.run_game(teams.create, BOB, "Other", "dig")

    async def test_default_creation_cost(self):
        settings.load()
        await self.run_game(players.give_emeralds, ALICE, 600)
        await self.run_game(teams.create, ALICE, "Rich Club", "RICH")
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 100)

    async def test_create_cost(self):
        settings.load({"teams": {"create_cost": 100}})
        with self.assertRaisesRegex(GameError, "Not enough emeralds"):
            await self.run_game(teams.create, ALICE, "Rich Club", "RICH")
        await self.run_game(players.give_emeralds, ALICE, 150)
        await self.run_game(teams.create, ALICE, "Rich Club", "RICH")
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 50)

    async def test_invite_accept_and_full_team(self):
        team = await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB, CAROL, DAVE, EVE)
        self.assertEqual((await self.run_game(teams.team_of, EVE))["team_id"], team["team_id"])
        with self.assertRaisesRegex(GameError, "full"):
            await self.run_game(teams.invite, ALICE, FRANK)

    async def test_only_the_leader_invites(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        with self.assertRaisesRegex(GameError, "Only the leader"):
            await self.run_game(teams.invite, BOB, CAROL)

    async def test_accept_needs_a_valid_invite(self):
        team = await self.make_team()
        with self.assertRaisesRegex(GameError, "expired"):
            await self.run_game(teams.accept, BOB, team["team_id"])
        await self.run_game(teams.invite, ALICE, BOB)
        self.advance(49 * 3600)
        with self.assertRaisesRegex(GameError, "expired"):
            await self.run_game(teams.accept, BOB, team["team_id"])

    async def test_join_by_tag_and_decline(self):
        await self.make_team()
        other = await self.run_game(teams.create, CAROL, "Red Stone", "RED")
        await self.run_game(teams.invite, ALICE, BOB)
        await self.run_game(teams.invite, CAROL, BOB)
        self.assertEqual(len(await self.run_game(teams.pending_invites, BOB)), 2)
        self.assertTrue(await self.run_game(teams.decline, BOB, other["team_id"]))
        res = await self.run_game(teams.join, BOB, "[dig]")
        self.assertEqual(res["members"], 2)
        # Joining a team clears the other invitations.
        self.assertEqual(await self.run_game(teams.pending_invites, BOB), [])

    async def test_cannot_invite_a_player_in_a_team(self):
        await self.make_team()
        await self.run_game(teams.create, BOB, "Red Stone", "RED")
        with self.assertRaisesRegex(GameError, "already in"):
            await self.run_game(teams.invite, ALICE, BOB)

    async def test_leader_leaving_hands_the_lead_over(self):
        team = await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB, CAROL)
        res = await self.run_game(teams.leave, ALICE)
        self.assertEqual(res["new_leader"], BOB)
        self.assertEqual((await self.run_game(teams.get_team, team["team_id"]))["leader_id"], BOB)
        await self.run_game(teams.leave, CAROL)
        res = await self.run_game(teams.leave, BOB)
        self.assertTrue(res["disbanded"])
        self.assertIsNone(await self.run_game(teams.get_team, team["team_id"]))

    async def test_kick_transfer_rename_disband(self):
        team = await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB, CAROL)
        await self.run_game(teams.kick, ALICE, CAROL)
        self.assertIsNone(await self.run_game(teams.team_of, CAROL))
        with self.assertRaisesRegex(GameError, "not in your team"):
            await self.run_game(teams.kick, ALICE, DAVE)

        await self.run_game(teams.transfer, ALICE, BOB)
        with self.assertRaisesRegex(GameError, "Only the leader"):
            await self.run_game(teams.rename, ALICE, "New Name")
        res = await self.run_game(teams.rename, BOB, None, "nw")
        self.assertEqual((res["after"]["name"], res["after"]["tag"]), ("Diamond Diggers", "NW"))

        res = await self.run_game(teams.disband, BOB)
        self.assertEqual(sorted(res["members"]), [ALICE, BOB])
        self.assertIsNone(await self.run_game(teams.get_team, team["team_id"]))
        self.assertIsNone(await self.run_game(teams.team_of, ALICE))

    async def test_staff_remove(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(teams.remove, "Diamond Diggers")
        self.assertIsNone(await self.run_game(teams.team_of, BOB))


class BonusTests(TeamTestCase):
    async def test_bonus_grows_with_active_members(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB, CAROL, DAVE, EVE)
        self.assertEqual(await self.run_game(teams.activity_bonus, ALICE), 0.0)
        self.assertAlmostEqual(await self.run_game(teams.activity_bonus, BOB), 0.05)
        self.assertAlmostEqual(await self.run_game(teams.activity_bonus, CAROL), 0.10)
        # Mining again the same day doesn't count twice.
        self.assertAlmostEqual(await self.run_game(teams.activity_bonus, ALICE), 0.10)
        await self.run_game(teams.activity_bonus, DAVE)
        self.assertAlmostEqual(await self.run_game(teams.activity_bonus, EVE), 0.20)
        # A new day starts from zero.
        self.advance(DAY)
        self.assertEqual(await self.run_game(teams.activity_bonus, ALICE), 0.0)

    async def test_bonus_is_capped(self):
        settings.load({"teams": {"xp_bonus_per_active_member": 0.5, "max_xp_bonus": 0.3, "create_cost": 0}})
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(teams.activity_bonus, ALICE)
        self.assertAlmostEqual(await self.run_game(teams.activity_bonus, BOB), 0.3)

    async def test_mining_applies_the_bonus(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        first = await self.run_game(mining.mine, ALICE)
        second = await self.run_game(mining.mine, BOB)
        self.assertEqual(first["team_bonus"], 0.0)
        self.assertAlmostEqual(second["team_bonus"], 0.05)

    async def test_no_team_no_bonus(self):
        self.assertEqual((await self.run_game(mining.mine, FRANK))["team_bonus"], 0.0)


class TeamSeasonTests(TeamTestCase):
    async def test_members_earnings_count_for_the_team(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(players.earn_emeralds, ALICE, 30)
        await self.run_game(players.earn_emeralds, BOB, 20)
        await self.run_game(players.earn_emeralds, CAROL, 500)  # no team
        await self.run_game(players.give_emeralds, ALICE, 1000)  # not earned
        data = await self.run_game(teams.season_overview, BOB)
        self.assertEqual([(t["tag"], t["score"]) for t in data["top"]], [("DIG", 50)])
        self.assertEqual((data["rank"], data["score"]), (1, 50))

    async def test_earnings_before_joining_stay_out(self):
        team = await self.make_team()
        await self.run_game(players.earn_emeralds, BOB, 100)
        await self.run_game(teams.invite, ALICE, BOB)
        await self.run_game(teams.accept, BOB, team["team_id"])
        await self.run_game(players.earn_emeralds, BOB, 10)
        info = await self.run_game(teams.overview, team["team_id"])
        self.assertEqual(info["score"], 10)

    async def test_week_end_shares_the_rewards(self):
        dig = await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.make_team(CAROL, "Red Stone", "RED")
        await self.run_game(players.earn_emeralds, ALICE, 300)
        await self.run_game(players.earn_emeralds, BOB, 100)
        await self.run_game(players.earn_emeralds, CAROL, 50)
        # Bob leaves before the end: what he brought is still his share.
        await self.run_game(teams.leave, BOB)
        self.assertEqual(await self.run_game(teams.close_finished), [])  # week not over

        before = {uid: await self.run_game(players.get_emeralds, uid) for uid in (ALICE, BOB, CAROL)}
        self.advance(7 * DAY)
        closed = await self.run_game(teams.close_finished)
        self.assertEqual(len(closed), 1)
        podium = closed[0]["podium"]
        self.assertEqual([(p["tag"], p["score"], p["reward"]) for p in podium], [("DIG", 400, 600), ("RED", 50, 300)])
        self.assertEqual(podium[0]["payout"], [(ALICE, 450), (BOB, 150)])
        # Alice and Bob also unlock "Squad Goals" (+150).
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), before[ALICE] + 450 + 150)
        self.assertEqual(await self.run_game(players.get_emeralds, BOB), before[BOB] + 150 + 150)
        self.assertEqual(await self.run_game(players.get_emeralds, CAROL), before[CAROL] + 300)
        self.assertEqual(await self.run_game(teams.close_finished), [])  # not paid twice

        # Rewards don't feed the new season, and the winner is remembered.
        data = await self.run_game(teams.season_overview, ALICE)
        self.assertEqual(data["top"], [])
        self.assertEqual(data["last_winner"]["team_id"], dig["team_id"])
        self.assertEqual((await self.run_game(teams.overview, dig["team_id"]))["wins"], 1)

    async def test_disbanding_after_the_week_keeps_the_rewards(self):
        team = await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(players.earn_emeralds, BOB, 300)
        self.advance(7 * DAY)  # the week is over, not closed yet
        await self.run_game(teams.disband, ALICE)
        closed = await self.run_game(teams.close_finished)
        podium = closed[0]["podium"]
        self.assertEqual((podium[0]["team_id"], podium[0]["tag"]), (team["team_id"], "DIG"))
        self.assertEqual(podium[0]["payout"], [(BOB, 600)])

    async def test_a_team_needs_two_scoring_members_to_be_ranked(self):
        settings.load({"teams": {"create_cost": 0, "min_members_ranked": 2}})
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(players.earn_emeralds, ALICE, 300)
        self.assertEqual((await self.run_game(teams.season_overview, ALICE))["top"], [])  # only Alice scored
        await self.run_game(players.earn_emeralds, BOB, 10)
        top = (await self.run_game(teams.season_overview, ALICE))["top"]
        self.assertEqual([(t["tag"], t["score"]) for t in top], [("DIG", 310)])

    async def test_disbanded_team_is_not_ranked(self):
        await self.make_team()
        await self.run_game(players.earn_emeralds, ALICE, 300)
        await self.run_game(teams.disband, ALICE)
        self.advance(7 * DAY)
        self.assertEqual(await self.run_game(teams.close_finished), [])


class TagTests(TeamTestCase):
    async def test_tags_in_rankings_and_profile(self):
        await self.make_team(ALICE, "Diamond Diggers", "DIG", BOB)
        await self.run_game(players.earn_emeralds, BOB, 10)
        await self.run_game(players.earn_emeralds, CAROL, 5)
        board = await self.run_game(leaderboard.leaderboard, "season", CAROL)
        self.assertEqual(board["tags"], {BOB: "DIG"})
        season = await self.run_game(seasons.overview, CAROL)
        self.assertEqual(season["tags"], {BOB: "DIG"})
        self.assertEqual((await self.run_game(leaderboard.profile, ALICE))["team"]["tag"], "DIG")
        self.assertIsNone((await self.run_game(leaderboard.profile, CAROL))["team"])


if __name__ == "__main__":
    unittest.main()
