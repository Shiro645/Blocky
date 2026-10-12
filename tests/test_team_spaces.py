"""Team spaces: the leader unlocks the private category once; a failure refunds it."""
from __future__ import annotations

from game import players, team_spaces, teams
from game.errors import GameError
from tests.helpers import GameTestCase

ALICE, BOB = 1, 2


class TeamSpaceTests(GameTestCase):
    overrides = {"teams": {"create_cost": 0}}

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.team = await self.run_game(teams.create, ALICE, "Diamond Diggers", "DIG")
        await self.run_game(teams.invite, ALICE, BOB)
        await self.run_game(teams.accept, BOB, self.team["team_id"])

    async def test_the_leader_unlocks_it_once(self):
        with self.assertRaisesRegex(GameError, "1,000"):
            await self.run_game(team_spaces.unlock, ALICE)
        await self.run_game(players.give_emeralds, ALICE, 2500)
        with self.assertRaisesRegex(GameError, "leader"):
            await self.run_game(team_spaces.check_unlock, BOB)
        self.assertEqual((await self.run_game(team_spaces.unlock, ALICE))["paid"], 1000)
        with self.assertRaisesRegex(GameError, "already"):
            await self.run_game(team_spaces.unlock, ALICE)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 1500)
        with self.assertRaisesRegex(GameError, "no category yet"):
            await self.run_game(team_spaces.leader_space, ALICE)  # not made on Discord yet
        await self.run_game(team_spaces.set_discord, self.team["team_id"], 11, 22)
        res = await self.run_game(team_spaces.leader_space, ALICE)
        self.assertEqual((res["space"]["role_id"], res["space"]["category_id"]), (11, 22))
        self.assertEqual(await self.run_game(team_spaces.refund, self.team["team_id"]), 0)  # made: no refund

    async def test_a_failure_refunds(self):
        await self.run_game(players.give_emeralds, ALICE, 1000)
        await self.run_game(team_spaces.unlock, ALICE)
        self.assertEqual(await self.run_game(team_spaces.refund, self.team["team_id"]), 1000)
        self.assertEqual(await self.run_game(players.get_emeralds, ALICE), 1000)
        self.assertIsNone(await self.run_game(team_spaces.get, self.team["team_id"]))

    async def test_spaces_outlive_their_team_for_the_cleanup(self):
        await self.run_game(players.give_emeralds, ALICE, 1000)
        await self.run_game(team_spaces.unlock, ALICE)
        [space] = await self.run_game(team_spaces.every)
        self.assertEqual((space["team"]["tag"], sorted(space["members"])), ("DIG", [ALICE, BOB]))
        await self.run_game(teams.disband, ALICE)
        [space] = await self.run_game(team_spaces.every)
        self.assertIsNone(space["team"])
        await self.run_game(team_spaces.forget, space["team_id"])
        self.assertEqual(await self.run_game(team_spaces.every), [])
